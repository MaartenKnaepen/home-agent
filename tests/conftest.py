import os
from unittest.mock import patch

from pathlib import Path

import pytest

from home_agent.config import AppConfig
from home_agent.db import init_db
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager


@pytest.fixture
def mock_env():
    env = {
        "TELEGRAM_BOT_TOKEN": "token",
        "OPENROUTER_API_KEY": "openrouter",
        "SEERR_API_KEY": "seerr",
        "ALLOWED_TELEGRAM_IDS": "[123,456]",
        "SEERR_URL": "http://localhost:8085",
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
        seerr_api_key="seerr",
        allowed_telegram_ids=[123, 456],
        seerr_url="http://localhost:8085",
        db_path="data/test.db",
        log_level="INFO",
    )


@pytest.fixture
async def test_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database for tests."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return db_path


# ────────────────────────────────────────────────────────────────────────────
# Test Setup Pattern Guide
# ────────────────────────────────────────────────────────────────────────────
#
# ProfileManager & HistoryManager fixtures are available to all tests via
# pytest dependency injection. When you need a fresh manager for a test:
#
#   @pytest.mark.asyncio
#   async def test_something(profile_manager: ProfileManager) -> None:
#       profile = await profile_manager.get(user_id=123)
#       assert profile is not None
#
# Alternatively, if you need to customize the manager setup, construct it
# manually in the test:
#
#   @pytest.mark.asyncio
#   async def test_custom_setup(test_db: Path) -> None:
#       profile_manager = ProfileManager(test_db)
#       profile = await profile_manager.get(user_id=123)
#
# The `profile_manager` and `history_manager` fixtures are the preferred approach
# for consistency across tests. Manual construction is only needed for edge cases.


@pytest.fixture
async def profile_manager(test_db: Path) -> ProfileManager:
    """Create a ProfileManager for a temporary test database.

    Use this fixture in tests that need profile persistence without manually
    constructing ProfileManager(test_db) in each test.

    Args:
        test_db: The temporary database path from the test_db fixture.

    Returns:
        A ProfileManager instance configured for the test database.
    """
    return ProfileManager(test_db)


@pytest.fixture
async def history_manager(test_db: Path) -> HistoryManager:
    """Create a HistoryManager for a temporary test database.

    Use this fixture in tests that need conversation history persistence without
    manually constructing HistoryManager(test_db) in each test.

    Args:
        test_db: The temporary database path from the test_db fixture.

    Returns:
        A HistoryManager instance configured for the test database.
    """
    return HistoryManager(test_db)
