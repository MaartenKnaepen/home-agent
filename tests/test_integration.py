"""Integration tests for home-agent end-to-end flow.

Verifies the full Telegram → Bot → Agent → DB pipeline using mocked
external dependencies (real LLM and MCP servers).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from telegram import Chat, Message, Update, User

from home_agent.bot import make_message_handler
from home_agent.config import AppConfig
from home_agent.db import init_db
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager


@pytest.fixture
async def integration_db(tmp_path: Path) -> Path:
    """Temporary SQLite database for integration tests."""
    db_path = tmp_path / "integration.db"
    await init_db(db_path)
    return db_path


@pytest.fixture
def integration_config() -> AppConfig:
    """AppConfig with test user 12345 whitelisted."""
    return AppConfig(
        telegram_bot_token="test_token",
        openrouter_api_key="test_key",
        jellyseerr_api_key="test_jelly_key",
        allowed_telegram_ids=[12345],
        jellyseerr_url="http://localhost:5055",
        db_path=Path("data/test.db"),
        log_level="DEBUG",
    )


def make_update(text: str, user_id: int = 12345) -> Update:
    """Create a mock Telegram Update."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    message = MagicMock(spec=Message)
    message.text = text
    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.send_action = AsyncMock()
    update.message = message
    return update


async def test_message_flow_persists_history(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """Full message flow persists both user and assistant turns to DB."""
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Hello there!"

    mock_agent = MagicMock()
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=False)
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    update = make_update("Hello", user_id=12345)
    await handler(update, MagicMock())

    update.message.reply_text.assert_called_once_with("Hello there!")

    history = await history_manager.get_history(user_id=12345)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[0]["content"] == "Hello"
    assert history[1]["role"] == "assistant"
    assert history[1]["content"] == "Hello there!"


async def test_unauthorized_user_not_persisted(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """Unauthorized user messages are rejected and not persisted to DB."""
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_agent = MagicMock()
    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    update = make_update("Hello", user_id=99999)  # not in whitelist
    await handler(update, MagicMock())

    update.message.reply_text.assert_called_once()
    rejection_text: str = update.message.reply_text.call_args[0][0]
    assert "not authorized" in rejection_text.lower() or "unauthorized" in rejection_text.lower()

    history = await history_manager.get_history(user_id=99999)
    assert len(history) == 0


async def test_agent_receives_correct_deps(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """Agent.run() is called with correct deps and message text."""
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Response"

    mock_agent = MagicMock()
    mock_agent.__aenter__ = AsyncMock(return_value=mock_agent)
    mock_agent.__aexit__ = AsyncMock(return_value=False)
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    update = make_update("search for Inception", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    assert call_args[0][0] == "search for Inception"  # first positional arg is the message text
    deps = call_args[1]["deps"]  # keyword arg
    assert deps.config is integration_config
    assert deps.user_profile.user_id == 12345
