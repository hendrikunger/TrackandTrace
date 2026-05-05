from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from slf_trace.api.schemas.companion import MeasurementRequest
from slf_trace.api.services import companion as companion_services
from slf_trace.companion.adapters.base import (
    BarcodeScanEvent,
    MeasurementEvent,
    MeasurementEventValue,
)
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
        self.measurement_requests = []
        self.station_config_calls = []
        self.heartbeats = []
        self.events = []
        self.barcode_scans = []

    async def fetch_station_config(self, station_id: int):
        self.station_config_calls.append(station_id)
        return {
            "station_id": station_id,
            "name": "Station 1",
            "scanner_host": None,
            "scanner_port": None,
            "scanner_protocol": None,
            "measurement_types": [],
        }

    async def fetch_measurement_request(self, station_id: int, after_id: int):
        for request in self.measurement_requests:
            if request["request_id"] > after_id:
                return request
        return {"request_id": None, "rueckmeldenummer": None}

    async def post_heartbeat(self, payload):
        self.heartbeats.append(payload)
        return {"status": "accepted", "heartbeat_id": 1, "station_id": payload["station_id"]}

    async def post_event(self, endpoint, payload):
        if self.fail_first_event:
            self.fail_first_event = False
            raise httpx.ConnectError("offline")
        self.events.append((endpoint, payload))
        if endpoint == "/api/companion/barcode-scans":
            self.barcode_scans.append(payload)
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
    assert payload["hostname"]
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
        "scanner_host": "10.0.0.21",
        "scanner_port": 9004,
        "scanner_protocol": "Keyence SR-X TCP",
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

    assert len(runtime.adapters) == 2
    assert runtime.adapters[0].name == "smb1-polling"
    assert runtime.adapters[1].name == "keyence-srx-scanner"


def test_runtime_queues_barcode_scan_events(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.enqueue_barcode_scan_event(
        BarcodeScanEvent(
            station_id=1,
            source_type="keyence_srx",
            rueckmeldenummer="RM-1",
            raw_payload="RM-1",
        )
    )

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/barcode-scans"
    assert queued[0].payload["rueckmeldenummer"] == "RM-1"


@pytest.mark.asyncio
async def test_runtime_attaches_measurement_request_to_measurement_events(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 17, "rueckmeldenummer": "RM-SCAN"}
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    assert await runtime.fetch_measurement_request_once()
    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="tcp",
            measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-1",
            values=[
                MeasurementEventValue(
                    measurement_type="breite",
                    value=Decimal("12.3"),
                    unit="mm",
                )
            ],
        )
    )

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/measurements"
    assert queued[0].payload["rueckmeldenummer"] == "RM-SCAN"
    assert runtime.latest_rueckmeldenummer is None


@pytest.mark.asyncio
async def test_runtime_barcode_scan_does_not_request_measurement(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())

    await runtime.handle_barcode_scan_event(
        BarcodeScanEvent(
            station_id=1,
            source_type="keyence_srx",
            rueckmeldenummer="RM-SCAN",
        )
    )

    assert runtime.latest_rueckmeldenummer is None


@pytest.mark.asyncio
async def test_runtime_ignores_measurement_events_without_barcode(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())

    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="tcp",
            measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-1",
            values=[
                MeasurementEventValue(
                    measurement_type="breite",
                    value=Decimal("12.3"),
                    unit="mm",
                )
            ],
        )
    )

    assert runtime.outbox.count() == 0


def test_runtime_queues_station_diagnostic_events(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())

    runtime.enqueue_station_event(
        event_type="adapter.connection_failed",
        severity="error",
        message="Scanner connection failed.",
        context={"adapter": "keyence-srx-scanner"},
    )

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/events"
    assert queued[0].payload["station_id"] == 1
    assert queued[0].payload["event_type"] == "adapter.connection_failed"
    assert queued[0].payload["context"] == {"adapter": "keyence-srx-scanner"}


@pytest.mark.asyncio
async def test_record_measurement_returns_existing_duplicate(monkeypatch) -> None:
    calls = {"resolve_part": 0, "add": 0, "flush": 0}
    existing = SimpleNamespace(
        id=7,
        station_id=1,
        part_id=11,
        idempotency_key="same-event",
        values=[],
    )

    async def get_station_or_404(session, station_id):
        return SimpleNamespace(id=station_id)

    async def validate_measurement_types(session, payload):
        return None

    async def find_measurement_by_idempotency(session, *, station_id, idempotency_key):
        assert station_id == 1
        assert idempotency_key == "same-event"
        return existing

    async def resolve_measurement_part(session, payload):
        calls["resolve_part"] += 1
        return SimpleNamespace(id=11)

    class FakeSession:
        def add(self, item):
            calls["add"] += 1

        async def flush(self):
            calls["flush"] += 1

    monkeypatch.setattr(companion_services, "get_station_or_404", get_station_or_404)
    monkeypatch.setattr(
        companion_services,
        "validate_measurement_types",
        validate_measurement_types,
    )
    monkeypatch.setattr(
        companion_services,
        "find_measurement_by_idempotency",
        find_measurement_by_idempotency,
    )
    monkeypatch.setattr(companion_services, "resolve_measurement_part", resolve_measurement_part)

    measurement, duplicate = await companion_services.record_measurement(
        FakeSession(),
        MeasurementRequest(
            station_id=1,
            idempotency_key="same-event",
            source_type="api_simulator",
            measured_at=datetime.now(UTC),
            rueckmeldenummer="RM-1",
            values=[{"measurement_type": "breite", "value": "12.4"}],
        ),
    )

    assert measurement is existing
    assert duplicate is True
    assert calls == {"resolve_part": 0, "add": 0, "flush": 0}
