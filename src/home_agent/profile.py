"""User profile models and persistence layer.

Defines Pydantic models for user profiles and a ProfileManager class
to handle database interactions via db.py.
"""

import logging
from datetime import datetime, time
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from home_agent.db import get_profile, save_profile

logger = logging.getLogger(__name__)


class MediaPreferences(BaseModel):
    """User's media consumption preferences.

    Attributes:
        preferred_genres: List of genres the user likes to watch.
        preferred_quality: Default quality for media requests (e.g., '1080p', '4k').
        preferred_language: Preferred audio/subtitle language (e.g., 'en', 'fr').
        avoid_genres: List of genres the user dislikes.
    """

    preferred_genres: list[str] = []
    preferred_quality: str = "1080p"
    preferred_language: str = "en"
    avoid_genres: list[str] = []


class NotificationPrefs(BaseModel):
    """User's notification preferences.

    Attributes:
        enabled: Whether notifications are enabled for this user.
        quiet_hours_start: Time when notifications should be muted.
        quiet_hours_end: Time when notifications should resume.
        notifications_by_source: Dict mapping notification sources to enabled status.
    """

    enabled: bool = True
    quiet_hours_start: Optional[time] = None
    quiet_hours_end: Optional[time] = None
    notifications_by_source: dict[str, bool] = {
        "media_requests": True,
        "system_alerts": True,
    }


class UserProfile(BaseModel):
    """Complete user profile with preferences, notes, and statistics.

    Attributes:
        user_id: Telegram user ID.
        name: Display name for the user.
        created_at: When the profile was first created.
        updated_at: When the profile was last updated.
        media_preferences: Media consumption preferences.
        notification_prefs: Notification settings.
        notes: Personal notes or observations about the user.
        stats: Usage statistics.
    """

    user_id: int
    name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    media_preferences: MediaPreferences = MediaPreferences()
    notification_prefs: NotificationPrefs = NotificationPrefs()
    notes: list[str] = []
    stats: dict[str, int] = {"requests_made": 0, "downloads_completed": 0}


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
        default_profile: Optional[UserProfile] = None,
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
        now = datetime.now()
        return UserProfile(
            user_id=0,  # Placeholder ID that will be replaced
            name=None,
            created_at=now,
            updated_at=now,
            media_preferences=MediaPreferences(),
            notification_prefs=NotificationPrefs(),
            notes=[],
            stats={"requests_made": 0, "downloads_completed": 0},
        )

    async def get(self, user_id: int) -> UserProfile:
        """Get or create user profile from the database.

        Args:
            user_id: Telegram user ID to retrieve profile for.

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

            if "notification_prefs" in profile_dict and isinstance(
                profile_dict["notification_prefs"], dict
            ):
                profile_dict["notification_prefs"] = NotificationPrefs(
                    **profile_dict["notification_prefs"]
                )
            else:
                profile_dict.setdefault(
                    "notification_prefs", NotificationPrefs()
                )

            # Ensure datetime fields are present
            if "created_at" not in profile_dict:
                profile_dict["created_at"] = datetime.now()
            if "updated_at" not in profile_dict:
                profile_dict["updated_at"] = datetime.now()

            return UserProfile(**profile_dict)

        # Create default profile for new user using the stored template
        logger.info("Creating default profile for user %s", user_id)
        now = datetime.now()
        new_profile = self.default_profile.model_copy(
            update={"user_id": user_id, "created_at": now, "updated_at": now}
        )
        await self.save(new_profile)
        return new_profile

    async def save(self, profile: UserProfile) -> None:
        """Save profile to database.

        Args:
            profile: User profile to save to database.
        """
        profile = profile.model_copy(update={"updated_at": datetime.now()})
        # Use mode="json" so datetime/time objects are serialised to ISO strings
        profile_data = profile.model_dump(mode="json")
        # Remove user_id — it's stored as the DB key, not in the data blob
        profile_data.pop("user_id", None)

        await save_profile(self.db_path, user_id=profile.user_id, data=profile_data)
        logger.info("Saved profile for user %s", profile.user_id)
