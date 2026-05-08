import asyncio
import hashlib
from dataclasses import dataclass, replace
from decimal import Decimal

import pytest

from slf_trace.companion.adapters import AdapterContext
from slf_trace.companion.adapters.factory import smb_config_from_dict
from slf_trace.companion.adapters.smb import (
    ProcessedHashStore,
    SmbPollingAdapterConfig,
    SmbPollingMeasurementAdapter,
    delete_remote_file_smbclient,
)
from slf_trace.parsing import ParserConfig


@dataclass(frozen=True)
class FakeEntry:
    filename: str
    isDirectory: bool = False


class FakeConnection:
    def __init__(self) -> None:
        self.files = {
            "/ExcelAusgabe/result_1.csv": _csv_with_measurement("10,1"),
            "/ExcelAusgabe/result_10.csv": _csv_with_measurement("12,4"),
        }
        self.retrieved_paths: list[str] = []
        self.deleted_paths: list[str] = []

    def listPath(self, share, remote_dir):
        assert share == "MEASURE"
        assert remote_dir == "/ExcelAusgabe"
        entries = [FakeEntry(".Trash", isDirectory=True), FakeEntry("ignored.txt")]
        entries.extend(
            FakeEntry(path.rsplit("/", 1)[1]) for path in sorted(self.files)
        )
        return entries

    def retrieveFile(self, share, remote_path, buffer):
        assert share == "MEASURE"
        self.retrieved_paths.append(remote_path)
        buffer.write(self.files[remote_path])

    def deleteFiles(self, share, remote_path):
        assert share == "MEASURE"
        self.deleted_paths.append(remote_path)
        self.files.pop(remote_path, None)


class FakeConnectionManager:
    def __init__(self) -> None:
        self.conn = FakeConnection()

    def get(self):
        return self.conn

    def close(self):
        return None


def _config(tmp_path) -> SmbPollingAdapterConfig:
    return SmbPollingAdapterConfig(
        server="10.0.0.50",
        share="MEASURE",
        username="station",
        password="secret",
        measurement_type="ueberstand",
        value_column_index=13,
        rueckmeldenummer="RM-SMB",
        delete_with_smbclient=False,
        processed_hashes_path=tmp_path / "processed.json",
    )


def _csv_with_measurement(value: str) -> bytes:
    columns = [""] * 14
    columns[13] = value
    return ("header\n" + ";".join(columns) + "\n").encode("cp1252")


@pytest.mark.asyncio
async def test_smb_adapter_polls_latest_csv_and_emits_events(tmp_path) -> None:
    measurements = []
    raw_payloads = []
    manager = FakeConnectionManager()
    adapter = SmbPollingMeasurementAdapter(
        _config(tmp_path),
        connection_manager=manager,
    )

    async def emit(event):
        measurements.append(event)

    async def emit_raw_payload(event):
        raw_payloads.append(event)

    measurement_active = True

    context = AdapterContext(
        station_id=1,
        emit=emit,
        emit_raw_payload=emit_raw_payload,
        parser_config=ParserConfig(measurement_types={"ueberstand"}),
        measurement_needed=lambda: measurement_active,
    )

    assert await adapter.poll_once(context) is True
    measurement_active = False
    assert await adapter.poll_once(context) is False

    assert measurements[0].source_type == "smb1"
    assert measurements[0].rueckmeldenummer == "RM-SMB"
    assert measurements[0].values[0].measurement_type == "ueberstand"
    assert measurements[0].values[0].value == Decimal("12.4")
    assert raw_payloads[0].payload_hash
    assert manager.conn.deleted_paths == ["/ExcelAusgabe/result_10.csv"]


@pytest.mark.asyncio
async def test_smb_adapter_reports_processing_error_as_station_event(tmp_path) -> None:
    station_events = []
    manager = FakeConnectionManager()
    manager.conn.files = {"/ExcelAusgabe/result_10.csv": b"header\n1;2\n"}
    adapter = SmbPollingMeasurementAdapter(
        replace(_config(tmp_path), poll_interval_seconds=0.01),
        connection_manager=manager,
    )

    async def emit(event):
        raise AssertionError(f"unexpected measurement event: {event}")

    async def emit_station_event(event_type, severity, message, context):
        station_events.append(
            {
                "event_type": event_type,
                "severity": severity,
                "message": message,
                "context": context,
            }
        )

    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=ParserConfig(measurement_types={"ueberstand"}),
        emit_station_event=emit_station_event,
        measurement_needed=lambda: True,
    )

    task = asyncio.create_task(adapter.start(context))
    await asyncio.sleep(0.04)
    await adapter.stop()
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert station_events == [
        {
            "event_type": "adapter.smb_read_failed",
            "severity": "error",
            "message": "SMB adapter could not process the measurement file.",
            "context": {
                "adapter": "smb1-polling",
                "error": "IndexError",
                "message": "/ExcelAusgabe/result_10.csv has no column 13.",
                "server": "10.0.0.50",
                "share": "MEASURE",
                "remote_dir": "/ExcelAusgabe",
                "measurement_type": "ueberstand",
            },
        }
    ]


@pytest.mark.asyncio
async def test_smb_adapter_waits_for_measurement_request_before_reading(tmp_path) -> None:
    measurements = []
    manager = FakeConnectionManager()
    adapter = SmbPollingMeasurementAdapter(
        _config(tmp_path),
        connection_manager=manager,
    )

    async def emit(event):
        measurements.append(event)

    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=ParserConfig(measurement_types={"ueberstand"}),
        measurement_needed=lambda: False,
    )

    assert await adapter.poll_once(context) is False

    assert measurements == []
    assert manager.conn.retrieved_paths == []
    assert manager.conn.deleted_paths == []


@pytest.mark.asyncio
async def test_smb_adapter_allows_same_content_in_different_files(tmp_path) -> None:
    measurements = []
    manager = FakeConnectionManager()
    manager.conn.files = {
        "/ExcelAusgabe/result_1.csv": _csv_with_measurement("12,4"),
        "/ExcelAusgabe/result_2.csv": _csv_with_measurement("12,4"),
    }
    adapter = SmbPollingMeasurementAdapter(
        _config(tmp_path),
        connection_manager=manager,
    )

    async def emit(event):
        measurements.append(event)

    context = AdapterContext(
        station_id=1,
        emit=emit,
        parser_config=ParserConfig(measurement_types={"ueberstand"}),
        measurement_needed=lambda: True,
    )

    assert await adapter.poll_once(context) is True
    assert await adapter.poll_once(context) is True

    assert [measurement.values[0].value for measurement in measurements] == [
        Decimal("12.4"),
        Decimal("12.4"),
    ]
    assert manager.conn.deleted_paths == [
        "/ExcelAusgabe/result_2.csv",
        "/ExcelAusgabe/result_1.csv",
    ]


def test_smb_adapter_deletes_stale_processed_file(tmp_path) -> None:
    manager = FakeConnectionManager()
    adapter = SmbPollingMeasurementAdapter(
        _config(tmp_path),
        connection_manager=manager,
    )
    content = manager.conn.files["/ExcelAusgabe/result_10.csv"]
    payload_hash = hashlib.sha256(content).hexdigest()
    adapter._processed_hashes.add(  # noqa: SLF001
        adapter.processed_key("/ExcelAusgabe/result_10.csv", payload_hash)
    )

    assert adapter.read_once() is None

    assert manager.conn.deleted_paths == ["/ExcelAusgabe/result_10.csv"]


def test_smb_adapter_finds_latest_numbered_file(tmp_path) -> None:
    adapter = SmbPollingMeasurementAdapter(
        _config(tmp_path),
        connection_manager=FakeConnectionManager(),
        processed_hashes=ProcessedHashStore(),
    )

    latest = adapter.find_latest_file(FakeConnection())

    assert latest is not None
    assert latest.name == "result_10.csv"
    assert latest.path == "/ExcelAusgabe/result_10.csv"


def test_smbclient_delete_uses_configured_protocol(monkeypatch) -> None:
    calls = []

    class Result:
        returncode = 0
        stdout = ""
        stderr = ""

    def run(cmd, capture_output, text, check):
        calls.append(cmd)
        assert capture_output is True
        assert text is True
        assert check is False
        return Result()

    monkeypatch.setattr("subprocess.run", run)

    delete_remote_file_smbclient(
        server="10.0.0.50",
        share="MEASURE",
        username="station",
        password="secret",
        remote_path="/ExcelAusgabe/result_10.csv",
        min_protocol="SMB2",
    )

    assert calls[0] == [
        "smbclient",
        "//10.0.0.50/MEASURE",
        "-U",
        "station%secret",
        "--option=client min protocol=SMB2",
        "-c",
        'del "ExcelAusgabe/result_10.csv"',
    ]


def test_smb_config_uses_per_station_remote_dir_and_env_secrets(monkeypatch) -> None:
    monkeypatch.setenv("SMB_USER", "station")
    monkeypatch.setenv("SMB_PASSWORD", "secret")

    config = smb_config_from_dict(
        {
            "type": "smb1_polling",
            "server": "10.0.0.50",
            "share": "MEASURE",
            "username_env": "SMB_USER",
            "password_env": "SMB_PASSWORD",
            "measurement_type": "ueberstand",
            "value_column_index": 13,
            "remote_dir": "/CustomOutput",
        }
    )

    assert config.remote_dir == "/CustomOutput"
    assert config.username == "station"
    assert config.password == "secret"


def test_smb_config_can_enable_smb2_for_test_shares() -> None:
    config = smb_config_from_dict(
        {
            "type": "smb1_polling",
            "server": "truenas.home.io",
            "share": "agents",
            "username": "station",
            "password": "secret",
            "measurement_type": "breite",
            "value_column_index": 0,
            "support_smb2": True,
            "use_ntlm_v2": True,
            "smbclient_min_protocol": "SMB2",
        }
    )

    assert config.support_smb2 is True
    assert config.use_ntlm_v2 is True
    assert config.smbclient_min_protocol == "SMB2"
