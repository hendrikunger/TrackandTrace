import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from slf_trace.api.schemas.companion import MeasurementRequest
from slf_trace.api.services import companion as companion_services
from slf_trace.companion.adapters.base import (
    AdapterContext,
    AdapterState,
    AdapterStatus,
    BarcodeScanEvent,
    MeasurementAdapter,
    MeasurementEvent,
    MeasurementEventValue,
)
from slf_trace.companion.adapters.simulator import (
    SimulatorAdapterConfig,
    SimulatorMeasurementAdapter,
)
from slf_trace.companion.outbox import Outbox
from slf_trace.companion.runtime import (
    CompanionRuntime,
    CompanionRuntimeConfig,
    config_from_settings,
    normalize_workflow_type,
)
from slf_trace.config import Settings


class FakeClient:
    def __init__(
        self,
        *,
        fail_first_event: bool = False,
        fail_barcode_scan: bool = False,
        fail_station_config_calls: int = 0,
        fail_measurement_request: bool = False,
        fail_heartbeat: bool = False,
        station_config: dict | None = None,
        part_measurement_values: dict | None = None,
    ) -> None:
        self.fail_first_event = fail_first_event
        self.fail_barcode_scan = fail_barcode_scan
        self.fail_station_config_calls = fail_station_config_calls
        self.fail_measurement_request = fail_measurement_request
        self.fail_heartbeat = fail_heartbeat
        self.measurement_requests = []
        self.station_config_calls = []
        self.heartbeats = []
        self.events = []
        self.barcode_scans = []
        self.part_measurement_value_requests = []
        self.part_measurement_values = part_measurement_values or {
            "part_id": 1,
            "rueckmeldenummer": "RM-SCAN",
            "values": [],
        }
        self.station_config = station_config or {
            "station_id": 1,
            "name": "Station 1",
            "scanner_host": None,
            "scanner_port": None,
            "scanner_protocol": None,
            "measurement_types": [],
        }

    async def fetch_station_config(self, station_id: int):
        self.station_config_calls.append(station_id)
        if self.fail_station_config_calls > 0:
            self.fail_station_config_calls -= 1
            raise httpx.ConnectError("offline")
        return {**self.station_config, "station_id": station_id}

    async def fetch_measurement_request(self, station_id: int, after_id: int):
        if self.fail_measurement_request:
            raise httpx.ConnectError("offline")
        for request in self.measurement_requests:
            if request["request_id"] > after_id:
                return request
        return {"request_id": None, "rueckmeldenummer": None}

    async def fetch_part_measurement_values(self, station_id: int, rueckmeldenummer: str):
        self.part_measurement_value_requests.append((station_id, rueckmeldenummer))
        return {**self.part_measurement_values, "rueckmeldenummer": rueckmeldenummer}

    async def post_heartbeat(self, payload):
        if self.fail_heartbeat:
            raise httpx.ConnectError("offline")
        self.heartbeats.append(payload)
        return {"status": "accepted", "heartbeat_id": 1, "station_id": payload["station_id"]}

    async def post_event(self, endpoint, payload):
        if self.fail_barcode_scan and endpoint == "/api/companion/barcode-scans":
            raise httpx.ConnectError("offline")
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


class CrashingAdapter(MeasurementAdapter):
    name = "crashing-adapter"

    def __init__(self) -> None:
        self.starts = 0

    async def start(self, context: AdapterContext) -> None:
        self.starts += 1
        raise RuntimeError("adapter boom")

    async def stop(self) -> None:
        return None

    def health(self) -> AdapterStatus:
        return AdapterStatus(name=self.name, state=AdapterState.DEGRADED)


def test_config_from_settings_requires_station_id() -> None:
    with pytest.raises(ValueError, match="STATION_ID"):
        config_from_settings(Settings(station_id=None))


def test_config_from_settings_parses_station_id() -> None:
    config = config_from_settings(
        Settings(
            station_id="42",
            server_url="http://server",
            companion_state_path="state.sqlite3",
            companion_config_poll_interval_seconds=12.5,
            station_token="station-secret",
        )
    )

    assert config.station_id == 42
    assert config.server_url == "http://server"
    assert config.config_poll_interval_seconds == 12.5
    assert config.station_token == "station-secret"


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
async def test_runtime_bootstrap_retries_station_config_when_api_is_unavailable(
    tmp_path,
) -> None:
    client = FakeClient(fail_station_config_calls=2)
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    await runtime.bootstrap_until_ready()

    assert runtime.station_config is not None
    assert client.station_config_calls == [1, 1, 1]


@pytest.mark.asyncio
async def test_runtime_detects_station_config_change(tmp_path) -> None:
    client = FakeClient(
        station_config={
            "station_id": 1,
            "name": "Station 1",
            "workflow_type": "measurement_capture",
            "scanner_host": None,
            "scanner_port": None,
            "scanner_protocol": None,
            "adapters": [{"type": "tcp_line", "name": "tcp-1", "enabled": False}],
            "measurement_types": [],
        }
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    await runtime.fetch_station_config()
    assert await runtime.refresh_station_config_once() is False
    assert runtime.config_reload_event.is_set() is False

    client.station_config = {
        **client.station_config,
        "adapters": [{"type": "tcp_line", "name": "tcp-1", "enabled": True}],
    }

    assert await runtime.refresh_station_config_once() is True
    assert runtime.config_reload_event.is_set() is True


@pytest.mark.asyncio
async def test_runtime_reuses_scanner_when_only_measurement_adapters_change(
    tmp_path,
    monkeypatch,
) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "name": "Station 1",
        "workflow_type": "measurement_capture",
        "scanner_host": "10.0.0.21",
        "scanner_port": 9004,
        "scanner_protocol": "Keyence SR-X TCP",
        "adapters": [{"type": "tcp_line", "name": "tcp-1", "enabled": False}],
        "measurement_types": [],
    }

    async def fake_run_adapters(adapters=None):
        await asyncio.Future()

    monkeypatch.setattr(runtime, "run_adapters", fake_run_adapters)

    await runtime.ensure_scanner_runtime()
    first_scanner = runtime.active_scanner_adapter
    first_task = runtime.active_scanner_task

    runtime.station_config = {
        **runtime.station_config,
        "adapters": [{"type": "tcp_line", "name": "tcp-1", "enabled": True}],
    }
    await runtime.ensure_scanner_runtime()

    assert runtime.active_scanner_adapter is first_scanner
    assert runtime.active_scanner_task is first_task

    await runtime.stop_scanner_runtime()


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
        "workflow_type": "Measurement capture",
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


def test_runtime_skips_measurement_adapters_for_non_measurement_workflow(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("SMB_USER", "station")
    monkeypatch.setenv("SMB_PASSWORD", "secret")
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "name": "Laser 1",
        "workflow_type": "laser_marking",
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

    assert len(runtime.adapters) == 1
    assert runtime.adapters[0].name == "keyence-srx-scanner"
    assert not runtime.is_measurement_capture_workflow()
    assert runtime.build_heartbeat_payload()["adapter_status"]["workflow_type"] == "laser_marking"


def test_runtime_starts_scanner_for_laser_marking_workflow(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "name": "Laser 1",
        "workflow_type": "laser_marking",
        "scanner_host": "10.0.0.21",
        "scanner_port": 9004,
        "scanner_protocol": "Keyence SR-X TCP",
    }

    runtime.configure_adapters_from_station_config()

    assert len(runtime.adapters) == 1
    assert runtime.adapters[0].name == "keyence-srx-scanner"


def test_runtime_starts_scanner_only_for_label_printing_workflow(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "name": "Label 1",
        "workflow_type": "label_printing",
        "scanner_host": "10.0.0.21",
        "scanner_port": 9004,
        "scanner_protocol": "Keyence SR-X TCP",
        "adapters": [{"type": "printer_stub", "name": "printer-stub"}],
    }

    runtime.configure_adapters_from_station_config()

    assert len(runtime.adapters) == 1
    assert runtime.adapters[0].name == "keyence-srx-scanner"
    assert runtime.build_heartbeat_payload()["adapter_status"]["workflow_type"] == "label_printing"


def test_workflow_type_normalizes_display_labels() -> None:
    assert normalize_workflow_type("Measurement capture") == "measurement_capture"
    assert normalize_workflow_type("Laser marking") == "laser_marking"
    assert normalize_workflow_type("label-printing") == "label_printing"


def test_runtime_records_adapter_configuration_failure_without_raising(tmp_path) -> None:
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=FakeClient())
    runtime.station_config = {
        "station_id": 1,
        "adapters": [
            {
                "type": "smb1_polling",
                "server": "10.0.0.50",
                "share": "MEASURE",
                "username_env": "MISSING_SMB_USER",
                "password_env": "MISSING_SMB_PASSWORD",
                "measurement_type": "ueberstand",
                "value_column_index": 13,
            }
        ],
    }

    assert runtime.configure_adapters_safely() is False
    assert runtime.adapters == []

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/events"
    assert queued[0].payload["event_type"] == "adapter.configuration_failed"


def test_companion_service_uses_enabled_adapter_measurement_type_codes() -> None:
    assert companion_services.enabled_adapter_measurement_type_codes(
        [
            {"enabled": True, "measurement_type": "breite"},
            {"enabled": False, "measurement_type": "innenring"},
            {"measurement_type": "breite"},
            {"enabled": True, "measurement_type": ""},
        ]
    ) == {"breite"}


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
async def test_runtime_aggregates_adapter_values_for_one_measurement_request(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 17, "rueckmeldenummer": "RM-SCAN"}
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
            {"code": "ueberstand", "label": "Überstand", "unit": "mm"},
        ]
    }

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

    assert runtime.outbox.count() == 0
    assert runtime.latest_rueckmeldenummer == "RM-SCAN"

    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="smb1",
            measured_at=datetime(2026, 4, 28, 15, 0, 1, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-2",
            values=[
                MeasurementEventValue(
                    measurement_type="ueberstand",
                    value=Decimal("1.5"),
                    unit="mm",
                )
            ],
        )
    )

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/measurements"
    assert queued[0].payload["rueckmeldenummer"] == "RM-SCAN"
    assert queued[0].payload["source_type"] == "companion_aggregate"
    assert queued[0].payload["idempotency_key"] == "measurement_request:1:17"
    assert queued[0].payload["values"] == [
        {
            "measurement_type": "breite",
            "value": "12.3",
            "unit": "mm",
            "result_status": None,
        },
        {
            "measurement_type": "ueberstand",
            "value": "1.5",
            "unit": "mm",
            "result_status": None,
        },
    ]
    assert runtime.latest_rueckmeldenummer is None


@pytest.mark.asyncio
async def test_runtime_reports_partial_measurement_progress_in_heartbeat(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 18, "rueckmeldenummer": "RM-PROGRESS"}
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
            {"code": "innenring", "label": "Innenring", "unit": "mm"},
        ]
    }

    assert await runtime.fetch_measurement_request_once()
    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="smb1",
            measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-progress-1",
            values=[
                MeasurementEventValue(
                    measurement_type="breite",
                    value=Decimal("77.7"),
                    unit="mm",
                )
            ],
        )
    )

    progress = client.heartbeats[0]["adapter_status"]["active_measurement_request"]
    assert progress["request_id"] == 18
    assert progress["rueckmeldenummer"] == "RM-PROGRESS"
    assert progress["received_measurement_types"] == ["breite"]
    assert progress["missing_measurement_types"] == ["innenring"]
    assert progress["values"][0]["value"] == "77.7"


@pytest.mark.asyncio
async def test_runtime_reports_only_missing_measurement_types_as_needed(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 19, "rueckmeldenummer": "RM-NEEDED"}
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
            {"code": "innenring", "label": "Innenring", "unit": "mm"},
        ]
    }

    assert await runtime.fetch_measurement_request_once()
    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="tcp",
            measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-needed-1",
            values=[
                MeasurementEventValue(
                    measurement_type="innenring",
                    value=Decimal("56.7"),
                    unit="mm",
                )
            ],
        )
    )

    assert runtime.measurement_type_needed("breite")
    assert not runtime.measurement_type_needed("innenring")


@pytest.mark.asyncio
async def test_runtime_expects_only_enabled_adapter_measurement_types(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 20, "rueckmeldenummer": "RM-DISABLED-ADAPTER"}
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
            {"code": "innenring", "label": "Innenring", "unit": "mm"},
        ],
        "adapters": [
            {
                "type": "smb1_polling",
                "enabled": True,
                "measurement_type": "breite",
            },
            {
                "type": "tcp_line",
                "enabled": False,
                "measurement_type": "innenring",
            },
        ],
    }

    assert runtime.expected_measurement_types() == {"breite"}
    assert await runtime.fetch_measurement_request_once()
    await runtime.handle_adapter_event(
        MeasurementEvent(
            station_id=1,
            source_type="smb1",
            measured_at=datetime(2026, 4, 28, 15, 0, tzinfo=UTC),
            rueckmeldenummer=None,
            idempotency_key="measurement-disabled-adapter-1",
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
    assert len(queued) == 1
    assert queued[0].endpoint == "/api/companion/measurements"
    assert queued[0].payload["rueckmeldenummer"] == "RM-DISABLED-ADAPTER"
    assert queued[0].payload["values"][0]["measurement_type"] == "breite"
    assert runtime.pending_measurement_request is None


@pytest.mark.asyncio
async def test_runtime_submits_partial_measurement_after_timeout(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 18, "rueckmeldenummer": "RM-PARTIAL"}
    )
    config = _config(str(tmp_path / "state.sqlite3"))
    config = CompanionRuntimeConfig(
        station_id=config.station_id,
        server_url=config.server_url,
        state_path=config.state_path,
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        outbox_retry_interval_seconds=config.outbox_retry_interval_seconds,
        measurement_aggregation_timeout_seconds=0.0,
    )
    runtime = CompanionRuntime(config, client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
            {"code": "ueberstand", "label": "Überstand", "unit": "mm"},
        ]
    }

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

    assert runtime.pending_request_timed_out()
    runtime.submit_pending_measurement(reason="timeout")

    queued = runtime.outbox.pending()
    assert queued[0].endpoint == "/api/companion/events"
    assert queued[0].payload["event_type"] == "measurement.partial"
    assert queued[1].endpoint == "/api/companion/measurements"
    assert queued[1].payload["rueckmeldenummer"] == "RM-PARTIAL"
    assert queued[1].payload["values"][0]["measurement_type"] == "breite"


@pytest.mark.asyncio
async def test_runtime_keeps_empty_measurement_request_open_after_timeout(tmp_path) -> None:
    client = FakeClient()
    client.measurement_requests.append(
        {"request_id": 19, "rueckmeldenummer": "RM-WAIT-FOR-SMB"}
    )
    config = _config(str(tmp_path / "state.sqlite3"))
    config = CompanionRuntimeConfig(
        station_id=config.station_id,
        server_url=config.server_url,
        state_path=config.state_path,
        heartbeat_interval_seconds=config.heartbeat_interval_seconds,
        outbox_retry_interval_seconds=config.outbox_retry_interval_seconds,
        measurement_aggregation_timeout_seconds=0.0,
    )
    runtime = CompanionRuntime(config, client=client)
    runtime.station_config = {
        "measurement_types": [
            {"code": "breite", "label": "Breite", "unit": "mm"},
        ]
    }

    assert await runtime.fetch_measurement_request_once()

    assert not runtime.pending_request_timed_out()
    assert runtime.measurement_needed()
    assert runtime.latest_rueckmeldenummer == "RM-WAIT-FOR-SMB"
    assert runtime.outbox.count() == 0


@pytest.mark.asyncio
async def test_runtime_barcode_scan_does_not_request_measurement(tmp_path) -> None:
    client = FakeClient()
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    await runtime.handle_barcode_scan_event(
        BarcodeScanEvent(
            station_id=1,
            source_type="keyence_srx",
            rueckmeldenummer="RM-SCAN",
        )
    )

    assert runtime.latest_rueckmeldenummer is None
    assert len(client.barcode_scans) == 1
    assert runtime.outbox.count() == 0


@pytest.mark.asyncio
async def test_runtime_barcode_scan_queues_when_immediate_send_fails(tmp_path) -> None:
    runtime = CompanionRuntime(
        _config(str(tmp_path / "state.sqlite3")),
        client=FakeClient(fail_barcode_scan=True),
    )

    await runtime.handle_barcode_scan_event(
        BarcodeScanEvent(
            station_id=1,
            source_type="keyence_srx",
            rueckmeldenummer="RM-SCAN",
        )
    )

    queued = runtime.outbox.pending()
    assert len(queued) == 1
    assert queued[0].endpoint == "/api/companion/barcode-scans"
    assert queued[0].payload["rueckmeldenummer"] == "RM-SCAN"


@pytest.mark.asyncio
async def test_runtime_writes_laser_output_file_after_scan(tmp_path) -> None:
    output_dir = tmp_path / "laser"
    client = FakeClient(
        part_measurement_values={
            "part_id": 17,
            "rueckmeldenummer": "RM-LASER",
            "values": [
                {"measurement_type": "measurement_1", "value": "value_1"},
                {"measurement_type": "measurement_2", "value": "value_2"},
            ],
        }
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)
    runtime.station_config = {
        "workflow_type": "laser_marking",
        "workflow_config": {"laser_output": {"path": str(output_dir)}},
    }

    await runtime.handle_barcode_scan_event(
        BarcodeScanEvent(
            station_id=1,
            source_type="keyence_srx",
            rueckmeldenummer="RM-LASER",
        )
    )

    assert client.part_measurement_value_requests == [(1, "RM-LASER")]
    assert (output_dir / "RM-LASER.txt").read_text(encoding="utf-8") == (
        "measurement_1\nvalue_1\nmeasurement_2\nvalue_2\n"
    )


@pytest.mark.asyncio
async def test_runtime_syncs_measurement_request_cursor_without_accepting_old_requests(
    tmp_path,
) -> None:
    client = FakeClient()
    client.measurement_requests.extend(
        [
            {"request_id": 3, "rueckmeldenummer": "RM-OLD-1"},
            {"request_id": 4, "rueckmeldenummer": "RM-OLD-2"},
        ]
    )
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    await runtime.sync_measurement_request_cursor()

    assert runtime.last_measurement_request_id == 4
    assert runtime.latest_rueckmeldenummer is None


@pytest.mark.asyncio
async def test_runtime_sync_cursor_keeps_running_when_server_is_unavailable(tmp_path) -> None:
    runtime = CompanionRuntime(
        _config(str(tmp_path / "state.sqlite3")),
        client=FakeClient(fail_measurement_request=True),
    )

    await runtime.sync_measurement_request_cursor()

    assert runtime.last_measurement_request_id == 0
    assert runtime.pending_measurement_request is None


@pytest.mark.asyncio
async def test_runtime_keeps_running_when_measurement_request_poll_fails(tmp_path) -> None:
    runtime = CompanionRuntime(
        _config(str(tmp_path / "state.sqlite3")),
        client=FakeClient(fail_measurement_request=True),
    )

    assert not await runtime.fetch_measurement_request_once()
    assert runtime.last_measurement_request_id == 0
    assert runtime.pending_measurement_request is None


@pytest.mark.asyncio
async def test_runtime_heartbeat_loop_keeps_running_when_server_is_unavailable(tmp_path) -> None:
    client = FakeClient(fail_heartbeat=True)
    runtime = CompanionRuntime(_config(str(tmp_path / "state.sqlite3")), client=client)

    task = asyncio.create_task(runtime.run_heartbeat_loop())
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert not task.done() or task.cancelled()
    assert client.heartbeats == []


@pytest.mark.asyncio
async def test_runtime_adapter_supervisor_restarts_crashing_adapter(tmp_path) -> None:
    adapter = CrashingAdapter()
    runtime = CompanionRuntime(
        _config(str(tmp_path / "state.sqlite3")),
        client=FakeClient(),
        adapters=[adapter],
    )
    context = AdapterContext(
        station_id=1,
        emit=runtime.handle_adapter_event,
        parser_config=runtime._parser_config_from_station_config(),
    )

    task = asyncio.create_task(runtime.run_adapter_supervisor(adapter, context))
    await asyncio.sleep(0.03)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    queued = runtime.outbox.pending()
    assert adapter.starts > 1
    assert queued[0].endpoint == "/api/companion/events"
    assert queued[0].payload["event_type"] == "adapter.failure"
    assert queued[0].payload["context"] == {
        "adapter": "crashing-adapter",
        "error": "RuntimeError",
    }


@pytest.mark.asyncio
async def test_runtime_keeps_running_after_one_shot_simulator_completes(tmp_path) -> None:
    runtime = CompanionRuntime(
        _config(str(tmp_path / "state.sqlite3")),
        client=FakeClient(),
        adapters=[
            SimulatorMeasurementAdapter(
                SimulatorAdapterConfig(payload="breite=1.2", rueckmeldenummer="RM-SIM")
            )
        ],
    )
    runtime.station_config = {
        "measurement_types": [{"code": "breite", "label": "Breite", "unit": "mm"}]
    }

    task = asyncio.create_task(runtime.run_adapters())
    await asyncio.sleep(0.03)

    assert not task.done()
    assert runtime.outbox.count() == 1

    task.cancel()
    await asyncio.gather(task, return_exceptions=True)


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
