import os
from typing import Any

from slf_trace.companion.adapters.base import MeasurementAdapter
from slf_trace.companion.adapters.scanner import (
    TcpBarcodeScannerAdapter,
    TcpBarcodeScannerAdapterConfig,
)
from slf_trace.companion.adapters.serial import (
    SerialRequestAdapterConfig,
    SerialRequestMeasurementAdapter,
)
from slf_trace.companion.adapters.smb import SmbPollingAdapterConfig, SmbPollingMeasurementAdapter
from slf_trace.companion.adapters.tcp import TcpLineAdapterConfig, TcpLineMeasurementAdapter


def build_adapters_from_config(configs: list[dict[str, Any]]) -> list[MeasurementAdapter]:
    adapters: list[MeasurementAdapter] = []
    for adapter_config in configs:
        if adapter_config.get("enabled", True) is False:
            continue

        adapter_type = str(adapter_config.get("type", "")).lower()
        if adapter_type in {"smb1", "smb1_polling", "smb"}:
            adapters.append(SmbPollingMeasurementAdapter(smb_config_from_dict(adapter_config)))
        elif adapter_type in {"serial", "serial_request", "serial_request_response"}:
            adapters.append(
                SerialRequestMeasurementAdapter(serial_request_config_from_dict(adapter_config))
            )
        elif adapter_type in {"tcp", "tcp_line", "tcp_ip"}:
            adapters.append(TcpLineMeasurementAdapter(tcp_line_config_from_dict(adapter_config)))
        else:
            raise ValueError(f"Unsupported station adapter type: {adapter_type!r}.")
    return adapters


def build_scanner_adapter_from_station_config(
    config: dict[str, Any],
) -> MeasurementAdapter | None:
    scanner_port = config.get("scanner_port")
    scanner_protocol = _optional_str(config, "scanner_protocol")
    if scanner_port in (None, "", 0):
        return None
    if scanner_protocol is not None and scanner_protocol.lower() == "none":
        return None

    return TcpBarcodeScannerAdapter(
        TcpBarcodeScannerAdapterConfig(
            listen_host="0.0.0.0",
            listen_port=_required_int(config, "scanner_port"),
            allowed_peer_host=_optional_str(config, "scanner_host"),
            name=_optional_str(config, "scanner_name") or "keyence-srx-scanner",
            source_type=_optional_str(config, "scanner_source_type") or "keyence_srx",
            encoding=_optional_str(config, "scanner_encoding") or "utf-8",
            reconnect_delay_seconds=float(config.get("scanner_reconnect_delay_seconds", 2.0)),
            heartbeat_timeout_seconds=float(config.get("scanner_heartbeat_timeout_seconds", 90.0)),
            heartbeat_check_interval_seconds=float(
                config.get("scanner_heartbeat_check_interval_seconds", 5.0)
            ),
            startup_command=_optional_str(config, "scanner_startup_command") or "LON",
            shutdown_command=_optional_str(config, "scanner_shutdown_command") or "LOFF",
            command_terminator=_decode_escape_sequences(
                _optional_str(config, "scanner_command_terminator") or "\\r\\n"
            ),
            command_host=_optional_str(config, "scanner_command_host")
            or _optional_str(config, "scanner_host"),
            command_port=int(config.get("scanner_command_port") or config.get("scanner_port")),
            command_timeout_seconds=float(config.get("scanner_command_timeout_seconds", 2.0)),
            command_hold_seconds=float(config.get("scanner_command_hold_seconds", 2.0)),
            startup_command_attempts=int(config.get("scanner_startup_command_attempts", 3)),
            startup_command_retry_seconds=float(
                config.get("scanner_startup_command_retry_seconds", 5.0)
            ),
        )
    )


def smb_config_from_dict(config: dict[str, Any]) -> SmbPollingAdapterConfig:
    return SmbPollingAdapterConfig(
        server=_required_str(config, "server"),
        share=_required_str(config, "share"),
        username=_secret_value(config, "username"),
        password=_secret_value(config, "password"),
        measurement_type=_required_str(config, "measurement_type"),
        value_column_index=_required_int(config, "value_column_index"),
        rueckmeldenummer=_optional_str(config, "rueckmeldenummer"),
        remote_dir=_optional_str(config, "remote_dir") or "/ExcelAusgabe",
        name=_optional_str(config, "name") or "smb1-polling",
        source_type=_optional_str(config, "source_type") or "smb1",
        client_name=_optional_str(config, "client_name") or "slf-trace-companion",
        server_name=_optional_str(config, "server_name"),
        port=int(config.get("port", 445)),
        timeout_seconds=float(config.get("timeout_seconds", 10.0)),
        poll_interval_seconds=float(config.get("poll_interval_seconds", 2.0)),
        encoding=_optional_str(config, "encoding") or "cp1252",
        delimiter=_optional_str(config, "delimiter") or ";",
        filename_pattern=_optional_str(config, "filename_pattern") or r"_(\d+)\.csv$",
        delete_after_success=bool(config.get("delete_after_success", True)),
        delete_with_smbclient=bool(config.get("delete_with_smbclient", True)),
        processed_hashes_path=_optional_str(config, "processed_hashes_path"),
    )


def serial_request_config_from_dict(config: dict[str, Any]) -> SerialRequestAdapterConfig:
    return SerialRequestAdapterConfig(
        port=_required_str(config, "port"),
        measurement_type=_required_str(config, "measurement_type"),
        name=_optional_str(config, "name") or "serial-request",
        source_type=_optional_str(config, "source_type") or "serial",
        rueckmeldenummer=_optional_str(config, "rueckmeldenummer"),
        command=_decode_escape_sequences(_optional_str(config, "command") or "?\\r"),
        baudrate=int(config.get("baudrate", 4800)),
        bytesize=int(config.get("bytesize", 7)),
        parity=_optional_str(config, "parity") or "E",
        stopbits=float(config.get("stopbits", 2.0)),
        timeout_seconds=float(config.get("timeout_seconds", 2.0)),
        poll_interval_seconds=float(config.get("poll_interval_seconds", 2.0)),
        encoding=_optional_str(config, "encoding") or "utf-8",
    )


def tcp_line_config_from_dict(config: dict[str, Any]) -> TcpLineAdapterConfig:
    return TcpLineAdapterConfig(
        host=_required_str(config, "host"),
        port=_required_int(config, "port"),
        measurement_type=_optional_str(config, "measurement_type"),
        name=_optional_str(config, "name") or "tcp-line",
        source_type=_optional_str(config, "source_type") or "tcp",
        rueckmeldenummer=_optional_str(config, "rueckmeldenummer"),
        command=_decode_escape_sequences(_optional_str(config, "command"))
        if _optional_str(config, "command") is not None
        else None,
        poll_interval_seconds=float(config.get("poll_interval_seconds", 1.0)),
        reconnect_delay_seconds=float(config.get("reconnect_delay_seconds", 2.0)),
        encoding=_optional_str(config, "encoding") or "utf-8",
    )


def _required_str(config: dict[str, Any], key: str) -> str:
    value = _optional_str(config, key)
    if value is None:
        raise ValueError(f"Missing required SMB adapter config value: {key}.")
    return value


def _required_int(config: dict[str, Any], key: str) -> int:
    if key not in config:
        raise ValueError(f"Missing required SMB adapter config value: {key}.")
    return int(config[key])


def _optional_str(config: dict[str, Any], key: str) -> str | None:
    value = config.get(key)
    if value is None or str(value).strip() == "":
        return None
    return str(value)


def _decode_escape_sequences(value: str) -> str:
    return bytes(value, "utf-8").decode("unicode_escape")


def _secret_value(config: dict[str, Any], key: str) -> str:
    value = _optional_str(config, key)
    env_name = _optional_str(config, f"{key}_env")
    if value is not None:
        return value
    if env_name is not None:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value
        raise ValueError(f"Environment variable {env_name!r} is not set.")
    raise ValueError(f"Missing required SMB adapter config value: {key} or {key}_env.")
