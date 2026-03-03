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
        seerr_url: Overseerr/Seerr instance URL.
        seerr_api_key: Overseerr/Seerr API key.
        allowed_telegram_ids: Authorized Telegram user IDs.
        db_path: Path to SQLite database file.
        log_level: Logging level.
        llm_model: PydanticAI model string (e.g. openrouter:qwen/qwq-32b:free).
        mcp_port: Port number for the MCP server HTTP endpoint.
        llm_max_retries: Maximum number of retries on HTTP 429 rate limit errors.
        llm_retry_base_delay: Base delay in seconds for exponential backoff on retries.
        llm_retry_max_delay: Maximum delay in seconds for exponential backoff (caps the doubling).
        asr_url: URL of the Qwen3-ASR transcription service.
    """

    telegram_bot_token: SecretStr
    openrouter_api_key: SecretStr
    seerr_url: str = "http://localhost:8096"
    seerr_api_key: SecretStr
    allowed_telegram_ids: list[int]
    db_path: Path = Field(default=Path("data/home_agent.db"))
    log_level: str = "INFO"
    llm_model: str = "openrouter:qwen/qwq-32b:free"
    mcp_port: int = 8085
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 30.0
    admin_telegram_ids: list[int] = Field(default=[])
    asr_url: str = Field(default="http://qwen3-asr:8086")
    """URL of the Qwen3-ASR transcription service."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""

    return AppConfig()
