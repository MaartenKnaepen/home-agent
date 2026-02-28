"""PydanticAI agent for home server management.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from pydantic_ai import Agent, RunContext

from home_agent.config import AppConfig
from home_agent.history import HistoryManager, sliding_window_processor
from home_agent.mcp.registry import MCPRegistry
from home_agent.profile import ProfileManager, UserProfile
from home_agent.tools.profile_tools import (
    set_confirmation_mode,
    set_movie_quality,
    set_reply_language,
    set_series_quality,
)

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


def create_agent(
    toolsets: list[Any] | None = None,
    model: str = "openrouter:qwen/qwq-32b:free",
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
) -> Agent[AgentDeps, str]:
    """Create a PydanticAI agent with optional MCP toolsets.

    Args:
        toolsets: Optional list of FastMCPToolset instances for MCP servers.
            If None, the agent runs without MCP tools (useful for tests).
        model: PydanticAI model string to use. Defaults to qwen/qwq-32b:free.
            Override via the LLM_MODEL environment variable in production.
        max_retries: Maximum number of retries on HTTP 429 rate limit errors.
            Defaults to 3.
        base_delay: Base delay in seconds for exponential backoff. Doubles each retry.
            Defaults to 1.0.
        max_delay: Maximum delay in seconds for exponential backoff. Caps the doubling.
            Defaults to 30.0.

    Returns:
        Configured Agent instance with system prompt and tools registered.
    """
    from home_agent.models.retry_model import RetryingModel

    # Pass the model string directly so the provider (and its API-key check) is
    # resolved lazily on the first request, honouring defer_model_check behaviour.
    retrying_model = RetryingModel(model, max_retries=max_retries, base_delay=base_delay, max_delay=max_delay)
    agent_instance: Agent[AgentDeps, str] = Agent(
        retrying_model,
        deps_type=AgentDeps,
        defer_model_check=True,
        toolsets=toolsets or [],
        history_processors=[sliding_window_processor(n=20)],
        system_prompt=(
            "You are a helpful home server assistant. "
            "You help the user manage their home server services including media, monitoring, and more. "
            "Always be concise and friendly. "
            "\n\n"
            "## Media Requests\n"
            "When the user asks to download, add, or request a movie or TV series:\n"
            "1. SEARCH FIRST: Always call search_media before requesting. Never guess a media ID.\n"
            "2. DISAMBIGUATE: When search returns results:\n"
            "   - If there is only ONE clear match (same title, year, and type as requested): "
            "skip straight to step 3 (QUALITY).\n"
            "   - If there are MULTIPLE results: present them as a numbered list. "
            "Include title, year, type (movie/series), and ONE distinguishing detail "
            "(director, lead actor, or brief description). Keep it concise.\n"
            "   - NEVER expose TMDB IDs, media IDs, or any technical identifiers to the user.\n"
            "   - Use natural language, not database terms.\n"
            "   Example (multiple results):\n"
            "     'I found a few options:\n"
            "     1. Troy (2004) — epic war film with Brad Pitt\n"
            "     2. Troy: Fall of a City (2018) — TV mini-series\n"
            "     Which one would you like?'\n"
            "   - If the user says 'the first one', 'number 2', or similar: accept it and proceed.\n"
            "   - If the user changes their mind after picking: restart from search.\n"
            "   - For sequels and franchises: always ask which one unless the user was specific "
            "(e.g. 'The Matrix Reloaded' is specific; 'The Matrix' is ambiguous if there are multiple entries).\n"
            "3. QUALITY: Before requesting, check the user's quality preference from your context. "
            "If movie_quality is NOT SET and the user wants a movie, ask: "
            "'Do you prefer 4K or 1080p for movies?' and call set_movie_quality with their answer. "
            "If series_quality is NOT SET and the user wants a series, ask: "
            "'Do you prefer 4K or 1080p for series?' and call set_series_quality with their answer.\n"
            "4. CONFIRM: When confirmation_mode is 'always', always confirm before calling "
            "request_media. Show the exact title, year, and quality you will request. "
            "Only proceed after the user says yes.\n"
            "   Example: 'I found Troy (2004). Request it in 4K?'\n"
            "   When confirmation_mode is 'never', skip confirmation and request immediately.\n"
            "\n"
            "## Language\n"
            "Always reply in the language specified in your context (reply_language). "
            "If the user asks you to switch language, call set_reply_language with the new language "
            "name (e.g. 'Dutch', 'French') and switch immediately in your next reply.\n"
            "\n"
            "## Tool Usage\n"
            "NEVER use raw_request for any purpose. It is disabled. "
            "Always use the dedicated tools: search_media, request_media, get_request.\n"
            "When requesting a TV series with request_media, you MUST include a 'seasons' "
            "parameter. Ask the user which seasons they want: all seasons, or specific ones "
            "(e.g. [1, 2, 3]). Pass 'all' or a list of season numbers.\n"
            "\n"
            "## Preferences\n"
            "If the user expresses preferences, habits, or personal details worth remembering, "
            "call update_user_note to record them for future conversations."
        ),
    )

    @agent_instance.system_prompt(dynamic=True)
    async def inject_user_profile(ctx: RunContext[AgentDeps]) -> str:
        """Inject user profile into the system prompt dynamically.

        Args:
            ctx: Runtime context with dependencies.

        Returns:
            A string fragment appended to the system prompt before each request.
        """
        profile = ctx.deps.user_profile
        prefs = profile.media_preferences

        name_part = (
            f"The user's name is {profile.name}."
            if profile.name
            else "The user has not set a name."
        )

        movie_q = (
            prefs.movie_quality
            if prefs.movie_quality
            else "NOT SET — ask the user before making any movie request"
        )
        series_q = (
            prefs.series_quality
            if prefs.series_quality
            else "NOT SET — ask the user before making any series request"
        )

        notes_part = (
            "Notes about this user: " + "; ".join(profile.notes)
            if profile.notes
            else ""
        )

        parts = [
            "## Current User Context",
            name_part,
            f"Reply language: {profile.reply_language} — always use this language.",
            f"Confirmation mode: {profile.confirmation_mode}.",
            f"Movie quality preference: {movie_q}.",
            f"Series quality preference: {series_q}.",
        ]
        if notes_part:
            parts.append(notes_part)

        return "\n".join(parts)

    @agent_instance.tool
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
        new_profile = profile.model_copy(update={"notes": [*profile.notes, note]})
        ctx.deps.user_profile = new_profile
        await ctx.deps.profile_manager.save(new_profile)
        logger.info("Added note to profile for user %s", profile.user_id)
        return f"Noted: {note}"

    # Register profile preference tools
    agent_instance.tool(set_movie_quality)
    agent_instance.tool(set_series_quality)
    agent_instance.tool(set_reply_language)
    agent_instance.tool(set_confirmation_mode)

    return agent_instance


def get_agent_toolsets(registry: MCPRegistry) -> list[Any]:
    """Get MCP toolsets from the registry for agent construction.

    Args:
        registry: MCP registry with registered server configurations.

    Returns:
        List of FastMCPToolset instances for all enabled servers.
    """
    return registry.get_toolsets()
