import os

import pytest
from pydantic import ValidationError

from home_agent.config import AppConfig, get_config


def test_config_loads_valid_env(mock_env):
    config = AppConfig()
    assert config.allowed_telegram_ids == [123, 456]


def test_missing_required_vars():
    os.environ.clear()
    with pytest.raises(ValidationError):
        AppConfig()


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
