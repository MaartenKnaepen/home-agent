import os
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from home_agent.config import AppConfig, get_config


def test_config_loads_valid_env(mock_env):
    config = AppConfig()
    assert config.allowed_telegram_ids == [123, 456]


def test_missing_required_vars():
    # Must bypass the .env file too — otherwise pydantic-settings reads it
    # even when os.environ is cleared, and validation passes.
    with pytest.raises(ValidationError):
        AppConfig(_env_file=None,
                  telegram_bot_token=None,  # type: ignore[arg-type]
                  openrouter_api_key=None,  # type: ignore[arg-type]
                  seerr_api_key=None,  # type: ignore[arg-type]
                  allowed_telegram_ids=None)  # type: ignore[arg-type]


def test_default_values(mock_env):
    config = AppConfig()
    assert config.log_level == "INFO"


def test_list_parsing(mock_env):
    os.environ["ALLOWED_TELEGRAM_IDS"] = "[1,2]"
    config = AppConfig()
    assert config.allowed_telegram_ids == [1, 2]


def test_singleton_pattern(mock_env):
    get_config.cache_clear()
    config1 = get_config()
    config2 = get_config()
    assert id(config1) == id(config2)


def test_retry_config_defaults(mock_env: None) -> None:
    """Retry config fields have correct defaults."""
    config = AppConfig()
    assert config.llm_max_retries == 3
    assert config.llm_retry_base_delay == 1.0


def test_retry_max_delay_default(mock_env):
    """llm_retry_max_delay defaults to 30.0."""
    config = AppConfig()
    assert config.llm_retry_max_delay == 30.0


def test_admin_telegram_ids_default_empty(mock_env):
    """admin_telegram_ids defaults to an empty list."""
    config = AppConfig()
    assert config.admin_telegram_ids == []


def test_admin_telegram_ids_parsed_from_env(mock_env):
    """admin_telegram_ids is parsed correctly from env."""
    import os
    os.environ["ADMIN_TELEGRAM_IDS"] = "[111, 222]"
    config = AppConfig()
    assert config.admin_telegram_ids == [111, 222]
