from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    langame_base_url: str = "https://sa-vlg1.langame.ru/public_api"
    langame_api_key: str
    # Safety switch: the bot may only read/analyse LANGAME data.
    langame_read_only: bool = True
    telegram_bot_token: str
    owner_telegram_ids: str = ""
    report_timezone: str = "Europe/Moscow"
    report_hour: int = 9
    report_minute: int = 0
    mini_app_url: str = ""
    web_host: str = "0.0.0.0"
    # Render provides PORT for Web Services; keep 8000 as the local default.
    web_port: int = 8000
    # PORT is injected by Render; main.py resolves it at startup when present.
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("database_url")
    @classmethod
    def _normalize_database_url(cls, value: str) -> str:
        # Managed providers (e.g. Render) hand out plain postgres:// / postgresql://
        # URLs. SQLAlchemy + asyncpg needs the postgresql+asyncpg:// scheme.
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://"):]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://"):]
        return value

    @property
    def owners(self) -> set[int]:
        result: set[int] = set()
        for value in self.owner_telegram_ids.split(","):
            value = value.strip()
            if value:
                result.add(int(value))
        return result


settings = Settings()
if not settings.langame_read_only:
    raise RuntimeError(
        "LANGAME_READ_ONLY must be true. This application is intentionally read-only against LANGAME."
    )
