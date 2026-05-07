from decimal import Decimal
from types import SimpleNamespace

import panel as pn

from slf_trace.config import Settings
from slf_trace.ui.branding import load_logo_svg
from slf_trace.ui.main import (
    SCANNER_PROTOCOL_OPTIONS,
    adapter_measurement_type_codes,
    kiosk_missing_progress_labels,
    kiosk_progress_message,
    kiosk_progress_value_text,
    kiosk_workflow_title,
    measurement_value_html,
    measurement_value_text,
    positive_poll_period_ms,
    resolve_kiosk_station_id,
    set_select_value,
    split_measurement_display_value,
    ui_websocket_origins,
)


def test_logo_svg_asset_is_available() -> None:
    svg = load_logo_svg()

    assert "<svg" in svg
    assert "viewBox" in svg
    assert "circle" in svg


def test_ui_websocket_origins_use_explicit_comma_separated_values() -> None:
    settings = Settings(ui_host="0.0.0.0", ui_port=8080)

    assert ui_websocket_origins(settings) == ["0.0.0.0:8080"]

    settings = Settings(ui_websocket_origins="api.home.io:8080, 10.0.0.151:8080")

    assert ui_websocket_origins(settings) == ["api.home.io:8080", "10.0.0.151:8080"]


def test_kiosk_poll_settings_have_fast_defaults() -> None:
    settings = Settings()

    assert settings.kiosk_scanner_poll_ms == 250
    assert settings.kiosk_measurement_poll_ms == 500
    assert positive_poll_period_ms(0, default=250) == 250
    assert positive_poll_period_ms(-1, default=500) == 500
    assert positive_poll_period_ms(125, default=500) == 125


def test_scanner_protocol_options_only_offer_supported_modes() -> None:
    assert SCANNER_PROTOCOL_OPTIONS == {
        "": "",
        "Keyence SR-X TCP": "Keyence SR-X TCP",
        "Disabled": "none",
    }
    assert "other" not in SCANNER_PROTOCOL_OPTIONS.values()


def test_select_value_does_not_duplicate_dict_option_values() -> None:
    widget = pn.widgets.Select(
        options={"Measurement capture": "measurement_capture"},
        value="measurement_capture",
    )

    set_select_value(widget, "measurement_capture")

    assert widget.options == {"Measurement capture": "measurement_capture"}
    assert widget.value == "measurement_capture"


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


def test_adapter_measurement_type_codes_use_enabled_adapters_only() -> None:
    assert adapter_measurement_type_codes(
        [
            {"enabled": True, "measurement_type": "breite"},
            {"enabled": False, "measurement_type": "innenring"},
            {"measurement_type": "breite"},
            {"enabled": True, "measurement_type": " "},
        ]
    ) == ["breite"]


def test_measurement_value_text_labels_values_by_measurement_type() -> None:
    measurement = SimpleNamespace(
        values=[
            SimpleNamespace(measurement_type="innenring", value=Decimal("45.0000"), unit="mm"),
            SimpleNamespace(measurement_type="breite", value=Decimal("32.2000"), unit="mm"),
        ]
    )
    station = {
        "measurement_type_details": [
            {"code": "breite", "label": "Breite"},
            {"code": "innenring", "label": "Innenring"},
        ]
    }

    assert measurement_value_text(measurement, station) == (
        "Breite: 32,2000 mm, Innenring: 45,0000 mm"
    )


def test_measurement_value_html_renders_each_value_on_own_line() -> None:
    measurement = SimpleNamespace(
        values=[
            SimpleNamespace(measurement_type="innenring", value=Decimal("45.0000"), unit="mm"),
            SimpleNamespace(measurement_type="breite", value=Decimal("32.2000"), unit="mm"),
        ]
    )
    station = {
        "measurement_type_details": [
            {"code": "breite", "label": "Breite"},
            {"code": "innenring", "label": "Innenring"},
        ]
    }

    html = measurement_value_html(measurement, station)

    assert html.count("slf-kiosk-value-row") == 2
    assert "slf-kiosk-value-comma" in html
    assert "font-variant-numeric:tabular-nums" in html
    assert "font-size:28px" in html
    assert "font-size:34px" in html
    assert ">Breite</span>" in html
    assert ">32</span>" in html
    assert ">2000</span>" in html
    assert ">Innenring</span>" in html
    assert ">45</span>" in html
    assert ">0000</span>" in html
    assert ">mm</span>" in html


def test_split_measurement_display_value_keeps_decimal_separator_in_own_column() -> None:
    assert split_measurement_display_value("32,2000 mm") == ("32", ",", "2000", "mm")
    assert split_measurement_display_value("45 mm") == ("45", ",", "0000", "mm")
    assert split_measurement_display_value("44") == ("44", ",", "0000", "")


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

    assert kiosk_progress_value_text(progress["values"][0]) == "77,7000 mm"
    assert kiosk_missing_progress_labels(progress, station) == ["Innenring"]
    message = kiosk_progress_message(progress, station, "Warte auf Innenring.")
    assert "Erledigt:" in message
    assert ">Breite</span>" in message
    assert ">77</span>" in message
    assert ">7000</span>" in message
    assert "Warte auf Innenring." in message
