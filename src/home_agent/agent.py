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
) -> Agent[AgentDeps, str]:
    """Create a PydanticAI agent with optional MCP toolsets.

    Args:
        toolsets: Optional list of FastMCPToolset instances for MCP servers.
            If None, the agent runs without MCP tools (useful for tests).
        model: PydanticAI model string to use. Defaults to qwen/qwq-32b:free.
            Override via the LLM_MODEL environment variable in production.

    Returns:
        Configured Agent instance with system prompt and tools registered.
    """
    agent_instance: Agent[AgentDeps, str] = Agent(
        model,
        deps_type=AgentDeps,
        defer_model_check=True,
        toolsets=toolsets or [],
        history_processors=[sliding_window_processor(n=20)],
        system_prompt=(
            "You are a helpful home server assistant. "
            "You help the user manage their home server services including media, monitoring, and more. "
            "Always be concise and friendly. "
            "For destructive or irreversible actions, always ask for confirmation before proceeding."
        ),
    )

    @agent_instance.system_prompt(dynamic=True)
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
        movie_q = prefs.movie_quality or "NOT SET — ask before first movie request"
        series_q = prefs.series_quality or "NOT SET — ask before first series request"
        notes_part = ("Notes about this user: " + "; ".join(profile.notes)) if profile.notes else ""
        return (
            f"{name_part} "
            f"Always reply in {profile.reply_language}. "
            f"Confirmation mode: {profile.confirmation_mode}. "
            f"Movie quality preference: {movie_q}. "
            f"Series quality preference: {series_q}. "
            f"{notes_part}"
        ).strip()

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
        profile.notes.append(note)
        await ctx.deps.profile_manager.save(profile)
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
