import argparse
import asyncio
import csv
import hashlib
import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx

DEFAULT_SERVER_URL = "http://localhost:8000"
DEFAULT_STATION_ID = 1
DEFAULT_RUECKMELDENUMMER = "RM-DEV-0001"
DEFAULT_MEASUREMENT_TYPE = "breite"
DEFAULT_MEASUREMENT_VALUE = Decimal("12.4")


def keyence_frame(barcode: str, *, terminator: str = "\r\n") -> bytes:
    return f"{barcode}{terminator}".encode("ascii")


def smb_csv_payload(
    value: Decimal | str,
    *,
    value_column_index: int = 13,
    delimiter: str = ";",
    header: bool = True,
) -> str:
    columns = [""] * (value_column_index + 1)
    columns[value_column_index] = str(value).replace(".", ",")
    buffer = io.StringIO()
    if header:
        buffer.write("header\n")
    writer = csv.writer(buffer, delimiter=delimiter, lineterminator="\n")
    writer.writerow(columns)
    return buffer.getvalue()


def write_smb_payload_file(
    directory: Path,
    *,
    value: Decimal | str = DEFAULT_MEASUREMENT_VALUE,
    value_column_index: int = 13,
    sequence: int = 1,
    prefix: str = "result",
    encoding: str = "cp1252",
) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{prefix}_{sequence}.csv"
    path.write_text(
        smb_csv_payload(value, value_column_index=value_column_index),
        encoding=encoding,
    )
    return path


async def send_keyence_frame(
    *,
    host: str,
    port: int,
    barcode: str,
    count: int = 1,
    delay_seconds: float = 0.0,
) -> None:
    _reader, writer = await asyncio.open_connection(host, port)
    try:
        for index in range(count):
            writer.write(keyence_frame(barcode))
            await writer.drain()
            if delay_seconds and index < count - 1:
                await asyncio.sleep(delay_seconds)
    finally:
        writer.close()
        await writer.wait_closed()


async def post_api_scan_and_measurement(
    *,
    server_url: str,
    station_id: int,
    rueckmeldenummer: str,
    measurement_type: str,
    value: Decimal,
    idempotency_key: str | None = None,
    timeout_seconds: float = 10.0,
) -> dict[str, Any]:
    measured_at = datetime.now(UTC).isoformat()
    stable_key = idempotency_key or _idempotency_key(
        station_id=station_id,
        rueckmeldenummer=rueckmeldenummer,
        measurement_type=measurement_type,
        value=value,
        measured_at=measured_at,
    )
    async with httpx.AsyncClient(
        base_url=server_url.rstrip("/"),
        timeout=timeout_seconds,
    ) as client:
        scan_response = await client.post(
            "/api/companion/barcode-scans",
            json={
                "station_id": station_id,
                "rueckmeldenummer": rueckmeldenummer,
                "source_type": "keyence_srx_simulator",
                "scanned_at": measured_at,
                "raw_payload": rueckmeldenummer,
            },
        )
        scan_response.raise_for_status()

        measurement_response = await client.post(
            "/api/companion/measurements",
            json={
                "station_id": station_id,
                "idempotency_key": stable_key,
                "source_type": "api_simulator",
                "measured_at": measured_at,
                "result_status": "pass",
                "rueckmeldenummer": rueckmeldenummer,
                "values": [
                    {
                        "measurement_type": measurement_type,
                        "value": str(value),
                        "unit": "mm",
                        "result_status": "pass",
                    }
                ],
            },
        )
        measurement_response.raise_for_status()
        return {
            "barcode_scan": scan_response.json(),
            "measurement": measurement_response.json(),
            "idempotency_key": stable_key,
        }


def _idempotency_key(
    *,
    station_id: int,
    rueckmeldenummer: str,
    measurement_type: str,
    value: Decimal,
    measured_at: str,
) -> str:
    content = f"{station_id}:{rueckmeldenummer}:{measurement_type}:{value}:{measured_at}"
    return f"sim:{hashlib.sha256(content.encode('utf-8')).hexdigest()[:32]}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="slf-trace-sim",
        description="Drive local station ingest flows without real devices.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    keyence = subcommands.add_parser("keyence", help="Send barcode frames to a scanner listener.")
    keyence.add_argument("--host", default="127.0.0.1")
    keyence.add_argument("--port", type=int, required=True)
    keyence.add_argument("--barcode", default=DEFAULT_RUECKMELDENUMMER)
    keyence.add_argument("--count", type=int, default=1)
    keyence.add_argument("--delay", type=float, default=0.0)

    smb = subcommands.add_parser("smb-file", help="Write an SMB adapter compatible CSV file.")
    smb.add_argument("--directory", type=Path, required=True)
    smb.add_argument("--value", default=str(DEFAULT_MEASUREMENT_VALUE))
    smb.add_argument("--value-column-index", type=int, default=13)
    smb.add_argument("--sequence", type=int, default=1)
    smb.add_argument("--prefix", default="result")
    smb.add_argument("--encoding", default="cp1252")

    api = subcommands.add_parser("api", help="Post barcode and measurement events to the API.")
    api.add_argument("--server-url", default=DEFAULT_SERVER_URL)
    api.add_argument("--station-id", type=int, default=DEFAULT_STATION_ID)
    api.add_argument("--rueckmeldenummer", default=DEFAULT_RUECKMELDENUMMER)
    api.add_argument("--measurement-type", default=DEFAULT_MEASUREMENT_TYPE)
    api.add_argument("--value", type=Decimal, default=DEFAULT_MEASUREMENT_VALUE)
    api.add_argument("--idempotency-key")

    return parser


async def run_async(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "keyence":
        await send_keyence_frame(
            host=args.host,
            port=args.port,
            barcode=args.barcode,
            count=args.count,
            delay_seconds=args.delay,
        )
        print(f"Sent {args.count} barcode frame(s) to {args.host}:{args.port}.")
        return 0

    if args.command == "smb-file":
        path = write_smb_payload_file(
            args.directory,
            value=args.value,
            value_column_index=args.value_column_index,
            sequence=args.sequence,
            prefix=args.prefix,
            encoding=args.encoding,
        )
        print(path)
        return 0

    if args.command == "api":
        response = await post_api_scan_and_measurement(
            server_url=args.server_url,
            station_id=args.station_id,
            rueckmeldenummer=args.rueckmeldenummer,
            measurement_type=args.measurement_type,
            value=args.value,
            idempotency_key=args.idempotency_key,
        )
        print(response)
        return 0

    raise ValueError(f"Unknown simulator command: {args.command}")


def run() -> None:
    raise SystemExit(asyncio.run(run_async()))
