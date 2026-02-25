import os

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
                  jellyseerr_api_key=None,  # type: ignore[arg-type]
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
