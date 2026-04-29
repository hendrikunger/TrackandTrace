from datetime import UTC, datetime, timedelta

from pydantic import ValidationError

from slf_trace.api.schemas.admin import StationConfigUpdate
from slf_trace.api.services.admin import is_station_online


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
