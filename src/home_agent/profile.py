"""User profile models and persistence layer.

Defines Pydantic models for user profiles and a ProfileManager class
to handle database interactions via db.py.
"""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from home_agent.db import get_profile, save_profile

logger = logging.getLogger(__name__)

# Minimal locale → language name mapping. Only languages the admin expects users
# to speak. Extend as needed. The LLM interprets these names in the system prompt.
_LOCALE_TO_LANGUAGE: dict[str, str] = {
    "nl": "Dutch",
    "en": "English",
    "fr": "French",
    "de": "German",
    "es": "Spanish",
}

_DEFAULT_LANGUAGE = "English"


def resolve_language(language_code: str | None) -> str:
    """Map a Telegram language_code to a human-readable language name.

    Args:
        language_code: ISO 639-1 code from Telegram (e.g. 'nl', 'en-US').
            May be None if the user hasn't set a Telegram locale.

    Returns:
        A human-readable language name (e.g. 'Dutch', 'English').
    """
    if not language_code:
        return _DEFAULT_LANGUAGE
    # Telegram can send codes like 'en-US'; take the first part
    base_code = language_code.split("-")[0].lower()
    return _LOCALE_TO_LANGUAGE.get(base_code, _DEFAULT_LANGUAGE)


class MediaPreferences(BaseModel):
    """User's media download preferences.

    Attributes:
        movie_quality: Preferred quality for movie downloads. None means not yet asked.
        series_quality: Preferred quality for series downloads. None means not yet asked.
    """

    movie_quality: Literal["4k", "1080p"] | None = None
    series_quality: Literal["4k", "1080p"] | None = None


class UserProfile(BaseModel):
    """Complete user profile with preferences and notes.

    Attributes:
        user_id: Telegram user ID.
        name: Display name for the user.
        created_at: When the profile was first created.
        updated_at: When the profile was last updated.
        reply_language: Language the agent uses to reply to this user.
        confirmation_mode: Whether the agent confirms before requesting media.
        media_preferences: Media download preferences.
        notes: Personal notes or observations about the user.
    """

    user_id: int
    name: str | None = None
    created_at: datetime
    updated_at: datetime
    reply_language: str = "English"
    confirmation_mode: Literal["always", "never"] = "always"
    media_preferences: MediaPreferences = MediaPreferences()
    notes: list[str] = []


class ProfileManager:
    """Manages user profiles with database persistence.

    Provides methods to get and save user profiles to the SQLite database,
    with automatic creation of default profiles for new users.

    Attributes:
        db_path: Path to the SQLite database file.
        default_profile: Template for creating default profiles when needed.
    """

    def __init__(
        self,
        db_path: str | Path,
        *,
        default_profile: UserProfile | None = None,
    ) -> None:
        """Initialize the ProfileManager with database path and default profile.

        Args:
            db_path: Path to the SQLite database file.
            default_profile: Optional template for creating default profiles.
        """
        self.db_path = Path(db_path)
        self.default_profile = default_profile or self._create_default_profile()

    def _create_default_profile(self) -> UserProfile:
        """Create a default UserProfile instance.

        Returns:
            A new UserProfile with default settings.
        """
        now = datetime.now(tz=timezone.utc)
        return UserProfile(
            user_id=0,
            name=None,
            created_at=now,
            updated_at=now,
            media_preferences=MediaPreferences(),
            notes=[],
        )

    async def get(self, user_id: int, *, language_code: str | None = None) -> UserProfile:
        """Get or create user profile from the database.

        Args:
            user_id: Telegram user ID to retrieve profile for.
            language_code: Optional Telegram locale code for auto-detecting
                reply language on first profile creation. Ignored for existing profiles.

        Returns:
            User profile from database or newly created default profile.
        """
        profile_data = await get_profile(self.db_path, user_id=user_id)
        if profile_data:
            profile_dict = {**profile_data}
            profile_dict["user_id"] = user_id

            # Reconstruct nested models from stored dict data
            if "media_preferences" in profile_dict and isinstance(
                profile_dict["media_preferences"], dict
            ):
                profile_dict["media_preferences"] = MediaPreferences(
                    **profile_dict["media_preferences"]
                )
            else:
                profile_dict.setdefault(
                    "media_preferences", MediaPreferences()
                )

            # Ensure datetime fields are present
            if "created_at" not in profile_dict:
                profile_dict["created_at"] = datetime.now(tz=timezone.utc)
            if "updated_at" not in profile_dict:
                profile_dict["updated_at"] = datetime.now(tz=timezone.utc)

            return UserProfile(**profile_dict)

        # Create default profile for new user using the stored template
        logger.info("Creating default profile for user %s", user_id)
        now = datetime.now(tz=timezone.utc)
        reply_language = resolve_language(language_code)
        new_profile = self.default_profile.model_copy(
            update={
                "user_id": user_id,
                "created_at": now,
                "updated_at": now,
                "reply_language": reply_language,
            }
        )
        await self.save(new_profile)
        return new_profile

    async def save(self, profile: UserProfile) -> None:
        """Save profile to database.

        Args:
            profile: User profile to save to database.
        """
        profile = profile.model_copy(update={"updated_at": datetime.now(tz=timezone.utc)})
        # Use mode="json" so datetime objects are serialised to ISO strings
        profile_data = profile.model_dump(mode="json")
        # Remove user_id — it's stored as the DB key, not in the data blob
        profile_data.pop("user_id", None)

        await save_profile(self.db_path, user_id=profile.user_id, data=profile_data)
        logger.info("Saved profile for user %s", profile.user_id)
