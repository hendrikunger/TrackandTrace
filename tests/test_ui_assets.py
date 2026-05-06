from slf_trace.config import Settings
from slf_trace.ui.branding import load_logo_svg
from slf_trace.ui.main import (
    kiosk_missing_progress_labels,
    kiosk_progress_message,
    kiosk_progress_value_text,
    kiosk_workflow_title,
    resolve_kiosk_station_id,
)


def test_logo_svg_asset_is_available() -> None:
    svg = load_logo_svg()

    assert "<svg" in svg
    assert "viewBox" in svg
    assert "circle" in svg


def test_kiosk_workflow_title_uses_station_measurement_config() -> None:
    assert (
        kiosk_workflow_title(
            {
                "name": "BREITE-01",
                "measurement_type_codes": ["breite"],
            }
        )
        == "Breite messen"
    )


def test_kiosk_workflow_title_uses_explicit_workflow_title() -> None:
    assert (
        kiosk_workflow_title(
            {
                "name": "LASER-01",
                "workflow_type": "laser_marking",
                "workflow_title": "Laser markieren",
                "measurement_type_codes": [],
            }
        )
        == "Laser markieren"
    )
    assert (
        kiosk_workflow_title(
            {
                "name": "FERTIG-01",
                "measurement_type_codes": ["ueberstand"],
            }
        )
        == "Fertig messen"
    )


def test_kiosk_station_id_uses_url_before_environment() -> None:
    station_id, source = resolve_kiosk_station_id(
        Settings(station_id="3"),
        {"station_id": [b"7"]},
    )

    assert station_id == 7
    assert source == "URL"


def test_kiosk_station_id_falls_back_to_environment() -> None:
    station_id, source = resolve_kiosk_station_id(Settings(station_id="3"), {})

    assert station_id == 3
    assert source == "STATION_ID"


def test_kiosk_station_id_allows_local_unconfigured_mode() -> None:
    assert resolve_kiosk_station_id(Settings(station_id=None), {}) == (None, None)


def test_kiosk_progress_helpers_format_received_values() -> None:
    progress = {
        "missing_measurement_types": ["innenring"],
        "values": [
            {"measurement_type": "breite", "value": "77.7", "unit": "mm"},
        ],
    }
    station = {
        "measurement_type_details": [
            {"code": "breite", "label": "Breite"},
            {"code": "innenring", "label": "Innenring"},
        ]
    }

    assert kiosk_progress_value_text(progress["values"][0]) == "77,7 mm"
    assert kiosk_missing_progress_labels(progress, station) == ["Innenring"]
    assert "Messwert empfangen" in kiosk_progress_message(progress, "Warte auf Innenring.")
