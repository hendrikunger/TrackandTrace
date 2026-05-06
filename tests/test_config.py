from slf_trace.config import Settings


def test_database_urls_use_expected_drivers() -> None:
    settings = Settings(
        database_host="db.example",
        database_port=5433,
        database_name="trace",
        database_user="trace_user",
        database_password="secret",
    )

    assert settings.database_url_async.startswith("postgresql+asyncpg://")
    assert settings.database_url_sync.startswith("postgresql+psycopg://")
    assert "db.example:5433/trace" in settings.database_url_async


def test_ui_development_defaults() -> None:
    settings = Settings()

    assert settings.ui_host == "127.0.0.1"
    assert settings.ui_port == 5006
    assert settings.ui_autoreload is True
    assert settings.companion_auth_required is False
    assert settings.station_token is None
