import asyncio
import hashlib
import importlib
import json
import re
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO
from pathlib import Path
from typing import Any

from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    MeasurementAdapter,
    MeasurementEvent,
    MeasurementEventValue,
    RawPayloadEvent,
)


@dataclass(frozen=True)
class SmbPollingAdapterConfig:
    server: str
    share: str
    username: str
    password: str
    measurement_type: str
    value_column_index: int
    rueckmeldenummer: str | None = None
    remote_dir: str = "/ExcelAusgabe"
    name: str = "smb1-polling"
    source_type: str = "smb1"
    client_name: str = "slf-trace-companion"
    server_name: str | None = None
    port: int = 445
    support_smb2: bool = False
    use_ntlm_v2: bool = False
    timeout_seconds: float = 10.0
    poll_interval_seconds: float = 2.0
    encoding: str = "cp1252"
    delimiter: str = ";"
    filename_pattern: str = r"_(\d+)\.csv$"
    delete_after_success: bool = True
    delete_with_smbclient: bool = True
    smbclient_min_protocol: str = "NT1"
    processed_hashes_path: str | Path | None = None


@dataclass(frozen=True)
class SmbFile:
    name: str
    path: str


@dataclass(frozen=True)
class SmbMeasurementRead:
    file: SmbFile
    content: str
    payload_hash: str
    processed_key: str
    value: Decimal


class ProcessedHashStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else None
        self._hashes = self._load()

    def contains(self, payload_hash: str) -> bool:
        return payload_hash in self._hashes

    def add(self, payload_hash: str) -> None:
        self._hashes.add(payload_hash)
        self._save()

    def _load(self) -> set[str]:
        if self.path is None or not self.path.exists():
            return set()
        return set(json.loads(self.path.read_text(encoding="utf-8")))

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(sorted(self._hashes), indent=2), encoding="utf-8")


class SmbConnectionManager:
    def __init__(self, config: SmbPollingAdapterConfig) -> None:
        self.config = config
        self.conn: Any | None = None

    def get(self) -> Any:
        if self.conn is None:
            self.conn = self._connect()
            return self.conn

        try:
            self.conn.echo(b"ping")
        except Exception:
            self.close()
            self.conn = self._connect()
        return self.conn

    def close(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    def _connect(self) -> Any:
        smb_structs, smb_connection = _load_pysmb()
        smb_structs.SUPPORT_SMB2 = self.config.support_smb2
        conn = smb_connection.SMBConnection(
            self.config.username,
            self.config.password,
            self.config.client_name,
            self.config.server_name or self.config.server,
            use_ntlm_v2=self.config.use_ntlm_v2,
            is_direct_tcp=self.config.port == 445,
        )
        connected = conn.connect(
            self.config.server,
            self.config.port,
            timeout=int(self.config.timeout_seconds),
        )
        if not connected:
            raise OSError(f"Could not connect to SMB server {self.config.server}.")
        return conn


class SmbPollingMeasurementAdapter(MeasurementAdapter):
    def __init__(
        self,
        config: SmbPollingAdapterConfig,
        *,
        connection_manager: SmbConnectionManager | None = None,
        processed_hashes: ProcessedHashStore | None = None,
    ) -> None:
        self.config = config
        self.name = config.name
        self._filename_pattern = re.compile(config.filename_pattern, re.IGNORECASE)
        self._connection_manager = connection_manager or SmbConnectionManager(config)
        self._processed_hashes = processed_hashes or ProcessedHashStore(
            config.processed_hashes_path
        )
        self._stop_event = asyncio.Event()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)
        self._last_reported_error: str | None = None

    async def start(self, context: AdapterContext) -> None:
        self._stop_event.clear()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STARTING)

        while not self._stop_event.is_set():
            try:
                if not _measurement_needed(context, self.config.measurement_type):
                    self._status = AdapterStatus(
                        name=self.name,
                        state=AdapterState.ONLINE,
                        message="Waiting for measurement request",
                        last_event_at=self._status.last_event_at,
                    )
                    await self._sleep_until_poll()
                    continue
                result = await asyncio.to_thread(self.read_once)
                emitted = await self.emit_read_result(context, result)
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.ONLINE,
                    message="Measurement emitted" if emitted else "No new SMB file",
                    last_event_at=datetime.now(UTC) if emitted else self._status.last_event_at,
                )
                self._last_reported_error = None
            except Exception as exc:  # noqa: BLE001 - SMB libraries raise mixed exception types.
                error_message = str(exc)
                self._status = AdapterStatus(
                    name=self.name,
                    state=AdapterState.DEGRADED,
                    last_error=error_message,
                )
                await self.report_processing_error(context, exc, error_message)

            await self._sleep_until_poll()

        self._connection_manager.close()
        self._status = AdapterStatus(name=self.name, state=AdapterState.STOPPED)

    async def stop(self) -> None:
        self._stop_event.set()

    def health(self) -> AdapterStatus:
        return self._status

    async def report_processing_error(
        self,
        context: AdapterContext,
        exc: Exception,
        error_message: str,
    ) -> None:
        if context.emit_station_event is None or error_message == self._last_reported_error:
            return
        self._last_reported_error = error_message
        await context.emit_station_event(
            "adapter.smb_read_failed",
            "error",
            "SMB adapter could not process the measurement file.",
            {
                "adapter": self.name,
                "error": exc.__class__.__name__,
                "message": error_message,
                "server": self.config.server,
                "share": self.config.share,
                "remote_dir": self.config.remote_dir,
                "measurement_type": self.config.measurement_type,
            },
        )

    async def poll_once(self, context: AdapterContext) -> bool:
        if not _measurement_needed(context, self.config.measurement_type):
            return False
        return await self.emit_read_result(context, self.read_once())

    async def emit_read_result(
        self,
        context: AdapterContext,
        result: SmbMeasurementRead | None,
    ) -> bool:
        if self.config.measurement_type not in context.parser_config.measurement_types:
            raise ValueError(
                f"Unsupported measurement type for station: {self.config.measurement_type}."
            )

        if result is None:
            return False

        event = MeasurementEvent(
            station_id=context.station_id,
            source_type=self.config.source_type,
            measured_at=datetime.now(UTC),
            rueckmeldenummer=self.config.rueckmeldenummer,
            idempotency_key=f"{self.config.source_type}:{result.payload_hash}",
            raw_payload_content=result.content,
            values=[
                MeasurementEventValue(
                    measurement_type=self.config.measurement_type,
                    value=result.value,
                    unit=context.parser_config.default_unit,
                )
            ],
        )

        if context.emit_raw_payload is not None:
            await context.emit_raw_payload(
                RawPayloadEvent(
                    station_id=context.station_id,
                    source_type=self.config.source_type,
                    content=result.content,
                    payload_hash=result.payload_hash,
                )
            )
        await context.emit(event)
        self._processed_hashes.add(result.processed_key)

        if self.config.delete_after_success:
            await asyncio.to_thread(self.delete_file, result.file.path)

        return True

    def read_once(self) -> SmbMeasurementRead | None:
        conn = self._connection_manager.get()
        file_info = self.find_latest_file(conn)
        if file_info is None:
            return None

        content_bytes = self.retrieve_file(conn, file_info.path)
        payload_hash = hashlib.sha256(content_bytes).hexdigest()
        processed_key = self.processed_key(file_info.path, payload_hash)
        if self._processed_hashes.contains(processed_key):
            if self.config.delete_after_success:
                self.delete_file(file_info.path)
            return None

        content = content_bytes.decode(self.config.encoding, errors="replace")
        value = self.extract_measurement_value(content, file_info.path)
        return SmbMeasurementRead(
            file=file_info,
            content=content,
            payload_hash=payload_hash,
            processed_key=processed_key,
            value=value,
        )

    def find_latest_file(self, conn: Any) -> SmbFile | None:
        max_file_number = -1
        best_name: str | None = None

        for entry in conn.listPath(self.config.share, self.config.remote_dir):
            if entry.isDirectory:
                continue

            clean_name = self.clean_smb_name(str(entry.filename))
            match = self._filename_pattern.search(clean_name)
            if match is None:
                continue

            number = int(match.group(1))
            if number > max_file_number:
                max_file_number = number
                best_name = clean_name

        if best_name is None:
            return None

        return SmbFile(name=best_name, path=f"{self.config.remote_dir}/{best_name}")

    def retrieve_file(self, conn: Any, remote_path: str) -> bytes:
        buffer = BytesIO()
        conn.retrieveFile(self.config.share, remote_path, buffer)
        return buffer.getvalue()

    def extract_measurement_value(self, content: str, path: str) -> Decimal:
        lines = [line for line in content.splitlines() if line.strip()]
        if not lines:
            raise ValueError(f"{path} is empty.")

        columns = lines[-1].split(self.config.delimiter)
        try:
            raw_value = columns[self.config.value_column_index]
        except IndexError as exc:
            raise IndexError(
                f"{path} has no column {self.config.value_column_index}."
            ) from exc

        try:
            return Decimal(raw_value.strip().replace(",", "."))
        except InvalidOperation as exc:
            raise ValueError(f"Could not parse measurement value {raw_value!r} in {path}.") from exc

    def delete_file(self, remote_path: str) -> None:
        if self.config.delete_with_smbclient:
            delete_remote_file_smbclient(
                server=self.config.server,
                share=self.config.share,
                username=self.config.username,
                password=self.config.password,
                remote_path=remote_path,
                min_protocol=self.config.smbclient_min_protocol,
            )
            return

        conn = self._connection_manager.get()
        conn.deleteFiles(self.config.share, remote_path)

    @staticmethod
    def clean_smb_name(name: str) -> str:
        return name.rstrip("\x00").strip()

    @staticmethod
    def processed_key(remote_path: str, payload_hash: str) -> str:
        return hashlib.sha256(f"{remote_path}\0{payload_hash}".encode()).hexdigest()

    async def _sleep_until_poll(self) -> None:
        try:
            await asyncio.wait_for(
                self._stop_event.wait(),
                timeout=self.config.poll_interval_seconds,
            )
        except TimeoutError:
            return


def _measurement_needed(context: AdapterContext, measurement_type: str | None) -> bool:
    if context.measurement_type_needed is not None:
        return context.measurement_type_needed(measurement_type)
    return context.measurement_needed is None or context.measurement_needed()


def delete_remote_file_smbclient(
    *,
    server: str,
    share: str,
    username: str,
    password: str,
    remote_path: str,
    min_protocol: str = "NT1",
) -> None:
    clean_path = remote_path.lstrip("/")
    cmd = [
        "smbclient",
        f"//{server}/{share}",
        "-U",
        f"{username}%{password}",
        f"--option=client min protocol={min_protocol}",
        "-c",
        f'del "{clean_path}"',
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            "smbclient delete failed\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )


def _load_pysmb() -> tuple[Any, Any]:
    try:
        smb_structs = importlib.import_module("smb.smb_structs")
        smb_connection = importlib.import_module("smb.SMBConnection")
    except ImportError as exc:
        raise RuntimeError(
            "SMB adapters require the optional 'pysmb' package to be installed."
        ) from exc
    return smb_structs, smb_connection
