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
