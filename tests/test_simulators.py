import asyncio
from decimal import Decimal

import httpx
import pytest

from slf_trace import simulators


def test_keyence_frame_uses_line_terminated_ascii() -> None:
    assert simulators.keyence_frame("RM-123") == b"RM-123\r\n"


def test_smb_payload_places_decimal_comma_in_configured_column() -> None:
    payload = simulators.smb_csv_payload(Decimal("12.4"), value_column_index=3)

    assert payload.splitlines()[-1] == ";;;12,4"


def test_write_smb_payload_file_creates_numbered_csv(tmp_path) -> None:
    path = simulators.write_smb_payload_file(
        tmp_path,
        value=Decimal("10.5"),
        value_column_index=2,
        sequence=9,
    )

    assert path.name == "result_9.csv"
    assert path.read_text(encoding="cp1252").splitlines()[-1] == ";;10,5"


@pytest.mark.asyncio
async def test_keyence_simulator_sends_frame_to_tcp_listener() -> None:
    frames = []

    async def handle(reader, writer):
        frames.append(await reader.readline())
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    host, port = server.sockets[0].getsockname()
    try:
        await simulators.send_keyence_frame(host=host, port=port, barcode="RM-TCP-1")
    finally:
        server.close()
        await server.wait_closed()

    assert frames == [b"RM-TCP-1\r\n"]


@pytest.mark.asyncio
async def test_api_simulator_posts_scan_then_measurement(monkeypatch) -> None:
    requests = []

    class FakeResponse:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class FakeClient:
        def __init__(self, *, base_url, timeout):
            assert base_url == "http://server"
            assert timeout == 10.0

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, path, json):
            requests.append((path, json))
            if path.endswith("barcode-scans"):
                return FakeResponse({"part_id": 1, "created": True})
            return FakeResponse({"measurement_id": 2, "duplicate": False})

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    response = await simulators.post_api_scan_and_measurement(
        server_url="http://server",
        station_id=1,
        rueckmeldenummer="RM-API-1",
        measurement_type="breite",
        value=Decimal("12.4"),
        idempotency_key="fixed-key",
    )

    assert requests[0][0] == "/api/companion/barcode-scans"
    assert requests[0][1]["raw_payload"] == "RM-API-1"
    assert requests[1][0] == "/api/companion/measurements"
    assert requests[1][1]["idempotency_key"] == "fixed-key"
    assert requests[1][1]["values"][0]["measurement_type"] == "breite"
    assert response["measurement"] == {"measurement_id": 2, "duplicate": False}
