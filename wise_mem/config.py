"""Application configuration, loaded from the environment / `.env`."""

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Settings sourced from environment variables (and `.env`).

    `DATABASE_URL` must use the async driver scheme, e.g.
    `postgresql+asyncpg://user:pass@host:5432/dbname`.
    """

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = Field(
        ...,
        description="Async SQLAlchemy DSN for Postgres (postgresql+asyncpg://...).",
    )
    db_echo: bool = Field(
        default=False,
        description="Log all SQL emitted by the engine (useful while developing).",
    )


settings = Settings()  # type: ignore[call-arg]  # values come from the environment
