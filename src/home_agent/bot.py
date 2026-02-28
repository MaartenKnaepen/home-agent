"""Telegram bot wiring for home-agent.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
Business logic lives in agent.py. This module is Telegram wiring only.
"""

from __future__ import annotations

import logging

from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelHTTPError
from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from home_agent.agent import AgentDeps
from home_agent.config import AppConfig
from home_agent.history import HistoryManager, convert_history_to_messages
from home_agent.profile import ProfileManager

logger = logging.getLogger(__name__)

_REJECTION_MESSAGE = "Sorry, you are not authorized to use this bot."


def _split_message(text: str, max_length: int = 4096) -> list[str]:
    """Split a long message into chunks that fit within Telegram's message size limit.

    Splits by newlines first, accumulating lines until a chunk would exceed
    max_length. If a single line exceeds max_length, it is split at the boundary.

    Args:
        text: The message text to split.
        max_length: Maximum number of characters per chunk. Defaults to 4096.

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
):
    """Create a Telegram message handler closure that captures app config and managers.

    Args:
        config: Application configuration containing the allowed user whitelist.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.

    Returns:
        An async handler coroutine compatible with python-telegram-bot.
    """

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
            await update.message.reply_text(_REJECTION_MESSAGE)
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

        deps = AgentDeps(
            config=config,
            profile_manager=profile_manager,
            history_manager=history_manager,
            user_profile=user_profile,
        )

        try:
            result = await agent.run(text, deps=deps, message_history=message_history)
            reply = result.output
            logger.info("Agent output for user %d: %r", user_id, reply[:200] if reply else reply)
        except ModelHTTPError as exc:
            if exc.status_code == 429:
                logger.warning("Rate limit exhausted for user %d after retries", user_id)
                await update.message.reply_text(
                    "⏳ The AI service is temporarily busy. Please try again in a moment."
                )
            else:
                logger.error("Model HTTP error for user %d: %s", user_id, exc, exc_info=True)
                await update.message.reply_text(
                    "Sorry, something went wrong processing your request."
                )
            return
        except Exception as exc:
            logger.error("Agent.run() failed for user %d: %s", user_id, exc, exc_info=True)
            await update.message.reply_text("Sorry, something went wrong processing your request.")
            return

        if not reply:
            logger.warning("Agent returned empty output for user %d", user_id)
            await update.message.reply_text("I completed the action but had no message to send back.")
            return

        # Persist both turns
        await history_manager.save_message(user_id=user_id, role="user", content=text)
        await history_manager.save_message(user_id=user_id, role="assistant", content=reply)

        for chunk in _split_message(reply):
            await update.message.reply_text(chunk)
        logger.debug("Sent agent reply to user %d", user_id)

    return handle_message


def create_application(
    config: AppConfig,
    profile_manager: ProfileManager,
    history_manager: HistoryManager,
    agent: Agent[AgentDeps, str],
) -> Application:
    """Build and return a configured Telegram Application.

    Does NOT start polling — the caller is responsible for that.

    Args:
        config: Application configuration used to wire the bot token and handlers.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history persistence.
        agent: The PydanticAI agent instance to use for inference.

    Returns:
        A fully configured :class:`telegram.ext.Application` instance.
    """
    token = config.telegram_bot_token.get_secret_value()
    app: Application = Application.builder().token(token).build()
    handler = make_message_handler(config, profile_manager, history_manager, agent)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
    app.add_error_handler(_error_handler)
    logger.info("Telegram application configured with whitelist: %s", config.allowed_telegram_ids)
    return app
