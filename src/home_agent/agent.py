"""PydanticAI agent for home server management.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from pydantic_ai import Agent, RunContext

from home_agent.config import AppConfig
from home_agent.history import HistoryManager, sliding_window_processor
from home_agent.profile import ProfileManager, UserProfile

logger = logging.getLogger(__name__)


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime.

    Attributes:
        config: Application configuration.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history.
        user_profile: The current user's profile.
    """

    config: AppConfig
    profile_manager: ProfileManager
    history_manager: HistoryManager
    user_profile: UserProfile


agent = Agent(
    "openrouter:qwen/qwq-32b:free",
    deps_type=AgentDeps,
    defer_model_check=True,
    history_processors=[sliding_window_processor(n=20)],
    system_prompt=(
        "You are a helpful home server assistant. "
        "You help the user manage their home server services including media, monitoring, and more. "
        "Always be concise and friendly. "
        "For destructive or irreversible actions, always ask for confirmation before proceeding."
    ),
)


@agent.system_prompt(dynamic=True)
async def inject_user_profile(ctx: RunContext[AgentDeps]) -> str:
    """Inject user profile into the system prompt dynamically.

    Args:
        ctx: Runtime context with dependencies.

    Returns:
        A string fragment to append to the system prompt.
    """
    profile = ctx.deps.user_profile
    name_part = f"The user's name is {profile.name}." if profile.name else "The user has not set a name."
    prefs = profile.media_preferences
    notes_part = ("Notes about this user: " + "; ".join(profile.notes)) if profile.notes else ""
    return (
        f"{name_part} "
        f"Media preferences — quality: {prefs.preferred_quality}, "
        f"language: {prefs.preferred_language}, "
        f"genres: {prefs.preferred_genres or 'none set'}, "
        f"avoid: {prefs.avoid_genres or 'none'}. "
        f"{notes_part}"
    ).strip()


@agent.tool
async def update_user_note(ctx: RunContext[AgentDeps], note: str) -> str:
    """Add an observation about the user to their profile.

    Call this when you learn something meaningful about the user's preferences,
    habits, or personality that would help you serve them better in future
    conversations.

    Args:
        ctx: Runtime context with dependencies.
        note: Free-form note about the user's preferences or behavior.

    Returns:
        Confirmation message.
    """
    profile = ctx.deps.user_profile
    profile.notes.append(note)
    await ctx.deps.profile_manager.save(profile)
    logger.info("Added note to profile for user %s", profile.user_id)
    return f"Noted: {note}"
