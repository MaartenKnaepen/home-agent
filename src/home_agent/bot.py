"""Telegram bot wiring for home-agent.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
Business logic lives in agent.py (step 1.6). This module is Telegram wiring only.
"""

from __future__ import annotations

import logging

from telegram import Update
from telegram.constants import ChatAction
from telegram.ext import (
    Application,
    ContextTypes,
    MessageHandler,
    filters,
)

from home_agent.config import AppConfig

logger = logging.getLogger(__name__)

_REJECTION_MESSAGE = "Sorry, you are not authorized to use this bot."


def make_message_handler(config: AppConfig):
    """Create a Telegram message handler closure that captures app config.

    Args:
        config: Application configuration containing the allowed user whitelist.

    Returns:
        An async handler coroutine compatible with python-telegram-bot.
    """

    async def handle_message(
        update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Handle an incoming Telegram text message.

        Enforces the whitelist, sends a typing indicator, then replies with a
        stub response (will be replaced by agent call in step 1.6).

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
        reply = f"[Agent stub] You said: {text}"
        await update.message.reply_text(reply)
        logger.debug("Sent stub reply to user %d", user_id)

    return handle_message


def create_application(config: AppConfig) -> Application:
    """Build and return a configured Telegram Application.

    Does NOT start polling — the caller is responsible for that.

    Args:
        config: Application configuration used to wire the bot token and handlers.

    Returns:
        A fully configured :class:`telegram.ext.Application` instance.
    """
    token = config.telegram_bot_token.get_secret_value()
    app: Application = Application.builder().token(token).build()
    handler = make_message_handler(config)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handler))
    logger.info("Telegram application configured with whitelist: %s", config.allowed_telegram_ids)
    return app


def run_bot(config: AppConfig) -> None:
    """Build the Telegram application and start polling for updates.

    Blocks until the bot is stopped (e.g. via Ctrl-C).

    Args:
        config: Application configuration.
    """
    logger.info("Starting Telegram bot polling…")
    create_application(config).run_polling()
