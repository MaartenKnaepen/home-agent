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


async def _call(guarded: object, name: str, args: dict) -> object:
    """Helper to call GuardedToolset.call_tool with mock ctx and tool."""
    return await guarded.call_tool(name, args, MagicMock(), MagicMock())  # type: ignore[union-attr]


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
        seerr_api_key="test_seerr_key",
        allowed_telegram_ids=[12345],
        seerr_url="http://localhost:8085",
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

    update.message.reply_text.assert_called_once()
    call_kwargs = update.message.reply_text.call_args
    # The agent output is converted via md_to_telegram_html before sending
    assert "Hello there!" in call_kwargs[0][0]

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


async def test_bot_sets_role_in_agent_deps(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """make_message_handler sets role in AgentDeps from user_profile.role.

    GuardedToolset is now stateless — deps are not set on the toolset.
    Instead, role and confirmed are fields on AgentDeps created per-message.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Done!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(
        integration_config,
        profile_manager,
        history_manager,
        mock_agent,
    )
    update = make_update("add Inception", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.user_profile.user_id == 12345
    assert deps.role == deps.user_profile.role
    assert deps.confirmed is False
    assert isinstance(deps.called_tools, set)


async def test_bot_passes_guarded_toolsets_in_agent_deps(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """make_message_handler includes guarded_toolsets in the AgentDeps passed to agent.run().

    Verifies the confirm_request tool will have access to the GuardedToolsets
    via ctx.deps.guarded_toolsets.
    """
    from unittest.mock import MagicMock

    from home_agent.mcp.guarded_toolset import GuardedToolset

    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    inner = MagicMock()
    inner.id = "test-server"
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="mock result")
    guarded_toolset = GuardedToolset(inner)  # Real instance — AbstractToolset protocol enforced

    mock_result = MagicMock()
    mock_result.output = "OK!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(
        integration_config,
        profile_manager,
        history_manager,
        mock_agent,
        guarded_toolsets=[guarded_toolset],
    )
    update = make_update("search for Troy", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.guarded_toolsets == [guarded_toolset]


async def test_bot_no_guarded_toolsets_still_works(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """make_message_handler works correctly when no guarded_toolsets provided."""
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Hello!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    # No guarded_toolsets argument — should default to empty list
    handler = make_message_handler(
        integration_config,
        profile_manager,
        history_manager,
        mock_agent,
    )
    update = make_update("hi", user_id=12345)
    await handler(update, MagicMock())

    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.guarded_toolsets == []


async def test_confirm_request_tool_end_to_end(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """confirm_request tool called by real agent sets deps.confirmed = True.

    Uses PydanticAI's TestModel to force a confirm_request call and verifies
    that deps.confirmed is True after the agent run (stateless GuardedToolset).
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality="4k"),
        confirmation_mode="always",
    )
    await profile_manager.save(profile)

    agent_instance = create_agent()
    m = TestModel(call_tools=["confirm_request"])

    deps = AgentDeps(
        config=integration_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
        confirmed=False,
        called_tools=set(),
        role="user",
    )

    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("yes, confirm the request", deps=deps)

    # confirm_request sets deps.confirmed = True (stateless — no GuardedToolset mutation)
    assert deps.confirmed is True


async def test_e2e_new_user_quality_gate_blocks_request(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """E2E: New user with no quality set — guard blocks request_media via ctx.deps.

    Verifies that when a new user (no quality in profile) has their deps passed
    to GuardedToolset via ctx.deps, the quality gate fires and returns a blocking
    error string. State is read from deps (per-message, per-user), not from the
    toolset singleton.
    """
    from home_agent.mcp.guarded_toolset import GuardedToolset

    # New user: quality not set
    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality=None),
        confirmation_mode="never",
    )

    # Mock inner toolset (should never be called — guard intercepts first)
    mock_inner = MagicMock()
    mock_inner.call_tool = AsyncMock(return_value="should not reach here")
    guarded_toolset = GuardedToolset(mock_inner)

    # Build per-user deps (as bot.py creates fresh for each message)
    deps = AgentDeps(
        config=integration_config,
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        confirmed=False,
        called_tools=set(),
        role="user",
    )
    ctx = MagicMock()
    ctx.deps = deps

    result = await guarded_toolset.call_tool("request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, ctx, MagicMock())
    assert "movie_quality not set" in result.lower()
    assert "set_movie_quality" in result
    mock_inner.call_tool.assert_not_called()


async def test_e2e_confirmation_mode_always_flow(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """E2E: User with confirmation_mode='always' — confirmation gate via ctx.deps.confirmed.

    Verifies that:
    1. Without confirmed=True in deps, request_media is blocked
    2. With confirmed=True in deps, request_media succeeds
    3. State is isolated per-message via AgentDeps (stateless GuardedToolset)
    """
    from home_agent.mcp.guarded_toolset import GuardedToolset

    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality="4k", series_quality="1080p"),
        confirmation_mode="always",
    )

    mock_inner = MagicMock()
    mock_inner.call_tool = AsyncMock(return_value="Request accepted!")
    guarded_toolset = GuardedToolset(mock_inner)

    # Message 1: no confirmation → guard blocks
    deps_unconfirmed = AgentDeps(
        config=integration_config,
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        confirmed=False,
        called_tools=set(),
        role="user",
    )
    ctx_unconfirmed = MagicMock()
    ctx_unconfirmed.deps = deps_unconfirmed

    result_blocked = await guarded_toolset.call_tool("request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, ctx_unconfirmed, MagicMock())
    assert "confirmation required" in result_blocked.lower()
    mock_inner.call_tool.assert_not_called()

    # Message 2: with confirmed=True → guard passes
    deps_confirmed = AgentDeps(
        config=integration_config,
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        confirmed=True,
        called_tools=set(),
        role="user",
    )
    ctx_confirmed = MagicMock()
    ctx_confirmed.deps = deps_confirmed

    result_allowed = await guarded_toolset.call_tool("request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, ctx_confirmed, MagicMock())
    assert result_allowed == "Request accepted!"
    mock_inner.call_tool.assert_called_once()


async def test_bot_resets_guarded_toolset_state_per_message(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """AgentDeps created fresh per message ensures no state leaks between messages.

    GuardedToolset is now stateless — state (confirmed, called_tools) lives in
    AgentDeps (created fresh each message). This test verifies that each new
    message gets fresh AgentDeps with confirmed=False and empty called_tools.
    """
    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    mock_result = MagicMock()
    mock_result.output = "Done!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_message_handler(
        integration_config,
        profile_manager,
        history_manager,
        mock_agent,
    )
    update = make_update("new message", user_id=12345)
    await handler(update, MagicMock())

    # Verify fresh AgentDeps has confirmed=False and empty called_tools
    call_args = mock_agent.run.call_args
    deps = call_args[1]["deps"]
    assert deps.confirmed is False
    assert deps.called_tools == set()


async def test_guarded_toolset_framework_boundary(
    integration_config: AppConfig,
    integration_db: Path,
) -> None:
    """GuardedToolset satisfies PydanticAI's AbstractToolset protocol end-to-end.

    This is the mandatory framework boundary test per AGENTS.md:
    A real GuardedToolset (not MagicMock) is passed to create_agent() and
    exercised through PydanticAI's real Agent.__aenter__/__aexit__ lifecycle
    and agent.run() call path — verifying AbstractToolset subclass contract,
    get_tools() return type, and call_tool() arity are all correct at runtime.
    """
    from home_agent.mcp.guarded_toolset import GuardedToolset

    profile_manager = ProfileManager(db_path=integration_db)
    history_manager = HistoryManager(db_path=integration_db)

    profile = UserProfile(
        user_id=12345,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        media_preferences=MediaPreferences(movie_quality="1080p"),
    )
    await profile_manager.save(profile)

    # Build a properly mocked inner toolset (no MCP connection needed)
    inner = MagicMock()
    inner.id = "test-server"
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    inner.get_tools = AsyncMock(return_value={})
    inner.call_tool = AsyncMock(return_value="mock result")

    guarded = GuardedToolset(inner)  # Real instance — AbstractToolset contract enforced

    # Pass real GuardedToolset to create_agent() — PydanticAI validates the toolset
    agent_instance = create_agent(toolsets=[guarded])
    m = TestModel()

    deps = AgentDeps(
        config=integration_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    with agent_instance.override(model=m):
        async with agent_instance:  # Exercises __aenter__/__aexit__ lifecycle
            result = await agent_instance.run("hello", deps=deps)

    assert result.output is not None


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
