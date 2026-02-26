"""Integration tests for home-agent end-to-end flow.

Verifies the full Telegram → Bot → Agent → DB pipeline using mocked
external dependencies (real LLM and MCP servers).
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai.models.test import TestModel
from telegram import Chat, Message, Update, User

from home_agent.agent import AgentDeps, create_agent
from home_agent.bot import make_message_handler
from home_agent.config import AppConfig
from home_agent.db import init_db
from home_agent.history import HistoryManager
from home_agent.profile import MediaPreferences, ProfileManager, UserProfile


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


async def test_new_user_locale_sets_reply_language(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """New user with Dutch locale gets reply_language='Dutch' in their profile.

    Verifies that when a new user's first message arrives with a Dutch Telegram
    locale, the bot auto-detects the language and persists 'Dutch' to the DB.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Hallo!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    # Build update with Dutch locale
    user = User(id=12345, is_bot=False, first_name="Test", language_code="nl")
    chat = Chat(id=12345, type="private")
    message = MagicMock(spec=Message)
    message.text = "hallo"
    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.send_action = AsyncMock()
    update.message = message

    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    await handler(update, MagicMock())

    profile = await profile_manager.get(12345)
    assert profile.reply_language == "Dutch"


async def test_agent_deps_include_user_profile(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """Agent.run() receives the user profile with correct quality preferences.

    Pre-saves a profile with specific quality and language settings, then
    confirms those values appear in the deps passed to the agent.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    # Pre-create profile with 4k movie quality
    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality="4k", series_quality="1080p"),
        reply_language="English",
        confirmation_mode="always",
    )
    await profile_manager.save(profile)

    mock_result = MagicMock()
    mock_result.output = "Response"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    update = make_update("add Troy", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.user_profile.media_preferences.movie_quality == "4k"
    assert deps.user_profile.media_preferences.series_quality == "1080p"
    assert deps.user_profile.reply_language == "English"
    assert deps.user_profile.confirmation_mode == "always"


async def test_set_movie_quality_tool_persists_via_full_agent(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """set_movie_quality tool called by real agent persists quality to DB.

    Uses PydanticAI's TestModel to force a call to set_movie_quality and
    verifies the result is actually written through to the database.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    # User with no quality set
    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality=None),
    )
    await profile_manager.save(profile)

    agent_instance = create_agent()
    # TestModel configured to call set_movie_quality
    m = TestModel(call_tools=["set_movie_quality"])

    deps = AgentDeps(
        config=integration_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("I want to add Troy", deps=deps)

    # Quality should have been updated in DB by the tool to a valid Literal value
    saved_profile = await profile_manager.get(12345)
    assert saved_profile.media_preferences.movie_quality in ("4k", "1080p")


async def test_confirmation_mode_never_in_deps(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """User with confirmation_mode='never' has it correctly in agent deps.

    Verifies that a pre-saved profile with confirmation_mode='never' is loaded
    and forwarded intact to the agent via AgentDeps.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        confirmation_mode="never",
    )
    await profile_manager.save(profile)

    mock_result = MagicMock()
    mock_result.output = "Done!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(integration_config, profile_manager, history_manager, mock_agent)
    update = make_update("add Troy", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.user_profile.confirmation_mode == "never"


async def test_language_switch_persists_across_messages(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """set_reply_language tool call persists language change for next message.

    Uses PydanticAI's TestModel to force a call to set_reply_language, then
    reads the profile back from DB to confirm the change was persisted.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        reply_language="English",
    )
    await profile_manager.save(profile)

    agent_instance = create_agent()
    # TestModel calls set_reply_language
    m = TestModel(call_tools=["set_reply_language"])

    deps = AgentDeps(
        config=integration_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("speak Dutch from now on", deps=deps)

    # Verify persisted to DB
    saved_profile = await profile_manager.get(12345)
    # TestModel generates a synthetic argument for the tool — the key thing is
    # the language was changed from the original "English" value via the DB round-trip
    assert saved_profile.reply_language != "English"
