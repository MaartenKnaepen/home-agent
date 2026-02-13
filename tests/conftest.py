import os
from unittest.mock import patch

import pytest

from home_agent.config import AppConfig


@pytest.fixture
def mock_env():
    env = {
        "TELEGRAM_BOT_TOKEN": "token",
        "OPENROUTER_API_KEY": "openrouter",
        "JELLYSEERR_API_KEY": "jelly",
        "ALLOWED_TELEGRAM_IDS": "[123,456]",
        "JELLYSEERR_URL": "http://localhost:5055",
        "DB_PATH": "data/test.db",
        "LOG_LEVEL": "INFO",
    }
    with patch.dict(os.environ, env, clear=True):
        yield env


@pytest.fixture
def mock_config() -> AppConfig:
    return AppConfig(
        telegram_bot_token="token",
        openrouter_api_key="openrouter",
        jellyseerr_api_key="jelly",
        allowed_telegram_ids=[123, 456],
        jellyseerr_url="http://localhost:5055",
        db_path="data/test.db",
        log_level="INFO",
    )
