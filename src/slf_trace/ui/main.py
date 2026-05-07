from __future__ import annotations

import json
import shutil
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from html import escape
from importlib import resources
from types import MappingProxyType
from typing import Any
from uuid import uuid4

import pandas as pd
import panel as pn
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, selectinload, sessionmaker

from slf_trace.api.services.admin import current_station_event, is_station_online, station_health
from slf_trace.config import Settings, get_settings
from slf_trace.models import (
    Measurement,
    MeasurementType,
    MeasurementValue,
    Part,
    RawPayload,
    Station,
    StationHeartbeat,
)
from slf_trace.security import generate_station_token, hash_station_token
from slf_trace.ui.branding import load_logo_svg

pn.extension("tabulator")

_session_factory: sessionmaker[Session] | None = None
_KIOSK_CSS_REGISTERED = False
_KIOSK_CHOICE_BUTTON_STYLESHEET = """
:host {
    font-size: 24px !important;
    height: 152px !important;
}
:host .bk-btn,
.bk-btn {
    font-size: 24px !important;
    height: 152px !important;
    min-height: 152px !important;
    font-weight: 700 !important;
}
:host .bk-btn *,
.bk-btn * {
    font-size: 24px !important;
}
"""
_ADMIN_TAB_STYLESHEET = """
.bk-header {
    gap: 6px;
    padding: 0 0 6px 0;
    margin-bottom: 10px;
    border-bottom: 2px solid #cbd5e1 !important;
}
.bk-tab {
    min-width: 112px;
    padding: 10px 16px !important;
    background: #e5e7eb !important;
    border: 1px solid #cbd5e1 !important;
    border-bottom-color: #94a3b8 !important;
    border-radius: 6px 6px 0 0 !important;
    color: #1f2937 !important;
    font-size: 15px;
    font-weight: 750;
}
.bk-tab:hover {
    background: #dbeafe !important;
    border-color: #93c5fd !important;
    color: #111827 !important;
}
.bk-tab.bk-active {
    background: #ffffff !important;
    border-color: #64748b !important;
    color: #0f766e !important;
    box-shadow: inset 0 4px 0 #0f766e;
}
"""
WORKFLOW_OPTIONS = {
    "Measurement capture": "measurement_capture",
    "Label printing": "label_printing",
    "Laser marking": "laser_marking",
}


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


def build_app(*, kiosk: bool = False) -> pn.Column:
    global _KIOSK_CSS_REGISTERED
    settings = get_settings()
    kiosk_station_id, kiosk_station_source = resolve_kiosk_station_id(
        settings,
        pn.state.session_args,
    )
    if not _KIOSK_CSS_REGISTERED:
        pn.config.raw_css.append(
            """
            :root {
                --slf-ink: #111827;
                --slf-muted: #4b5563;
                --slf-border: #d1d5db;
                --slf-surface: #f8fafc;
                --slf-accent: #0f766e;
                --slf-accent-dark: #115e59;
            }
            .slf-kiosk input {
                font-size: 30px !important;
                min-height: 72px;
            }
            .slf-kiosk .bk-btn {
                font-size: 20px !important;
                min-height: 64px;
                font-weight: 700;
            }
            .slf-kiosk-choice.bk-btn,
            .slf-kiosk-choice .bk-btn {
                font-size: 24px !important;
                min-height: 152px;
                height: 152px;
                padding-left: 24px;
                padding-right: 24px;
            }
            .slf-kiosk-choice *,
            .slf-kiosk-choice.bk-btn *,
            .slf-kiosk-choice .bk-btn * {
                font-size: 24px !important;
            }
            .slf-kiosk-choice-row .bk-btn {
                font-size: 24px !important;
                min-height: 152px;
                height: 152px;
                font-weight: 700;
            }
            .slf-kiosk select {
                min-height: 44px;
            }
            .slf-kiosk h2, .slf-kiosk h3 {
                letter-spacing: 0;
            }
            """
        )
        _KIOSK_CSS_REGISTERED = True
    logo = pn.pane.SVG(load_logo_svg(), width=220, height=64, sizing_mode="fixed")
    header = pn.Row(
        logo,
        pn.Column(
            pn.pane.HTML(
                "<h1 style='margin:0;color:#111827;font-size:30px'>SLF Track and Trace</h1>"
            ),
            pn.pane.HTML(
                f"<div style='color:#4b5563'>Environment: "
                f"<strong>{settings.app_env}</strong></div>"
            ),
            sizing_mode="stretch_width",
            margin=(0, 0, 0, 0),
        ),
        sizing_mode="stretch_width",
        align="start",
        styles={
            "background": "#ffffff",
            "border": "1px solid #d1d5db",
            "border-radius": "8px",
            "padding": "14px 18px",
            "margin-bottom": "12px",
        },
    )

    station_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "id": None,
            "status": None,
            "health": None,
            "name": None,
            "location": None,
            "last_heartbeat": None,
            "workflow": None,
            "measurement_types": None,
            "active": None,
        },
        selectable=1,
        height=180,
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
    adapter_detail_message = pn.pane.Markdown("Select a station to view adapter state.")
    adapter_detail_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "adapter": None,
            "state": None,
            "last_event": None,
            "error": None,
        },
        height=160,
        sizing_mode="stretch_width",
        visible=False,
    )
    diagnostics_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "occurred_at": None,
            "severity": None,
            "event_type": None,
            "message": None,
        },
        height=180,
        sizing_mode="stretch_width",
    )

    input_width = 260
    adapter_field_width = 260
    name = pn.widgets.TextInput(name="Name", width=input_width)
    location = pn.widgets.TextInput(name="Location", width=input_width)
    scanner_host = pn.widgets.TextInput(name="Scanner IP", width=input_width)
    scanner_port = pn.widgets.IntInput(name="Listen port", start=0, end=65535, value=0, width=140)
    scanner_protocol = pn.widgets.Select(
        name="Scanner protocol",
        options=["", "Keyence SR-X TCP", "none", "other"],
        width=180,
    )
    workflow_type = pn.widgets.Select(
        name="Workflow type",
        options=WORKFLOW_OPTIONS,
        value="measurement_capture",
        width=260,
    )
    workflow_title = pn.widgets.TextInput(
        name="Display title",
        placeholder="Optional kiosk title",
        width=260,
    )
    workflow_config = pn.widgets.TextAreaInput(
        name="Workflow config JSON",
        value="{}",
        height=120,
        sizing_mode="stretch_width",
    )
    active = pn.widgets.Checkbox(name="Active", value=True)
    station_token_status = pn.pane.Markdown("Companion token: `not configured`")
    station_token_button = pn.widgets.Button(
        name="Generate new station token",
        button_type="primary",
        width=220,
    )
    station_token_output = pn.widgets.TextAreaInput(
        name="New station token (shown once)",
        value="",
        height=90,
        sizing_mode="stretch_width",
        visible=False,
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
    adapter_enabled = pn.widgets.Checkbox(
        name="Enabled",
        value=True,
        width=adapter_field_width,
    )
    adapter_name = pn.widgets.TextInput(
        name="Adapter name",
        value="smb1-polling",
        width=adapter_field_width,
    )
    adapter_type = pn.widgets.Select(
        name="Adapter type",
        options={
            "SMB1 polling": "smb1_polling",
            "Serial request": "serial_request",
            "TCP/IP line": "tcp_line",
        },
        value="smb1_polling",
        width=adapter_field_width,
    )
    adapter_server = pn.widgets.TextInput(name="SMB server", width=adapter_field_width)
    adapter_share = pn.widgets.TextInput(name="Share", width=adapter_field_width)
    adapter_remote_dir = pn.widgets.TextInput(
        name="Remote directory",
        value="/ExcelAusgabe",
        width=adapter_field_width,
    )
    adapter_filename_pattern = pn.widgets.TextInput(
        name="Filename pattern",
        value=r"_(\d+)\.csv$",
        width=adapter_field_width,
    )
    adapter_measurement_type = pn.widgets.Select(
        name="Measurement type",
        options=[],
        width=adapter_field_width,
    )
    adapter_value_column_index = pn.widgets.IntInput(
        name="Value column index",
        start=0,
        value=13,
        width=adapter_field_width,
    )
    adapter_username_env = pn.widgets.TextInput(
        name="Username env",
        value="SMB_USER",
        width=adapter_field_width,
    )
    adapter_password_env = pn.widgets.TextInput(
        name="Password env",
        value="SMB_PASSWORD",
        width=adapter_field_width,
    )
    adapter_encoding = pn.widgets.Select(
        name="Encoding",
        options=["cp1252", "utf-8", "latin-1"],
        value="cp1252",
        width=adapter_field_width,
    )
    adapter_delimiter = pn.widgets.TextInput(
        name="Delimiter",
        value=";",
        width=adapter_field_width,
    )
    adapter_poll_interval = pn.widgets.FloatInput(
        name="Poll interval seconds",
        start=0.1,
        value=2.0,
        width=adapter_field_width,
    )
    adapter_delete_after_success = pn.widgets.Checkbox(
        name="Delete after success",
        value=True,
        width=adapter_field_width,
    )
    adapter_delete_with_smbclient = pn.widgets.Checkbox(
        name="Use smbclient delete",
        value=True,
        width=adapter_field_width,
    )
    adapter_processed_hashes_path = pn.widgets.TextInput(
        name="Processed hashes path",
        value="state/smb-processed.json",
        width=adapter_field_width,
    )
    serial_port = pn.widgets.TextInput(
        name="Serial port",
        value="COM5",
        width=adapter_field_width,
    )
    serial_command = pn.widgets.TextInput(
        name="Command",
        value=r"?\r",
        width=adapter_field_width,
    )
    serial_baudrate = pn.widgets.IntInput(
        name="Baudrate",
        start=1,
        value=4800,
        width=adapter_field_width,
    )
    serial_bytesize = pn.widgets.Select(
        name="Data bits",
        options=[5, 6, 7, 8],
        value=7,
        width=adapter_field_width,
    )
    serial_parity = pn.widgets.Select(
        name="Parity",
        options={"None": "N", "Even": "E", "Odd": "O", "Mark": "M", "Space": "S"},
        value="E",
        width=adapter_field_width,
    )
    serial_stopbits = pn.widgets.Select(
        name="Stop bits",
        options=[1.0, 1.5, 2.0],
        value=2.0,
        width=adapter_field_width,
    )
    serial_timeout = pn.widgets.FloatInput(
        name="Timeout seconds",
        start=0.1,
        value=2.0,
        width=adapter_field_width,
    )
    tcp_host = pn.widgets.TextInput(name="TCP host", width=adapter_field_width)
    tcp_port = pn.widgets.IntInput(
        name="TCP port",
        start=1,
        end=65535,
        value=9000,
        width=adapter_field_width,
    )
    tcp_reconnect_delay = pn.widgets.FloatInput(
        name="Reconnect delay seconds",
        start=0.1,
        value=2.0,
        width=adapter_field_width,
    )
    tcp_command = pn.widgets.TextInput(
        name="Query command",
        value=r"?\r",
        width=adapter_field_width,
    )
    adapter_add_button = pn.widgets.Button(
        name="Add adapter",
        button_type="primary",
        width=130,
        disabled=True,
    )
    adapter_remove_button = pn.widgets.Button(name="Remove", button_type="danger", width=110)
    adapter_preview = pn.pane.JSON(
        [],
        name="Adapter config",
        depth=4,
        height=220,
        sizing_mode="stretch_width",
    )
    adapter_message = pn.pane.Alert("", alert_type="info", visible=False)

    refresh_button = pn.widgets.Button(name="Refresh", button_type="primary")
    new_station_button = pn.widgets.Button(name="New station", button_type="primary")
    create_station_button = pn.widgets.Button(
        name="Create station",
        button_type="success",
        visible=False,
    )
    cancel_station_button = pn.widgets.Button(
        name="Cancel draft",
        button_type="light",
        visible=False,
    )
    station_message = pn.pane.Alert("", alert_type="info", visible=False)

    rueckmeldenummer = pn.widgets.TextInput(name="Rückmeldenummer")
    history_station = pn.widgets.Select(
        name="Station",
        options={"All stations": 0},
        value=0,
        width=260,
    )
    lookup_button = pn.widgets.Button(
        name="Lookup",
        button_type="primary",
        margin=0,
    )
    lookup_button_stack = pn.Column(
        pn.pane.HTML("&nbsp;", height=22, margin=0),
        lookup_button,
        margin=0,
        width=120,
    )
    history_table = pn.widgets.Tabulator(
        value=pd.DataFrame(),
        editors={
            "id": None,
            "station": None,
            "measured_at": None,
            "source": None,
            "raw_payload_id": None,
        },
        selectable=1,
        height=260,
        sizing_mode="stretch_width",
    )
    measurement_values = pn.pane.Markdown("Search a Rückmeldenummer to view measurements.")
    raw_payload_detail = pn.pane.Markdown("Raw payload content appears here.")
    lookup_message = pn.pane.Alert("", alert_type="info", visible=False)

    kiosk_operator_logo = pn.pane.SVG(load_logo_svg(), width=132, height=44, sizing_mode="fixed")
    kiosk_station = pn.widgets.Select(name="Station", options={}, visible=False)
    kiosk_refresh_button = pn.widgets.Button(name="Aktualisieren", button_type="light", width=130)
    kiosk_title = pn.pane.HTML(
        "<div style='font-size:24px;font-weight:800;color:#1f3b57'>Station auswählen</div>",
        sizing_mode="fixed",
    )
    kiosk_station_badge = pn.pane.HTML(
        "",
        sizing_mode="fixed",
    )
    kiosk_status = pn.pane.HTML("")
    kiosk_message = pn.pane.Alert("", alert_type="info", visible=False)
    kiosk_barcode = pn.widgets.TextInput(
        name="",
        placeholder="Barcode scannen / Rückmeldenummer eingeben",
        sizing_mode="stretch_width",
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
    kiosk_keep_measurement_button = pn.widgets.Button(
        name="Wert behalten",
        button_type="success",
        width=220,
        height=152,
        visible=False,
        css_classes=["slf-kiosk-choice"],
        styles={"font-size": "24px", "height": "152px"},
        stylesheets=[_KIOSK_CHOICE_BUTTON_STYLESHEET],
    )
    kiosk_new_measurement_button = pn.widgets.Button(
        name="Neu messen",
        button_type="primary",
        width=220,
        height=152,
        visible=False,
        css_classes=["slf-kiosk-choice"],
        styles={"font-size": "24px", "height": "152px"},
        stylesheets=[_KIOSK_CHOICE_BUTTON_STYLESHEET],
    )
    kiosk_measurement_inputs: dict[str, pn.widgets.TextInput] = {}
    kiosk_measurement_form = pn.Column(sizing_mode="stretch_width")
    kiosk_summary = pn.pane.Markdown("")
    kiosk_current_station_id: int | None = None
    kiosk_current_barcode: str | None = None
    kiosk_last_scan_raw_payload_id: int | None = None
    kiosk_pending_existing_measurement: dict[str, str] | None = None
    kiosk_waiting_for_new_measurement = False
    kiosk_measurement_baseline_id = 0

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

    def set_station_draft_mode(enabled: bool) -> None:
        new_station_button.visible = not enabled
        create_station_button.visible = enabled
        cancel_station_button.visible = enabled

    def refresh_stations(
        _: object | None = None,
        *,
        select_station_id: int | None = None,
        clear_message: bool = True,
    ) -> None:
        nonlocal station_rows
        try:
            with session_scope(settings) as session:
                station_rows = load_station_rows(session)
                type_options = load_measurement_type_options(session)
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
                    "health": row["health_state"],
                    "name": row["name"],
                    "location": row["location"],
                    "last_heartbeat": row["last_heartbeat_at"],
                    "workflow": row["workflow_type"],
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
                station = next(
                    (row for row in station_rows if row["id"] == select_station_id),
                    None,
                )
                if station is not None:
                    update_station_status_bar(station)
        if clear_message:
            station_message.visible = False

    def fill_station_form(station: dict[str, Any]) -> None:
        nonlocal loading_station_form
        loading_station_form = True
        try:
            name.value = station["name"] or ""
            location.value = station["location"] or ""
            scanner_host.value = station["scanner_host"] or ""
            scanner_port.value = station["scanner_port"] or 0
            set_select_value(scanner_protocol, station["scanner_protocol"] or "")
            set_select_value(workflow_type, station["workflow_type"] or "measurement_capture")
            workflow_title.value = station["workflow_title"] or ""
            workflow_config.value = json.dumps(
                station.get("workflow_config") or {},
                indent=2,
                sort_keys=True,
            )
            active.value = station["active"]
            load_adapter_configs(station.get("adapter_config") or [])
        finally:
            loading_station_form = False

    def update_station_status_bar(station: dict[str, Any]) -> None:
        station_name_status.object = f"**{station['name']}**"
        station_health_status.object = f"Health: `{station['health_state']}`"
        station_heartbeat_status.object = (
            f"Last heartbeat: `{station['last_heartbeat_at'] or 'never'}`"
        )
        station_companion_status.object = (
            f"Companion: `{station['companion_version'] or 'unknown'}`"
        )
        station_host_status.object = f"Hostname: `{station['hostname'] or '-'}`"
        station_location_status.object = (
            f"Latest issue: `{station['health_message'] or station['location'] or '-'}`"
        )
        token_text = "configured" if station.get("companion_token_configured") else "not configured"
        station_token_status.object = f"Companion token: `{token_text}`"
        diagnostics_table.value = pd.DataFrame(station["recent_events"])
        adapter_rows = adapter_status_rows(station.get("adapter_status"))
        adapter_detail_table.value = pd.DataFrame(adapter_rows)
        adapter_detail_table.visible = bool(adapter_rows)
        adapter_detail_message.object = (
            "" if adapter_rows else "No adapter state reported yet."
        )
        adapter_detail_message.visible = not bool(adapter_rows)

    def clear_station_form() -> None:
        nonlocal loading_station_form
        loading_station_form = True
        try:
            name.value = ""
            location.value = ""
            scanner_host.value = ""
            scanner_port.value = 0
            scanner_protocol.value = ""
            workflow_type.value = "measurement_capture"
            workflow_title.value = ""
            workflow_config.value = "{}"
            active.value = True
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
        set_station_draft_mode(False)
        station = next(
            row for row in station_rows if row["id"] == selected_station_id
        )
        fill_station_form(station)
        update_station_status_bar(station)
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
        station_message.visible = False

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
            "location": location.value.strip() or None,
            "scanner_host": scanner_host.value.strip() or None,
            "scanner_port": scanner_port.value or None,
            "scanner_protocol": scanner_protocol.value.strip() or None,
            "workflow_type": workflow_type.value,
            "workflow_title": workflow_title.value.strip() or None,
            "workflow_config": parse_workflow_config(workflow_config.value),
            "active": active.value,
        }

    def start_new_station(_: object | None = None) -> None:
        nonlocal creating_station, selected_station_id
        creating_station = True
        set_station_draft_mode(True)
        selected_station_id = None
        station_table.selection = []
        clear_station_form()
        station_name_status.object = "**New station**"
        station_health_status.object = "Status: `draft`"
        station_heartbeat_status.object = "Last heartbeat: `never`"
        station_companion_status.object = "Companion: `unknown`"
        station_host_status.object = "Hostname: `-`"
        station_location_status.object = "Location: `-`"
        station_token_status.object = "Companion token: `not configured`"
        station_token_output.visible = False
        station_token_output.value = ""
        adapter_detail_table.value = pd.DataFrame()
        adapter_detail_table.visible = False
        adapter_detail_message.object = "Select a station to view adapter state."
        adapter_detail_message.visible = True
        diagnostics_table.value = pd.DataFrame()
        set_message(station_message, "Enter station details, then save.")

    def cancel_new_station(_: object | None = None) -> None:
        nonlocal creating_station
        creating_station = False
        set_station_draft_mode(False)
        station_table.selection = []
        clear_station_form()
        set_message(station_message, "New station cancelled.")

    def create_station_from_form() -> None:
        nonlocal creating_station, selected_station_id
        try:
            values = current_station_config_values()
            values["adapter_config"] = [dict(config) for config in adapter_configs]
            with session_scope(settings) as session:
                station = Station(**values)
                session.add(station)
                session.flush()
                created_station_id = station.id
        except Exception as exc:  # noqa: BLE001
            set_message(station_message, f"Could not create station: {exc}", "danger")
            return

        creating_station = False
        set_station_draft_mode(False)
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
        update_adapter_action_state()

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
            adapter_delete_after_success.value = True
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
            tcp_command.value = r"?\r"
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
            adapter_delete_after_success.value = bool(config.get("delete_after_success", True))
            adapter_delete_with_smbclient.value = bool(config.get("delete_with_smbclient", True))
            adapter_processed_hashes_path.value = str(
                config.get("processed_hashes_path") or "state/smb-processed.json"
            )
            config_type = str(config.get("type") or "smb1_polling")
            serial_port.value = (
                str(config.get("port") or "COM5")
                if config_type == "serial_request"
                else "COM5"
            )
            serial_command.value = str(config.get("command") or r"?\r")
            serial_baudrate.value = int(config.get("baudrate", 4800))
            serial_bytesize.value = int(config.get("bytesize", 7))
            serial_parity.value = str(config.get("parity") or "E")
            serial_stopbits.value = float(config.get("stopbits", 2.0))
            serial_timeout.value = float(config.get("timeout_seconds", 2.0))
            tcp_host.value = str(config.get("host") or "")
            tcp_port.value = int(config.get("port", 9000)) if config_type == "tcp_line" else 9000
            tcp_reconnect_delay.value = float(config.get("reconnect_delay_seconds", 2.0))
            tcp_command.value = str(config.get("command") or r"?\r")
        finally:
            loading_adapter_form = False
        update_adapter_action_state()

    def current_adapter_values() -> dict[str, Any]:
        if adapter_type.value == "tcp_line":
            values = {
                "type": adapter_type.value,
                "enabled": adapter_enabled.value,
                "name": adapter_name.value.strip() or "tcp-line",
                "host": tcp_host.value.strip(),
                "port": tcp_port.value,
                "measurement_type": adapter_measurement_type.value,
                "command": tcp_command.value,
                "poll_interval_seconds": adapter_poll_interval.value,
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
        update_selected_station_adapter_measurement_types()
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
        update_adapter_action_state()
        if selected_adapter_index is None:
            return

        try:
            adapter_configs[selected_adapter_index] = current_adapter_values()
            render_adapter_configs()
            save_adapter_configs()
        except Exception as exc:  # noqa: BLE001
            set_message(adapter_message, f"Could not autosave adapter config: {exc}", "danger")

    def update_adapter_action_state() -> None:
        try:
            current_adapter_values()
        except Exception:  # noqa: BLE001
            adapter_add_button.disabled = True
        else:
            adapter_add_button.disabled = False

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

    def generate_selected_station_token(_: object | None = None) -> None:
        if selected_station_id is None:
            set_message(station_message, "Select a station first.", "warning")
            return

        token = generate_station_token()
        try:
            with session_scope(settings) as session:
                station = session.get(Station, selected_station_id)
                if station is None:
                    raise ValueError(f"Station {selected_station_id} was not found.")
                station.companion_token_hash = hash_station_token(token)
        except Exception as exc:  # noqa: BLE001
            set_message(station_message, f"Could not generate station token: {exc}", "danger")
            return

        station = next(row for row in station_rows if row["id"] == selected_station_id)
        station["companion_token_configured"] = True
        station_token_status.object = "Companion token: `configured`"
        station_token_output.value = f"STATION_TOKEN={token}"
        station_token_output.visible = True
        set_message(
            station_message,
            "New token generated. Copy it into the station service environment now; "
            "it will not be shown again after refresh.",
            "success",
        )

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
        table_data.loc[row_index, "workflow"] = station["workflow_type"]
        table_data.loc[row_index, "active"] = station["active"]
        station_table.value = table_data

    def update_selected_station_adapter_measurement_types() -> None:
        if selected_station_id is None:
            return

        station = next(row for row in station_rows if row["id"] == selected_station_id)
        measurement_type_codes = adapter_measurement_type_codes(adapter_configs)
        station["measurement_type_codes"] = measurement_type_codes
        station["measurement_type_details"] = [
            {"code": code, "label": code, "unit": None} for code in measurement_type_codes
        ]

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
        if rueckmeldenummer.value.strip():
            set_message(lookup_message, f"Loaded {len(history_rows)} measurements.")
        else:
            set_message(lookup_message, f"Loaded latest {len(history_rows)} measurements.")

    def select_measurement(event: Any) -> None:
        if not event.new:
            return

        row_index = event.new[0]
        if history_table.value.empty or row_index >= len(history_table.value):
            return

        row = history_table.value.iloc[row_index]
        payload_id = row["raw_payload_id"]
        if payload_id and not pd.isna(payload_id):
            inspect_payload(int(payload_id))
        else:
            raw_payload_detail.object = "Selected measurement has no linked raw payload."
        measurement_values.object = values_markdown(
            selected_history.get(int(row["id"]), [])
        )

    def inspect_payload(raw_payload_id: int) -> None:
        try:
            with session_scope(settings) as session:
                detail = load_raw_payload(session, raw_payload_id)
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
            if row["active"]
            and (
                row["workflow_type"] != "measurement_capture"
                or row["measurement_type_details"]
            )
        ]
        kiosk_station.options = {row["name"]: row["id"] for row in measurement_stations}
        if not kiosk_station.options:
            kiosk_station.value = None
            kiosk_title.object = (
                "<div style='font-size:24px;font-weight:800;color:#1f3b57'>"
                "Keine Messstation konfiguriert</div>"
            )
            kiosk_station_badge.object = ""
            kiosk_status.object = "Aktive Messstation mit Messart zuweisen."
            return

        if kiosk_station_id is None:
            kiosk_station.value = next(iter(kiosk_station.options.values()))
        elif kiosk_station_id in kiosk_station.options.values():
            kiosk_station.value = kiosk_station_id
        else:
            kiosk_station.value = None
            kiosk_title.object = (
                "<div style='font-size:24px;font-weight:800;color:#1f3b57'>"
                "Station nicht gefunden</div>"
            )
            kiosk_station_badge.object = ""
            kiosk_status.object = (
                f"Station {kiosk_station_id} aus {kiosk_station_source} ist nicht aktiv "
                "oder hat keine Messart zugewiesen."
            )
            kiosk_message.object = (
                "Admin-Konfiguration prüfen oder lokal mit "
                "`/kiosk?station_id=<id>` eine andere Station öffnen."
            )
            kiosk_message.alert_type = "danger"
            kiosk_message.visible = True
            return
        load_kiosk_station()

    def load_kiosk_station(_: object | None = None) -> None:
        nonlocal kiosk_current_station_id, kiosk_current_barcode, kiosk_last_scan_raw_payload_id
        nonlocal kiosk_pending_existing_measurement, kiosk_waiting_for_new_measurement
        nonlocal kiosk_measurement_baseline_id
        if kiosk_station.value is None:
            return
        kiosk_current_station_id = int(kiosk_station.value)
        kiosk_current_barcode = None
        kiosk_pending_existing_measurement = None
        kiosk_waiting_for_new_measurement = False
        kiosk_measurement_baseline_id = 0
        kiosk_keep_measurement_button.visible = False
        kiosk_new_measurement_button.visible = False
        with session_scope(settings) as session:
            latest_scan = load_latest_scanner_raw_payload(session, kiosk_current_station_id)
        kiosk_last_scan_raw_payload_id = latest_scan[0] if latest_scan is not None else None
        station = station_row_by_id(kiosk_current_station_id)
        kiosk_title.object = (
            "<div style='font-size:24px;font-weight:800;color:#1f3b57'>"
            f"{escape(kiosk_workflow_title(station))}</div>"
        )
        kiosk_station_badge.object = kiosk_station_badge_html(station)
        kiosk_barcode.value = ""
        kiosk_check_measurement_button.disabled = True
        build_kiosk_measurement_form(station)
        if station["workflow_type"] == "measurement_capture":
            kiosk_barcode.visible = True
            update_kiosk_status(step=1)
            set_message(
                kiosk_message,
                "Bitte Barcode scannen oder Rückmeldenummer eingeben.",
                "info",
            )
        else:
            kiosk_barcode.visible = False
            update_kiosk_status(step=1)
            set_message(
                kiosk_message,
                f"Workflow `{station['workflow_type']}` ist konfiguriert.",
                "info",
            )
        kiosk_summary.object = kiosk_station_summary(station)

    def build_kiosk_measurement_form(station: dict[str, Any]) -> None:
        kiosk_measurement_inputs.clear()
        if station.get("workflow_type") != "measurement_capture":
            kiosk_measurement_form.objects = []
            return

        rows = []
        for detail in station["measurement_type_details"]:
            input_widget = pn.widgets.TextInput(
                name=detail["label"],
                placeholder=f"Wert in {detail['unit'] or 'Einheit'}",
                width=300,
                disabled=True,
            )
            kiosk_measurement_inputs[detail["code"]] = input_widget
            rows.append(
                pn.Row(
                    input_widget,
                    pn.pane.HTML(
                        (
                            "<div style='padding-top:28px;color:#4b5563;font-size:15px'>"
                            f"<strong>{detail['code']}</strong>"
                            f"{' / ' + detail['unit'] if detail['unit'] else ''}"
                            "</div>"
                        ),
                        width=180,
                    ),
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
        nonlocal kiosk_current_barcode, kiosk_pending_existing_measurement
        nonlocal kiosk_waiting_for_new_measurement
        if kiosk_current_station_id is None:
            set_message(kiosk_message, "Keine Station ausgewählt.", "danger")
            return

        barcode = kiosk_barcode.value.strip()
        if not barcode:
            set_message(kiosk_message, "Bitte zuerst einen Barcode scannen.", "warning")
            update_kiosk_status(step=1)
            return
        if len(barcode) > 120:
            set_message(kiosk_message, "Der Barcode ist zu lang.", "danger")
            return

        kiosk_current_barcode = barcode
        kiosk_pending_existing_measurement = None
        kiosk_waiting_for_new_measurement = False
        kiosk_keep_measurement_button.visible = False
        kiosk_new_measurement_button.visible = False
        for input_widget in kiosk_measurement_inputs.values():
            input_widget.disabled = False
        kiosk_check_measurement_button.disabled = False

        station = station_row_by_id(kiosk_current_station_id)
        measurement_type_codes = set(station.get("measurement_type_codes") or [])
        try:
            with session_scope(settings) as session:
                existing = load_latest_measurement_for_station_type(
                    session,
                    measurement_type_codes,
                    barcode,
                )
        except Exception as exc:  # noqa: BLE001
            set_message(
                kiosk_message,
                f"Vorhandene Messung konnte nicht geprüft werden: {exc}",
                "danger",
            )
            return

        if existing is not None:
            kiosk_pending_existing_measurement = {
                "value_text": measurement_value_text(
                    existing,
                    station_row_by_id(kiosk_current_station_id),
                ),
                "station_name": existing.station.name if existing.station else "andere Station",
            }
            kiosk_message.object = (
                "<div style='font-size:24px;line-height:1.3;font-weight:700'>"
                f"Vorhandene Messung: {kiosk_pending_existing_measurement['value_text']}"
                "</div>"
                "<div style='font-size:16px;margin-top:8px'>"
                f"Quelle: {escape(kiosk_pending_existing_measurement['station_name'])}. "
                "Wert behalten oder neu vom Messgerät laden?"
                "</div>"
            )
            kiosk_message.alert_type = "warning"
            kiosk_message.visible = True
            kiosk_keep_measurement_button.visible = True
            kiosk_new_measurement_button.visible = True
            update_kiosk_status(step=2)
            return

        request_kiosk_measurement()

    def request_kiosk_measurement(_: object | None = None) -> None:
        nonlocal kiosk_waiting_for_new_measurement, kiosk_pending_existing_measurement
        nonlocal kiosk_measurement_baseline_id
        if kiosk_current_station_id is None or kiosk_current_barcode is None:
            return
        kiosk_pending_existing_measurement = None
        kiosk_waiting_for_new_measurement = True
        kiosk_keep_measurement_button.visible = False
        kiosk_new_measurement_button.visible = False
        try:
            with session_scope(settings) as session:
                latest_current_station_measurement = load_latest_measurement_for_part(
                    session,
                    kiosk_current_station_id,
                    kiosk_current_barcode,
                )
                kiosk_measurement_baseline_id = (
                    latest_current_station_measurement.id
                    if latest_current_station_measurement is not None
                    else 0
                )
                create_measurement_request(
                    session,
                    station_id=kiosk_current_station_id,
                    rueckmeldenummer=kiosk_current_barcode,
                )
        except Exception as exc:  # noqa: BLE001
            kiosk_waiting_for_new_measurement = False
            set_message(
                kiosk_message,
                f"Messanforderung konnte nicht gesendet werden: {exc}",
                "danger",
            )
            return
        update_kiosk_status(step=2)
        set_message(kiosk_message, "Barcode erfasst. Warte auf neuen Messwert...", "info")
        check_kiosk_measurement()

    def keep_kiosk_existing_measurement(_: object | None = None) -> None:
        nonlocal kiosk_current_barcode, kiosk_pending_existing_measurement
        if kiosk_pending_existing_measurement is None:
            return
        show_kiosk_measurement_found(kiosk_pending_existing_measurement["value_text"])
        kiosk_barcode.value = ""
        kiosk_current_barcode = None
        kiosk_pending_existing_measurement = None
        kiosk_keep_measurement_button.visible = False
        kiosk_new_measurement_button.visible = False
        kiosk_check_measurement_button.disabled = True
        update_kiosk_status(step=1)

    def check_kiosk_measurement(_: object | None = None) -> None:
        nonlocal kiosk_current_barcode, kiosk_waiting_for_new_measurement
        nonlocal kiosk_measurement_baseline_id
        if kiosk_current_station_id is None or kiosk_current_barcode is None:
            set_message(kiosk_message, "Bitte zuerst Barcode übernehmen.", "warning")
            return
        if not kiosk_waiting_for_new_measurement:
            return

        try:
            with session_scope(settings) as session:
                measurement = load_latest_measurement_for_part(
                    session,
                    kiosk_current_station_id,
                    kiosk_current_barcode,
                    after_measurement_id=kiosk_measurement_baseline_id,
                )
                progress = load_kiosk_measurement_progress(
                    session,
                    station_id=kiosk_current_station_id,
                    rueckmeldenummer=kiosk_current_barcode,
                )
        except Exception as exc:  # noqa: BLE001
            set_message(kiosk_message, f"Messwert konnte nicht geprüft werden: {exc}", "danger")
            return

        if measurement is None:
            received_types = set()
            if progress is not None:
                received_types = update_kiosk_progress(progress)
            if received_types:
                missing_labels = kiosk_missing_progress_labels(
                    progress or {},
                    station_row_by_id(kiosk_current_station_id),
                )
                waiting_text = (
                    f"Warte auf: {', '.join(missing_labels)}."
                    if missing_labels
                    else "Warte auf Upload."
                )
                set_message(
                    kiosk_message,
                    kiosk_progress_message(
                        progress or {},
                        station_row_by_id(kiosk_current_station_id),
                        waiting_text,
                    ),
                    "info",
                )
                update_kiosk_status(step=2)
            else:
                set_message(
                    kiosk_message,
                    (
                        "Noch kein Messwert vom Adapter empfangen. Messvorgang am Gerät prüfen."
                    ),
                    "warning",
                )
                update_kiosk_status(step=2)
            return

        show_kiosk_measurement_found(
            measurement_value_text(
                measurement,
                station_row_by_id(kiosk_current_station_id),
            )
        )
        kiosk_barcode.value = ""
        kiosk_current_barcode = None
        kiosk_waiting_for_new_measurement = False
        kiosk_measurement_baseline_id = 0
        kiosk_check_measurement_button.disabled = True
        for input_widget in kiosk_measurement_inputs.values():
            input_widget.value = ""
            input_widget.disabled = True
        update_kiosk_status(step=1)

    def show_kiosk_measurement_found(value_text: str) -> None:
        kiosk_message.object = (
            "<div style='font-size:28px;line-height:1.25;font-weight:700'>"
            f"Messung gefunden: {escape(value_text)}"
            "</div>"
        )
        kiosk_message.alert_type = "success"
        kiosk_message.visible = True

    def update_kiosk_progress(progress: dict[str, Any]) -> set[str]:
        received_types = set()
        for value in progress.get("values", []):
            measurement_type = str(value.get("measurement_type") or "")
            if not measurement_type:
                continue
            received_types.add(measurement_type)
            input_widget = kiosk_measurement_inputs.get(measurement_type)
            if input_widget is not None:
                input_widget.value = kiosk_progress_value_text(value)
                input_widget.disabled = True
        return received_types

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

    def process_kiosk_barcode(event: Any) -> None:
        barcode = str(event.new or "").strip()
        if not barcode or barcode == kiosk_current_barcode:
            return
        accept_kiosk_barcode()

    def poll_kiosk_scanner_scan() -> None:
        nonlocal kiosk_last_scan_raw_payload_id
        if not kiosk or kiosk_current_station_id is None:
            return
        station = station_row_by_id(kiosk_current_station_id)
        if station.get("workflow_type") != "measurement_capture":
            return

        try:
            with session_scope(settings) as session:
                latest_scan = load_latest_scanner_raw_payload(session, kiosk_current_station_id)
        except Exception as exc:  # noqa: BLE001
            set_message(kiosk_message, f"Scanner-Scan konnte nicht gelesen werden: {exc}", "danger")
            return

        if latest_scan is None:
            return

        raw_payload_id, barcode = latest_scan
        if raw_payload_id == kiosk_last_scan_raw_payload_id:
            return

        kiosk_last_scan_raw_payload_id = raw_payload_id
        if not barcode or barcode == kiosk_current_barcode:
            return

        kiosk_barcode.value = barcode

    def poll_kiosk_measurement() -> None:
        if not kiosk or kiosk_current_barcode is None:
            return
        check_kiosk_measurement()

    def auto_refresh_stations() -> None:
        if kiosk or creating_station:
            return
        refresh_stations(
            select_station_id=selected_station_id,
            clear_message=False,
        )

    def update_kiosk_status(*, step: int) -> None:
        labels = [
            ("1", "Barcode"),
            ("2", "Messwert"),
            ("3", "Hochladen"),
        ]
        rendered_steps = []
        for number, label in labels:
            active = int(number) == step
            done = int(number) < step
            background = "#0f766e" if active else "#d1fae5" if done else "#e5e7eb"
            color = "white" if active else "#065f46" if done else "#111827"
            border = "#0f766e" if active or done else "#d1d5db"
            rendered_steps.append(
                f"<span style='display:inline-block;min-width:96px;padding:12px 10px;"
                f"margin-right:4px;border-radius:6px;background:{background};color:{color};"
                f"border:1px solid {border};text-align:center;font-weight:700'>"
                f"{number}. {label}</span>"
            )
        kiosk_status.object = (
            "<div style='margin:10px 0 14px 0'>" + "".join(rendered_steps) + "</div>"
        )

    station_table.param.watch(select_station, "selection")
    adapter_table.param.watch(select_adapter, "selection")
    history_table.param.watch(select_measurement, "selection")
    kiosk_station.param.watch(load_kiosk_station, "value")
    refresh_button.on_click(refresh_stations)
    new_station_button.on_click(start_new_station)
    create_station_button.on_click(create_station_from_form)
    cancel_station_button.on_click(cancel_new_station)
    adapter_add_button.on_click(add_adapter)
    adapter_remove_button.on_click(remove_adapter)
    station_token_button.on_click(generate_selected_station_token)
    lookup_button.on_click(lookup_measurements)
    kiosk_refresh_button.on_click(refresh_stations)
    kiosk_barcode_button.on_click(accept_kiosk_barcode)
    kiosk_barcode.param.watch(process_kiosk_barcode, "value")
    kiosk_check_measurement_button.on_click(check_kiosk_measurement)
    kiosk_keep_measurement_button.on_click(keep_kiosk_existing_measurement)
    kiosk_new_measurement_button.on_click(request_kiosk_measurement)
    if kiosk:
        pn.state.add_periodic_callback(poll_kiosk_scanner_scan, period=1000)
        pn.state.add_periodic_callback(poll_kiosk_measurement, period=1000)
    else:
        pn.state.add_periodic_callback(auto_refresh_stations, period=5000)

    for field_widget in (
        name,
        location,
        scanner_host,
        scanner_port,
        scanner_protocol,
        workflow_type,
        workflow_title,
        workflow_config,
        active,
    ):
        field_widget.param.watch(autosave_config, "value")
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
                        location,
                        active,
                        ncols=2,
                        align="start",
                    ),
                    pn.pane.Markdown("### Companion API token"),
                    station_token_status,
                    station_token_button,
                    station_token_output,
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
                "Workflow",
                pn.Column(
                    pn.GridBox(
                        workflow_type,
                        workflow_title,
                        ncols=2,
                        align="start",
                    ),
                    workflow_config,
                    sizing_mode="stretch_width",
                ),
            ),
            sizing_mode="stretch_width",
            stylesheets=[_ADMIN_TAB_STYLESHEET],
        ),
        station_message,
        align="start",
        sizing_mode="stretch_width",
    )

    adapter_common_section = pn.Column(
        pn.pane.Markdown("### Common"),
        adapter_enabled,
        pn.GridBox(
            adapter_type,
            adapter_name,
            adapter_measurement_type,
            adapter_poll_interval,
            adapter_encoding,
            ncols=2,
            align="start",
        ),
        sizing_mode="stretch_width",
    )
    smb_adapter_section = pn.Column(
        pn.pane.Markdown("### SMB1 polling"),
        pn.GridBox(
            adapter_server,
            adapter_share,
            adapter_remote_dir,
            adapter_username_env,
            adapter_password_env,
            adapter_value_column_index,
            adapter_filename_pattern,
            adapter_delimiter,
            adapter_delete_after_success,
            adapter_delete_with_smbclient,
            adapter_processed_hashes_path,
            ncols=2,
            align="start",
        ),
        sizing_mode="stretch_width",
    )
    tcp_adapter_section = pn.Column(
        pn.pane.Markdown("### TCP/IP line"),
        pn.GridBox(
            tcp_host,
            tcp_port,
            tcp_command,
            adapter_poll_interval,
            tcp_reconnect_delay,
            ncols=2,
            align="start",
        ),
        sizing_mode="stretch_width",
    )
    serial_adapter_section = pn.Column(
        pn.pane.Markdown("### Serial request"),
        pn.GridBox(
            serial_port,
            serial_command,
            serial_baudrate,
            serial_bytesize,
            serial_parity,
            serial_stopbits,
            serial_timeout,
            ncols=2,
            align="start",
        ),
        sizing_mode="stretch_width",
    )

    def update_adapter_type_sections(_: object | None = None) -> None:
        smb_adapter_section.visible = adapter_type.value == "smb1_polling"
        tcp_adapter_section.visible = adapter_type.value == "tcp_line"
        serial_adapter_section.visible = adapter_type.value == "serial_request"
        if not loading_adapter_form:
            default_names = {
                "smb1_polling": "smb1-polling",
                "tcp_line": "tcp-line",
                "serial_request": "serial-request",
            }
            known_default_names = set(default_names.values())
            if adapter_name.value.strip() in known_default_names or not adapter_name.value.strip():
                adapter_name.value = default_names.get(adapter_type.value, adapter_name.value)
        update_adapter_action_state()

    update_adapter_type_sections()
    adapter_type.param.watch(update_adapter_type_sections, "value")

    adapter_config_form = pn.Column(
        pn.pane.Markdown("### Configuration"),
        pn.Row(adapter_add_button, adapter_remove_button),
        adapter_table,
        pn.pane.Markdown("#### Adapter settings"),
        adapter_common_section,
        smb_adapter_section,
        tcp_adapter_section,
        serial_adapter_section,
        adapter_message,
        pn.Accordion(
            ("Effective adapter JSON", adapter_preview),
            active=[],
            sizing_mode="stretch_width",
        ),
        sizing_mode="stretch_width",
    )
    adapter_runtime_section = pn.Column(
        pn.pane.Markdown("### Runtime state"),
        adapter_detail_message,
        adapter_detail_table,
        pn.pane.Markdown("### Recent diagnostics"),
        diagnostics_table,
        sizing_mode="stretch_width",
    )
    station_adapters_section = pn.Column(
        pn.pane.Markdown("## Adapters"),
        adapter_runtime_section,
        adapter_config_form,
        sizing_mode="stretch_width",
        styles={
            "border-top": "1px solid #d0d7de",
            "padding-top": "18px",
            "margin-top": "8px",
        },
    )
    kiosk_panel = pn.Column(
        pn.Row(
            pn.Row(
                kiosk_title,
                kiosk_station_badge,
                align="center",
                sizing_mode="stretch_width",
                styles={"gap": "14px"},
            ),
            pn.Spacer(sizing_mode="stretch_width"),
            kiosk_operator_logo,
            sizing_mode="stretch_width",
            align="center",
            styles={
                "border-bottom": "1px solid #d1d5db",
                "padding": "0 0 18px 0",
                "margin-bottom": "14px",
            },
        ),
        kiosk_status,
        pn.pane.HTML(
            "<div style='font-size:28px;font-weight:800;color:#111827'>"
            "Rückmeldenummer scannen</div>"
        ),
        kiosk_barcode,
        pn.Spacer(sizing_mode="stretch_height"),
        kiosk_message,
        pn.Row(
            kiosk_keep_measurement_button,
            kiosk_new_measurement_button,
            css_classes=["slf-kiosk-choice-row"],
            styles={"gap": "14px"},
        ),
        sizing_mode="stretch_width",
        css_classes=["slf-kiosk"],
        styles={
            "padding": "28px",
            "background": "#ffffff",
            "min-height": "calc(100vh - 32px)",
        },
    )

    if kiosk:
        return pn.Column(
            kiosk_panel,
            sizing_mode="stretch_width",
            styles={"background": "#ffffff", "padding": "16px"},
        )

    return pn.Column(
        header,
        pn.Tabs(
            (
                "Stations",
                pn.Column(
                    pn.Row(
                        refresh_button,
                        new_station_button,
                        create_station_button,
                        cancel_station_button,
                    ),
                    station_table,
                    station_status_bar,
                    station_config_form,
                    station_adapters_section,
                    sizing_mode="stretch_width",
                ),
            ),
            (
                "Measurement history",
                pn.Column(
                    pn.Row(
                        rueckmeldenummer,
                        history_station,
                        lookup_button_stack,
                        sizing_mode="stretch_width",
                        align="start",
                    ),
                    lookup_message,
                    history_table,
                    measurement_values,
                    raw_payload_detail,
                    sizing_mode="stretch_width",
                ),
            ),
            sizing_mode="stretch_width",
            stylesheets=[_ADMIN_TAB_STYLESHEET],
        ),
        sizing_mode="stretch_width",
        styles={"background": "#f3f4f6", "padding": "16px"},
    )


def build_admin_app() -> pn.Column:
    return build_app(kiosk=False)


def build_kiosk_app() -> pn.Column:
    return build_app(kiosk=True)


def load_station_rows(session: Session) -> list[dict[str, Any]]:
    latest_measurement_at = {
        station_id: measured_at
        for station_id, measured_at in session.execute(
            select(Measurement.station_id, func.max(Measurement.created_at)).group_by(
                Measurement.station_id
            )
        )
    }
    stations = session.scalars(
        select(Station)
        .options(
            selectinload(Station.heartbeats),
            selectinload(Station.events),
        )
        .order_by(Station.name)
    ).all()
    measurement_type_details_by_code = load_measurement_type_details_by_code(session)

    rows = []
    for station in stations:
        latest_heartbeat = max(
            station.heartbeats,
            key=lambda heartbeat: heartbeat.received_at,
            default=None,
        )
        latest_event = max(
            station.events,
            key=lambda event: event.occurred_at,
            default=None,
        )
        latest_event = current_station_event(
            latest_event,
            latest_measurement_at.get(station.id),
        )
        current_events = [
            event
            for event in sorted(
                station.events,
                key=lambda item: item.occurred_at,
                reverse=True,
            )
            if current_station_event(event, latest_measurement_at.get(station.id)) is not None
        ][:20]
        status = latest_heartbeat.status if latest_heartbeat else None
        received_at = latest_heartbeat.received_at if latest_heartbeat else None
        online = is_station_online(status, received_at)
        health_state, health_message = station_health(
            online=online,
            status_value=status,
            adapter_status=latest_heartbeat.adapter_status if latest_heartbeat else None,
            latest_event=latest_event,
        )
        measurement_type_codes = adapter_measurement_type_codes(station.adapter_config or [])
        rows.append(
            {
                "id": station.id,
                "name": station.name,
                "location": station.location,
                "scanner_host": station.scanner_host,
                "scanner_port": station.scanner_port,
                "scanner_protocol": station.scanner_protocol,
                "workflow_type": station.workflow_type,
                "workflow_title": station.workflow_title,
                "workflow_config": station.workflow_config or {},
                "adapter_config": station.adapter_config or [],
                "payload_format": station.payload_format,
                "timing_notes": station.timing_notes,
                "network_notes": station.network_notes,
                "active": station.active,
                "status": status,
                "health_state": health_state,
                "health_message": health_message,
                "online": online,
                "last_heartbeat_at": format_datetime(received_at),
                "last_event_at": format_datetime(
                    latest_event.occurred_at if latest_event else None
                ),
                "last_event_type": latest_event.event_type if latest_event else None,
                "last_event_severity": latest_event.severity if latest_event else None,
                "last_event_message": latest_event.message if latest_event else None,
                "recent_events": [
                    {
                        "occurred_at": format_datetime(event.occurred_at),
                        "severity": event.severity,
                        "event_type": event.event_type,
                        "message": event.message,
                    }
                    for event in current_events
                ],
                "hostname": latest_heartbeat.hostname if latest_heartbeat else None,
                "companion_version": latest_heartbeat.companion_version
                if latest_heartbeat
                else None,
                "companion_token_configured": bool(station.companion_token_hash),
                "adapter_status": latest_heartbeat.adapter_status
                if latest_heartbeat
                else None,
                "measurement_type_codes": measurement_type_codes,
                "measurement_type_details": [
                    measurement_type_details_by_code.get(
                        code,
                        {"code": code, "label": code, "unit": None},
                    )
                    for code in measurement_type_codes
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


def load_measurement_type_details_by_code(session: Session) -> dict[str, dict[str, str | None]]:
    return {
        measurement_type.code: {
            "code": measurement_type.code,
            "label": measurement_type.label,
            "unit": measurement_type.unit,
        }
        for measurement_type in session.scalars(select(MeasurementType)).all()
    }


def adapter_measurement_type_codes(configs: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            measurement_type
            for config in configs
            if config.get("enabled", True) is not False
            for measurement_type in [str(config.get("measurement_type") or "").strip()]
            if measurement_type
        }
    )


def kiosk_workflow_title(station: dict[str, Any]) -> str:
    if station.get("workflow_title"):
        return str(station["workflow_title"])

    workflow_type = station.get("workflow_type") or "measurement_capture"
    if workflow_type == "label_printing":
        return "Etikett drucken"
    if workflow_type == "laser_marking":
        return "Laser markieren"
    if workflow_type != "measurement_capture":
        return station.get("name") or str(workflow_type)

    name_parts = str(station.get("name") or "").lower()
    measurement_codes = set(station.get("measurement_type_codes") or [])
    if "fertig" in name_parts or "ueberstand" in measurement_codes:
        return "Fertig messen"
    if "breite" in name_parts or measurement_codes == {"breite"}:
        return "Breite messen"
    return station.get("name") or "Messen"


def kiosk_station_summary(station: dict[str, Any]) -> str:
    measurement_labels = ", ".join(
        detail["label"] for detail in station.get("measurement_type_details", [])
    )
    lines = [
        f"Station: `{station['name']}`",
        f"Standort: `{station['location'] or '-'}`",
        f"Workflow: `{station.get('workflow_type') or 'measurement_capture'}`",
    ]
    if station.get("workflow_type") == "measurement_capture":
        lines.append(f"Messarten: `{measurement_labels or '-'}`")
    else:
        lines.append("Messarten: `nicht erforderlich`")
    return "\n".join(lines)


def kiosk_station_badge_html(station: dict[str, Any]) -> str:
    status_text = "Online" if station.get("online") else "Offline"
    status_background = "#d1fae5" if station.get("online") else "#fee2e2"
    status_color = "#065f46" if station.get("online") else "#991b1b"
    station_name = escape(str(station.get("name") or "-"))
    return (
        "<div style='display:flex;flex-wrap:wrap;gap:8px;align-items:center'>"
        f"<span style='background:{status_background};color:{status_color};"
        "border-radius:6px;padding:7px 10px;font-weight:700'>"
        f"{status_text}</span>"
        "<span style='background:#f3f4f6;color:#111827;border-radius:6px;"
        f"padding:7px 10px'>Station: <strong>{station_name}</strong></span>"
        "</div>"
    )


def load_latest_measurement_for_part(
    session: Session,
    station_id: int,
    rueckmeldenummer: str,
    *,
    after_measurement_id: int = 0,
) -> Measurement | None:
    return session.scalars(
        select(Measurement)
        .join(Measurement.part)
        .options(selectinload(Measurement.values))
        .where(
            Measurement.station_id == station_id,
            Measurement.part.has(rueckmeldenummer=rueckmeldenummer),
            Measurement.id > after_measurement_id,
        )
        .order_by(Measurement.measured_at.desc(), Measurement.id.desc())
        .limit(1)
    ).one_or_none()


def load_latest_measurement_for_station_type(
    session: Session,
    measurement_type_codes: set[str],
    rueckmeldenummer: str,
) -> Measurement | None:
    if not measurement_type_codes:
        return None

    measurements = session.scalars(
        select(Measurement)
        .join(Measurement.part)
        .options(
            selectinload(Measurement.station),
            selectinload(Measurement.values),
        )
        .where(Measurement.part.has(rueckmeldenummer=rueckmeldenummer))
        .order_by(Measurement.measured_at.desc(), Measurement.id.desc())
    ).all()
    for measurement in measurements:
        value_codes = {value.measurement_type for value in measurement.values}
        if value_codes == measurement_type_codes:
            return measurement
    return None


def measurement_value_text(measurement: Measurement, station: dict[str, Any] | None = None) -> str:
    label_by_code = {
        str(detail.get("code")): str(detail.get("label") or detail.get("code"))
        for detail in (station or {}).get("measurement_type_details", [])
        if detail.get("code")
    }
    return ", ".join(
        (
            f"{label_by_code.get(value.measurement_type, value.measurement_type)}: "
            f"{str(value.value).replace('.', ',')} {value.unit or ''}"
        ).strip()
        for value in sorted(measurement.values, key=lambda item: item.measurement_type)
    )


def load_kiosk_measurement_progress(
    session: Session,
    *,
    station_id: int,
    rueckmeldenummer: str,
) -> dict[str, Any] | None:
    heartbeat = session.scalars(
        select(StationHeartbeat)
        .where(StationHeartbeat.station_id == station_id)
        .order_by(StationHeartbeat.received_at.desc(), StationHeartbeat.id.desc())
        .limit(1)
    ).one_or_none()
    if heartbeat is None or not heartbeat.adapter_status:
        return None

    progress = heartbeat.adapter_status.get("active_measurement_request")
    if not isinstance(progress, dict):
        return None
    if str(progress.get("rueckmeldenummer") or "") != rueckmeldenummer:
        return None
    return progress


def kiosk_progress_value_text(value: dict[str, Any]) -> str:
    number = str(value.get("value") or "").replace(".", ",")
    unit = str(value.get("unit") or "").strip()
    return f"{number} {unit}".strip()


def kiosk_missing_progress_labels(
    progress: dict[str, Any],
    station: dict[str, Any],
) -> list[str]:
    label_by_code = {
        detail["code"]: detail["label"]
        for detail in station.get("measurement_type_details", [])
    }
    return [
        label_by_code.get(code, code)
        for code in progress.get("missing_measurement_types", [])
    ]


def kiosk_progress_message(
    progress: dict[str, Any],
    station: dict[str, Any],
    waiting_text: str,
) -> str:
    label_by_code = {
        detail["code"]: detail["label"]
        for detail in station.get("measurement_type_details", [])
    }
    values = progress.get("values", [])
    rendered_values = []
    for value in values:
        measurement_type = str(value.get("measurement_type") or "")
        label = label_by_code.get(measurement_type, measurement_type)
        rendered_values.append(
            f"{escape(label)}: {escape(kiosk_progress_value_text(value))}"
        )
    value_text = ", ".join(rendered_values)
    return (
        "<div style='font-size:22px;line-height:1.3;font-weight:700'>"
        f"Erledigt: {value_text}"
        "</div>"
        "<div style='font-size:16px;margin-top:8px'>"
        f"{escape(waiting_text)}"
        "</div>"
    )


def create_measurement_request(
    session: Session,
    *,
    station_id: int,
    rueckmeldenummer: str,
) -> None:
    request_key = f"measurement_request:{station_id}:{rueckmeldenummer}:{uuid4()}"
    session.add(
        RawPayload(
            station_id=station_id,
            source_type="measurement_request",
            payload_hash=sha256(request_key.encode("utf-8")).hexdigest(),
            content=rueckmeldenummer,
        )
    )


def load_latest_scanner_raw_payload(
    session: Session,
    station_id: int,
) -> tuple[int, str] | None:
    raw_payload = session.scalars(
        select(RawPayload)
        .where(
            RawPayload.station_id == station_id,
            RawPayload.source_type == "keyence_srx",
        )
        .order_by(RawPayload.received_at.desc(), RawPayload.id.desc())
        .limit(1)
    ).one_or_none()
    if raw_payload is None:
        return None
    return int(raw_payload.id), raw_payload.content.strip()


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
                "delete_after_success": config.get("delete_after_success", True),
            }
        )
    return rows


def load_measurement_history(
    session: Session,
    rueckmeldenummer: str,
    station_id: int | None = None,
) -> tuple[list[dict[str, Any]], dict[int, list[dict[str, Any]]]]:
    query = (
        select(Measurement)
        .join(Measurement.part)
        .options(
            selectinload(Measurement.station),
            selectinload(Measurement.values).selectinload(MeasurementValue.type_definition),
        )
    )
    if rueckmeldenummer:
        query = query.where(Measurement.part.has(rueckmeldenummer=rueckmeldenummer))
    if station_id is not None:
        query = query.where(Measurement.station_id == station_id)
    if not rueckmeldenummer:
        query = query.limit(50)

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

    lines = ["### Measurement values", "| Type | Value |", "| --- | --- |"]
    for value in values:
        label = value["label"] or value["type"]
        lines.append(f"| {label} | {value['value']} {value['unit']} |")
    return "\n".join(lines)


def adapter_status_rows(adapter_status: dict[str, Any] | None) -> list[dict[str, str]]:
    if not adapter_status:
        return []

    adapters = adapter_status.get("adapters")
    if not isinstance(adapters, dict) or not adapters:
        return []

    rows = []
    for name, raw_status in sorted(adapters.items()):
        status = raw_status if isinstance(raw_status, dict) else {}
        rows.append(
            {
                "adapter": str(name),
                "state": str(status.get("state") or "-"),
                "last_event": str(status.get("last_event_at") or "-"),
                "error": str(status.get("last_error") or "-"),
            }
        )
    return rows


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


def parse_workflow_config(value: str) -> dict[str, Any]:
    if not value.strip():
        return {}

    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Workflow config must be a JSON object.")
    return parsed


def resolve_kiosk_station_id(
    settings: Settings,
    session_args: dict[str, list[bytes | str]] | MappingProxyType[str, list[bytes | str]]
    | None = None,
) -> tuple[int | None, str | None]:
    query_value = first_query_arg(
        session_args or {},
        "station_id",
        "station",
        "kiosk_station_id",
    )
    if query_value is not None:
        return parse_station_id(query_value, "URL parameter"), "URL"

    if settings.station_id is not None and str(settings.station_id).strip():
        return parse_station_id(str(settings.station_id), "STATION_ID"), "STATION_ID"

    return None, None


def first_query_arg(
    session_args: dict[str, list[bytes | str]] | MappingProxyType[str, list[bytes | str]],
    *names: str,
) -> str | None:
    for name in names:
        values = session_args.get(name)
        if not values:
            continue
        value = values[0]
        if isinstance(value, bytes):
            return value.decode("utf-8")
        return str(value)
    return None


def parse_station_id(value: str, source: str) -> int:
    clean_value = value.strip()
    if not clean_value.isdigit():
        raise ValueError(f"{source} must be a positive integer station id.")
    station_id = int(clean_value)
    if station_id < 1:
        raise ValueError(f"{source} must be a positive integer station id.")
    return station_id


def run() -> None:
    settings = get_settings()
    panel_command = [sys.executable, "-m", "panel"]
    if shutil.which("panel") is not None:
        panel_command = ["panel"]

    app_resource = resources.files("slf_trace.ui").joinpath("app.py")
    kiosk_resource = resources.files("slf_trace.ui").joinpath("kiosk.py")
    with (
        resources.as_file(app_resource) as app_path,
        resources.as_file(kiosk_resource) as kiosk_path,
    ):
        command = [
            *panel_command,
            "serve",
            "--address",
            settings.ui_host,
            "--port",
            str(settings.ui_port),
            "--allow-websocket-origin",
            ui_websocket_origin(settings),
        ]
        if settings.ui_autoreload:
            command.append("--dev")
        command.extend([str(app_path), str(kiosk_path)])

        subprocess.run(command, check=True)


def ui_websocket_origin(settings: Settings) -> str:
    return f"{settings.ui_host}:{settings.ui_port}"
