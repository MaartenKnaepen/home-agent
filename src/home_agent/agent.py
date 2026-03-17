"""PydanticAI agent for home server management.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pydantic_ai import Agent, RunContext
from telegram import Bot

from home_agent.config import AppConfig
from home_agent.history import HistoryManager, sliding_window_processor
from home_agent.profile import ProfileManager, UserProfile
from home_agent.prompts import SYSTEM_PROMPT
from home_agent.tools.profile_tools import (
    set_confirmation_mode,
    set_movie_quality,
    set_reply_language,
    set_series_quality,
)
from home_agent.tools.telegram_tools import send_confirmation_keyboard, send_poster_image

if TYPE_CHECKING:
    from home_agent.mcp.guarded_toolset import GuardedToolset

logger = logging.getLogger(__name__)


@dataclass
class RetryConfig:
    """Configuration for exponential backoff retry behavior.

    Attributes:
        max_retries: Maximum number of retries on HTTP 429 rate limit errors.
        base_delay: Base delay in seconds for exponential backoff. Doubles each retry.
        max_delay: Maximum delay in seconds for exponential backoff. Caps the doubling.
    """

    max_retries: int = 3
    base_delay: float = 1.0
    max_delay: float = 30.0


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime.

    All fields are per-user and per-message — a fresh AgentDeps is created
    for each incoming message in handle_message(). GuardedToolset reads state
    from ctx.deps (this dataclass) via PydanticAI's RunContext, making the
    GuardedToolset itself stateless and safe for concurrent multi-user access.

    Attributes:
        config: Application configuration.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history.
        user_profile: The current user's profile.
        guarded_toolsets: GuardedToolset instances wrapping MCP toolsets.
        telegram_bot: Telegram Bot instance for sending messages/photos.
            Set by bot.py before each agent.run() call. None in tests.
        telegram_chat_id: Telegram chat ID for sending messages.
            Set by bot.py before each agent.run() call. None in tests.
        confirmed: True when the user has confirmed a pending media request
            via the inline keyboard ✅ button. Read by GuardedToolset.call_tool()
            to unblock the confirmation gate for this turn only.
        called_tools: Names of MCP tools called successfully this turn.
            Tracked by GuardedToolset.call_tool() for observability.
        role: Permission level for this user — 'admin', 'user', or 'read_only'.
            Read by GuardedToolset.call_tool() to enforce the role gate.
    """

    config: AppConfig
    profile_manager: ProfileManager
    history_manager: HistoryManager
    user_profile: UserProfile
    guarded_toolsets: list[GuardedToolset] = field(default_factory=list)
    telegram_bot: Bot | None = None
    telegram_chat_id: int | None = None
    confirmed: bool = False
    called_tools: set[str] = field(default_factory=set)
    role: Literal["admin", "user", "read_only"] = "user"


def create_agent(
    toolsets: list[Any] | None = None,
    model: str = "openrouter:qwen/qwq-32b:free",
    retry_config: RetryConfig | None = None,
) -> Agent[AgentDeps, str]:
    """Create a PydanticAI agent with optional MCP toolsets.

    Args:
        toolsets: Optional list of FastMCPToolset instances for MCP servers.
            If None, the agent runs without MCP tools (useful for tests).
        model: PydanticAI model string to use. Defaults to qwen/qwq-32b:free.
            Override via the LLM_MODEL environment variable in production.
        retry_config: RetryConfig for exponential backoff on rate limits.
            If None, defaults are used (3 retries, 1.0s base delay, 30.0s max).

    Returns:
        Configured Agent instance with system prompt and tools registered.
    """
    from home_agent.models.retry_model import RetryingModel

    _retry_config = retry_config or RetryConfig()
    # Pass the model string directly so the provider (and its API-key check) is
    # resolved lazily on the first request, honouring defer_model_check behaviour.
    retrying_model = RetryingModel(
        model,
        max_retries=_retry_config.max_retries,
        base_delay=_retry_config.base_delay,
        max_delay=_retry_config.max_delay,
    )
    agent_instance: Agent[AgentDeps, str] = Agent(
        retrying_model,
        deps_type=AgentDeps,
        defer_model_check=True,
        toolsets=toolsets or [],
        history_processors=[sliding_window_processor(n=20)],
        system_prompt=SYSTEM_PROMPT,
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

    # Register Telegram rich UX tools
    agent_instance.tool(send_confirmation_keyboard)
    agent_instance.tool(send_poster_image)

    return agent_instance


