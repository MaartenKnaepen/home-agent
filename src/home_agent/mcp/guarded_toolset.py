"""GuardedToolset — MCP tool call middleware.

Wraps a FastMCPToolset and intercepts all tool calls to enforce quality,
role, and confirmation gates before forwarding to the real toolset.

This toolset is stateless — all per-user state is read from ctx.deps
(AgentDeps), which PydanticAI creates fresh per message per user. This
makes GuardedToolset safe for concurrent multi-user access.

Adheres to home-agent coding standards: type hints, Google-style docstrings,
async-first.
"""

from __future__ import annotations

import logging
from typing import Any

from pydantic_ai import RunContext
from pydantic_ai.toolsets.abstract import AbstractToolset, ToolsetTool

logger = logging.getLogger(__name__)


class GuardedToolset(AbstractToolset[Any]):
    """Wraps a FastMCPToolset and enforces gates on MCP tool calls.

    Properly subclasses AbstractToolset so PydanticAI treats it as a first-class
    toolset. Delegates get_tools() and lifecycle (__aenter__/__aexit__) to the
    inner toolset transparently. Intercepts call_tool() to apply quality, role,
    and confirmation gates before forwarding.

    This class is intentionally stateless — it stores only inner_toolset (set
    once at creation time). All per-user state (confirmed, called_tools, role)
    is read from ctx.deps (AgentDeps), which is created fresh per message so
    concurrent users cannot interfere with each other.

    Gate failures return plain English error strings — the LLM reads these as
    tool results and must respond accordingly.

    Attributes:
        inner_toolset: The underlying FastMCPToolset to forward calls to.
    """

    def __init__(self, inner_toolset: Any) -> None:
        """Initialise with the inner FastMCPToolset to wrap.

        Args:
            inner_toolset: The FastMCPToolset instance to intercept calls for.
        """
        self.inner_toolset = inner_toolset

    @property
    def id(self) -> str | None:
        """Delegate id to inner toolset."""
        return self.inner_toolset.id

    async def __aenter__(self) -> GuardedToolset:
        """Enter context — delegate to inner toolset to set up MCP connections."""
        await self.inner_toolset.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        """Exit context — delegate to inner toolset to tear down MCP connections."""
        return await self.inner_toolset.__aexit__(*args)

    async def get_tools(self, ctx: RunContext[Any]) -> dict[str, ToolsetTool[Any]]:
        """Delegate tool listing to the inner toolset.

        Args:
            ctx: The run context.

        Returns:
            Dict of tool name to ToolsetTool, unchanged from the inner toolset.
        """
        return await self.inner_toolset.get_tools(ctx)

    async def call_tool(
        self,
        name: str,
        tool_args: dict[str, Any],
        ctx: RunContext[Any],
        tool: ToolsetTool[Any],
    ) -> Any:
        """Intercept a tool call, apply guards, then forward to inner toolset.

        All state is read from ctx.deps — the per-user, per-message AgentDeps
        created fresh for each message. This makes GuardedToolset safe for
        concurrent multi-user access.

        Gate order:
        0. Role gate — ``read_only`` users cannot call ``request_media``.
        1. Quality gate — ``request_media`` for a movie requires
           ``movie_quality`` to be set; for TV requires ``series_quality``.
        2. Confirmation gate — if ``confirmation_mode == 'always'`` and
           ``ctx.deps.confirmed`` is False, block and ask for confirmation.
        3. Pass-through — all other tools (and ``request_media`` once gates
           pass) are forwarded to the inner toolset.

        After a successful ``request_media`` call, ``ctx.deps.confirmed`` is
        reset so the next request requires fresh confirmation.

        Args:
            name: Name of the MCP tool being called.
            tool_args: Arguments dict passed to the tool.
            ctx: The run context containing per-user AgentDeps.
            tool: The tool definition from get_tools().

        Returns:
            Tool result, or a plain English gate error string.
        """
        if name == "request_media":
            # Gate 0: role gate — read_only users cannot request media
            role = getattr(ctx.deps, "role", "user")
            if role == "read_only":
                msg = "You do not have permission to request media."
                logger.warning(
                    "request_media blocked by role gate",
                    extra={"reason": "read_only_role"},
                )
                return msg

            # Gate 1: quality gate
            media_type = tool_args.get("mediaType")
            prefs = ctx.deps.user_profile.media_preferences

            if media_type == "movie" and not prefs.movie_quality:
                error_msg = (
                    "STOP: movie_quality not set. Ask the user: "
                    "'Do you prefer 4K or 1080p for movies?' "
                    "Then call set_movie_quality with their answer."
                )
                logger.warning(
                    "request_media blocked by quality gate",
                    extra={
                        "reason": "movie_quality_not_set",
                        "error_msg": error_msg,
                    },
                )
                return error_msg

            if media_type == "tv" and not prefs.series_quality:
                error_msg = (
                    "STOP: series_quality not set. Ask the user: "
                    "'Do you prefer 4K or 1080p for series?' "
                    "Then call set_series_quality with their answer."
                )
                logger.warning(
                    "request_media blocked by quality gate",
                    extra={
                        "reason": "series_quality_not_set",
                        "error_msg": error_msg,
                    },
                )
                return error_msg

            # Gate 2: confirmation gate
            confirmation_mode = ctx.deps.user_profile.confirmation_mode
            confirmed = getattr(ctx.deps, "confirmed", False)

            if confirmation_mode == "always" and not confirmed:
                error_msg = (
                    "STOP: Confirmation required. Show the user exactly what "
                    "you're about to request (title, year, quality) and call "
                    "confirm_request with mediaId and mediaType after they approve."
                )
                logger.warning(
                    "request_media blocked by confirmation gate",
                    extra={
                        "reason": "confirmation_required",
                        "error_msg": error_msg,
                    },
                )
                return error_msg

        # All other tools (and request_media once gates pass) go through
        logger.debug("Tool call allowed", extra={"tool": name})
        result = await self.inner_toolset.call_tool(name, tool_args, ctx, tool)

        # Track successful calls in per-user AgentDeps
        if hasattr(ctx.deps, "called_tools"):
            ctx.deps.called_tools.add(name)

        # Reset confirmed in AgentDeps after successful request_media
        if name == "request_media" and hasattr(ctx.deps, "confirmed"):
            ctx.deps.confirmed = False
            logger.info("request_media succeeded, confirmed reset in AgentDeps")

        return result
