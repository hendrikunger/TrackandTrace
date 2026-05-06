from functools import lru_cache
from urllib.parse import quote_plus

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    app_host: str = "0.0.0.0"
    app_port: int = 8000
    ui_host: str = "127.0.0.1"
    ui_port: int = 5006
    ui_autoreload: bool = True

    database_host: str = "localhost"
    database_port: int = 5432
    database_name: str = "trackandtrace_dev"
    database_user: str = "trackandtrace_admin"
    database_password: str = Field(default="", repr=False)

    station_id: str | None = None
    server_url: str = "http://localhost:8000"
    companion_state_path: str = "companion_state.sqlite3"
    companion_log_path: str | None = "logs/slf-trace-companion.log"
    companion_log_max_bytes: int = 5_000_000
    companion_log_backup_count: int = 5
    companion_heartbeat_interval_seconds: float = 10.0
    companion_outbox_retry_interval_seconds: float = 2.0
    companion_measurement_aggregation_timeout_seconds: float = 300.0
    companion_auth_required: bool = False
    station_token: str | None = Field(default=None, repr=False)

    @property
    def database_url_async(self) -> str:
        return self._database_url("postgresql+asyncpg")

    @property
    def database_url_sync(self) -> str:
        return self._database_url("postgresql+psycopg")

    def _database_url(self, driver: str) -> str:
        user = quote_plus(self.database_user)
        password = quote_plus(self.database_password)
        auth = f"{user}:{password}" if password else user
        return (
            f"{driver}://{auth}@{self.database_host}:{self.database_port}/"
            f"{self.database_name}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
