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
    db_nullpool: bool = Field(
        default=False,
        description="Use a non-pooling engine (NullPool). Set in tests so "
        "connections aren't reused across event loops.",
    )

    ollama_host: str = Field(
        default="http://localhost:11434",
        description="Base URL of the Ollama server used for embeddings.",
    )
    embedding_model: str = Field(
        default="nomic-embed-text",
        description="Ollama model name used to embed memory text (768-dim).",
    )


settings = Settings()  # type: ignore[call-arg]  # values come from the environment
