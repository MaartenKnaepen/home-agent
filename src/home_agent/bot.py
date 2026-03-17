"""Telegram bot wiring for home-agent.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
Business logic lives in agent.py. This module is Telegram wiring only.
"""

from __future__ import annotations

import logging
import socket
from collections.abc import Callable, Coroutine
from typing import Any

import httpx
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from telegram import Update
from telegram.constants import ChatAction, ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from home_agent.agent import AgentDeps
from home_agent.config import AppConfig
from home_agent.formatting import md_to_telegram_html
from home_agent.history import HistoryManager, convert_history_to_messages
from home_agent.mcp.guarded_toolset import GuardedToolset
from home_agent.profile import ProfileManager

logger = logging.getLogger(__name__)

_REJECTION_MESSAGE = "Sorry, you are not authorized to use this bot."


async def _invoke_agent(
    text: str,
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    agent: Agent[AgentDeps, str],
    guarded_toolsets: list[GuardedToolset],
    pending_confirmations: dict[int, tuple[int, str]],
) -> None:
    """Build AgentDeps, run the agent, and send the HTML-formatted reply.

    Shared agent invocation logic used by both text and voice message handlers.
    Handles profile loading, pending_confirmations consumption, agent.run(),
    history persistence, message splitting, and error handling.

    Args:
        text: The user's message text (typed or transcribed).
        update: The incoming Telegram update.
        context: The callback context provided by python-telegram-bot.
        config: Application configuration.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.
        guarded_toolsets: List of GuardedToolset instances.
        pending_confirmations: Shared dict keyed by user_id for inline-keyboard
            confirmations.
    """
    assert update.effective_user is not None

    user_id = update.effective_user.id
    chat_id = update.effective_chat.id if update.effective_chat else None

    # Load user profile, seeding language for new users from Telegram locale
    language_code = update.effective_user.language_code
    user_profile = await profile_manager.get(user_id, language_code=language_code)

    # Load and convert conversation history to PydanticAI ModelMessage objects
    raw_history = await history_manager.get_history(user_id=user_id)
    message_history = convert_history_to_messages(raw_history)

    # Read and consume any pending confirmation from the inline keyboard
    confirmed = False
    if user_id in pending_confirmations:
        _media_id, _media_type = pending_confirmations.pop(user_id)
        confirmed = True
        logger.info(
            "Consumed pending confirmation for user",
            extra={
                "user_id": user_id,
                "mediaId": _media_id,
                "mediaType": _media_type,
            },
        )

    deps = AgentDeps(
        config=config,
        profile_manager=profile_manager,
        history_manager=history_manager,
        user_profile=user_profile,
        guarded_toolsets=guarded_toolsets,
        telegram_bot=context.bot,
        telegram_chat_id=chat_id,
        confirmed=confirmed,
        called_tools=set(),
        role=user_profile.role,
    )

    async def _send_reply(text_to_send: str, **kwargs: Any) -> None:
        """Send a reply via message.reply_text or bot.send_message as appropriate."""
        if update.message is not None:
            await update.message.reply_text(text_to_send, **kwargs)
        elif chat_id is not None:
            await context.bot.send_message(chat_id=chat_id, text=text_to_send, **kwargs)

    try:
        result = await agent.run(text, deps=deps, message_history=message_history)
        reply = result.output
        logger.info("Agent output for user %d: %r", user_id, reply[:200] if reply else reply)
    except ModelHTTPError as exc:
        if exc.status_code == 429:
            logger.warning("Rate limit exhausted for user %d after retries", user_id)
            await _send_reply(
                "⏳ The AI service is temporarily busy. Please try again in a moment.",
                parse_mode=ParseMode.HTML,
            )
        else:
            logger.error("Model HTTP error for user %d: %s", user_id, exc, exc_info=True)
            await _send_reply(
                "Sorry, something went wrong processing your request.",
                parse_mode=ParseMode.HTML,
            )
        return
    except Exception as exc:
        logger.error("Agent.run() failed for user %d: %s", user_id, exc, exc_info=True)
        await _send_reply(
            "Sorry, something went wrong processing your request.",
            parse_mode=ParseMode.HTML,
        )
        return

    if not reply:
        logger.warning("Agent returned empty output for user %d", user_id)
        await _send_reply(
            "I completed the action but had no message to send back.",
            parse_mode=ParseMode.HTML,
        )
        return

    # Persist both turns
    await history_manager.save_message(user_id=user_id, role="user", content=text)
    await history_manager.save_message(user_id=user_id, role="assistant", content=reply)

    html_reply = md_to_telegram_html(reply)
    for chunk in _split_message(html_reply):
        await _send_reply(chunk, parse_mode=ParseMode.HTML)
    logger.debug("Sent agent reply to user %d", user_id)


def _split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long HTML message into chunks respecting tag boundaries.

    Splits by newline only — never inside an HTML tag — to prevent broken
    Telegram HTML parse_mode output. If a single line exceeds max_length,
    it is split at max_length (rare: only for extreme cases).

    Args:
        text: The HTML-formatted message text to split.
        max_length: Maximum characters per chunk. Defaults to 4096.

    Returns:
        A list of string chunks, each at most max_length characters.
    """
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0

    for line in text.splitlines(keepends=True):
        # If a single line is too long, flush current chunk and split the line
        while len(line) > max_length:
            if current:
                chunks.append("".join(current))
                current = []
                current_len = 0
            chunks.append(line[:max_length])
            line = line[max_length:]

        if current_len + len(line) > max_length:
            chunks.append("".join(current))
            current = []
            current_len = 0

        current.append(line)
        current_len += len(line)

    if current:
        chunks.append("".join(current))

    return chunks or [""]


async def _error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log all unhandled exceptions from the Telegram bot.

    Args:
        update: The update that caused the error (may be None).
        context: The callback context containing the exception.
    """
    logger.error("Unhandled exception in Telegram handler", exc_info=context.error)


def make_message_handler(
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    agent: Agent[AgentDeps, str],
    guarded_toolsets: list[GuardedToolset] | None = None,
    pending_confirmations: dict[int, tuple[int, str]] | None = None,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]:
    """Create a Telegram message handler closure that captures app config and managers.

    Args:
        config: Application configuration containing the allowed user whitelist.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.
        guarded_toolsets: Optional list of GuardedToolset instances. GuardedToolset
            is now stateless — no deps injection needed.
        pending_confirmations: Shared dict keyed by user_id for storing inline-keyboard
            confirmations between the callback handler and the message handler.

    Returns:
        An async handler coroutine compatible with python-telegram-bot.
    """
    _guarded_toolsets: list[GuardedToolset] = guarded_toolsets or []
    _pending_confirmations: dict[int, tuple[int, str]] = (
        pending_confirmations if pending_confirmations is not None else {}
    )

    async def handle_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle an incoming Telegram text message.

        Enforces the whitelist, sends a typing indicator, calls the agent,
        and persists both turns of the conversation.

        Args:
            update: The incoming Telegram update.
            context: The callback context provided by python-telegram-bot.
        """
        if update.effective_user is None or update.message is None:
            logger.warning("Received update with no user or message; ignoring.")
            return

        user_id = update.effective_user.id
        if user_id not in config.allowed_telegram_ids:
            logger.info("Rejected unauthorized user %d", user_id)
            await update.message.reply_text(_REJECTION_MESSAGE, parse_mode=ParseMode.HTML)
            return

        logger.debug("Authorized user %d sent a message", user_id)

        if update.effective_chat is not None:
            await update.effective_chat.send_action(action=ChatAction.TYPING)

        text = update.message.text or ""
        # Shared invocation path for text messages — handles profile loading, history,
        # agent execution, error handling, and reply formatting. Also used by voice and
        # callback handlers for consistency.
        await _invoke_agent(
            text, update, context,
            config, profile_manager, history_manager, agent,
            _guarded_toolsets, _pending_confirmations,
        )

    return handle_message


def make_voice_handler(
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    agent: Agent[AgentDeps, str],
    guarded_toolsets: list[GuardedToolset] | None = None,
) -> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]:
    """Create a Telegram voice message handler.

    Downloads the OGG voice file from Telegram, POSTs it to the ASR service for
    transcription, then forwards the transcribed text to the agent as a normal message.

    Args:
        config: Application configuration (contains asr_url and allowed_telegram_ids).
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.
        guarded_toolsets: Optional list of GuardedToolset instances.

    Returns:
        An async handler coroutine compatible with python-telegram-bot.
    """
    _guarded_toolsets: list[GuardedToolset] = guarded_toolsets or []
    # Voice handler has no shared pending_confirmations — always starts fresh.
    _pending_confirmations: dict[int, tuple[int, str]] = {}

    async def handle_voice(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle an incoming Telegram voice message.

        Rejects unauthorized users before any ASR call, downloads the OGG file,
        POSTs to the ASR service, and on success delegates to the normal agent flow.

        Args:
            update: The incoming Telegram update containing the voice message.
            context: The callback context provided by python-telegram-bot.
        """
        if update.effective_user is None or update.message is None:
            logger.warning("Received voice update with no user or message; ignoring.")
            return

        user_id = update.effective_user.id

        # Authorization check BEFORE any ASR call
        if user_id not in config.allowed_telegram_ids:
            logger.info("Rejected unauthorized voice user %d", user_id)
            await update.message.reply_text(_REJECTION_MESSAGE, parse_mode=ParseMode.HTML)
            return

        voice = update.message.voice
        if voice is None:
            return

        logger.debug(
            "Voice message received from user %d, duration=%ds",
            user_id,
            voice.duration,
        )

        # Show typing indicator during download + transcription
        if update.effective_chat is not None:
            await update.effective_chat.send_action(action=ChatAction.TYPING)

        try:
            # Download OGG voice file from Telegram
            voice_file = await context.bot.get_file(voice.file_id)
            ogg_bytes = await voice_file.download_as_bytearray()
            logger.debug("Downloaded voice OGG: %d bytes from user %d", len(ogg_bytes), user_id)

            # POST to ASR transcription service
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{config.asr_url}/transcribe",
                    files={"audio": ("voice.ogg", bytes(ogg_bytes), "audio/ogg")},
                )
                response.raise_for_status()
                transcribed_text: str = response.json()["text"].strip()

            logger.info(
                "Transcribed voice for user %d: %r",
                user_id,
                transcribed_text[:100] if transcribed_text else "",
            )

            if not transcribed_text:
                await update.message.reply_text(
                    "🎙️ I couldn't make out what you said. Please try again.",
                    parse_mode=ParseMode.HTML,
                )
                return

            # Reuse the shared invocation path after transcription. Ensures voice messages
            # flow through the same agent pipeline as text messages.
            await _invoke_agent(
                transcribed_text, update, context,
                config, profile_manager, history_manager, agent,
                _guarded_toolsets, _pending_confirmations,
            )

        except httpx.TimeoutException as exc:
            logger.warning("ASR timeout for user %d: %s", user_id, exc)
            await update.message.reply_text(
                "🎙️ Voice transcription timed out. Please try again or type your message.",
                parse_mode=ParseMode.HTML,
            )
        except httpx.HTTPStatusError as exc:
            logger.error(
                "ASR HTTP error for user %d: status=%d %s",
                user_id,
                exc.response.status_code,
                exc,
            )
            await update.message.reply_text(
                "🎙️ Voice transcription is temporarily unavailable. Please type your message instead.",
                parse_mode=ParseMode.HTML,
            )
        except httpx.RequestError as exc:
            logger.error("ASR request error for user %d: %s", user_id, exc)
            await update.message.reply_text(
                "🎙️ Voice transcription is temporarily unavailable. Please type your message instead.",
                parse_mode=ParseMode.HTML,
            )
        except Exception as exc:
            logger.error(
                "Voice handler failed for user %d: %s", user_id, exc, exc_info=True
            )
            await update.message.reply_text(
                "🎙️ Something went wrong processing your voice message.",
                parse_mode=ParseMode.HTML,
            )

    return handle_voice


def make_callback_handler(
    config: AppConfig,
    guarded_toolsets: list[GuardedToolset],
    agent: Agent[AgentDeps, str],
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    pending_confirmations: dict[int, tuple[int, str]] | None = None,
):
    """Create a Telegram CallbackQueryHandler for inline keyboard button presses.

    Handles callback data in the format 'confirm:{mediaId}:{mediaType}' and 'cancel'.
    On confirm: stores the confirmation in pending_confirmations keyed by user_id,
    then re-runs the agent with a synthetic message so it calls request_media.
    On cancel: removes any pending confirmation and sends a cancellation message.

    Args:
        config: Application configuration for the allowed user whitelist.
        guarded_toolsets: List of GuardedToolset instances (stateless — not mutated).
        agent: The PydanticAI agent instance to re-run on confirmation.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        pending_confirmations: Shared dict for storing per-user confirmations.
            If None, a new dict is created (isolated to this handler).

    Returns:
        An async handler coroutine compatible with python-telegram-bot.
    """
    _pending_confirmations: dict[int, tuple[int, str]] = (
        pending_confirmations if pending_confirmations is not None else {}
    )

    async def handle_callback(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle an inline keyboard callback query.

        Args:
            update: The incoming Telegram update containing the callback query.
            context: The callback context provided by python-telegram-bot.
        """
        query = update.callback_query
        if query is None:
            return
        await query.answer()  # Always answer to remove loading spinner

        if update.effective_user is None:
            return

        user_id = update.effective_user.id
        if user_id not in config.allowed_telegram_ids:
            await query.edit_message_text("Not authorized.")
            return

        data = query.data  # e.g. "confirm:27205:movie" or "cancel"

        if data and data.startswith("confirm:"):
            parts = data.split(":")
            if len(parts) != 3:  # noqa: PLR2004
                logger.warning("Invalid confirm callback data: %s", data)
                return
            _, media_id_str, media_type = parts
            try:
                media_id = int(media_id_str)
            except ValueError:
                logger.warning("Invalid mediaId in callback data: %s", media_id_str)
                return

            # Store confirmation keyed by user_id — handle_message will consume it
            _pending_confirmations[user_id] = (media_id, media_type)
            logger.info(
                "Stored pending confirmation",
                extra={"user_id": user_id, "mediaId": media_id, "mediaType": media_type},
            )

            await query.edit_message_text(
                "✅ Confirmed. Requesting now...",
                parse_mode=ParseMode.HTML,
            )

            # Reuse the shared invocation path — handles profile loading, history,
            # confirmation consumption (via pending_confirmations), agent execution,
            # error handling, and reply formatting. The pending confirmation was stored
            # above and will be consumed by _invoke_agent() at the start of its run.
            await _invoke_agent(
                "confirmed, please proceed with the request",
                update, context,
                config, profile_manager, history_manager, agent,
                guarded_toolsets, _pending_confirmations,
            )

        elif data == "cancel":
            # Remove any pending confirmation for this user
            _pending_confirmations.pop(user_id, None)
            await query.edit_message_text("❌ Cancelled.")
            logger.info("User %d cancelled the media request", user_id)

    return handle_callback


def create_application(
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    agent: Agent[AgentDeps, str],
    guarded_toolsets: list[GuardedToolset] | None = None,
) -> Application:
    """Build and return a configured Telegram Application.

    Does NOT start polling — the caller is responsible for that.

    Args:
        config: Application configuration used to wire the bot token and handlers.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.
        guarded_toolsets: Optional list of GuardedToolset instances.

    Returns:
        A fully configured :class:`telegram.ext.Application` instance.
    """
    _guarded_toolsets = guarded_toolsets or []
    # Shared dict — both handlers share the same reference so confirmations
    # written by the callback handler are visible to the message handler.
    pending_confirmations: dict[int, tuple[int, str]] = {}

    token = config.telegram_bot_token.get_secret_value()

    # Configure TCP keepalive on the Telegram HTTP connection pool.
    # Without this, idle connections are silently closed by Telegram's servers
    # (or intermediate NAT devices) after a few seconds. When the agent takes
    # several seconds to run, the next reply_text() call finds the pooled
    # connection stale and times out with ConnectTimeout.
    # Keepalive probes keep the connection alive and detect closure immediately
    # so httpx can open a fresh connection without a full timeout penalty.
    request = HTTPXRequest(
        connection_pool_size=8,
        socket_options=[
            (socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1),    # Enable TCP keepalive
            (socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10),  # Start probing after 10s idle
            (socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5),  # Probe every 5s
            (socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3),    # Give up after 3 failed probes
        ],
    )
    app: Application = Application.builder().token(token).request(request).build()
    handler = make_message_handler(
        config,
        profile_manager,
        history_manager,
        agent,
        _guarded_toolsets,
        pending_confirmations,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
    voice_handler = make_voice_handler(
        config,
        profile_manager,
        history_manager,
        agent,
        _guarded_toolsets,
    )
    app.add_handler(MessageHandler(filters.VOICE, voice_handler))
    callback_handler = make_callback_handler(
        config,
        _guarded_toolsets,
        agent,
        profile_manager,
        history_manager,
        pending_confirmations,
    )
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_error_handler(_error_handler)
    logger.info("Telegram application configured with whitelist: %s", config.allowed_telegram_ids)
    return app
