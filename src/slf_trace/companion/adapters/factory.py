import os
from typing import Any

from slf_trace.companion.adapters.base import MeasurementAdapter
from slf_trace.companion.adapters.smb import SmbPollingAdapterConfig, SmbPollingMeasurementAdapter


def build_adapters_from_config(configs: list[dict[str, Any]]) -> list[MeasurementAdapter]:
    adapters: list[MeasurementAdapter] = []
    for adapter_config in configs:
        if adapter_config.get("enabled", True) is False:
            continue

        adapter_type = str(adapter_config.get("type", "")).lower()
        if adapter_type in {"smb1", "smb1_polling", "smb"}:
            adapters.append(SmbPollingMeasurementAdapter(smb_config_from_dict(adapter_config)))
        else:
            raise ValueError(f"Unsupported station adapter type: {adapter_type!r}.")
    return adapters


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
        delete_after_success=bool(config.get("delete_after_success", False)),
        delete_with_smbclient=bool(config.get("delete_with_smbclient", True)),
        processed_hashes_path=_optional_str(config, "processed_hashes_path"),
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
