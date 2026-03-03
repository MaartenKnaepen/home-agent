"""Telegram-specific agent tools for rich UX.

Provides tools for sending inline keyboards and poster images from the agent.
These tools are one-way: they send a Telegram message and return a string
confirmation to the agent.

Adheres to home-agent coding standards: type hints, Google-style docstrings,
async-first.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode

from pydantic_ai import RunContext

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p/w500"


async def send_confirmation_keyboard(
    ctx: RunContext[Any],
    mediaId: int,  # noqa: N803
    mediaType: str,  # noqa: N803
    title: str,
    year: int | None,
    quality: str,
) -> str:
    """Send an inline keyboard asking the user to confirm a media request.

    Call this instead of asking for confirmation in plain text. The user's
    button press will directly trigger the request without another LLM call.

    Args:
        ctx: Runtime context with dependencies.
        mediaId: TMDB ID of the media to request.
        mediaType: "movie" or "tv".
        title: Human-readable title to show in the confirmation message.
        year: Release year to show in the confirmation message. None if unknown.
        quality: Quality string to show (e.g. "4K", "1080p").

    Returns:
        Confirmation that the keyboard was sent.
    """
    year_str = f" ({year})" if year else ""
    text = (
        f"🎬 <b>{title}{year_str}</b>\n"
        f"Quality: <b>{quality}</b>\n\n"
        f"Request this?"
    )
    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Yes", callback_data=f"confirm:{mediaId}:{mediaType}"
                ),
                InlineKeyboardButton("❌ No", callback_data="cancel"),
            ]
        ]
    )

    bot = ctx.deps.telegram_bot
    chat_id = ctx.deps.telegram_chat_id

    if bot is None or chat_id is None:
        logger.warning(
            "send_confirmation_keyboard called without telegram_bot/chat_id in deps"
        )
        return (
            f"Could not send confirmation keyboard (no bot context). "
            f"Please confirm '{title}{year_str}' in {quality} by replying yes/no."
        )

    await bot.send_message(
        chat_id=chat_id,
        text=text,
        parse_mode=ParseMode.HTML,
        reply_markup=keyboard,
    )

    logger.info(
        "Sent confirmation keyboard",
        extra={"mediaId": mediaId, "mediaType": mediaType, "title": title},
    )
    return (
        f"Confirmation keyboard sent for '{title}{year_str}' in {quality}. "
        f"Waiting for user to press a button."
    )


async def send_poster_image(
    ctx: RunContext[Any],
    posterPath: str | None,  # noqa: N803
    caption: str | None = None,
) -> str:
    """Send a movie or TV show poster image to the user.

    Constructs the full TMDB CDN URL from the partial posterPath returned by
    get_media_details. Telegram downloads the image directly from TMDB's CDN
    (publicly reachable). Falls back to text if posterPath is None or send_photo fails.

    Args:
        ctx: Runtime context with dependencies.
        posterPath: Partial TMDB image path (e.g. '/abc123.jpg'). If None, no image is sent.
        caption: Optional caption to display below the image.

    Returns:
        Confirmation that the image was sent, or a fallback message.
    """
    if not posterPath:
        logger.debug("send_poster_image called with no posterPath — skipping")
        return "No poster image available."

    url = f"{TMDB_IMAGE_BASE}{posterPath}"
    bot = ctx.deps.telegram_bot
    chat_id = ctx.deps.telegram_chat_id

    if bot is None or chat_id is None:
        logger.warning(
            "send_poster_image called without telegram_bot/chat_id in deps"
        )
        return "Could not send poster image (no bot context)."

    try:
        await bot.send_photo(
            chat_id=chat_id,
            photo=url,
            caption=caption,
            parse_mode=ParseMode.HTML if caption else None,
        )
        logger.info("Sent poster image", extra={"url": url})
        return "Poster image sent."
    except Exception as e:
        logger.warning(
            "send_poster_image failed", extra={"url": url, "error": str(e)}
        )
        return "Could not send poster image (unavailable)."
