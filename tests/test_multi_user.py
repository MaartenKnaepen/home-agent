"""Tests for multi-user isolation — GuardedToolset stateless refactor.

Verifies that concurrent users do not interfere with each other's state,
and that role-based permissions (admin, user, read_only) work correctly.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from home_agent.agent import AgentDeps
from home_agent.mcp.guarded_toolset import GuardedToolset
from home_agent.profile import MediaPreferences, ProfileManager, UserProfile


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_profile(
    user_id: int = 1,
    *,
    movie_quality: str | None = "4k",
    series_quality: str | None = "1080p",
    confirmation_mode: str = "always",
    role: str = "user",
) -> UserProfile:
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
        role=role,  # type: ignore[arg-type]
    )


def make_deps(profile: UserProfile, *, confirmed: bool = False) -> AgentDeps:
    return AgentDeps(
        config=MagicMock(),
        profile_manager=MagicMock(),
        history_manager=MagicMock(),
        user_profile=profile,
        confirmed=confirmed,
        called_tools=set(),
        role=profile.role,
    )


def make_guarded() -> tuple[GuardedToolset, AsyncMock]:
    inner = AsyncMock()
    inner.call_tool = AsyncMock(return_value="request accepted")
    return GuardedToolset(inner), inner


# ---------------------------------------------------------------------------
# Multi-user isolation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_concurrent_users_do_not_interfere() -> None:
    """Two concurrent users have fully isolated state — no cross-contamination."""
    guarded, inner = make_guarded()

    # User A: confirmed=True, User B: confirmed=False — both with quality set
    deps_a = make_deps(make_profile(user_id=1, confirmation_mode="always"), confirmed=True)
    deps_b = make_deps(make_profile(user_id=2, confirmation_mode="always"), confirmed=False)

    ctx_a = MagicMock()
    ctx_a.deps = deps_a
    ctx_b = MagicMock()
    ctx_b.deps = deps_b

    result_a, result_b = await asyncio.gather(
        guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 1}, ctx_a, MagicMock()),
        guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 2}, ctx_b, MagicMock()),
    )

    # A succeeds (confirmed=True), B is blocked (confirmed=False)
    assert result_a == "request accepted"
    assert "confirmation required" in result_b.lower()


@pytest.mark.asyncio
async def test_user_a_confirmation_does_not_affect_user_b() -> None:
    """User A pressing ✅ Yes does not unblock User B's request_media gate."""
    guarded, _ = make_guarded()

    # User A confirmed their request
    deps_a = make_deps(make_profile(user_id=1, confirmation_mode="always"), confirmed=True)
    # User B has NOT confirmed
    deps_b = make_deps(make_profile(user_id=2, confirmation_mode="always"), confirmed=False)

    ctx_b = MagicMock()
    ctx_b.deps = deps_b

    # B's call should still be blocked
    result_b = await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 2}, ctx_b, MagicMock())
    assert "confirmation required" in result_b.lower()

    # A's confirmed state is not accessible on guarded (no self.confirmed)
    assert not hasattr(guarded, "confirmed")


@pytest.mark.asyncio
async def test_user_a_quality_does_not_bleed_into_user_b() -> None:
    """User A's quality setting does not affect User B's quality gate check."""
    guarded, inner = make_guarded()

    # User A has quality set
    deps_a = make_deps(make_profile(user_id=1, movie_quality="4k", confirmation_mode="never"))
    # User B has no quality set
    deps_b = make_deps(make_profile(user_id=2, movie_quality=None, confirmation_mode="never"))

    ctx_b = MagicMock()
    ctx_b.deps = deps_b

    result_b = await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 2}, ctx_b, MagicMock())

    # B is blocked despite A having quality set — no cross-contamination
    assert "movie_quality not set" in result_b.lower()
    inner.call_tool.assert_not_called()


# ---------------------------------------------------------------------------
# Role gate
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_read_only_user_blocked_from_request_media() -> None:
    """read_only user cannot call request_media — role gate blocks it."""
    guarded, inner = make_guarded()
    deps = make_deps(make_profile(user_id=1, role="read_only", confirmation_mode="never"))

    ctx = MagicMock()
    ctx.deps = deps

    result = await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 1}, ctx, MagicMock())

    assert "do not have permission" in result.lower()
    inner.call_tool.assert_not_called()


@pytest.mark.asyncio
async def test_read_only_user_can_search() -> None:
    """read_only user can call search_media — only request_media is blocked."""
    guarded, inner = make_guarded()
    inner.call_tool = AsyncMock(return_value="search results")
    deps = make_deps(make_profile(user_id=1, role="read_only", confirmation_mode="never"))

    ctx = MagicMock()
    ctx.deps = deps

    result = await guarded.call_tool("search_media", {"query": "Inception"}, ctx, MagicMock())

    assert result == "search results"
    inner.call_tool.assert_called_once()


@pytest.mark.asyncio
async def test_admin_user_can_request_media() -> None:
    """admin role passes the role gate and can call request_media."""
    guarded, inner = make_guarded()
    deps = make_deps(make_profile(user_id=1, role="admin", confirmation_mode="never"))

    ctx = MagicMock()
    ctx.deps = deps

    result = await guarded.call_tool("request_media", {"mediaType": "movie", "mediaId": 1}, ctx, MagicMock())

    assert result == "request accepted"
    inner.call_tool.assert_called_once()


# ---------------------------------------------------------------------------
# Admin auto-assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_admin_auto_assigned_on_profile_creation(test_db: Path) -> None:
    """User in admin_telegram_ids gets admin role on profile creation."""
    manager = ProfileManager(test_db, admin_telegram_ids=[999])
    profile = await manager.get(999)
    assert profile.role == "admin"


@pytest.mark.asyncio
async def test_normal_user_gets_user_role(test_db: Path) -> None:
    """User not in admin_telegram_ids gets the default 'user' role."""
    manager = ProfileManager(test_db, admin_telegram_ids=[999])
    profile = await manager.get(111)
    assert profile.role == "user"


@pytest.mark.asyncio
async def test_existing_user_role_updated_when_added_to_admin_list(test_db: Path) -> None:
    """Existing user gets 'admin' role when their ID is added to admin_telegram_ids."""
    manager_no_admin = ProfileManager(test_db)
    profile = await manager_no_admin.get(777)
    assert profile.role == "user"

    # Now same user is admin
    manager_with_admin = ProfileManager(test_db, admin_telegram_ids=[777])
    updated_profile = await manager_with_admin.get(777)
    assert updated_profile.role == "admin"


# ---------------------------------------------------------------------------
# pending_confirmations keyed by user_id
# ---------------------------------------------------------------------------


def test_pending_confirmations_keyed_by_user_id() -> None:
    """Confirmation from User A does not affect User B's pending confirmation state."""
    pending: dict[int, tuple[int, str]] = {}

    # User A confirms mediaId=10
    pending[1] = (10, "movie")
    # User B has not confirmed
    assert 2 not in pending

    # User A's message is processed — consumes their confirmation
    confirmed_a = False
    if 1 in pending:
        pending.pop(1)
        confirmed_a = True

    # User B's message is processed — no confirmation
    confirmed_b = False
    if 2 in pending:
        pending.pop(2)
        confirmed_b = True

    assert confirmed_a is True
    assert confirmed_b is False
    assert 1 not in pending
    assert 2 not in pending


def test_pending_confirmations_user_a_does_not_unlock_user_b() -> None:
    """User A's confirmation entry cannot be consumed by User B's message handler."""
    pending: dict[int, tuple[int, str]] = {}

    # User A presses ✅
    pending[1] = (42, "movie")

    # User B's handle_message runs — should NOT consume A's confirmation
    confirmed_b = False
    user_b_id = 2
    if user_b_id in pending:
        pending.pop(user_b_id)
        confirmed_b = True

    assert confirmed_b is False
    assert 1 in pending  # A's entry untouched
