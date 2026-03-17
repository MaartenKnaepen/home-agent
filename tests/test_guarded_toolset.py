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


def make_ctx(deps: AgentDeps) -> MagicMock:
    """Create a mock RunContext with the given deps."""
    ctx = MagicMock()
    ctx.deps = deps
    return ctx


async def _call(guarded: GuardedToolset, name: str, args: dict, deps: AgentDeps | None = None) -> object:
    """Helper to call GuardedToolset.call_tool with mock ctx and tool."""
    ctx = make_ctx(deps) if deps is not None else MagicMock()
    return await guarded.call_tool(name, args, ctx, MagicMock())


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


def make_deps(profile: UserProfile, *, confirmed: bool = False, role: str = "user") -> AgentDeps:
    """Create AgentDeps with the given profile and mock managers."""
    return AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        guarded_toolsets=[],
        confirmed=confirmed,
        called_tools=set(),
        role=role,
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
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_no_quality)

    assert "movie_quality not set" in result.lower()
    assert "set_movie_quality" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_movie_blocked_logs_warning(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Quality gate block for movie emits a WARNING log."""
    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_no_quality)

    assert "request_media blocked by quality gate" in caplog.text


# ---------------------------------------------------------------------------
# Quality gate — TV series
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_blocked_when_series_quality_not_set(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is blocked when series_quality is None."""
    result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456}, deps_no_quality)

    assert "series_quality not set" in result.lower()
    assert "set_series_quality" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_tv_blocked_logs_warning(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Quality gate block for TV emits a WARNING log."""
    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456}, deps_no_quality)

    assert "request_media blocked by quality gate" in caplog.text


# ---------------------------------------------------------------------------
# Quality gate passes — quality is set, no confirmation required
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_request_media_movie_allowed_when_quality_set_no_confirmation(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed when movie_quality set and confirmation_mode='never'."""
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_with_quality)

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_request_media_tv_allowed_when_quality_set_no_confirmation(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed for TV when series_quality set and confirmation_mode='never'."""
    result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456}, deps_with_quality)

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
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_always_confirm)

    assert "confirmation required" in result.lower()
    assert "send_confirmation_keyboard" in result
    mock_inner_toolset.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_request_media_blocked_confirmation_logs_warning(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Confirmation gate block emits a WARNING log."""
    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_always_confirm)

    assert "request_media blocked by confirmation gate" in caplog.text


@pytest.mark.asyncio
async def test_request_media_allowed_when_confirmation_required_and_confirmed(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """request_media is allowed when confirmation_mode='always' and confirmed=True."""
    deps_confirmed = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=True,
    )
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_confirmed)

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Confirmed flag lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_flag_resets_after_successful_request_media(
    guarded: GuardedToolset, deps_always_confirm: AgentDeps
) -> None:
    """confirmed flag (in deps) is reset to False after request_media succeeds."""
    deps_confirmed = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=True,
    )
    ctx = make_ctx(deps_confirmed)
    await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, ctx, MagicMock())

    assert ctx.deps.confirmed is False


@pytest.mark.asyncio
async def test_confirmed_flag_not_reset_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """confirmed flag is NOT reset when the call is blocked by a gate."""
    deps_confirmed = make_deps(make_profile(movie_quality=None), confirmed=True)
    ctx = make_ctx(deps_confirmed)

    await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 123}, ctx, MagicMock())

    # confirmed stays True because the gate blocked before forwarding
    assert ctx.deps.confirmed is True


# ---------------------------------------------------------------------------
# Stateless verification — no set_confirmed(), no .deps, no .confirmed attrs
# ---------------------------------------------------------------------------


def test_guarded_toolset_has_no_stateful_attributes(guarded: GuardedToolset) -> None:
    """GuardedToolset has no deps/confirmed/called_tools instance attributes."""
    assert not hasattr(guarded, "deps")
    assert not hasattr(guarded, "confirmed")
    assert not hasattr(guarded, "called_tools")


# ---------------------------------------------------------------------------
# Pass-through: non-request_media tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_media_passes_through_without_gate(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """search_media passes through to the inner toolset without any gate."""
    result = await _call(guarded, "search_media", {"query": "Inception"}, deps_no_quality)

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_unknown_tool_passes_through(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, mock_inner_toolset: AsyncMock
) -> None:
    """Unknown/future tools pass through without any gate."""
    result = await _call(guarded, "pdf_extract", {"file_id": "abc123"}, deps_no_quality)

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_pass_through_logs_debug(
    guarded: GuardedToolset, deps_with_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Pass-through tool calls emit a DEBUG log."""
    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        await _call(guarded, "search_media", {"query": "Inception"}, deps_with_quality)

    assert "Tool call allowed" in caplog.text


# ---------------------------------------------------------------------------
# called_tools tracking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_called_tools_updated_after_pass_through(
    guarded: GuardedToolset, deps_with_quality: AgentDeps
) -> None:
    """called_tools set is updated in ctx.deps when a tool call succeeds."""
    ctx = make_ctx(deps_with_quality)
    await guarded.call_tool("search_media", {"query": "Inception"}, ctx, MagicMock())

    assert "search_media" in ctx.deps.called_tools


@pytest.mark.asyncio
async def test_called_tools_not_updated_on_gate_block(
    guarded: GuardedToolset, deps_no_quality: AgentDeps
) -> None:
    """called_tools set is NOT updated when a gate blocks the call."""
    ctx = make_ctx(deps_no_quality)
    await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 1}, ctx, MagicMock())

    assert "request_media" not in ctx.deps.called_tools


# ---------------------------------------------------------------------------
# No deps set
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_deps_quality_set_request_media_allowed(
    guarded: GuardedToolset, mock_inner_toolset: AsyncMock
) -> None:
    """When deps has quality set and no confirmation required, request_media passes through."""
    deps = make_deps(make_profile(movie_quality="4k", confirmation_mode="never"))
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1}, deps)

    assert result == "tool result"
    mock_inner_toolset.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Sync helper for logging test (using asyncio.run inside sync test)
# ---------------------------------------------------------------------------


def test_guard_block_logs_warning_sync(
    guarded: GuardedToolset, deps_no_quality: AgentDeps, caplog: pytest.LogCaptureFixture
) -> None:
    """Guard block emits WARNING log (sync wrapper around async call)."""
    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(
            _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_no_quality)
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
    deps = make_deps(make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"))

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps)

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
    deps = make_deps(make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"))

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        result = await _call(guarded, "request_media", {"mediaType": "tv", "mediaId": 456, "seasons": "all"}, deps)

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
    deps1 = make_deps(profile)

    # First request with 4K quality set — passes through
    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps1)
    assert result1 == "request accepted"

    # Simulate quality change mid-conversation via model_copy (new message = new deps)
    profile2 = profile.model_copy(
        update={"media_preferences": profile.media_preferences.model_copy(update={"movie_quality": "1080p"})}
    )
    deps2 = make_deps(profile2)

    # Second request with updated 1080p quality — also passes through
    result2 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 456, "is4k": False}, deps2)
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
    deps = make_deps(make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="never"))

    # First request: 4K — guard passes (quality is set), MCP returns error
    result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps)
    assert "4K not available" in result1

    # Second request: fallback 1080p — guard still passes (quality is set)
    result2 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": False}, deps)
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
    deps = make_deps(make_profile(movie_quality="4k", series_quality="4k", confirmation_mode="never"))

    result = await _call(
        guarded,
        "request_media",
        {"mediaType": "tv", "mediaId": 789, "seasons": [1, 2, 3], "is4k": True},
        deps,
    )

    assert "seasons 1-3 requested" in result
    mock_inner.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_series_no_quality_seasons_still_blocked() -> None:
    """Series request with seasons is blocked if series_quality not set — seasons don't bypass gate."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)
    deps = make_deps(make_profile(movie_quality="4k", series_quality=None, confirmation_mode="never"))

    result = await _call(
        guarded,
        "request_media",
        {"mediaType": "tv", "mediaId": 789, "seasons": [1, 2, 3], "is4k": True},
        deps,
    )

    assert "series_quality not set" in result.lower()
    mock_inner.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Edge case: confirm flow via ctx.deps.confirmed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_keyboard_confirm_then_request_media_same_turn() -> None:
    """Simulate full confirm flow: guard blocks → confirmed=True in deps → request_media succeeds."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    # Step 1: Guard blocks — confirmation not yet given (confirmed=False)
    deps_unconfirmed = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=False,
    )
    result1 = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps_unconfirmed)
    assert "confirmation required" in result1.lower()
    mock_inner.call_tool.assert_not_called()

    # Step 2: User confirms (new AgentDeps with confirmed=True — as built by bot.py callback)
    deps_confirmed = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=True,
    )
    ctx = make_ctx(deps_confirmed)

    # Step 3: Model retries request_media — now passes through
    result2 = await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, ctx, MagicMock())
    assert result2 == "request accepted"
    mock_inner.call_tool.assert_called_once()

    # Step 4: Confirmed flag is reset in deps after success
    assert ctx.deps.confirmed is False


# ---------------------------------------------------------------------------
# Edge case: confirmed=True unblocks any request_media regardless of mediaId
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_confirmed_flag_unblocks_any_media_id() -> None:
    """confirmed=True in deps unblocks any request_media regardless of mediaId.

    Design note: the confirmed flag is intentionally not mediaId-scoped.
    """
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    deps_confirmed = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=True,
    )
    # request_media called for mediaId 456 — confirmed=True still unblocks
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 456, "is4k": True}, deps_confirmed)
    assert result == "request accepted"
    mock_inner.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Logging verification: WARNING on guard block
# ---------------------------------------------------------------------------


def test_logging_warning_on_guard_block(caplog: pytest.LogCaptureFixture) -> None:
    """Guard block emits WARNING log containing tool name and reason (sync via asyncio.run)."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)
    deps = make_deps(make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"))

    with caplog.at_level(logging.WARNING, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(
            _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 123, "is4k": True}, deps)
        )

    assert "request_media blocked" in caplog.text
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
    deps = make_deps(make_profile(movie_quality=None, series_quality=None, confirmation_mode="never"))

    with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.guarded_toolset"):
        asyncio.run(_call(guarded, "search_media", {"query": "Inception"}, deps))

    assert "Tool call allowed" in caplog.text
    debug_records = [r for r in caplog.records if r.levelno == logging.DEBUG]
    assert any("search_media" in str(r.getMessage()) or "search_media" in str(getattr(r, "tool", "")) for r in debug_records)


# ---------------------------------------------------------------------------
# New: role gate — read_only blocked from request_media
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_user_cannot_request_media() -> None:
    """read_only role is blocked from request_media by the role gate."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="tool result")
    guarded = GuardedToolset(mock_inner)
    deps = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="never"),
        role="read_only",
    )

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1}, deps)

    assert "do not have permission" in result.lower()
    mock_inner.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_admin_user_can_request_media() -> None:
    """admin role can call request_media (role gate allows admin and user)."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)
    deps = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="never"),
        role="admin",
    )

    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1}, deps)

    assert result == "request accepted"
    mock_inner.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_call_tool_reads_confirmed_from_ctx_deps() -> None:
    """call_tool reads confirmed from ctx.deps.confirmed, not from self."""
    mock_inner = AsyncMock()
    mock_inner.call_tool = AsyncMock(return_value="request accepted")
    guarded = GuardedToolset(mock_inner)

    # GuardedToolset has no .confirmed attribute
    assert not hasattr(guarded, "confirmed")

    deps = make_deps(
        make_profile(movie_quality="4k", series_quality="1080p", confirmation_mode="always"),
        confirmed=True,
    )
    result = await _call(guarded, "request_media", {"mediaType": "movie", "mediaId": 1}, deps)

    # confirmed=True in deps → gate passes
    assert result == "request accepted"
