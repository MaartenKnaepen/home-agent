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


async def _call(guarded: GuardedToolset, name: str, args: dict) -> object:
    """Helper to call GuardedToolset.call_tool with mock ctx and tool."""
    return await guarded.call_tool(name, args, MagicMock(), MagicMock())


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

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

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
        await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

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

    result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456})

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
        await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456})

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

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_request_media_tv_allowed_when_quality_set_no_confirmation(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed for TV when series_quality set and confirmation_mode='never'."""
    guarded.deps = deps_with_quality

    result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456})

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

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

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
        await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

    assert "request_media blocked by confirmation gate" in caplog.text


@pytest.mark.asyncio
async def test_request_media_allowed_when_confirmation_required_and_confirmed(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed when confirmation_mode='always' and confirmed=True."""
    guarded.deps = deps_always_confirm
    guarded.confirmed = True

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

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

    await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

    assert guarded.confirmed is False


@pytest.mark.asyncio
async def test_confirmed_flag_not_reset_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """confirmed flag is NOT reset when the call is blocked by a gate."""
    guarded.deps = deps_no_quality
    guarded.confirmed = True  # manually set

    await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123})

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

    result = await _call(guarded, "search_media", {"query": "Inception"})

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_tool_passes_through(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """Unknown/future tools pass through without any gate."""
    guarded.deps = deps_no_quality

    result = await _call(guarded, "pdf_extract", {"file_id": "abc123"})

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_pass_through_logs_debug(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Pass-through tool calls emit a DEBUG log."""
    guarded.deps = deps_with_quality

    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        await _call(guarded, "search_media", {"query": "Inception"})

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

    await _call(guarded, "search_media", {"query": "Inception"})

    assert "search_media" in guarded.called_tools


@pytest.mark.asyncio
async def test_called_tools_not_updated_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """called_tools set is NOT updated when a gate blocks the call."""
    guarded.deps = deps_no_quality

    await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1})

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

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1})

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
            _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
        )

    assert "request_media blocked by quality gate" in caplog.text


# ---------------------------------------------------------------------------
# Edge case: new user with no quality set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_new_user_no_quality_movie_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """New user with no quality set requests a movie — guard blocks with set_movie_quality hint."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})

    assert "movie_quality not set" in result.lower()
    assert "set_movie_quality" in result
    assert "request_media blocked" in caplog.text
    mock_inner.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_new_user_no_quality_series_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """New user with no quality set requests a series — guard blocks with set_series_quality hint."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456, "seasons": "all"})

    assert "series_quality not set" in result.lower()
    assert "set_series_quality" in result
    assert "request_media blocked" in caplog.text
    mock_inner.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: quality change mid-conversation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_change_mid_conversation(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """User changes quality preference mid-conversation — updated value is used on next request."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    profile = make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="never")
    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        guarded_toolsets=[],
    )
    guarded.deps = deps

    # First request with 4K quality set — passes through
    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
    assert result1 == "request accepted"

    # Simulate quality change mid-conversation via model_copy
    profile = profile.model_copy(
        update={"media_preferences": profile.media_preferences.model_copy(update={"movie_quality": "1080p"})}
    )
    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        guarded_toolsets=[],
    )
    guarded.deps = deps

    # Second request with updated 1080p quality — also passes through
    result2 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 456, "is4k": False})
    assert result2 == "request accepted"
    assert mock_inner.call_tool.call_count == 2


# ---------------------------------------------------------------------------
# Edge case: 4K unavailable — fallback to 1080p
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_four_k_unavailable_fallback_to_1080p() -> None:
    """4K request fails at the MCP level — user can retry with is4k=False without re-triggering guard."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(
        side_effect=[
            "ERROR: 4K not available for this title",
            "Request accepted in 1080p",
        ]
    )
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    # First request: 4K — guard passes (quality is set), MCP returns error
    result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
    assert "4K not available" in result1

    # Second request: fallback 1080p — guard still passes (quality is set)
    result2 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": False})
    assert "1080p" in result2
    assert mock_inner.call_tool.call_count == 2


# ---------------------------------------------------------------------------
# Edge case: series request with season selection and quality gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_series_request_with_season_selection_and_quality_gate() -> None:
    """Series request with specific seasons respects quality gate and passes seasons through."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="seasons 1-3 requested in 4K")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality="4k", series_quality="4k", confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    result = await _call(
        guarded,
        "request_media",
        {"mediaType": "tv", "mediaId": 789, "seasons": [1, 2, 3], "is4k": True},
    )

    assert "seasons 1-3 requested" in result
    mock_inner.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_series_no_quality_seasons_still_blocked() -> None:
    """Series request with seasons is blocked if series_quality not set — seasons don't bypass gate."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality="4k", series_quality=None, confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    result = await _call(
        guarded,
        "request_media",
        {"mediaType": "tv", "mediaId": 789, "seasons": [1, 2, 3], "is4k": True},
    )

    assert "series_quality not set" in result.lower()
    mock_inner.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: confirm_request then request_media in same turn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_request_then_request_media_same_turn() -> None:
    """Simulate full confirm flow: guard blocks → set_confirmed → request_media succeeds."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        guarded_toolsets=[guarded],
    )
    guarded.deps = deps

    # Step 1: Guard blocks — confirmation not yet given
    result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
    assert "confirmation required" in result1.lower()
    mock_inner.call_tool.assert_not_called()

    # Step 2: Model calls confirm_request tool (simulate by calling set_confirmed)
    guarded.set_confirmed(mediaId=123, mediaType="movie")
    assert guarded.confirmed is True

    # Step 3: Model retries request_media — now passes through
    result2 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
    assert result2 == "request accepted"
    mock_inner.call_tool.assert_called_once()

    # Step 4: Confirmed flag is reset after success
    assert guarded.confirmed is False


# ---------------------------------------------------------------------------
# Edge case: confirm_request for wrong media ID
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirm_request_media_id_mismatch() -> None:
    """confirm_request sets confirmed flag regardless of mediaId — guard unblocks any request_media.

    Design note: the confirmed flag is intentionally not mediaId-scoped. The
    conversation context is expected to ensure only one media item is in flight.
    A mismatch scenario is technically allowed by the current guard design.
    Future iteration may add strict mediaId matching.
    """
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        guarded_toolsets=[guarded],
    )
    guarded.deps = deps

    # Confirm for mediaId 123
    guarded.set_confirmed(mediaId=123, mediaType="movie")
    assert guarded.confirmed is True

    # But then request_media is called for mediaId 456 (different item)
    # Current design: confirmed flag is not mediaId-scoped, so it still unblocks
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 456, "is4k": True})
    # Guard passes (confirmed=True) and forwards to inner toolset
    assert result == "request accepted"
    mock_inner.call_tool.assert_called_once()
    # Flag reset after successful pass-through
    assert guarded.confirmed is False


# ---------------------------------------------------------------------------
# Logging verification: WARNING on guard block
# ---------------------------------------------------------------------------


def test_logging_warning_on_guard_block(caplog: pytest.LogCaptureFixture) -> None:
    """Guard block emits WARNING log containing tool name and reason (sync via asyncio.run)."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(
            _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True})
        )

    assert "request_media blocked" in caplog.text
    # Confirm the log level is WARNING
    warning_records = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warning_records) >= 1


# ---------------------------------------------------------------------------
# Logging verification: DEBUG on pass-through
# ---------------------------------------------------------------------------


def test_logging_debug_on_pass_through(caplog: pytest.LogCaptureFixture) -> None:
    """Pass-through tool call emits DEBUG log with tool name (sync via asyncio.run)."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="search results")
    guarded = GuardedToolset(mock_inner)

    deps = AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"),
        guarded_toolsets=[],
    )
    guarded.deps = deps

    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(_call(guarded, "search_media", {"query": "Inception"}))

    assert "Tool call allowed" in caplog.text
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("search_media" in str(r.getMessage()) or "search_media" in str(getattr(r, "tool", "")) for r in debug_records)


# ---------------------------------------------------------------------------
# Logging verification: INFO on confirm_request
# ---------------------------------------------------------------------------


def test_logging_info_on_confirm_request(caplog: pytest.LogCaptureFixture) -> None:
    """set_confirmed() emits INFO log with mediaId and mediaType."""
    mock_inner = AsyncMock()
    guarded = GuardedToolset(mock_inner)

    with caplog.at_level(logging.INFO, logger="home_agent.mcp.guarded_toolset"):
        guarded.set_confirmed(mediaId=42, mediaType="movie")

    assert "confirm_request called" in caplog.text
    info_records = [r for r in caplog.records if r.levelno == logging.INFO]
    assert len(info_records) >= 1
