from __future__ import annotations

import shutil
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from importlib import resources
from typing import Any

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
    RawPayload,
    Station,
    StationMeasurementType,
)

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
    adapter_detail = pn.pane.JSON({}, name="Adapter State", depth=3, height=300)

    input_width = 260
    name = pn.widgets.TextInput(name="Name", width=input_width)
    hostname = pn.widgets.TextInput(name="Hostname", width=input_width)
    location = pn.widgets.TextInput(name="Location", width=input_width)
    operating_system = pn.widgets.TextInput(name="Operating system", width=input_width)
    machine_name = pn.widgets.TextInput(name="Machine name", width=input_width)
    machine_type = pn.widgets.TextInput(name="Machine type", width=input_width)
    measurement_interface = pn.widgets.TextInput(
        name="Measurement interface",
        width=input_width,
    )
    scanner_host = pn.widgets.TextInput(name="Scanner host", width=input_width)
    scanner_port = pn.widgets.TextInput(name="Scanner port", width=140)
    scanner_protocol = pn.widgets.TextInput(name="Scanner protocol", width=180)
    payload_format = pn.widgets.TextAreaInput(name="Payload format", height=90, width=820)
    timing_notes = pn.widgets.TextAreaInput(name="Timing notes", height=70, width=400)
    network_notes = pn.widgets.TextAreaInput(name="Network notes", height=70, width=400)
    active = pn.widgets.Checkbox(name="Active", value=True)
    measurement_types = pn.widgets.MultiChoice(
        name="Allowed measurement types",
        options=[],
        width=820,
    )

    refresh_button = pn.widgets.Button(name="Refresh", button_type="primary")
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

    station_rows: list[dict[str, Any]] = []
    selected_station_id: int | None = None
    selected_history: dict[int, list[dict[str, Any]]] = {}
    loading_station_form = False

    def set_message(pane: pn.pane.Alert, text: str, alert_type: str = "info") -> None:
        pane.object = text
        pane.alert_type = alert_type
        pane.visible = True

    def refresh_stations(_: object | None = None) -> None:
        nonlocal station_rows
        try:
            with session_scope(settings) as session:
                station_rows = load_station_rows(session)
                measurement_types.options = load_measurement_type_options(session)
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
        set_message(station_message, f"Loaded {len(station_rows)} stations.")

    def fill_station_form(station: dict[str, Any]) -> None:
        nonlocal loading_station_form
        loading_station_form = True
        try:
            name.value = station["name"] or ""
            hostname.value = station["hostname"] or ""
            location.value = station["location"] or ""
            operating_system.value = station["operating_system"] or ""
            machine_name.value = station["machine_name"] or ""
            machine_type.value = station["machine_type"] or ""
            measurement_interface.value = station["measurement_interface"] or ""
            scanner_host.value = station["scanner_host"] or ""
            scanner_port.value = str(station["scanner_port"] or "")
            scanner_protocol.value = station["scanner_protocol"] or ""
            payload_format.value = station["payload_format"] or ""
            timing_notes.value = station["timing_notes"] or ""
            network_notes.value = station["network_notes"] or ""
            active.value = station["active"]
            measurement_types.value = station["measurement_type_codes"]
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

    def select_station(event: Any) -> None:
        nonlocal selected_station_id
        if not event.new:
            selected_station_id = None
            return

        row_index = event.new[0]
        if station_table.value.empty or row_index >= len(station_table.value):
            return

        selected_station_id = int(station_table.value.iloc[row_index]["id"])
        station = next(
            row for row in station_rows if row["id"] == selected_station_id
        )
        fill_station_form(station)
        update_station_status_bar(station)
        adapter_detail.object = station["adapter_status"] or {}

    def autosave_config(_: object | None = None) -> None:
        if loading_station_form:
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

        return {
            "name": station_name,
            "hostname": hostname.value.strip() or None,
            "location": location.value.strip() or None,
            "operating_system": operating_system.value.strip() or None,
            "machine_name": machine_name.value.strip() or None,
            "machine_type": machine_type.value.strip() or None,
            "measurement_interface": measurement_interface.value.strip() or None,
            "scanner_host": scanner_host.value.strip() or None,
            "scanner_port": parse_optional_port(scanner_port.value),
            "scanner_protocol": scanner_protocol.value.strip() or None,
            "payload_format": payload_format.value.strip() or None,
            "timing_notes": timing_notes.value.strip() or None,
            "network_notes": network_notes.value.strip() or None,
            "active": active.value,
        }

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

    station_table.param.watch(select_station, "selection")
    history_table.param.watch(select_measurement, "selection")
    refresh_button.on_click(refresh_stations)
    lookup_button.on_click(lookup_measurements)
    load_payload_button.on_click(inspect_payload)

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
        payload_format,
        timing_notes,
        network_notes,
        active,
    ):
        field_widget.param.watch(autosave_config, "value")
    measurement_types.param.watch(autosave_measurement_types, "value")

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
        pn.GridBox(
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
            ncols=2,
            align="start",
        ),
        payload_format,
        pn.Row(timing_notes, network_notes, align="start"),
        active,
        measurement_types,
        station_message,
        align="start",
        width=860,
    )

    return pn.Column(
        pn.pane.Markdown("# SLF Track and Trace"),
        pn.pane.Markdown(f"Environment: `{settings.app_env}`"),
        pn.Tabs(
            (
                "Stations",
                pn.Column(
                    pn.Row(refresh_button),
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
                    for link in station.measurement_type_links
                    if link.active
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
