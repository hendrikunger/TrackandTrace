from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from slf_trace.companion.adapters.base import MeasurementEvent, MeasurementEventValue
from slf_trace.companion.outbox import Outbox
from slf_trace.companion.runtime import (
    CompanionRuntime,
    CompanionRuntimeConfig,
    config_from_settings,
)
from slf_trace.config import Settings


class FakeClient:
    def __init__(self, *, fail_first_event: bool = False) -> None:
        self.fail_first_event = fail_first_event
        self.station_config_calls = []
        self.heartbeats = []
        self.events = []

    async def fetch_station_config(self, station_id: int):
        self.station_config_calls.append(station_id)
        return {"station_id": station_id, "name": "Station 1", "measurement_types": []}

    async def post_heartbeat(self, payload):
        self.heartbeats.append(payload)
        return {"status": "accepted", "heartbeat_id": 1, "station_id": payload["station_id"]}

    async def post_event(self, endpoint, payload):
        if self.fail_first_event:
            self.fail_first_event = False
            raise httpx.ConnectError("offline")
        self.events.append((endpoint, payload))
        return {"status": "accepted"}


def _config(state_path: str) -> CompanionRuntimeConfig:
    return CompanionRuntimeConfig(
        station_id=1,
        server_url="http://localhost:8000",
        state_path=state_path,
        heartbeat_interval_seconds=0.01,
        outbox_retry_interval_seconds=0.01,
    )


def test_config_from_settings_requires_station_id() -> None:
    with pytest.raises(ValueError, match="STATION_ID"):
        config_from_settings(Settings(station_id=None))


def test_config_from_settings_parses_station_id() -> None:
    config = config_from_settings(
        Settings(
            station_id="42",
            server_url="http://server",
            companion_state_path="state.sqlite3",
        )
    )

    assert config.station_id == 42
    assert config.server_url == "http://server"


def test_outbox_persists_events(tmp_path) -> None:
    path = tmp_path / "outbox.sqlite3"
    outbox = Outbox(path)

    event_id = outbox.enqueue("/api/companion/measurements", {"idempotency_key": "abc"})

    restarted_outbox = Outbox(path)
    assert restarted_outbox.count() == 1
    assert restarted_outbox.pending()[0].id == event_id
    assert restarted_outbox.pending()[0].payload == {"idempotency_key": "abc"}


@pytest.mark.asyncio
async def test_runtime_builds_heartbeat_payload(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())

    payload = runtime.build_heartbeat_payload(status="starting")

    assert payload["station_id"] == 1
    assert payload["status"] == "starting"
    assert payload["companion_version"]
    assert payload["adapter_status"]["outbox_pending"] == 0


@pytest.mark.asyncio
async def test_runtime_fetches_config_and_sends_heartbeat(tmp_path) -> None:
    client = FakeClient()
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    config = await runtime.fetch_station_config()
    response = await runtime.send_heartbeat(status="online")

    assert config["station_id"] == 1
    assert response["status"] == "accepted"
    assert client.station_config_calls == [1]
    assert client.heartbeats[0]["status"] == "online"


@pytest.mark.asyncio
async def test_runtime_retries_outbox_events(tmp_path) -> None:
    client = FakeClient(fail_first_event=True)
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.enqueue_event("/api/companion/measurements", {"idempotency_key": "abc"})

    assert await runtime.flush_outbox_once() == 0
    assert runtime.outbox.count() == 1

    assert await runtime.flush_outbox_once() == 1
    assert runtime.outbox.count() == 0
    assert client.events == [("/api/companion/measurements", {"idempotency_key": "abc"})]


def test_runtime_queues_measurement_events(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    event = MeasurementEvent(
        station_id=1,
        source_type="simulator",
        measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
        rueckmeldenummer="RM-1",
        idempotency_key="measurement-1",
        values=[
            MeasurementEventValue(
                measurement_type="breite",
                value=Decimal("12.3"),
                unit="mm",
            )
        ],
    )

    runtime.enqueue_measurement_event(event)

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/measurements"
    assert queued[0].payload["idempotency_key"] == "measurement-1"
    assert queued[0].payload["values"] == [
        {
            "measurement_type": "breite",
            "value": "12.3",
            "unit": "mm",
            "result_status": None,
        }
    ]


def test_runtime_builds_adapters_from_station_config(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("SMB_USER", "station")
    monkeypatch.setenv("SMB_PASSWORD", "secret")
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "name": "Station 1",
        "adapters": [
            {
                "type": "smb1_polling",
                "server": "10.0.0.50",
                "share": "MEASURE",
                "username_env": "SMB_USER",
                "password_env": "SMB_PASSWORD",
                "measurement_type": "ueberstand",
                "value_column_index": 13,
                "remote_dir": "/ExcelAusgabe",
            }
        ],
    }

    runtime.configure_adapters_from_station_config()

    assert len(runtime.adapters) == 1
    assert runtime.adapters[0].name == "smb1-polling"
