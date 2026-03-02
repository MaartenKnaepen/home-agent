"""GuardedToolset — MCP tool call middleware.

Wraps a FastMCPToolset and intercepts all tool calls to enforce quality
and confirmation gates before forwarding to the real toolset.

Adheres to home-agent coding standards: type hints, Google-style docstrings,
async-first.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class GuardedToolset:
    """Wraps a FastMCPToolset and enforces gates on MCP tool calls.

    Gates are checked in order before any tool call is forwarded to the inner
    toolset.  Gate failures return plain English error strings — the LLM reads
    these as tool results and must respond accordingly.

    Attributes:
        inner_toolset: The underlying FastMCPToolset to forward calls to.
        deps: AgentDeps injected before each agent.run() call. None until set.
        confirmed: True when confirm_request has been called for this turn.
        called_tools: Set of tool names called successfully in this turn.
    """

    def __init__(self, inner_toolset: Any) -> None:
        """Initialise with the inner FastMCPToolset to wrap.

        Args:
            inner_toolset: The FastMCPToolset instance to intercept calls for.
        """
        self.inner_toolset = inner_toolset
        self.deps: Any | None = None
        self.confirmed: bool = False
        self.called_tools: set[str] = set()

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """Intercept a tool call, apply guards, then forward to inner toolset.

        Gate order:
        1. Quality gate — ``request_media`` for a movie requires
           ``movie_quality`` to be set; for TV requires ``series_quality``.
        2. Confirmation gate — if ``confirmation_mode == 'always'`` and
           ``confirmed`` is False, block and ask for confirmation.
        3. Pass-through — all other tools (and ``request_media`` once gates
           pass) are forwarded to the inner toolset.

        After a successful ``request_media`` call the ``confirmed`` flag is
        reset so the next request requires fresh confirmation.

        Args:
            name: Name of the MCP tool being called.
            arguments: Arguments dict passed to the tool.

        Returns:
            Tool result string, or a plain English gate error string.
        """
        # Guard 1: request_media quality check
        if name == "request_media":
            media_type = arguments.get("mediaType")
            if media_type == "movie" and not self._has_movie_quality():
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

            if media_type == "tv" and not self._has_series_quality():
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

        # Guard 2: request_media confirmation check
        if name == "request_media":
            if self._needs_confirmation() and not self.confirmed:
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
        result = await self.inner_toolset.call_tool(name, arguments)

        # Track successful calls and reset confirmation after request_media
        self.called_tools.add(name)
        if name == "request_media":
            self.confirmed = False
            logger.info("request_media succeeded, confirmation flag reset")

        return result

    def set_confirmed(self, mediaId: int, mediaType: str) -> None:  # noqa: N803
        """Set the confirmed flag, signalling user approval for this turn.

        Called by the ``confirm_request`` agent tool after the user approves.

        Args:
            mediaId: TMDB ID of the media being confirmed.
            mediaType: Media type — ``"movie"`` or ``"tv"``.
        """
        self.confirmed = True
        logger.info(
            "confirm_request called",
            extra={"mediaId": mediaId, "mediaType": mediaType},
        )

    def _has_movie_quality(self) -> bool:
        """Return True if movie_quality is set in the user profile.

        Returns:
            True when ``deps`` is available and movie_quality is not None.
        """
        if not self.deps:
            return False
        return self.deps.user_profile.media_preferences.movie_quality is not None

    def _has_series_quality(self) -> bool:
        """Return True if series_quality is set in the user profile.

        Returns:
            True when ``deps`` is available and series_quality is not None.
        """
        if not self.deps:
            return False
        return self.deps.user_profile.media_preferences.series_quality is not None

    def _needs_confirmation(self) -> bool:
        """Return True if the user profile requires confirmation before requests.

        Returns:
            True when ``deps`` is available and confirmation_mode is ``"always"``.
        """
        if not self.deps:
            return False
        return self.deps.user_profile.confirmation_mode == "always"
