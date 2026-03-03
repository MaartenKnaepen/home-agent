"""Telegram bot wiring for home-agent.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
Business logic lives in agent.py. This module is Telegram wiring only.
"""

from __future__ import annotations

import logging

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

from home_agent.agent import AgentDeps
from home_agent.config import AppConfig
from home_agent.formatting import md_to_telegram_html
from home_agent.history import HistoryManager, convert_history_to_messages
from home_agent.mcp.guarded_toolset import GuardedToolset
from home_agent.profile import ProfileManager

logger = logging.getLogger(__name__)

_REJECTION_MESSAGE = "Sorry, you are not authorized to use this bot."


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
):
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

        # Load user profile, seeding language for new users from Telegram locale
        language_code = update.effective_user.language_code
        user_profile = await profile_manager.get(user_id, language_code=language_code)

        # Load and convert conversation history to PydanticAI ModelMessage objects
        raw_history = await history_manager.get_history(user_id=user_id)
        message_history = convert_history_to_messages(raw_history)

        # Read and consume any pending confirmation from the inline keyboard
        confirmed = False
        if user_id in _pending_confirmations:
            _media_id, _media_type = _pending_confirmations.pop(user_id)
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
            guarded_toolsets=_guarded_toolsets,
            telegram_bot=context.bot,
            telegram_chat_id=update.effective_chat.id if update.effective_chat else None,
            confirmed=confirmed,
            called_tools=set(),
            role=user_profile.role,
        )

        try:
            result = await agent.run(text, deps=deps, message_history=message_history)
            reply = result.output
            logger.info("Agent output for user %d: %r", user_id, reply[:200] if reply else reply)
        except ModelHTTPError as exc:
            if exc.status_code == 429:
                logger.warning("Rate limit exhausted for user %d after retries", user_id)
                await update.message.reply_text(
                    "⏳ The AI service is temporarily busy. Please try again in a moment.",
                    parse_mode=ParseMode.HTML,
                )
            else:
                logger.error("Model HTTP error for user %d: %s", user_id, exc, exc_info=True)
                await update.message.reply_text(
                    "Sorry, something went wrong processing your request.",
                    parse_mode=ParseMode.HTML,
                )
            return
        except Exception as exc:
            logger.error("Agent.run() failed for user %d: %s", user_id, exc, exc_info=True)
            await update.message.reply_text(
                "Sorry, something went wrong processing your request.",
                parse_mode=ParseMode.HTML,
            )
            return

        if not reply:
            logger.warning("Agent returned empty output for user %d", user_id)
            await update.message.reply_text(
                "I completed the action but had no message to send back.",
                parse_mode=ParseMode.HTML,
            )
            return

        # Persist both turns
        await history_manager.save_message(user_id=user_id, role="user", content=text)
        await history_manager.save_message(user_id=user_id, role="assistant", content=reply)

        html_reply = md_to_telegram_html(reply)
        for chunk in _split_message(html_reply):
            await update.message.reply_text(chunk, parse_mode=ParseMode.HTML)
        logger.debug("Sent agent reply to user %d", user_id)

    return handle_message


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

            # Re-run agent with a synthetic "yes confirmed" message so it calls
            # request_media now that the confirmation gate will be unblocked.
            language_code = update.effective_user.language_code
            user_profile = await profile_manager.get(user_id, language_code=language_code)
            raw_history = await history_manager.get_history(user_id=user_id)
            message_history = convert_history_to_messages(raw_history)

            # Consume the pending confirmation immediately for this re-run
            confirmed = False
            if user_id in _pending_confirmations:
                _pending_confirmations.pop(user_id)
                confirmed = True

            deps = AgentDeps(
                config=config,
                profile_manager=profile_manager,
                history_manager=history_manager,
                user_profile=user_profile,
                guarded_toolsets=guarded_toolsets,
                telegram_bot=context.bot,
                telegram_chat_id=update.effective_chat.id if update.effective_chat else None,
                confirmed=confirmed,
                called_tools=set(),
                role=user_profile.role,
            )

            try:
                result = await agent.run(
                    "confirmed, please proceed with the request",
                    deps=deps,
                    message_history=message_history,
                )
                reply = result.output
                if reply:
                    await history_manager.save_message(
                        user_id=user_id, role="assistant", content=reply
                    )
                    html_reply = md_to_telegram_html(reply)
                    if update.effective_chat:
                        for chunk in _split_message(html_reply):
                            await context.bot.send_message(
                                chat_id=update.effective_chat.id,
                                text=chunk,
                                parse_mode=ParseMode.HTML,
                            )
            except Exception as exc:
                logger.error(
                    "Agent re-run after confirm failed for user %d: %s",
                    user_id,
                    exc,
                    exc_info=True,
                )
                if update.effective_chat:
                    await context.bot.send_message(
                        chat_id=update.effective_chat.id,
                        text="Sorry, something went wrong processing your request.",
                        parse_mode=ParseMode.HTML,
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
    app: Application = Application.builder().token(token).build()
    handler = make_message_handler(
        config,
        profile_manager,
        history_manager,
        agent,
        _guarded_toolsets,
        pending_confirmations,
    )
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
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
