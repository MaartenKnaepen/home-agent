"""Application configuration management."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr, field_validator
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
        llm_model: PydanticAI model string (e.g. openrouter:qwen/qwq-32b:free).
        mcp_port: Port number for the MCP server HTTP endpoint.
        jellyseerr_4k_profile_id: Jellyseerr quality profile ID for 4K requests.
            None means use Jellyseerr's default profile.
        jellyseerr_1080p_profile_id: Jellyseerr quality profile ID for 1080p requests.
            None means use Jellyseerr's default profile.
        llm_max_retries: Maximum number of retries on HTTP 429 rate limit errors.
        llm_retry_base_delay: Base delay in seconds for exponential backoff on retries.
        llm_retry_max_delay: Maximum delay in seconds for exponential backoff (caps the doubling).
    """

    telegram_bot_token: SecretStr
    openrouter_api_key: SecretStr
    jellyseerr_url: str = "http://localhost:5055"
    jellyseerr_api_key: SecretStr
    allowed_telegram_ids: list[int]
    db_path: Path = Field(default=Path("data/home_agent.db"))
    log_level: str = "INFO"
    llm_model: str = "openrouter:qwen/qwq-32b:free"
    mcp_port: int = 5056
    jellyseerr_4k_profile_id: int | None = None
    jellyseerr_1080p_profile_id: int | None = None
    llm_max_retries: int = 3
    llm_retry_base_delay: float = 1.0
    llm_retry_max_delay: float = 30.0

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
    )

    @field_validator("jellyseerr_4k_profile_id", "jellyseerr_1080p_profile_id")
    @classmethod
    def validate_profile_id(cls, v: int | None) -> int | None:
        """Validate that profile IDs are positive integers when set.

        Args:
            v: The profile ID value to validate.

        Returns:
            The validated profile ID, or None.

        Raises:
            ValueError: If the profile ID is not a positive integer.
        """
        if v is not None and v <= 0:
            raise ValueError("Jellyseerr profile ID must be a positive integer")
        return v


@lru_cache
def get_config() -> AppConfig:
    """Return cached application configuration."""

    return AppConfig()
