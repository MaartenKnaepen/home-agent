"""Profile update tools for the PydanticAI agent.

These functions are registered as agent tools in agent.py via
agent_instance.tool(func) after import. They must not import
home_agent.agent to avoid circular imports.

Adheres to home-agent coding standards: type hints, Google-style docstrings,
async-first.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from pydantic_ai import RunContext

logger = logging.getLogger(__name__)


async def set_movie_quality(
    ctx: RunContext[Any], quality: Literal["4k", "1080p"]
) -> str:
    """Store the user's preferred movie download quality.

    Call this when the user specifies their preferred quality for movie
    downloads. Once set, use this quality for all future movie requests
    without asking again.

    Args:
        ctx: Runtime context with dependencies.
        quality: Preferred quality — either '4k' or '1080p'.

    Returns:
        Confirmation message.
    """
    profile = ctx.deps.user_profile
    profile.media_preferences = profile.media_preferences.model_copy(
        update={"movie_quality": quality}
    )
    await ctx.deps.profile_manager.save(profile)
    logger.info("Set movie quality to %s for user %s", quality, profile.user_id)
    return f"Got it! I'll request movies in {quality} from now on."


async def set_series_quality(
    ctx: RunContext[Any], quality: Literal["4k", "1080p"]
) -> str:
    """Store the user's preferred series download quality.

    Call this when the user specifies their preferred quality for TV series
    downloads. Once set, use this quality for all future series requests
    without asking again.

    Args:
        ctx: Runtime context with dependencies.
        quality: Preferred quality — either '4k' or '1080p'.

    Returns:
        Confirmation message.
    """
    profile = ctx.deps.user_profile
    profile.media_preferences = profile.media_preferences.model_copy(
        update={"series_quality": quality}
    )
    await ctx.deps.profile_manager.save(profile)
    logger.info("Set series quality to %s for user %s", quality, profile.user_id)
    return f"Got it! I'll request series in {quality} from now on."


async def set_reply_language(ctx: RunContext[Any], language: str) -> str:
    """Update the language the agent uses to reply to this user.

    Call this when the user asks to switch the reply language, e.g.
    'from now on talk to me in Dutch' or 'speak French'.
    Accepts natural language names: 'Dutch', 'French', 'German', 'English', etc.
    The agent should normalize input before calling (e.g. 'nl' → 'Dutch').

    Args:
        ctx: Runtime context with dependencies.
        language: Human-readable language name to use for replies.

    Returns:
        Confirmation message in the new language.
    """
    profile = ctx.deps.user_profile
    profile = profile.model_copy(update={"reply_language": language})
    ctx.deps.user_profile = profile
    await ctx.deps.profile_manager.save(profile)
    logger.info("Set reply language to %s for user %s", language, profile.user_id)
    return f"Understood! I'll reply in {language} from now on."


async def set_confirmation_mode(
    ctx: RunContext[Any], mode: Literal["always", "never"]
) -> str:
    """Toggle whether the agent confirms before requesting media.

    Call this when the user asks to skip or enable confirmation prompts.
    'always' = agent always confirms before requesting (default, recommended).
    'never' = agent requests immediately without asking.

    Args:
        ctx: Runtime context with dependencies.
        mode: Confirmation mode — 'always' or 'never'.

    Returns:
        Confirmation message.
    """
    profile = ctx.deps.user_profile
    profile = profile.model_copy(update={"confirmation_mode": mode})
    ctx.deps.user_profile = profile
    await ctx.deps.profile_manager.save(profile)
    logger.info("Set confirmation_mode to %s for user %s", mode, profile.user_id)
    if mode == "never":
        return "Got it! I'll request media immediately without asking for confirmation."
    return "Got it! I'll always confirm before requesting media."
