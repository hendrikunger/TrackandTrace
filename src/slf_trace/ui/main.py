from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from importlib import resources
from typing import Any
from uuid import uuid4

import pandas as pd
import panel as pn
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from slf_trace.api.services.admin import is_station_online
from slf_trace.config import Settings, get_settings
from slf_trace.models import (
    Measurement,
    MeasurementType,
    MeasurementValue,
    Part,
    RawPayload,
    Station,
    StationMeasurementType,
)
from slf_trace.ui.branding import load_logo_svg

pn.extension("tabulator")

_session_factory: sessionmaker[Session] | None = None


@contextmanager
def session_scope(settings: Settings) -> Iterator[Session]:
    global _session_factory
    if _session_factory is None:
        engine = create_engine(settings.database_url_sync, pool_pre_ping=True)
        _session_factory = sessionmaker(engine, expire_on_commit=False)

    session = _session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def build_app() -> pn.Column:
    settings = get_settings()
    logo = pn.pane.SVG(load_logo_svg(), width=220, height=64, sizing_mode="fixed")
    header = pn.Row(
        logo,
        pn.Column(
            pn.pane.Markdown("# SLF Track and Trace"),
            pn.pane.Markdown(f"Environment: `{settings.app_env}`"),
            sizing_mode="stretch_width",
            margin=(0, 0, 0, 0),
        ),
        sizing_mode="stretch_width",
        align="start",
    )

    station_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "id": None,
            "status": None,
            "name": None,
            "location": None,
            "machine": None,
            "last_heartbeat": None,
            "measurement_types": None,
            "active": None,
        },
        selectable=1,
        height=300,
        sizing_mode="stretch_width",
    )
    station_name_status = pn.pane.Markdown(
        "Select a station to review configuration.",
        width=180,
    )
    station_health_status = pn.pane.Markdown("", width=130)
    station_heartbeat_status = pn.pane.Markdown("", width=260)
    station_companion_status = pn.pane.Markdown("", width=190)
    station_host_status = pn.pane.Markdown("", width=220)
    station_location_status = pn.pane.Markdown("", width=220)
    adapter_detail = pn.pane.JSON({}, name="Adapter State", depth=3, height=260)

    input_width = 260
    name = pn.widgets.TextInput(name="Name", width=input_width)
    hostname = pn.widgets.TextInput(name="Hostname", width=input_width)
    location = pn.widgets.TextInput(name="Location", width=input_width)
    operating_system = pn.widgets.Select(
        name="Operating system",
        options=["", "Ubuntu 24.04 LTS", "Windows 11"],
        width=input_width,
    )
    machine_name = pn.widgets.TextInput(name="Machine name", width=input_width)
    machine_type = pn.widgets.Select(
        name="Machine type",
        options=["", "dedicated_measurement", "scanner_only", "manual", "other"],
        width=input_width,
    )
    measurement_interface = pn.widgets.Select(
        name="Measurement interface",
        options=["", "SMB1", "SMB2", "TCP/IP", "serial", "local_file", "other"],
        width=input_width,
    )
    scanner_host = pn.widgets.TextInput(name="Scanner IP", width=input_width)
    scanner_port = pn.widgets.IntInput(name="Listen port", start=0, end=65535, value=0, width=140)
    scanner_protocol = pn.widgets.Select(
        name="Scanner protocol",
        options=["", "Keyence SR-X TCP", "none", "other"],
        width=180,
    )
    active = pn.widgets.Checkbox(name="Active", value=True)
    measurement_types = pn.widgets.MultiChoice(
        name="Allowed measurement types",
        options=[],
        width=820,
    )

    adapter_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "enabled": None,
            "type": None,
            "name": None,
            "server": None,
                "share": None,
                "remote_dir": None,
                "host": None,
                "port": None,
                "command": None,
                "measurement_type": None,
                "value_column_index": None,
                "delete_after_success": None,
        },
        selectable=1,
        height=180,
        sizing_mode="stretch_width",
    )
    adapter_enabled = pn.widgets.Checkbox(name="Enabled", value=True)
    adapter_name = pn.widgets.TextInput(
        name="Adapter name",
        value="smb1-polling",
        width=input_width,
    )
    adapter_type = pn.widgets.Select(
        name="Adapter type",
        options={
            "SMB1 polling": "smb1_polling",
            "Serial request": "serial_request",
            "TCP/IP line": "tcp_line",
        },
        value="smb1_polling",
        width=input_width,
    )
    adapter_server = pn.widgets.TextInput(name="SMB server", width=input_width)
    adapter_share = pn.widgets.TextInput(name="Share", width=180)
    adapter_remote_dir = pn.widgets.TextInput(
        name="Remote directory",
        value="/ExcelAusgabe",
        width=220,
    )
    adapter_filename_pattern = pn.widgets.TextInput(
        name="Filename pattern",
        value=r"_(\d+)\.csv$",
        width=220,
    )
    adapter_measurement_type = pn.widgets.Select(name="Measurement type", options=[], width=220)
    adapter_value_column_index = pn.widgets.IntInput(
        name="Value column index",
        start=0,
        value=13,
        width=160,
    )
    adapter_username_env = pn.widgets.TextInput(name="Username env", value="SMB_USER", width=180)
    adapter_password_env = pn.widgets.TextInput(
        name="Password env",
        value="SMB_PASSWORD",
        width=180,
    )
    adapter_encoding = pn.widgets.Select(
        name="Encoding",
        options=["cp1252", "utf-8", "latin-1"],
        value="cp1252",
        width=140,
    )
    adapter_delimiter = pn.widgets.TextInput(name="Delimiter", value=";", width=100)
    adapter_poll_interval = pn.widgets.FloatInput(
        name="Poll interval seconds",
        start=0.1,
        value=2.0,
        width=170,
    )
    adapter_delete_after_success = pn.widgets.Checkbox(name="Delete after success", value=False)
    adapter_delete_with_smbclient = pn.widgets.Checkbox(name="Use smbclient delete", value=True)
    adapter_processed_hashes_path = pn.widgets.TextInput(
        name="Processed hashes path",
        value="state/smb-processed.json",
        width=260,
    )
    serial_port = pn.widgets.TextInput(name="Serial port", value="COM5", width=160)
    serial_command = pn.widgets.TextInput(name="Command", value=r"?\r", width=120)
    serial_baudrate = pn.widgets.IntInput(name="Baudrate", start=1, value=4800, width=130)
    serial_bytesize = pn.widgets.Select(name="Data bits", options=[5, 6, 7, 8], value=7, width=110)
    serial_parity = pn.widgets.Select(
        name="Parity",
        options={"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"},
        value="E",
        width=120,
    )
    serial_stopbits = pn.widgets.Select(
        name="Stop bits",
        options=[1.0, 1.5, 2.0],
        value=2.0,
        width=120,
    )
    serial_timeout = pn.widgets.FloatInput(name="Timeout seconds", start=0.1, value=2.0, width=150)
    tcp_host = pn.widgets.TextInput(name="TCP host", width=220)
    tcp_port = pn.widgets.IntInput(name="TCP port", start=1, end=65535, value=9000, width=140)
    tcp_reconnect_delay = pn.widgets.FloatInput(
        name="Reconnect delay seconds",
        start=0.1,
        value=2.0,
        width=190,
    )
    adapter_add_button = pn.widgets.Button(name="Add adapter", button_type="primary", width=130)
    adapter_remove_button = pn.widgets.Button(name="Remove", button_type="danger", width=110)
    adapter_preview = pn.pane.JSON([], name="Adapter config", depth=4, height=260)
    adapter_message = pn.pane.Alert("", alert_type="info", visible=False)

    refresh_button = pn.widgets.Button(name="Refresh", button_type="primary")
    new_station_button = pn.widgets.Button(name="New station", button_type="primary")
    save_station_button = pn.widgets.Button(name="Save station", button_type="success")
    cancel_station_button = pn.widgets.Button(name="Cancel", button_type="light")
    station_message = pn.pane.Alert("", alert_type="info", visible=False)

    rueckmeldenummer = pn.widgets.TextInput(name="Rückmeldenummer")
    history_station = pn.widgets.Select(
        name="Station",
        options={"All stations": 0},
        value=0,
        width=260,
    )
    lookup_button = pn.widgets.Button(name="Lookup", button_type="primary")
    history_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "id": None,
            "station": None,
            "measured_at": None,
            "result": None,
            "source": None,
            "raw_payload_id": None,
        },
        selectable=1,
        height=260,
        sizing_mode="stretch_width",
    )
    measurement_values = pn.pane.Markdown("Search a Rückmeldenummer to view measurements.")
    raw_payload_id = pn.widgets.IntInput(name="Raw payload ID", start=1, value=1)
    load_payload_button = pn.widgets.Button(name="Inspect payload", button_type="primary")
    raw_payload_detail = pn.pane.Markdown("Raw payload content appears here.")
    lookup_message = pn.pane.Alert("", alert_type="info", visible=False)

    kiosk_station = pn.widgets.Select(name="Station", options={}, width=320)
    kiosk_refresh_button = pn.widgets.Button(name="Aktualisieren", button_type="light", width=130)
    kiosk_reset_button = pn.widgets.Button(name="Neuer Vorgang", button_type="primary", width=140)
    kiosk_title = pn.pane.Markdown("## Station auswählen")
    kiosk_status = pn.pane.Markdown("Bereit.")
    kiosk_message = pn.pane.Alert("", alert_type="info", visible=False)
    kiosk_barcode = pn.widgets.TextInput(
        name="Barcode / Rückmeldenummer",
        placeholder="Barcode scannen oder eingeben",
        width=360,
    )
    kiosk_barcode_button = pn.widgets.Button(
        name="Barcode übernehmen",
        button_type="primary",
        width=170,
    )
    kiosk_check_measurement_button = pn.widgets.Button(
        name="Messwert prüfen",
        button_type="light",
        width=150,
        disabled=True,
    )
    kiosk_upload_button = pn.widgets.Button(
        name="Messung hochladen",
        button_type="success",
        width=180,
        disabled=True,
    )
    kiosk_measurement_inputs: dict[str, pn.widgets.TextInput] = {}
    kiosk_measurement_form = pn.Column(sizing_mode="stretch_width")
    kiosk_summary = pn.pane.Markdown("")
    kiosk_current_station_id: int | None = None
    kiosk_current_barcode: str | None = None

    station_rows: list[dict[str, Any]] = []
    selected_station_id: int | None = None
    creating_station = False
    selected_adapter_index: int | None = None
    adapter_configs: list[dict[str, Any]] = []
    selected_history: dict[int, list[dict[str, Any]]] = {}
    loading_station_form = False
    loading_adapter_form = False

    def set_message(pane: pn.pane.Alert, text: str, alert_type: str = "info") -> None:
        pane.object = text
        pane.alert_type = alert_type
        pane.visible = True

    def refresh_stations(
        _: object | None = None,
        *,
        select_station_id: int | None = None,
    ) -> None:
        nonlocal station_rows
        try:
            with session_scope(settings) as session:
                station_rows = load_station_rows(session)
                type_options = load_measurement_type_options(session)
                measurement_types.options = type_options
                adapter_measurement_type.options = type_options
                if type_options and not adapter_measurement_type.value:
                    adapter_measurement_type.value = type_options[0]
        except Exception as exc:  # noqa: BLE001
            set_message(station_message, f"Could not load station data: {exc}", "danger")
            return

        station_table.value = pd.DataFrame(
            [
                {
                    "id": row["id"],
                    "status": "online" if row["online"] else "offline",
                    "name": row["name"],
                    "location": row["location"],
                    "machine": row["machine_name"],
                    "last_heartbeat": row["last_heartbeat_at"],
                    "measurement_types": ", ".join(row["measurement_type_codes"]),
                    "active": row["active"],
                }
                for row in station_rows
            ]
        )
        history_station.options = {"All stations": 0} | {
            row["name"]: row["id"] for row in station_rows
        }
        refresh_kiosk_station_options()
        if select_station_id is not None:
            matching_rows = station_table.value.index[
                station_table.value["id"] == select_station_id
            ].tolist()
            if matching_rows:
                station_table.selection = [matching_rows[0]]
        set_message(station_message, f"Loaded {len(station_rows)} stations.")

    def fill_station_form(station: dict[str, Any]) -> None:
        nonlocal loading_station_form
        loading_station_form = True
        try:
            name.value = station["name"] or ""
            hostname.value = station["hostname"] or ""
            location.value = station["location"] or ""
            set_select_value(operating_system, station["operating_system"] or "")
            machine_name.value = station["machine_name"] or ""
            set_select_value(machine_type, station["machine_type"] or "")
            set_select_value(measurement_interface, station["measurement_interface"] or "")
            scanner_host.value = station["scanner_host"] or ""
            scanner_port.value = station["scanner_port"] or 0
            set_select_value(scanner_protocol, station["scanner_protocol"] or "")
            active.value = station["active"]
            measurement_types.value = station["measurement_type_codes"]
            load_adapter_configs(station.get("adapter_config") or [])
        finally:
            loading_station_form = False

    def update_station_status_bar(station: dict[str, Any]) -> None:
        status = "online" if station["online"] else "offline"
        station_name_status.object = f"**{station['name']}**"
        station_health_status.object = f"Status: `{status}`"
        station_heartbeat_status.object = (
            f"Last heartbeat: `{station['last_heartbeat_at'] or 'never'}`"
        )
        station_companion_status.object = (
            f"Companion: `{station['companion_version'] or 'unknown'}`"
        )
        station_host_status.object = f"Hostname: `{station['hostname'] or '-'}`"
        station_location_status.object = f"Location: `{station['location'] or '-'}`"

    def clear_station_form() -> None:
        nonlocal loading_station_form
        loading_station_form = True
        try:
            name.value = ""
            hostname.value = ""
            location.value = ""
            operating_system.value = ""
            machine_name.value = ""
            machine_type.value = ""
            measurement_interface.value = ""
            scanner_host.value = ""
            scanner_port.value = 0
            scanner_protocol.value = ""
            active.value = True
            measurement_types.value = []
            load_adapter_configs([])
        finally:
            loading_station_form = False

    def select_station(event: Any) -> None:
        nonlocal creating_station, selected_station_id
        if not event.new:
            if not creating_station:
                selected_station_id = None
            return

        row_index = event.new[0]
        if station_table.value.empty or row_index >= len(station_table.value):
            return

        selected_station_id = int(station_table.value.iloc[row_index]["id"])
        creating_station = False
        station = next(
            row for row in station_rows if row["id"] == selected_station_id
        )
        fill_station_form(station)
        update_station_status_bar(station)
        adapter_detail.object = station["adapter_status"] or {}
        render_adapter_configs()

    def autosave_config(_: object | None = None) -> None:
        if loading_station_form:
            return

        if creating_station:
            return

        if selected_station_id is None:
            set_message(station_message, "Select a station first.", "warning")
            return

        try:
            values = current_station_config_values()
            with session_scope(settings) as session:
                station = session.get(Station, selected_station_id)
                if station is None:
                    raise ValueError(f"Station {selected_station_id} was not found.")
                for field, value in values.items():
                    setattr(station, field, value)
        except Exception as exc:  # noqa: BLE001
            set_message(station_message, f"Could not autosave station config: {exc}", "danger")
            return

        update_selected_station_row(values)
        set_message(station_message, "Station config autosaved.")

    def current_station_config_values() -> dict[str, Any]:
        station_name = name.value.strip()
        if not station_name:
            raise ValueError("Station name is required.")
        if scanner_port.value is not None and scanner_port.value < 0:
            raise ValueError("Scanner port must be empty or between 1 and 65535.")
        if scanner_port.value and scanner_port.value > 65535:
            raise ValueError("Scanner port must be empty or between 1 and 65535.")

        return {
            "name": station_name,
            "hostname": hostname.value.strip() or None,
            "location": location.value.strip() or None,
            "operating_system": operating_system.value.strip() or None,
            "machine_name": machine_name.value.strip() or None,
            "machine_type": machine_type.value.strip() or None,
            "measurement_interface": measurement_interface.value.strip() or None,
            "scanner_host": scanner_host.value.strip() or None,
            "scanner_port": scanner_port.value or None,
            "scanner_protocol": scanner_protocol.value.strip() or None,
            "active": active.value,
        }

    def start_new_station(_: object | None = None) -> None:
        nonlocal creating_station, selected_station_id
        creating_station = True
        selected_station_id = None
        station_table.selection = []
        clear_station_form()
        station_name_status.object = "**New station**"
        station_health_status.object = "Status: `draft`"
        station_heartbeat_status.object = "Last heartbeat: `never`"
        station_companion_status.object = "Companion: `unknown`"
        station_host_status.object = "Hostname: `-`"
        station_location_status.object = "Location: `-`"
        adapter_detail.object = {}
        set_message(station_message, "Enter station details, then save.")

    def cancel_new_station(_: object | None = None) -> None:
        nonlocal creating_station
        creating_station = False
        station_table.selection = []
        clear_station_form()
        set_message(station_message, "New station cancelled.")

    def save_station(_: object | None = None) -> None:
        if creating_station:
            create_station_from_form()
            return
        autosave_config()

    def create_station_from_form() -> None:
        nonlocal creating_station, selected_station_id
        try:
            values = current_station_config_values()
            values["adapter_config"] = [dict(config) for config in adapter_configs]
            with session_scope(settings) as session:
                station = Station(**values)
                session.add(station)
                session.flush()
                replace_station_measurement_types(
                    session,
                    station.id,
                    measurement_types.value,
                )
                created_station_id = station.id
        except Exception as exc:  # noqa: BLE001
            set_message(station_message, f"Could not create station: {exc}", "danger")
            return

        creating_station = False
        selected_station_id = created_station_id
        refresh_stations(select_station_id=created_station_id)
        set_message(station_message, "Station created.")

    def load_adapter_configs(configs: list[dict[str, Any]]) -> None:
        nonlocal adapter_configs, selected_adapter_index
        adapter_configs = [dict(config) for config in configs]
        selected_adapter_index = None
        adapter_table.selection = []
        render_adapter_configs()
        if adapter_configs:
            load_adapter_form(adapter_configs[0])
        else:
            reset_adapter_form()

    def render_adapter_configs() -> None:
        adapter_table.value = pd.DataFrame(adapter_summary_rows(adapter_configs))
        adapter_preview.object = adapter_configs

    def select_adapter(event: Any) -> None:
        nonlocal selected_adapter_index
        if not event.new:
            selected_adapter_index = None
            return

        row_index = event.new[0]
        if row_index >= len(adapter_configs):
            selected_adapter_index = None
            return

        selected_adapter_index = row_index
        load_adapter_form(adapter_configs[row_index])

    def reset_adapter_form(_: object | None = None) -> None:
        nonlocal loading_adapter_form
        loading_adapter_form = True
        try:
            adapter_enabled.value = True
            adapter_type.value = "smb1_polling"
            adapter_name.value = "smb1-polling"
            adapter_server.value = ""
            adapter_share.value = ""
            adapter_remote_dir.value = "/ExcelAusgabe"
            adapter_filename_pattern.value = r"_(\d+)\.csv$"
            if adapter_measurement_type.options:
                adapter_measurement_type.value = adapter_measurement_type.options[0]
            adapter_value_column_index.value = 13
            adapter_username_env.value = "SMB_USER"
            adapter_password_env.value = "SMB_PASSWORD"
            adapter_encoding.value = "cp1252"
            adapter_delimiter.value = ";"
            adapter_poll_interval.value = 2.0
            adapter_delete_after_success.value = False
            adapter_delete_with_smbclient.value = True
            adapter_processed_hashes_path.value = "state/smb-processed.json"
            serial_port.value = "COM5"
            serial_command.value = r"?\r"
            serial_baudrate.value = 4800
            serial_bytesize.value = 7
            serial_parity.value = "E"
            serial_stopbits.value = 2.0
            serial_timeout.value = 2.0
            tcp_host.value = ""
            tcp_port.value = 9000
            tcp_reconnect_delay.value = 2.0
        finally:
            loading_adapter_form = False

    def load_adapter_form(config: dict[str, Any]) -> None:
        nonlocal loading_adapter_form
        loading_adapter_form = True
        try:
            adapter_enabled.value = bool(config.get("enabled", True))
            adapter_type.value = str(config.get("type") or "smb1_polling")
            adapter_name.value = str(config.get("name") or "smb1-polling")
            adapter_server.value = str(config.get("server") or "")
            adapter_share.value = str(config.get("share") or "")
            adapter_remote_dir.value = str(config.get("remote_dir") or "/ExcelAusgabe")
            adapter_filename_pattern.value = str(
                config.get("filename_pattern") or r"_(\d+)\.csv$"
            )
            adapter_measurement_type.value = str(
                config.get("measurement_type") or adapter_measurement_type.value or ""
            )
            adapter_value_column_index.value = int(config.get("value_column_index", 13))
            adapter_username_env.value = str(config.get("username_env") or "SMB_USER")
            adapter_password_env.value = str(config.get("password_env") or "SMB_PASSWORD")
            adapter_encoding.value = str(config.get("encoding") or "cp1252")
            adapter_delimiter.value = str(config.get("delimiter") or ";")
            adapter_poll_interval.value = float(config.get("poll_interval_seconds", 2.0))
            adapter_delete_after_success.value = bool(config.get("delete_after_success", False))
            adapter_delete_with_smbclient.value = bool(config.get("delete_with_smbclient", True))
            adapter_processed_hashes_path.value = str(
                config.get("processed_hashes_path") or "state/smb-processed.json"
            )
            serial_port.value = str(config.get("port") or "COM5")
            serial_command.value = str(config.get("command") or r"?\r")
            serial_baudrate.value = int(config.get("baudrate", 4800))
            serial_bytesize.value = int(config.get("bytesize", 7))
            serial_parity.value = str(config.get("parity") or "E")
            serial_stopbits.value = float(config.get("stopbits", 2.0))
            serial_timeout.value = float(config.get("timeout_seconds", 2.0))
            tcp_host.value = str(config.get("host") or "")
            tcp_port.value = int(config.get("port", 9000))
            tcp_reconnect_delay.value = float(config.get("reconnect_delay_seconds", 2.0))
        finally:
            loading_adapter_form = False

    def current_adapter_values() -> dict[str, Any]:
        if adapter_type.value == "tcp_line":
            values = {
                "type": adapter_type.value,
                "enabled": adapter_enabled.value,
                "name": adapter_name.value.strip() or "tcp-line",
                "host": tcp_host.value.strip(),
                "port": tcp_port.value,
                "measurement_type": adapter_measurement_type.value,
                "reconnect_delay_seconds": tcp_reconnect_delay.value,
                "encoding": adapter_encoding.value,
            }
            validate_tcp_adapter_config(values)
            return {key: value for key, value in values.items() if value not in ("", None)}

        if adapter_type.value == "serial_request":
            values = {
                "type": adapter_type.value,
                "enabled": adapter_enabled.value,
                "name": adapter_name.value.strip() or "serial-request",
                "port": serial_port.value.strip(),
                "command": serial_command.value,
                "measurement_type": adapter_measurement_type.value,
                "baudrate": serial_baudrate.value,
                "bytesize": serial_bytesize.value,
                "parity": serial_parity.value,
                "stopbits": serial_stopbits.value,
                "timeout_seconds": serial_timeout.value,
                "poll_interval_seconds": adapter_poll_interval.value,
                "encoding": adapter_encoding.value,
            }
            validate_serial_adapter_config(values)
            return {key: value for key, value in values.items() if value not in ("", None)}

        values = {
            "type": adapter_type.value,
            "enabled": adapter_enabled.value,
            "name": adapter_name.value.strip() or "smb1-polling",
            "server": adapter_server.value.strip(),
            "share": adapter_share.value.strip(),
            "username_env": adapter_username_env.value.strip(),
            "password_env": adapter_password_env.value.strip(),
            "remote_dir": adapter_remote_dir.value.strip(),
            "filename_pattern": adapter_filename_pattern.value.strip() or r"_(\d+)\.csv$",
            "measurement_type": adapter_measurement_type.value,
            "value_column_index": adapter_value_column_index.value,
            "encoding": adapter_encoding.value,
            "delimiter": adapter_delimiter.value or ";",
            "poll_interval_seconds": adapter_poll_interval.value,
            "delete_after_success": adapter_delete_after_success.value,
            "delete_with_smbclient": adapter_delete_with_smbclient.value,
            "processed_hashes_path": adapter_processed_hashes_path.value.strip(),
        }
        validate_adapter_config(values)
        return {key: value for key, value in values.items() if value not in ("", None)}

    def validate_adapter_config(values: dict[str, Any]) -> None:
        required = {
            "server": "SMB server",
            "share": "Share",
            "username_env": "Username env",
            "password_env": "Password env",
            "remote_dir": "Remote directory",
            "measurement_type": "Measurement type",
        }
        missing = [label for key, label in required.items() if not values.get(key)]
        if missing:
            raise ValueError(f"Missing adapter fields: {', '.join(missing)}.")
        if values["value_column_index"] < 0:
            raise ValueError("Value column index must be 0 or greater.")
        if values["poll_interval_seconds"] <= 0:
            raise ValueError("Poll interval must be greater than 0.")

    def validate_serial_adapter_config(values: dict[str, Any]) -> None:
        required = {
            "port": "Serial port",
            "command": "Command",
            "measurement_type": "Measurement type",
        }
        missing = [label for key, label in required.items() if not values.get(key)]
        if missing:
            raise ValueError(f"Missing adapter fields: {', '.join(missing)}.")
        if values["baudrate"] <= 0:
            raise ValueError("Baudrate must be greater than 0.")
        if values["timeout_seconds"] <= 0:
            raise ValueError("Timeout must be greater than 0.")
        if values["poll_interval_seconds"] <= 0:
            raise ValueError("Poll interval must be greater than 0.")

    def validate_tcp_adapter_config(values: dict[str, Any]) -> None:
        required = {
            "host": "TCP host",
            "port": "TCP port",
            "measurement_type": "Measurement type",
        }
        missing = [label for key, label in required.items() if not values.get(key)]
        if missing:
            raise ValueError(f"Missing adapter fields: {', '.join(missing)}.")
        if values["port"] < 1 or values["port"] > 65535:
            raise ValueError("TCP port must be between 1 and 65535.")
        if values["reconnect_delay_seconds"] <= 0:
            raise ValueError("Reconnect delay must be greater than 0.")

    def save_adapter_configs() -> None:
        if creating_station:
            set_message(adapter_message, "Adapter config staged for new station.")
            return

        if selected_station_id is None:
            set_message(adapter_message, "Select a station first.", "warning")
            return

        try:
            with session_scope(settings) as session:
                station = session.get(Station, selected_station_id)
                if station is None:
                    raise ValueError(f"Station {selected_station_id} was not found.")
                station.adapter_config = adapter_configs
        except Exception as exc:  # noqa: BLE001
            set_message(adapter_message, f"Could not save adapter config: {exc}", "danger")
            return

        station = next(row for row in station_rows if row["id"] == selected_station_id)
        station["adapter_config"] = [dict(config) for config in adapter_configs]
        set_message(adapter_message, "Adapter config saved.")

    def add_adapter(_: object | None = None) -> None:
        try:
            adapter_configs.append(current_adapter_values())
            render_adapter_configs()
            save_adapter_configs()
        except Exception as exc:  # noqa: BLE001
            set_message(adapter_message, f"Could not add adapter: {exc}", "danger")

    def autoupdate_adapter(_: object | None = None) -> None:
        if loading_adapter_form:
            return
        if selected_adapter_index is None:
            return

        try:
            adapter_configs[selected_adapter_index] = current_adapter_values()
            render_adapter_configs()
            save_adapter_configs()
        except Exception as exc:  # noqa: BLE001
            set_message(adapter_message, f"Could not autosave adapter config: {exc}", "danger")

    def remove_adapter(_: object | None = None) -> None:
        nonlocal selected_adapter_index
        if selected_adapter_index is None:
            set_message(adapter_message, "Select an adapter first.", "warning")
            return
        adapter_configs.pop(selected_adapter_index)
        selected_adapter_index = None
        adapter_table.selection = []
        render_adapter_configs()
        save_adapter_configs()

    def update_selected_station_row(values: dict[str, Any]) -> None:
        if selected_station_id is None:
            return

        station = next(
            row for row in station_rows if row["id"] == selected_station_id
        )
        station.update(values)
        update_station_status_bar(station)

        table_data = station_table.value.copy()
        matching_rows = table_data.index[table_data["id"] == selected_station_id].tolist()
        if not matching_rows:
            return

        row_index = matching_rows[0]
        table_data.loc[row_index, "name"] = station["name"]
        table_data.loc[row_index, "location"] = station["location"]
        table_data.loc[row_index, "machine"] = station["machine_name"]
        table_data.loc[row_index, "active"] = station["active"]
        station_table.value = table_data

    def autosave_measurement_types(_: object | None = None) -> None:
        if loading_station_form:
            return

        if creating_station:
            return

        if selected_station_id is None:
            set_message(station_message, "Select a station first.", "warning")
            return

        try:
            with session_scope(settings) as session:
                replace_station_measurement_types(
                    session,
                    selected_station_id,
                    measurement_types.value,
                )
        except Exception as exc:  # noqa: BLE001
            set_message(
                station_message,
                f"Could not autosave measurement type assignment: {exc}",
                "danger",
            )
            return

        update_selected_station_measurement_types(measurement_types.value)
        set_message(station_message, "Measurement type assignment autosaved.")

    def update_selected_station_measurement_types(measurement_type_codes: list[str]) -> None:
        if selected_station_id is None:
            return

        station = next(
            row for row in station_rows if row["id"] == selected_station_id
        )
        station["measurement_type_codes"] = measurement_type_codes

        table_data = station_table.value.copy()
        matching_rows = table_data.index[table_data["id"] == selected_station_id].tolist()
        if not matching_rows:
            return

        table_data.loc[matching_rows[0], "measurement_types"] = ", ".join(
            measurement_type_codes
        )
        station_table.value = table_data

    def lookup_measurements(_: object | None = None) -> None:
        selected_history.clear()
        raw_payload_detail.object = "Select a measurement with a raw payload to inspect it."
        try:
            with session_scope(settings) as session:
                history_rows, value_rows = load_measurement_history(
                    session,
                    rueckmeldenummer.value.strip(),
                    history_station.value or None,
                )
        except Exception as exc:  # noqa: BLE001
            history_table.value = pd.DataFrame()
            measurement_values.object = ""
            set_message(lookup_message, f"Could not load history: {exc}", "danger")
            return

        selected_history.update(value_rows)
        history_table.value = pd.DataFrame(history_rows)
        set_message(lookup_message, f"Loaded {len(history_rows)} measurements.")

    def select_measurement(event: Any) -> None:
        if not event.new:
            return

        row_index = event.new[0]
        if history_table.value.empty or row_index >= len(history_table.value):
            return

        row = history_table.value.iloc[row_index]
        payload_id = row["raw_payload_id"]
        if payload_id and not pd.isna(payload_id):
            raw_payload_id.value = int(payload_id)
            inspect_payload()
        else:
            raw_payload_detail.object = "Selected measurement has no linked raw payload."
        measurement_values.object = values_markdown(
            selected_history.get(int(row["id"]), [])
        )

    def inspect_payload(_: object | None = None) -> None:
        try:
            with session_scope(settings) as session:
                detail = load_raw_payload(session, raw_payload_id.value)
        except Exception as exc:  # noqa: BLE001
            set_message(lookup_message, f"Could not load raw payload: {exc}", "danger")
            return

        raw_payload_detail.object = raw_payload_markdown(detail)

    def station_row_by_id(station_id: int) -> dict[str, Any]:
        return next(row for row in station_rows if row["id"] == station_id)

    def refresh_kiosk_station_options() -> None:
        measurement_stations = [
            row
            for row in station_rows
            if row["active"] and row["measurement_type_details"]
        ]
        kiosk_station.options = {row["name"]: row["id"] for row in measurement_stations}
        if not kiosk_station.options:
            kiosk_station.value = None
            kiosk_title.object = "## Keine Messstation konfiguriert"
            kiosk_status.object = "Aktive Messstation mit Messart zuweisen."
            return

        configured_station_id = (
            int(settings.station_id)
            if str(settings.station_id or "").isdigit()
            else None
        )
        preferred_station_id = (
            configured_station_id
            if configured_station_id in kiosk_station.options.values()
            else kiosk_current_station_id
        )
        if preferred_station_id in kiosk_station.options.values():
            kiosk_station.value = preferred_station_id
        elif kiosk_station.value not in kiosk_station.options.values():
            kiosk_station.value = next(iter(kiosk_station.options.values()))
        load_kiosk_station()

    def load_kiosk_station(_: object | None = None) -> None:
        nonlocal kiosk_current_station_id, kiosk_current_barcode
        if kiosk_station.value is None:
            return
        kiosk_current_station_id = int(kiosk_station.value)
        kiosk_current_barcode = None
        station = station_row_by_id(kiosk_current_station_id)
        kiosk_title.object = f"## {kiosk_workflow_title(station)}"
        kiosk_barcode.value = ""
        kiosk_upload_button.disabled = True
        kiosk_check_measurement_button.disabled = True
        build_kiosk_measurement_form(station)
        update_kiosk_status(
            step=1,
            message="Bitte Barcode scannen oder Rückmeldenummer eingeben.",
        )
        kiosk_summary.object = kiosk_station_summary(station)
        kiosk_message.visible = False

    def build_kiosk_measurement_form(station: dict[str, Any]) -> None:
        kiosk_measurement_inputs.clear()
        rows = []
        for detail in station["measurement_type_details"]:
            input_widget = pn.widgets.TextInput(
                name=detail["label"],
                placeholder=f"Wert in {detail['unit'] or 'Einheit'}",
                width=220,
                disabled=True,
            )
            kiosk_measurement_inputs[detail["code"]] = input_widget
            rows.append(
                pn.Row(
                    input_widget,
                    pn.pane.Markdown(f"`{detail['code']}` {detail['unit'] or ''}", width=180),
                    sizing_mode="stretch_width",
                    align="end",
                )
            )
        if not rows:
            rows = [
                pn.pane.Alert(
                    "Für diese Station ist keine Messart zugewiesen.",
                    alert_type="warning",
                )
            ]
        kiosk_measurement_form.objects = rows

    def accept_kiosk_barcode(_: object | None = None) -> None:
        nonlocal kiosk_current_barcode
        if kiosk_current_station_id is None:
            set_message(kiosk_message, "Keine Station ausgewählt.", "danger")
            return

        barcode = kiosk_barcode.value.strip()
        if not barcode:
            set_message(kiosk_message, "Bitte zuerst einen Barcode scannen.", "warning")
            update_kiosk_status(step=1, message="Warte auf Barcode.")
            return
        if len(barcode) > 120:
            set_message(kiosk_message, "Der Barcode ist zu lang.", "danger")
            return

        kiosk_current_barcode = barcode
        for input_widget in kiosk_measurement_inputs.values():
            input_widget.disabled = False
        kiosk_upload_button.disabled = False
        kiosk_check_measurement_button.disabled = False
        update_kiosk_status(
            step=2,
            message=(
                f"Barcode `{barcode}` erfasst. Messwert vom Gerät übernehmen oder "
                "Messwert manuell eintragen."
            ),
        )
        set_message(kiosk_message, "Barcode wurde übernommen.", "success")

    def check_kiosk_measurement(_: object | None = None) -> None:
        if kiosk_current_station_id is None or kiosk_current_barcode is None:
            set_message(kiosk_message, "Bitte zuerst Barcode übernehmen.", "warning")
            return

        try:
            with session_scope(settings) as session:
                measurement = load_latest_measurement_for_part(
                    session,
                    kiosk_current_station_id,
                    kiosk_current_barcode,
                )
        except Exception as exc:  # noqa: BLE001
            set_message(kiosk_message, f"Messwert konnte nicht geprüft werden: {exc}", "danger")
            return

        if measurement is None:
            set_message(
                kiosk_message,
                (
                    "Noch kein Messwert vom Adapter empfangen. Gerät prüfen oder "
                    "Messwert manuell eintragen."
                ),
                "warning",
            )
            update_kiosk_status(step=3, message="Warte auf Messwert vom Gerät.")
            return

        value_text = ", ".join(
            f"{value.measurement_type}={value.value} {value.unit or ''}"
            for value in sorted(measurement.values, key=lambda item: item.measurement_type)
        )
        set_message(kiosk_message, f"Messung gefunden: {value_text}", "success")
        update_kiosk_status(step=4, message="Messung wurde bereits zentral gespeichert.")

    def upload_kiosk_measurement(_: object | None = None) -> None:
        if kiosk_current_station_id is None:
            set_message(kiosk_message, "Keine Station ausgewählt.", "danger")
            return
        if kiosk_current_barcode is None:
            set_message(kiosk_message, "Bitte zuerst Barcode übernehmen.", "warning")
            return

        try:
            parsed_values = parse_kiosk_measurement_values()
            if not parsed_values:
                raise ValueError("Bitte mindestens einen Messwert eintragen.")
            with session_scope(settings) as session:
                measurement_id = save_kiosk_measurement(
                    session,
                    station_id=kiosk_current_station_id,
                    rueckmeldenummer=kiosk_current_barcode,
                    values=parsed_values,
                )
        except Exception as exc:  # noqa: BLE001
            set_message(kiosk_message, f"Messung konnte nicht hochgeladen werden: {exc}", "danger")
            update_kiosk_status(step=3, message="Fehler beim Hochladen. Bitte Eingaben prüfen.")
            return

        set_message(
            kiosk_message,
            f"Messung erfolgreich hochgeladen. Messung #{measurement_id}",
            "success",
        )
        update_kiosk_status(step=4, message="Fertig. Nächsten Barcode scannen.")
        kiosk_upload_button.disabled = True
        kiosk_check_measurement_button.disabled = True

    def parse_kiosk_measurement_values() -> dict[str, Decimal]:
        values = {}
        for measurement_type, input_widget in kiosk_measurement_inputs.items():
            raw_value = input_widget.value.strip()
            if not raw_value:
                continue
            try:
                values[measurement_type] = Decimal(raw_value.replace(",", "."))
            except InvalidOperation as exc:
                raise ValueError(f"Messwert für {measurement_type} ist keine Zahl.") from exc
        return values

    def reset_kiosk(_: object | None = None) -> None:
        load_kiosk_station()

    def update_kiosk_status(*, step: int, message: str) -> None:
        labels = [
            ("1", "Barcode"),
            ("2", "Messwert"),
            ("3", "Hochladen"),
            ("4", "Fertig"),
        ]
        rendered_steps = []
        for number, label in labels:
            active = int(number) == step
            background = "#0f766e" if active else "#e5e7eb"
            color = "white" if active else "#111827"
            rendered_steps.append(
                f"<span style='display:inline-block;min-width:120px;padding:10px 14px;"
                f"margin-right:8px;border-radius:6px;background:{background};color:{color};"
                f"text-align:center;font-weight:600'>{number}. {label}</span>"
            )
        kiosk_status.object = "<div>" + "".join(rendered_steps) + f"</div><p>{message}</p>"

    station_table.param.watch(select_station, "selection")
    adapter_table.param.watch(select_adapter, "selection")
    history_table.param.watch(select_measurement, "selection")
    kiosk_station.param.watch(load_kiosk_station, "value")
    refresh_button.on_click(refresh_stations)
    new_station_button.on_click(start_new_station)
    save_station_button.on_click(save_station)
    cancel_station_button.on_click(cancel_new_station)
    adapter_add_button.on_click(add_adapter)
    adapter_remove_button.on_click(remove_adapter)
    lookup_button.on_click(lookup_measurements)
    load_payload_button.on_click(inspect_payload)
    kiosk_refresh_button.on_click(refresh_stations)
    kiosk_reset_button.on_click(reset_kiosk)
    kiosk_barcode_button.on_click(accept_kiosk_barcode)
    kiosk_check_measurement_button.on_click(check_kiosk_measurement)
    kiosk_upload_button.on_click(upload_kiosk_measurement)

    for field_widget in (
        name,
        hostname,
        location,
        operating_system,
        machine_name,
        machine_type,
        measurement_interface,
        scanner_host,
        scanner_port,
        scanner_protocol,
        active,
    ):
        field_widget.param.watch(autosave_config, "value")
    measurement_types.param.watch(autosave_measurement_types, "value")
    for adapter_widget in (
        adapter_enabled,
        adapter_type,
        adapter_name,
        adapter_server,
        adapter_share,
        adapter_remote_dir,
        adapter_filename_pattern,
        adapter_measurement_type,
        adapter_value_column_index,
        adapter_username_env,
        adapter_password_env,
        adapter_encoding,
        adapter_delimiter,
        adapter_poll_interval,
        adapter_delete_after_success,
        adapter_delete_with_smbclient,
        adapter_processed_hashes_path,
        serial_port,
        serial_command,
        serial_baudrate,
        serial_bytesize,
        serial_parity,
        serial_stopbits,
        serial_timeout,
        tcp_host,
        tcp_port,
        tcp_reconnect_delay,
    ):
        adapter_widget.param.watch(autoupdate_adapter, "value")

    refresh_stations()

    station_status_bar = pn.Row(
        station_name_status,
        station_health_status,
        station_heartbeat_status,
        station_companion_status,
        station_host_status,
        station_location_status,
        sizing_mode="stretch_width",
        align="start",
        styles={
            "background": "#f6f8fa",
            "border": "1px solid #d0d7de",
            "padding": "8px 12px",
        },
    )
    station_config_form = pn.Column(
        pn.Tabs(
            (
                "Station",
                pn.Column(
                    pn.GridBox(
                        name,
                        hostname,
                        location,
                        operating_system,
                        machine_name,
                        machine_type,
                        measurement_interface,
                        active,
                        ncols=2,
                        align="start",
                    ),
                    sizing_mode="stretch_width",
                ),
            ),
            (
                "Scanner",
                pn.GridBox(
                    scanner_host,
                    scanner_port,
                    scanner_protocol,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "Measurements",
                pn.Column(measurement_types, sizing_mode="stretch_width"),
            ),
            sizing_mode="stretch_width",
        ),
        station_message,
        align="start",
        width=860,
    )
    adapter_config_form = pn.Column(
        pn.Row(adapter_add_button, adapter_remove_button),
        adapter_table,
        pn.pane.Markdown("### Adapter settings"),
        pn.Tabs(
            (
                "Common",
                pn.GridBox(
                    adapter_enabled,
                    adapter_type,
                    adapter_name,
                    adapter_measurement_type,
                    adapter_poll_interval,
                    adapter_encoding,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "SMB1",
                pn.GridBox(
                    adapter_server,
                    adapter_share,
                    adapter_remote_dir,
                    adapter_username_env,
                    adapter_password_env,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "TCP/IP",
                pn.GridBox(
                    tcp_host,
                    tcp_port,
                    tcp_reconnect_delay,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "Serial",
                pn.GridBox(
                    serial_port,
                    serial_command,
                    serial_baudrate,
                    serial_bytesize,
                    serial_parity,
                    serial_stopbits,
                    serial_timeout,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "Parsing",
                pn.GridBox(
                    adapter_value_column_index,
                    adapter_filename_pattern,
                    adapter_delimiter,
                    ncols=3,
                    align="start",
                ),
            ),
            (
                "Runtime",
                pn.GridBox(
                    adapter_delete_after_success,
                    adapter_delete_with_smbclient,
                    adapter_processed_hashes_path,
                    ncols=3,
                    align="start",
                ),
            ),
            sizing_mode="stretch_width",
        ),
        adapter_message,
        pn.pane.Markdown("### Effective adapter JSON"),
        adapter_preview,
        sizing_mode="stretch_width",
    )
    kiosk_panel = pn.Column(
        pn.Row(
            pn.Column(
                kiosk_title,
                kiosk_summary,
                sizing_mode="stretch_width",
            ),
            pn.Spacer(sizing_mode="stretch_width"),
            pn.Column(
                pn.Row(kiosk_station, kiosk_refresh_button, kiosk_reset_button, align="end"),
                width=640,
            ),
            sizing_mode="stretch_width",
            align="start",
        ),
        kiosk_status,
        kiosk_message,
        pn.Row(
            pn.Column(
                pn.pane.Markdown("### 1. Barcode scannen"),
                pn.Row(kiosk_barcode, kiosk_barcode_button, align="end"),
                pn.pane.Markdown("### 2. Messwert erfassen"),
                kiosk_measurement_form,
                pn.Row(kiosk_check_measurement_button, kiosk_upload_button, align="end"),
                sizing_mode="stretch_width",
            ),
            pn.Column(
                pn.pane.Markdown("### Hinweise"),
                pn.pane.Markdown(
                    "\n".join(
                        [
                            "- Barcode scannen oder Rückmeldenummer eingeben.",
                            "- Messwerte kommen im Regelbetrieb vom Stationsadapter.",
                            (
                                "- Manuelle Eingabe ist als Fallback für Entwicklung "
                                "und Störungen gedacht."
                            ),
                            "- Bei Fehlern Vorgang zurücksetzen und erneut scannen.",
                        ]
                    )
                ),
                width=360,
                styles={
                    "background": "#f8fafc",
                    "border": "1px solid #d1d5db",
                    "padding": "12px",
                    "border-radius": "6px",
                },
            ),
            sizing_mode="stretch_width",
            align="start",
        ),
        sizing_mode="stretch_width",
        styles={"padding": "8px 0"},
    )

    return pn.Column(
        header,
        pn.Tabs(
            (
                "Kiosk",
                kiosk_panel,
            ),
            (
                "Stations",
                pn.Column(
                    pn.Row(
                        refresh_button,
                        new_station_button,
                        save_station_button,
                        cancel_station_button,
                    ),
                    station_table,
                    station_status_bar,
                    pn.Row(
                        station_config_form,
                        pn.Column(
                            pn.pane.Markdown("### Adapter State"),
                            adapter_detail,
                            width=420,
                        ),
                        sizing_mode="stretch_width",
                        align="start",
                    ),
                    pn.pane.Markdown("## Adapter configuration"),
                    adapter_config_form,
                    sizing_mode="stretch_width",
                ),
            ),
            (
                "Measurement history",
                pn.Column(
                    pn.Row(
                        rueckmeldenummer,
                        history_station,
                        lookup_button,
                        sizing_mode="stretch_width",
                    ),
                    lookup_message,
                    history_table,
                    measurement_values,
                    pn.Row(raw_payload_id, load_payload_button),
                    raw_payload_detail,
                    sizing_mode="stretch_width",
                ),
            ),
            sizing_mode="stretch_width",
        ),
        sizing_mode="stretch_width",
    )


def load_station_rows(session: Session) -> list[dict[str, Any]]:
    stations = session.scalars(
        select(Station)
        .options(
            selectinload(Station.heartbeats),
            selectinload(Station.measurement_type_links).selectinload(
                StationMeasurementType.measurement_type
            ),
        )
        .order_by(Station.name)
    ).all()

    rows = []
    for station in stations:
        latest_heartbeat = max(
            station.heartbeats,
            key=lambda heartbeat: heartbeat.received_at,
            default=None,
        )
        status = latest_heartbeat.status if latest_heartbeat else None
        received_at = latest_heartbeat.received_at if latest_heartbeat else None
        active_measurement_links = [
            link for link in station.measurement_type_links if link.active
        ]
        rows.append(
            {
                "id": station.id,
                "name": station.name,
                "hostname": station.hostname,
                "location": station.location,
                "operating_system": station.operating_system,
                "machine_name": station.machine_name,
                "machine_type": station.machine_type,
                "measurement_interface": station.measurement_interface,
                "scanner_host": station.scanner_host,
                "scanner_port": station.scanner_port,
                "scanner_protocol": station.scanner_protocol,
                "adapter_config": station.adapter_config or [],
                "payload_format": station.payload_format,
                "timing_notes": station.timing_notes,
                "network_notes": station.network_notes,
                "active": station.active,
                "status": status,
                "online": is_station_online(status, received_at),
                "last_heartbeat_at": format_datetime(received_at),
                "companion_version": latest_heartbeat.companion_version
                if latest_heartbeat
                else None,
                "adapter_status": latest_heartbeat.adapter_status
                if latest_heartbeat
                else None,
                "measurement_type_codes": [
                    link.measurement_type_code
                    for link in active_measurement_links
                ],
                "measurement_type_details": [
                    {
                        "code": link.measurement_type_code,
                        "label": link.measurement_type.label
                        if link.measurement_type
                        else link.measurement_type_code,
                        "unit": link.measurement_type.unit if link.measurement_type else None,
                    }
                    for link in sorted(
                        active_measurement_links,
                        key=lambda item: item.measurement_type_code,
                    )
                ],
            }
        )
    return rows


def load_measurement_type_options(session: Session) -> list[str]:
    return list(
        session.scalars(
            select(MeasurementType.code)
            .where(MeasurementType.active.is_(True))
            .order_by(MeasurementType.code)
        )
    )


def kiosk_workflow_title(station: dict[str, Any]) -> str:
    name_parts = " ".join(
        str(value or "")
        for value in (
            station.get("name"),
            station.get("machine_name"),
            station.get("machine_type"),
        )
    ).lower()
    measurement_codes = set(station.get("measurement_type_codes") or [])
    if "fertig" in name_parts or "ueberstand" in measurement_codes:
        return "Fertig messen"
    if "breite" in name_parts or measurement_codes == {"breite"}:
        return "Breite messen"
    return station.get("machine_name") or station.get("name") or "Messen"


def kiosk_station_summary(station: dict[str, Any]) -> str:
    measurement_labels = ", ".join(
        detail["label"] for detail in station.get("measurement_type_details", [])
    )
    return "\n".join(
        [
            f"Station: `{station['name']}`",
            f"Standort: `{station['location'] or '-'}`",
            f"Messarten: `{measurement_labels or '-'}`",
        ]
    )


def load_latest_measurement_for_part(
    session: Session,
    station_id: int,
    rueckmeldenummer: str,
) -> Measurement | None:
    return session.scalars(
        select(Measurement)
        .join(Measurement.part)
        .options(selectinload(Measurement.values))
        .where(
            Measurement.station_id == station_id,
            Measurement.part.has(rueckmeldenummer=rueckmeldenummer),
        )
        .order_by(Measurement.measured_at.desc(), Measurement.id.desc())
        .limit(1)
    ).one_or_none()


def save_kiosk_measurement(
    session: Session,
    *,
    station_id: int,
    rueckmeldenummer: str,
    values: dict[str, Decimal],
) -> int:
    station = session.get(Station, station_id)
    if station is None:
        raise ValueError("Station wurde nicht gefunden.")

    allowed_details = {
        link.measurement_type_code: link.measurement_type
        for link in station.measurement_type_links
        if link.active
    }
    unsupported_types = sorted(set(values) - set(allowed_details))
    if unsupported_types:
        raise ValueError(
            "Messart ist für diese Station nicht erlaubt: "
            f"{', '.join(unsupported_types)}"
        )

    part = session.scalars(
        select(Part).where(Part.rueckmeldenummer == rueckmeldenummer)
    ).one_or_none()
    if part is None:
        part = Part(rueckmeldenummer=rueckmeldenummer)
        session.add(part)
        session.flush()

    measurement = Measurement(
        part_id=part.id,
        station_id=station_id,
        result_status="unknown",
        measured_at=datetime.now(UTC),
        source_type="operator_kiosk",
        raw_payload_id=None,
        idempotency_key=f"kiosk:{station_id}:{uuid4().hex}",
        values=[
            MeasurementValue(
                measurement_type=measurement_type,
                value=value,
                unit=allowed_details[measurement_type].unit
                if allowed_details[measurement_type]
                else None,
                result_status=None,
            )
            for measurement_type, value in values.items()
        ],
    )
    session.add(measurement)
    session.flush()
    return measurement.id


def set_select_value(widget: pn.widgets.Select, value: str) -> None:
    if value and value not in widget.options:
        widget.options = [*widget.options, value]
    widget.value = value


def adapter_summary_rows(configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for config in configs:
        rows.append(
            {
                "enabled": config.get("enabled", True),
                "type": config.get("type", ""),
                "name": config.get("name", ""),
                "server": config.get("server", ""),
                "share": config.get("share", ""),
                "remote_dir": config.get("remote_dir", ""),
                "host": config.get("host", ""),
                "port": config.get("port", ""),
                "command": config.get("command", ""),
                "measurement_type": config.get("measurement_type", ""),
                "value_column_index": config.get("value_column_index", ""),
                "delete_after_success": config.get("delete_after_success", False),
            }
        )
    return rows


def replace_station_measurement_types(
    session: Session,
    station_id: int,
    measurement_type_codes: list[str],
) -> None:
    requested_codes = set(measurement_type_codes)
    existing_links = session.scalars(
        select(StationMeasurementType).where(
            StationMeasurementType.station_id == station_id
        )
    ).all()
    links_by_code = {link.measurement_type_code: link for link in existing_links}

    for code, link in links_by_code.items():
        link.active = code in requested_codes

    for code in sorted(requested_codes - links_by_code.keys()):
        session.add(
            StationMeasurementType(
                station_id=station_id,
                measurement_type_code=code,
                active=True,
            )
        )


def load_measurement_history(
    session: Session,
    rueckmeldenummer: str,
    station_id: int | None = None,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    if not rueckmeldenummer:
        return [], {}

    query = (
        select(Measurement)
        .join(Measurement.part)
        .options(
            selectinload(Measurement.station),
            selectinload(Measurement.values).selectinload(MeasurementValue.type_definition),
        )
        .where(Measurement.part.has(rueckmeldenummer=rueckmeldenummer))
    )
    if station_id is not None:
        query = query.where(Measurement.station_id == station_id)

    measurements = session.scalars(
        query.order_by(Measurement.measured_at.desc(), Measurement.id.desc())
    ).all()

    history_rows = []
    value_rows = {}
    for measurement in measurements:
        history_rows.append(
            {
                "id": measurement.id,
                "station": measurement.station.name,
                "measured_at": format_datetime(measurement.measured_at),
                "result": measurement.result_status,
                "source": measurement.source_type,
                "raw_payload_id": measurement.raw_payload_id,
            }
        )
        value_rows[measurement.id] = [
            {
                "type": value.measurement_type,
                "label": value.type_definition.label if value.type_definition else "",
                "value": value.value,
                "unit": value.unit or "",
                "result": value.result_status or "",
            }
            for value in sorted(measurement.values, key=lambda item: item.measurement_type)
        ]
    return history_rows, value_rows


def load_raw_payload(session: Session, raw_payload_id: int) -> dict[str, Any]:
    raw_payload = session.scalars(
        select(RawPayload)
        .options(selectinload(RawPayload.station))
        .where(RawPayload.id == raw_payload_id)
    ).one_or_none()
    if raw_payload is None:
        raise ValueError(f"Raw payload {raw_payload_id} was not found.")

    return {
        "id": raw_payload.id,
        "station": raw_payload.station.name,
        "source_type": raw_payload.source_type,
        "payload_hash": raw_payload.payload_hash,
        "received_at": format_datetime(raw_payload.received_at),
        "content": raw_payload.content,
    }


def values_markdown(values: list[dict[str, Any]]) -> str:
    if not values:
        return "No measurement values recorded."

    lines = ["### Measurement values", "| Type | Value | Result |", "| --- | --- | --- |"]
    for value in values:
        label = value["label"] or value["type"]
        lines.append(
            f"| {label} | {value['value']} {value['unit']} | {value['result'] or '-'} |"
        )
    return "\n".join(lines)


def raw_payload_markdown(detail: dict[str, Any]) -> str:
    return "\n".join(
        [
            f"### Raw payload {detail['id']}",
            f"- Station: `{detail['station']}`",
            f"- Source: `{detail['source_type']}`",
            f"- Received: `{detail['received_at']}`",
            f"- Hash: `{detail['payload_hash']}`",
            "",
            "```text",
            detail["content"],
            "```",
        ]
    )


def format_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.isoformat(timespec="seconds")


def parse_optional_port(value: str) -> int | None:
    if not value.strip():
        return None

    port = int(value)
    if port < 1 or port > 65535:
        raise ValueError("Scanner port must be between 1 and 65535.")
    return port


def run() -> None:
    settings = get_settings()
    panel_executable = shutil.which("panel")
    if panel_executable is None:
        raise RuntimeError(
            "Panel executable was not found. Install project dependencies with "
            '`python -m pip install -e ".[dev]"`.'
        )

    app_resource = resources.files("slf_trace.ui").joinpath("app.py")
    with resources.as_file(app_resource) as app_path:
        command = [
            panel_executable,
            "serve",
            "--address",
            settings.ui_host,
            "--port",
            str(settings.ui_port),
            "--show",
            "--allow-websocket-origin",
            ui_websocket_origin(settings),
            str(app_path),
        ]
        if settings.ui_autoreload:
            command.insert(-1, "--dev")

        subprocess.run(command, check=True)


def ui_websocket_origin(settings: Settings) -> str:
    return f"{settings.ui_host}:{settings.ui_port}"
