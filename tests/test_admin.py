from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from pydantic import ValidationError

from slf_trace.api.schemas.admin import StationConfigUpdate
from slf_trace.api.services.admin import adapter_problem_message, is_station_online, station_health


def test_station_online_requires_recent_online_heartbeat() -> None:
    now = datetime(2026, 4, 28, 12, 0, tzinfo=UTC)

    assert is_station_online("online", now - timedelta(minutes=1), now=now)
    assert not is_station_online("online", now - timedelta(minutes=6), now=now)
    assert not is_station_online("offline", now - timedelta(minutes=1), now=now)


def test_station_config_validates_scanner_port_range() -> None:
    try:
        StationConfigUpdate(scanner_port=70000)
    except ValidationError as exc:
        assert "less than or equal to 65535" in str(exc)
    else:
        raise AssertionError("Expected scanner_port validation to fail.")


def test_station_health_reports_adapter_error_as_degraded() -> None:
    state, message = station_health(
        online=True,
        status_value="online",
        adapter_status={
            "adapters": {
                "scanner": {
                    "state": "degraded",
                    "last_error": "No scanner heartbeat received.",
                }
            }
        },
    )

    assert state == "degraded"
    assert message == "scanner: No scanner heartbeat received."


def test_station_health_reports_latest_problem_event_as_degraded() -> None:
    state, message = station_health(
        online=True,
        status_value="online",
        adapter_status=None,
        latest_event=SimpleNamespace(
            severity="error",
            event_type="parser.failure",
            message="Unknown measurement type.",
        ),
    )

    assert state == "degraded"
    assert message == "parser.failure: Unknown measurement type."


def test_adapter_problem_message_ignores_online_adapters() -> None:
    assert (
        adapter_problem_message({"adapters": {"tcp": {"state": "online"}}})
        is None
    )
