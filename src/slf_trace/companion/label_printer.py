import asyncio
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

VALUE_TOKEN = "{{value}}"
VALUE_DOT_TOKEN = "{{value_dot}}"
VALUE_COMMA_TOKEN = "{{value_comma}}"
VALUE_RAW_TOKEN = "{{value_raw}}"
UNIT_TOKEN = "{{unit}}"
RUECKMELDENUMMER_TOKEN = "{{rueckmeldenummer}}"
SUPPORTED_VALUE_FORMATS = {"comma", "dot", "raw", "with_unit"}
SUPPORTED_MISSING_BEHAVIORS = {"block", "warn_allow_print"}


@dataclass(frozen=True)
class LabelMeasurementValue:
    measurement_type: str
    value: Decimal
    unit: str | None = None


@dataclass(frozen=True)
class LabelReplacementRule:
    measurement_type: str
    search: str
    replace: str
    value_format: str = "comma"
    missing_value_behavior: str = "block"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> "LabelReplacementRule":
        value_format = str(config.get("value_format") or "comma")
        if value_format not in SUPPORTED_VALUE_FORMATS:
            value_format = "comma"
        missing_behavior = str(config.get("missing_value_behavior") or "block")
        if missing_behavior not in SUPPORTED_MISSING_BEHAVIORS:
            missing_behavior = "block"
        return cls(
            measurement_type=str(config.get("measurement_type") or "").strip(),
            search=str(config.get("search") or ""),
            replace=str(config.get("replace") or VALUE_TOKEN),
            value_format=value_format,
            missing_value_behavior=missing_behavior,
        )


@dataclass(frozen=True)
class LabelPrinterConfig:
    template_dir: Path
    selected_template: str
    encoding: str = "cp1252"
    print_backend: str = "win32print"
    printer_name: str = "Vario III 107/12"
    tcp_host: str | None = None
    tcp_port: int = 9100
    require_confirmation: bool = False
    replacements: list[LabelReplacementRule] = field(default_factory=list)

    @classmethod
    def from_workflow_config(cls, workflow_config: dict[str, Any]) -> "LabelPrinterConfig":
        raw_config = workflow_config.get("label_printing") or workflow_config
        if not isinstance(raw_config, dict):
            raw_config = {}
        template_dir = str(raw_config.get("template_dir") or r"C:\SLF\TrackTrace\labels")
        replacements = raw_config.get("replacements") or []
        return cls(
            template_dir=Path(template_dir),
            selected_template=str(raw_config.get("selected_template") or "").strip(),
            encoding=str(raw_config.get("encoding") or "cp1252"),
            print_backend=str(raw_config.get("print_backend") or "win32print"),
            printer_name=str(raw_config.get("printer_name") or "Vario III 107/12"),
            tcp_host=_optional_str(raw_config.get("tcp_host")),
            tcp_port=int(raw_config.get("tcp_port") or 9100),
            require_confirmation=bool(raw_config.get("require_confirmation", False)),
            replacements=[
                LabelReplacementRule.from_config(rule)
                for rule in replacements
                if isinstance(rule, dict)
            ],
        )

    @property
    def template_path(self) -> Path:
        if not self.selected_template:
            raise ValueError("Label printing requires a selected PRN template.")
        template_path = Path(self.selected_template)
        if template_path.is_absolute():
            return template_path
        return self.template_dir / template_path


@dataclass(frozen=True)
class LabelRenderResult:
    content: str
    printable: bool
    missing_blocked: list[str]
    missing_warned: list[str]
    replaced_count: int


def available_label_templates(config: LabelPrinterConfig) -> list[str]:
    if not config.template_dir.exists() or not config.template_dir.is_dir():
        return []
    return sorted(path.name for path in config.template_dir.glob("*.prn") if path.is_file())


def load_label_template(config: LabelPrinterConfig) -> str:
    return config.template_path.read_text(encoding=config.encoding)


def render_label_template(
    template_text: str,
    *,
    rueckmeldenummer: str,
    values: list[LabelMeasurementValue],
    rules: list[LabelReplacementRule],
    allow_missing_values: bool = False,
) -> LabelRenderResult:
    values_by_type = {value.measurement_type: value for value in values}
    content = template_text
    missing_blocked: list[str] = []
    missing_warned: list[str] = []
    replaced_count = 0

    for rule in rules:
        if not rule.search:
            continue
        value = values_by_type.get(rule.measurement_type)
        if value is None:
            if rule.missing_value_behavior == "warn_allow_print":
                missing_warned.append(rule.measurement_type)
                replacement_value = " " if allow_missing_values else ""
            else:
                missing_blocked.append(rule.measurement_type)
                replacement_value = ""
        else:
            replacement_value = format_label_value(value, rule.value_format)

        replacement = apply_label_tokens(
            rule.replace,
            value=value,
            replacement_value=replacement_value,
            rueckmeldenummer=rueckmeldenummer,
        )
        content, count = _replace_once_with_count(content, rule.search, replacement)
        replaced_count += count

    printable = not missing_blocked and (allow_missing_values or not missing_warned)
    return LabelRenderResult(
        content=content,
        printable=printable,
        missing_blocked=sorted(set(missing_blocked)),
        missing_warned=sorted(set(missing_warned)),
        replaced_count=replaced_count,
    )


def apply_label_tokens(
    text: str,
    *,
    value: LabelMeasurementValue | None,
    replacement_value: str,
    rueckmeldenummer: str,
) -> str:
    unit = value.unit if value is not None and value.unit is not None else ""
    replacements = {
        VALUE_TOKEN: replacement_value,
        VALUE_DOT_TOKEN: format_label_value(value, "dot") if value is not None else " ",
        VALUE_COMMA_TOKEN: format_label_value(value, "comma") if value is not None else " ",
        VALUE_RAW_TOKEN: format_label_value(value, "raw") if value is not None else " ",
        UNIT_TOKEN: unit,
        RUECKMELDENUMMER_TOKEN: rueckmeldenummer,
    }
    rendered = text
    for token, token_value in replacements.items():
        rendered = rendered.replace(token, token_value)
    return rendered


def format_label_value(value: LabelMeasurementValue | None, value_format: str) -> str:
    if value is None:
        return " "
    raw = str(value.value)
    if value_format == "raw":
        return raw
    if value_format == "dot":
        return raw
    comma = raw.replace(".", ",")
    if value_format == "with_unit":
        return f"{comma} {value.unit or ''}".strip()
    return comma


async def print_label_content(config: LabelPrinterConfig, content: str) -> str:
    payload = content.encode(config.encoding)
    backend = config.print_backend.strip().lower()
    if backend in {"tcp", "raw_tcp", "tcp_ip"}:
        return await print_label_tcp(config, payload)

    try:
        return await asyncio.to_thread(print_label_win32, config, payload)
    except Exception:
        if config.tcp_host:
            return await print_label_tcp(config, payload)
        raise


def print_label_win32(config: LabelPrinterConfig, payload: bytes) -> str:
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("win32print is not installed on this station.") from exc

    printer_handle = win32print.OpenPrinter(config.printer_name)
    try:
        job = win32print.StartDocPrinter(printer_handle, 1, ("SLF label", None, "RAW"))
        try:
            win32print.StartPagePrinter(printer_handle)
            written = win32print.WritePrinter(printer_handle, payload)
            if written is not None and written != len(payload):
                raise RuntimeError(
                    f"Windows printer accepted {written} of {len(payload)} label bytes."
                )
            win32print.EndPagePrinter(printer_handle)
        finally:
            win32print.EndDocPrinter(printer_handle)
    finally:
        win32print.ClosePrinter(printer_handle)
    return f"win32print:{config.printer_name}:job:{job}:bytes:{len(payload)}"


def win32_printer_info(config: LabelPrinterConfig) -> dict[str, Any]:
    try:
        import win32print  # type: ignore[import-not-found]
    except ImportError as exc:
        raise RuntimeError("win32print is not installed on this station.") from exc

    printer_handle = win32print.OpenPrinter(config.printer_name)
    try:
        info = win32print.GetPrinter(printer_handle, 2)
    finally:
        win32print.ClosePrinter(printer_handle)

    return {
        "printer_name": str(info.get("pPrinterName") or config.printer_name),
        "driver_name": str(info.get("pDriverName") or ""),
        "port_name": str(info.get("pPortName") or ""),
        "status": int(info.get("Status") or 0),
        "attributes": int(info.get("Attributes") or 0),
        "jobs": int(info.get("cJobs") or 0),
    }


async def print_label_tcp(config: LabelPrinterConfig, payload: bytes) -> str:
    if not config.tcp_host:
        raise ValueError("TCP label printing requires tcp_host.")
    reader, writer = await asyncio.open_connection(config.tcp_host, config.tcp_port)
    try:
        writer.write(payload)
        if not payload.endswith(b"\r\n"):
            writer.write(b"\r\n")
        await writer.drain()
        if reader.at_eof():
            return f"tcp:{config.tcp_host}:{config.tcp_port}"
    finally:
        writer.close()
        await writer.wait_closed()
    return f"tcp:{config.tcp_host}:{config.tcp_port}"


def _replace_once_with_count(text: str, search: str, replacement: str) -> tuple[str, int]:
    count = text.count(search)
    return text.replace(search, replacement), count


def _optional_str(value: object) -> str | None:
    if value is None or str(value).strip() == "":
        return None
    return str(value)
