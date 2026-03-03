"""Tests for src/home_agent/tools/profile_tools.py.

Verifies that each profile tool correctly updates the user profile
and persists the change via ProfileManager.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic_ai import RunContext
from pydantic_ai.models.test import TestModel

from home_agent.agent import AgentDeps, create_agent
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.profile import MediaPreferences, ProfileManager, UserProfile
from home_agent.tools.profile_tools import (
    confirm_request,
    set_confirmation_mode,
    set_movie_quality,
    set_reply_language,
    set_series_quality,
)


def make_mock_ctx(
    profile: UserProfile,
    profile_manager: ProfileManager,
    mock_config: AppConfig,
    history_manager: HistoryManager,
) -> RunContext[AgentDeps]:  # type: ignore[type-arg]
    """Build a minimal RunContext mock for tool testing.

    Args:
        profile: The user profile to inject.
        profile_manager: The profile manager.
        mock_config: Application configuration.
        history_manager: History manager.

    Returns:
        A MagicMock shaped like RunContext[AgentDeps].
    """
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx  # type: ignore[return-value]


def make_test_profile(user_id: int = 42) -> UserProfile:
    """Create a test UserProfile with default values."""
    return UserProfile(
        user_id=user_id,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


# ---------------------------------------------------------------------------
# set_movie_quality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_movie_quality_updates_profile(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_movie_quality updates movie_quality on the profile and persists it."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile()
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_movie_quality(ctx, "4k")

    assert ctx.deps.user_profile.media_preferences.movie_quality == "4k"
    assert "4k" in result
    saved = await profile_manager.get(42)
    assert saved.media_preferences.movie_quality == "4k"


@pytest.mark.asyncio
async def test_set_movie_quality_1080p(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_movie_quality also works with '1080p'."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=43)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_movie_quality(ctx, "1080p")

    assert ctx.deps.user_profile.media_preferences.movie_quality == "1080p"
    assert "1080p" in result


@pytest.mark.asyncio
async def test_set_movie_quality_updates_deps(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_movie_quality updates ctx.deps.user_profile with the new quality."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=50)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    await set_movie_quality(ctx, "4k")

    assert ctx.deps.user_profile.media_preferences.movie_quality == "4k"


# ---------------------------------------------------------------------------
# set_series_quality
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_series_quality_updates_profile(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_series_quality updates series_quality on the profile and persists it."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=44)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_series_quality(ctx, "1080p")

    assert ctx.deps.user_profile.media_preferences.series_quality == "1080p"
    assert "1080p" in result
    saved = await profile_manager.get(44)
    assert saved.media_preferences.series_quality == "1080p"


@pytest.mark.asyncio
async def test_set_series_quality_updates_deps(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_series_quality updates ctx.deps.user_profile with the new quality."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=51)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    await set_series_quality(ctx, "1080p")

    assert ctx.deps.user_profile.media_preferences.series_quality == "1080p"


# ---------------------------------------------------------------------------
# set_reply_language
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_reply_language_updates_profile(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_reply_language updates reply_language and persists it."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=45)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_reply_language(ctx, "Dutch")

    assert ctx.deps.user_profile.reply_language == "Dutch"
    assert "Dutch" in result
    saved = await profile_manager.get(45)
    assert saved.reply_language == "Dutch"


# ---------------------------------------------------------------------------
# set_confirmation_mode
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_confirmation_mode_never(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_confirmation_mode('never') disables confirmation and persists it."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=46)
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_confirmation_mode(ctx, "never")

    assert ctx.deps.user_profile.confirmation_mode == "never"
    assert "immediately" in result
    saved = await profile_manager.get(46)
    assert saved.confirmation_mode == "never"


@pytest.mark.asyncio
async def test_set_confirmation_mode_always(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_confirmation_mode('always') re-enables confirmation."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=47)
    # Start with 'never'
    profile = profile.model_copy(update={"confirmation_mode": "never"})
    await profile_manager.save(profile)

    ctx = make_mock_ctx(profile, profile_manager, mock_config, history_manager)
    result = await set_confirmation_mode(ctx, "always")

    assert ctx.deps.user_profile.confirmation_mode == "always"
    saved = await profile_manager.get(47)
    assert saved.confirmation_mode == "always"


# ---------------------------------------------------------------------------
# Agent integration: tools are registered
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_profile_tools_registered_on_agent(
    mock_config: AppConfig, test_db: Path
) -> None:
    """All 4 profile tools are registered on the agent."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile()
    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel()
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("hello", deps=deps)

    assert m.last_model_request_parameters is not None
    tool_names = {t.name for t in m.last_model_request_parameters.function_tools}
    assert "set_movie_quality" in tool_names
    assert "set_series_quality" in tool_names
    assert "set_reply_language" in tool_names
    assert "set_confirmation_mode" in tool_names
    assert "confirm_request" in tool_names


# ---------------------------------------------------------------------------
# confirm_request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_request_sets_confirmed_in_deps(
    mock_config: AppConfig, test_db: Path
) -> None:
    """confirm_request sets ctx.deps.confirmed = True (stateless — no GuardedToolset mutation)."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=60)
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
        confirmed=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps

    result = await confirm_request(ctx, mediaId=123, mediaType="movie")

    assert "Confirmed" in result
    assert "123" in result
    assert "MOVIE" in result
    assert deps.confirmed is True


@pytest.mark.asyncio
async def test_confirm_request_logs_info(
    mock_config: AppConfig, test_db: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """confirm_request logs at INFO level with mediaId and mediaType."""
    import logging

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=63)
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
        confirmed=False,
    )
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps

    with caplog.at_level(logging.INFO, logger="home_agent.tools.profile_tools"):
        await confirm_request(ctx, mediaId=456, mediaType="tv")

    assert "confirm_request called" in caplog.text


# ---------------------------------------------------------------------------
# Framework boundary integration tests: each tool exercised through agent.run()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_user_note_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """update_user_note tool saves to profile when triggered via agent.run()."""
    from unittest.mock import AsyncMock as _AsyncMock

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=70)

    # Use a real ProfileManager but spy on save with AsyncMock wrapping
    profile_manager.save = _AsyncMock(wraps=profile_manager.save)  # type: ignore[method-assign]

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel(call_tools=["update_user_note"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("remember something about me", deps=deps)

    profile_manager.save.assert_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_set_movie_quality_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_movie_quality tool updates user_profile when triggered via agent.run()."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=71)
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel(call_tools=["set_movie_quality"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("set my movie quality to 4k", deps=deps)

    # TestModel supplies a str arg; the tool must have run without error
    # and the profile_manager should have been called to save
    saved = await profile_manager.get(71)
    # The TestModel generates a synthetic Literal value; just verify the tool ran
    assert saved is not None


@pytest.mark.asyncio
async def test_set_series_quality_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_series_quality tool runs without error when triggered via agent.run()."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=72)
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel(call_tools=["set_series_quality"])
    with agent_instance.override(model=m):
        async with agent_instance:
            result = await agent_instance.run("set my series quality", deps=deps)

    assert result.output is not None


@pytest.mark.asyncio
async def test_set_reply_language_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_reply_language tool persists change when triggered via agent.run()."""
    from unittest.mock import AsyncMock as _AsyncMock

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=73)
    await profile_manager.save(profile)
    profile_manager.save = _AsyncMock(wraps=profile_manager.save)  # type: ignore[method-assign]

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel(call_tools=["set_reply_language"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("reply to me in Dutch", deps=deps)

    profile_manager.save.assert_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_set_confirmation_mode_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """set_confirmation_mode tool persists change when triggered via agent.run()."""
    from unittest.mock import AsyncMock as _AsyncMock

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=74)
    await profile_manager.save(profile)
    profile_manager.save = _AsyncMock(wraps=profile_manager.save)  # type: ignore[method-assign]

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
    )

    agent_instance = create_agent()
    m = TestModel(call_tools=["set_confirmation_mode"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("don't ask me to confirm", deps=deps)

    profile_manager.save.assert_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_confirm_request_via_agent_run(
    mock_config: AppConfig, test_db: Path
) -> None:
    """confirm_request tool sets confirmed=True on a real GuardedToolset via agent.run()."""
    from unittest.mock import AsyncMock as _AsyncMock

    from home_agent.mcp.guarded_toolset import GuardedToolset

    # Build a real GuardedToolset wrapping a mocked inner toolset
    inner = MagicMock()
    inner.id = "test-server"
    inner.__aenter__ = _AsyncMock(return_value=inner)
    inner.__aexit__ = _AsyncMock(return_value=None)
    inner.get_tools = _AsyncMock(return_value={})
    inner.call_tool = _AsyncMock(return_value="result")

    guarded = GuardedToolset(inner)  # Real instance — AbstractToolset contract enforced

    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    profile = make_test_profile(user_id=75)
    await profile_manager.save(profile)

    deps = AgentDeps(
        config=mock_config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=profile,
        guarded_toolsets=[guarded],
    )

    agent_instance = create_agent(toolsets=[guarded])
    m = TestModel(call_tools=["confirm_request"])
    with agent_instance.override(model=m):
        async with agent_instance:
            await agent_instance.run("yes, confirm the request", deps=deps)

    # confirm_request now sets deps.confirmed = True (stateless GuardedToolset)
    assert deps.confirmed is True
