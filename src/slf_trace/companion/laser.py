import asyncio
import os
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from string import Formatter
from typing import Any


@dataclass(frozen=True)
class LaserMeasurementValue:
    measurement_type: str
    value: str


@dataclass(frozen=True)
class LaserOutputTarget:
    filename_template: str = "{rueckmeldenummer}.txt"
    encoding: str = "utf-8"
    newline: str = "\n"
    path: str | None = None
    smb: dict[str, Any] | None = None

    @classmethod
    def from_workflow_config(cls, workflow_config: dict[str, Any]) -> "LaserOutputTarget":
        raw_output = workflow_config.get("laser_output") or workflow_config
        output = raw_output if isinstance(raw_output, dict) else {}
        filename_template = str(
            output.get("filename_template")
            or output.get("output_filename_template")
            or workflow_config.get("laser_output_filename_template")
            or "{rueckmeldenummer}.txt"
        )
        path = output.get("path") or output.get("output_path") or output.get("output_dir")
        return cls(
            filename_template=filename_template,
            encoding=str(output.get("encoding") or "utf-8"),
            newline=str(output.get("newline") or "\n"),
            path=str(path) if path else None,
            smb=output.get("smb") if isinstance(output.get("smb"), dict) else None,
        )

    def validate(self) -> None:
        if self.path is None and self.smb is None:
            raise ValueError("Laser output requires workflow_config.laser_output.path or .smb.")


def format_laser_measurement_file(
    values: list[LaserMeasurementValue],
    *,
    newline: str = "\n",
) -> str:
    lines: list[str] = []
    for value in values:
        lines.append(value.measurement_type)
        lines.append(value.value)
    return newline.join(lines) + newline


async def write_laser_measurement_file(
    target: LaserOutputTarget,
    *,
    rueckmeldenummer: str,
    part_id: int,
    values: list[LaserMeasurementValue],
) -> str:
    target.validate()
    filename = render_filename(
        target.filename_template,
        rueckmeldenummer=rueckmeldenummer,
        part_id=part_id,
    )
    content = format_laser_measurement_file(values, newline=target.newline)
    if target.smb is not None:
        await asyncio.to_thread(write_smb_file, target, filename, content)
        return filename

    assert target.path is not None
    path = Path(target.path) / filename
    await asyncio.to_thread(write_local_file, path, content, target.encoding)
    return str(path)


def write_local_file(path: Path, content: str, encoding: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.tmp")
    temp_path.write_text(content, encoding=encoding)
    temp_path.replace(path)


def write_smb_file(target: LaserOutputTarget, filename: str, content: str) -> None:
    assert target.smb is not None
    smb_structs, smb_connection = _load_pysmb()
    smb_config = target.smb
    smb_structs.SUPPORT_SMB2 = bool(smb_config.get("support_smb2", True))
    username = _config_secret(smb_config, "username", "username_env")
    password = _config_secret(smb_config, "password", "password_env")
    server = str(smb_config["server"])
    share = str(smb_config["share"])
    remote_dir = str(smb_config.get("remote_dir") or "/")
    remote_path = f"{remote_dir.rstrip('/')}/{filename}"
    port = int(smb_config.get("port") or 445)
    conn = smb_connection.SMBConnection(
        username,
        password,
        str(smb_config.get("client_name") or "slf-trace-companion"),
        str(smb_config.get("server_name") or server),
        use_ntlm_v2=bool(smb_config.get("use_ntlm_v2", True)),
        is_direct_tcp=port == 445,
    )
    try:
        connected = conn.connect(server, port, timeout=int(smb_config.get("timeout_seconds") or 10))
        if not connected:
            raise OSError(f"Could not connect to SMB server {server}.")
        conn.storeFile(share, remote_path, BytesIO(content.encode(target.encoding)))
    finally:
        conn.close()


def render_filename(template: str, *, rueckmeldenummer: str, part_id: int) -> str:
    values = {
        "rueckmeldenummer": sanitize_filename(rueckmeldenummer),
        "part_id": str(part_id),
    }
    allowed_fields = set(values)
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name and field_name not in allowed_fields:
            raise ValueError(f"Unsupported laser output filename field: {field_name}.")
    return template.format(**values)


def sanitize_filename(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value)


def _config_secret(config: dict[str, Any], value_key: str, env_key: str) -> str:
    if config.get(value_key):
        return str(config[value_key])
    env_name = config.get(env_key)
    if env_name:
        return os.environ[str(env_name)]
    raise ValueError(f"SMB config requires {value_key} or {env_key}.")


def _load_pysmb() -> tuple[Any, Any]:
    try:
        smb_structs = __import__("smb.smb_structs", fromlist=[""])
        smb_connection = __import__("smb.SMBConnection", fromlist=["SMBConnection"])
    except ImportError as exc:
        raise RuntimeError(
            "pysmb is required for direct laser SMB output. Install with `.[smb]`."
        ) from exc
    return smb_structs, smb_connection
