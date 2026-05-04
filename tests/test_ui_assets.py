from slf_trace.ui.branding import load_logo_svg
from slf_trace.ui.main import kiosk_workflow_title


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
    assert (
        kiosk_workflow_title(
            {
                "name": "FERTIG-01",
                "measurement_type_codes": ["ueberstand"],
            }
        )
        == "Fertig messen"
    )
