"""Application configuration management."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration loaded from environment variables.

    Attributes:
        telegram_bot_token: Telegram Bot API token.
        openrouter_api_key: OpenRouter API key.
        jellyseerr_url: Jellyseerr instance URL.
        jellyseerr_api_key: Jellyseerr API key.
        allowed_telegram_ids: Authorized Telegram user IDs.
        db_path: Path to SQLite database file.
        log_level: Logging level.
    """

    telegram_bot_token: SecretStr
    openrouter_api_key: SecretStr
    jellyseerr_url: str = "http://localhost:5055"
    jellyseerr_api_key: SecretStr
    allowed_telegram_ids: list[int]
    db_path: Path = Field(default=Path("data/home_agent.db"))
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""

    return AppConfig()
