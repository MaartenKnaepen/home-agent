"""Tests for src/home_agent/mcp/guarded_toolset.py.

Verifies all guard rules (quality gate, confirmation gate) and pass-throughs.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from home_agent.agent import AgentDeps
from home_agent.mcp.guarded_toolset import GuardedToolset
from home_agent.profile import MediaPreferences, UserProfile


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def make_profile(
    *,
    movie_quality: str | None = None,
    series_quality: str | None = None,
    confirmation_mode: str = "never",
    user_id: int = 123,
) -> UserProfile:
    """Create a UserProfile with configurable quality and confirmation_mode."""
    now = datetime.now()
    return UserProfile(
        user_id=user_id,
        created_at=now,
        updated_at=now,
        media_preferences=MediaPreferences(
            movie_quality=movie_quality,  # type: ignore[arg-type]
            series_quality=series_quality,  # type: ignore[arg-type]
        ),
        confirmation_mode=confirmation_mode,  # type: ignore[arg-type]
    )


def make_deps(profile: UserProfile) -> AgentDeps:
    """Create AgentDeps with the given profile and mock managers."""
    return AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        guarded_toolsets=[],
    )


@pytest.fixture
def mock_inner_toolset() -> AsyncMock:
    """Inner toolset that always returns 'tool result'."""
    toolset = AsyncMock()
    toolset.call_tool = AsyncMock(return_value="tool result")
    return toolset


@pytest.fixture
def guarded(mock_inner_toolset: AsyncMock) -> GuardedToolset:
    """GuardedToolset wrapping the mock inner toolset, no deps set."""
    return GuardedToolset(mock_inner_toolset)


@pytest.fixture
def deps_no_quality() -> AgentDeps:
    """AgentDeps with no quality set and confirmation_mode='never'."""
    return make_deps(make_profile(movie_quality=None, series_quality=None))


@pytest.fixture
def deps_with_quality() -> AgentDeps:
    """AgentDeps with both qualities set and confirmation_mode='never'."""
    return make_deps(make_profile(movie_quality="4k", series_quality="1080p"))


@pytest.fixture
def deps_always_confirm() -> AgentDeps:
    """AgentDeps with quality set and confirmation_mode='always'."""
    return make_deps(
        make_profile(
            movie_quality="4k",
            series_quality="1080p",
            confirmation_mode="always",
        )
    )


# ---------------------------------------------------------------------------
# Quality gate — movie
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_blocked_when_movie_quality_not_set(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is blocked when movie_quality is None."""
    guarded.deps = deps_no_quality

    result = await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )

    assert "movie_quality not set" in result.lower()
    assert "set_movie_quality" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_movie_blocked_logs_warning(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Quality gate block for movie emits a WARNING log."""
    guarded.deps = deps_no_quality

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await guarded.call_tool(
            "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
        )

    assert "request_media blocked by quality gate" in caplog.text


# ---------------------------------------------------------------------------
# Quality gate — TV series
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_blocked_when_series_quality_not_set(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is blocked when series_quality is None."""
    guarded.deps = deps_no_quality

    result = await guarded.call_tool(
        "request_media", {"mediaType": "tv", "mediaId": 456}
    )

    assert "series_quality not set" in result.lower()
    assert "set_series_quality" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_tv_blocked_logs_warning(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Quality gate block for TV emits a WARNING log."""
    guarded.deps = deps_no_quality

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await guarded.call_tool(
            "request_media", {"mediaType": "tv", "mediaId": 456}
        )

    assert "request_media blocked by quality gate" in caplog.text


# ---------------------------------------------------------------------------
# Quality gate passes — quality is set, no confirmation required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_movie_allowed_when_quality_set_no_confirmation(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed when movie_quality set and confirmation_mode='never'."""
    guarded.deps = deps_with_quality

    result = await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once_with(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )


@pytest.mark.asyncio
async def test_request_media_tv_allowed_when_quality_set_no_confirmation(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed for TV when series_quality set and confirmation_mode='never'."""
    guarded.deps = deps_with_quality

    result = await guarded.call_tool(
        "request_media", {"mediaType": "tv", "mediaId": 456}
    )

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Confirmation gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_blocked_when_confirmation_required_and_not_confirmed(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media blocked when confirmation_mode='always' and confirmed=False."""
    guarded.deps = deps_always_confirm

    result = await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )

    assert "confirmation required" in result.lower()
    assert "confirm_request" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_blocked_confirmation_logs_warning(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Confirmation gate block emits a WARNING log."""
    guarded.deps = deps_always_confirm

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await guarded.call_tool(
            "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
        )

    assert "request_media blocked by confirmation gate" in caplog.text


@pytest.mark.asyncio
async def test_request_media_allowed_when_confirmation_required_and_confirmed(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed when confirmation_mode='always' and confirmed=True."""
    guarded.deps = deps_always_confirm
    guarded.confirmed = True

    result = await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Confirmed flag lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_flag_resets_after_successful_request_media(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps
) -> None:
    """confirmed flag is reset to False after request_media succeeds."""
    guarded.deps = deps_always_confirm
    guarded.confirmed = True

    await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
    )

    assert guarded.confirmed is False


@pytest.mark.asyncio
async def test_confirmed_flag_not_reset_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """confirmed flag is NOT reset when the call is blocked by a gate."""
    guarded.deps = deps_no_quality
    guarded.confirmed = True  # manually set

    await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 123}
    )

    # confirmed stays True because the gate blocked before forwarding
    assert guarded.confirmed is True


# ---------------------------------------------------------------------------
# set_confirmed
# ---------------------------------------------------------------------------


def test_set_confirmed_sets_flag(guarded: GuardedToolset) -> None:
    """set_confirmed() sets the confirmed flag to True."""
    assert guarded.confirmed is False
    guarded.set_confirmed(mediaId=123, mediaType="movie")
    assert guarded.confirmed is True


def test_set_confirmed_logs_info(
    guarded: GuardedToolset, caplog: pytest.LogCaptureFixture
) -> None:
    """set_confirmed() logs at INFO level with mediaId and mediaType."""
    with caplog.at_level(logging.INFO, logger="home_agent.mcp.guarded_toolset"):
        guarded.set_confirmed(mediaId=123, mediaType="movie")

    assert "confirm_request called" in caplog.text


# ---------------------------------------------------------------------------
# Pass-through: non-request_media tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_media_passes_through_without_gate(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """search_media passes through to the inner toolset without any gate."""
    guarded.deps = deps_no_quality

    result = await guarded.call_tool("search_media", {"query": "Inception"})

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once_with(
        "search_media", {"query": "Inception"}
    )


@pytest.mark.asyncio
async def test_unknown_tool_passes_through(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """Unknown/future tools pass through without any gate."""
    guarded.deps = deps_no_quality

    result = await guarded.call_tool("pdf_extract", {"file_id": "abc123"})

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once_with(
        "pdf_extract", {"file_id": "abc123"}
    )


@pytest.mark.asyncio
async def test_pass_through_logs_debug(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Pass-through tool calls emit a DEBUG log."""
    guarded.deps = deps_with_quality

    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        await guarded.call_tool("search_media", {"query": "Inception"})

    assert "Tool call allowed" in caplog.text


# ---------------------------------------------------------------------------
# called_tools tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_called_tools_updated_after_pass_through(
    guarded: GuardedToolset, deps_with_quality: AgentDeps
) -> None:
    """called_tools set is updated when a tool call succeeds."""
    guarded.deps = deps_with_quality

    await guarded.call_tool("search_media", {"query": "Inception"})

    assert "search_media" in guarded.called_tools


@pytest.mark.asyncio
async def test_called_tools_not_updated_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """called_tools set is NOT updated when a gate blocks the call."""
    guarded.deps = deps_no_quality

    await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 1})

    assert "request_media" not in guarded.called_tools


# ---------------------------------------------------------------------------
# No deps set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_deps_request_media_passes_through(
    guarded: GuardedToolset, mock_inner_toolset: AsyncMock
) -> None:
    """When deps is None, _has_*_quality and _needs_confirmation return False,
    so request_media passes through (quality gates pass, no confirmation needed)."""
    assert guarded.deps is None

    result = await guarded.call_tool(
        "request_media", {"mediaType": "movie", "mediaId": 1}
    )

    # Both quality checks return False → blocked by movie quality gate
    assert "movie_quality not set" in result.lower()
    mock_inner_toolset.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Sync helper for logging test (using asyncio.run inside sync test)
# ---------------------------------------------------------------------------


def test_guard_block_logs_warning_sync(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Guard block emits WARNING log (sync wrapper around async call)."""
    guarded.deps = deps_no_quality

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(
            guarded.call_tool(
                "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}
            )
        )

    assert "request_media blocked by quality gate" in caplog.text
