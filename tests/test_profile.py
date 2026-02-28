"""Tests for user profile models and ProfileManager."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from home_agent.profile import MediaPreferences, ProfileManager, UserProfile, resolve_language


def _make_profile(user_id: int = 1) -> UserProfile:
    """Create a minimal UserProfile for testing."""
    now = datetime.now(tz=timezone.utc)
    return UserProfile(
        user_id=user_id,
        created_at=now,
        updated_at=now,
    )


# ── Model defaults ────────────────────────────────────────────────────────────


def test_default_profile_has_sensible_defaults() -> None:
    """Newly created default profile has expected default values."""
    profile = _make_profile()
    assert profile.media_preferences.movie_quality is None
    assert profile.media_preferences.series_quality is None
    assert profile.reply_language == "English"
    assert profile.confirmation_mode == "always"
    assert len(profile.notes) == 0


def test_media_preferences_defaults() -> None:
    """MediaPreferences has correct default values."""
    prefs = MediaPreferences()
    assert prefs.movie_quality is None
    assert prefs.series_quality is None


# ── Serialisation ─────────────────────────────────────────────────────────────


def test_profile_serializes_deserializes_identically() -> None:
    """A profile serialises to a dict and deserialises back identically."""
    original_profile = UserProfile(
        user_id=42,
        name="Alice",
        created_at=datetime(2024, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
        updated_at=datetime(2024, 6, 1, 8, 0, 0, tzinfo=timezone.utc),
        reply_language="dutch",
        confirmation_mode="never",
        media_preferences=MediaPreferences(
            movie_quality="4k",
            series_quality="1080p",
        ),
        notes=["Likes quiet hours after 22:00"],
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
    assert profile.media_preferences.movie_quality is None
    assert profile.media_preferences.series_quality is None
    assert profile.reply_language == "English"
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
        update={"movie_quality": "4k"}
    )
    profile = profile.model_copy(update={"media_preferences": updated_prefs})
    await manager.save(profile)

    # Re-fetch and verify persistence
    saved_profile = await manager.get(user_id)

    assert saved_profile.media_preferences.movie_quality == "4k"


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
    now = datetime.now(tz=timezone.utc)
    custom_default = UserProfile(
        user_id=0,
        created_at=now,
        updated_at=now,
        media_preferences=MediaPreferences(movie_quality="4k"),
    )
    manager = ProfileManager(test_db, default_profile=custom_default)

    profile = await manager.get(555)

    assert profile.media_preferences.movie_quality == "4k"


# ── Migration & new fields ────────────────────────────────────────────────────


def test_profile_migration_ignores_removed_fields() -> None:
    """Profile with old removed fields deserializes without error."""
    old_data = {
        "user_id": 1,
        "name": "OldUser",
        "created_at": "2024-01-01T00:00:00",
        "updated_at": "2024-01-01T00:00:00",
        "media_preferences": {
            "preferred_genres": ["action"],
            "preferred_quality": "1080p",
            "preferred_language": "en",
            "avoid_genres": ["horror"],
        },
        "notification_prefs": {"enabled": True},
        "stats": {"requests_made": 5},
    }
    # Pydantic should ignore unknown fields and use defaults for new fields
    profile = UserProfile.model_validate(old_data)
    assert profile.user_id == 1
    assert profile.reply_language == "English"
    assert profile.confirmation_mode == "always"
    assert profile.media_preferences.movie_quality is None


def test_profile_new_fields_roundtrip() -> None:
    """New profile fields (reply_language, confirmation_mode) survive JSON round-trip."""
    profile = UserProfile(
        user_id=42,
        created_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        updated_at=datetime(2024, 1, 1, tzinfo=timezone.utc),
        reply_language="dutch",
        confirmation_mode="never",
        media_preferences=MediaPreferences(movie_quality="4k", series_quality="1080p"),
    )
    json_str = profile.model_dump_json()
    reloaded = UserProfile.model_validate_json(json_str)
    assert reloaded.reply_language == "dutch"
    assert reloaded.confirmation_mode == "never"
    assert reloaded.media_preferences.movie_quality == "4k"
    assert reloaded.media_preferences.series_quality == "1080p"


# ── Language auto-detection ────────────────────────────────────────────────────


def test_resolve_language_known_locale() -> None:
    """resolve_language maps known locale codes to language names."""
    assert resolve_language("nl") == "Dutch"
    assert resolve_language("en") == "English"
    assert resolve_language("fr") == "French"
    assert resolve_language("de") == "German"
    assert resolve_language("es") == "Spanish"


def test_resolve_language_with_region_code() -> None:
    """resolve_language handles locale codes with region suffix."""
    assert resolve_language("en-US") == "English"
    assert resolve_language("nl-BE") == "Dutch"
    assert resolve_language("fr-CA") == "French"


def test_resolve_language_unknown_falls_back() -> None:
    """resolve_language returns English for unknown locale codes."""
    assert resolve_language("ja") == "English"
    assert resolve_language("zh") == "English"


def test_resolve_language_none_falls_back() -> None:
    """resolve_language returns English when language_code is None."""
    assert resolve_language(None) == "English"


@pytest.mark.asyncio
async def test_profile_manager_uses_language_code_for_new_user(
    test_db: Path,
) -> None:
    """ProfileManager sets reply_language from language_code for new users."""
    manager = ProfileManager(test_db)
    profile = await manager.get(777, language_code="nl")
    assert profile.reply_language == "Dutch"


def test_default_profile_has_timezone_aware_datetimes() -> None:
    """Default profile created by _create_default_profile() has timezone-aware datetimes."""
    manager = ProfileManager(":memory:")
    profile = manager._create_default_profile()
    assert profile.created_at.tzinfo is not None
    assert profile.updated_at.tzinfo is not None


@pytest.mark.asyncio
async def test_profile_roundtrip_preserves_timezone(test_db: Path) -> None:
    """Saving and reloading a profile preserves timezone-aware datetimes."""
    manager = ProfileManager(test_db)
    profile = await manager.get(9001)
    assert profile.created_at.tzinfo is not None

    await manager.save(profile)
    reloaded = await manager.get(9001)
    assert reloaded.created_at.tzinfo is not None


@pytest.mark.asyncio
async def test_profile_manager_ignores_language_code_for_existing_user(
    test_db: Path,
) -> None:
    """ProfileManager ignores language_code for users with existing profiles."""
    manager = ProfileManager(test_db)
    # Create with Dutch
    await manager.get(888, language_code="nl")
    # Re-fetch with English — should NOT change
    profile = await manager.get(888, language_code="en")
    assert profile.reply_language == "Dutch"
