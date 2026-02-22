"""Tests for user profile models and ProfileManager."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from home_agent.db import init_db
from home_agent.profile import MediaPreferences, NotificationPrefs, ProfileManager, UserProfile


@pytest.fixture
async def test_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database for profile tests.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Path to the initialised test database.
    """
    db_path = tmp_path / "test_profile.db"
    await init_db(db_path)
    return db_path


def _make_profile(user_id: int = 1) -> UserProfile:
    """Create a minimal UserProfile for testing."""
    now = datetime.now()
    return UserProfile(
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )


# ── Model defaults ────────────────────────────────────────────────────────────


def test_default_profile_has_sensible_defaults() -> None:
    """Newly created default profile has expected default values."""
    profile = _make_profile()

    assert profile.media_preferences.preferred_quality == "1080p"
    assert profile.media_preferences.preferred_language == "en"
    assert profile.media_preferences.preferred_genres == []
    assert profile.media_preferences.avoid_genres == []
    assert len(profile.notes) == 0
    assert profile.stats == {"requests_made": 0, "downloads_completed": 0}
    assert profile.notification_prefs.enabled is True


def test_media_preferences_defaults() -> None:
    """MediaPreferences has correct default values."""
    prefs = MediaPreferences()

    assert prefs.preferred_quality == "1080p"
    assert prefs.preferred_language == "en"
    assert prefs.preferred_genres == []
    assert prefs.avoid_genres == []


def test_notification_prefs_defaults() -> None:
    """NotificationPrefs has correct default values."""
    prefs = NotificationPrefs()

    assert prefs.enabled is True
    assert prefs.quiet_hours_start is None
    assert prefs.quiet_hours_end is None
    assert prefs.notifications_by_source == {
        "media_requests": True,
        "system_alerts": True,
    }


# ── Serialisation ─────────────────────────────────────────────────────────────


def test_profile_serializes_deserializes_identically() -> None:
    """A profile serialises to a dict and deserialises back identically."""
    original_profile = UserProfile(
        user_id=42,
        name="Alice",
        created_at=datetime(2024, 1, 1, 12, 0, 0),
        updated_at=datetime(2024, 6, 1, 8, 0, 0),
        media_preferences=MediaPreferences(
            preferred_genres=["sci-fi", "drama"],
            preferred_quality="4k",
            preferred_language="fr",
            avoid_genres=["horror"],
        ),
        notification_prefs=NotificationPrefs(enabled=False),
        notes=["Likes quiet hours after 22:00"],
        stats={"requests_made": 5, "downloads_completed": 3},
    )

    dumped = original_profile.model_dump()
    reloaded_profile = UserProfile(**dumped)

    assert original_profile.model_dump() == reloaded_profile.model_dump()


def test_profile_json_roundtrip() -> None:
    """Profile survives a JSON encode/decode cycle."""
    profile = _make_profile(user_id=7)
    json_str = profile.model_dump_json()
    reloaded = UserProfile.model_validate_json(json_str)

    assert profile.model_dump() == reloaded.model_dump()


# ── ProfileManager ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_profile_manager_creates_default_for_unknown_user(
    test_db: Path,
) -> None:
    """ProfileManager creates and saves a default profile for a user that doesn't exist."""
    new_user_id = 9999
    manager = ProfileManager(test_db)

    profile = await manager.get(new_user_id)

    assert profile is not None
    assert profile.user_id == new_user_id
    assert profile.media_preferences.preferred_quality == "1080p"
    assert profile.notes == []


@pytest.mark.asyncio
async def test_profile_manager_persists_newly_created_profile(
    test_db: Path,
) -> None:
    """A default profile created by get() can be retrieved on a second call."""
    manager = ProfileManager(test_db)

    first = await manager.get(100)
    second = await manager.get(100)

    assert first.user_id == second.user_id == 100
    assert first.created_at == second.created_at


@pytest.mark.asyncio
async def test_profile_manager_updates_and_persists_fields(
    test_db: Path,
) -> None:
    """ProfileManager properly updates and persists profile field changes."""
    manager = ProfileManager(test_db)
    user_id = 200

    # Create initial profile
    profile = await manager.get(user_id)

    # Mutate media preferences
    updated_prefs = profile.media_preferences.model_copy(
        update={"preferred_quality": "4k"}
    )
    profile = profile.model_copy(update={"media_preferences": updated_prefs})
    await manager.save(profile)

    # Re-fetch and verify persistence
    saved_profile = await manager.get(user_id)

    assert saved_profile.media_preferences.preferred_quality == "4k"


@pytest.mark.asyncio
async def test_profile_manager_saves_notes(test_db: Path) -> None:
    """Notes appended to a profile are persisted to the database."""
    manager = ProfileManager(test_db)
    user_id = 300

    profile = await manager.get(user_id)
    profile = profile.model_copy(update={"notes": ["Prefers evenings"]})
    await manager.save(profile)

    reloaded = await manager.get(user_id)

    assert reloaded.notes == ["Prefers evenings"]


@pytest.mark.asyncio
async def test_profile_manager_custom_default_profile(test_db: Path) -> None:
    """ProfileManager uses a supplied default_profile template for new users."""
    now = datetime.now()
    custom_default = UserProfile(
        user_id=0,
        created_at=now,
        updated_at=now,
        media_preferences=MediaPreferences(preferred_quality="720p"),
    )
    manager = ProfileManager(test_db, default_profile=custom_default)

    profile = await manager.get(555)

    assert profile.media_preferences.preferred_quality == "720p"
