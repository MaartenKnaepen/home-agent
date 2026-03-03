"""Tests for src/home_agent/tools/telegram_tools.py.

Tests for send_confirmation_keyboard and send_poster_image agent tools.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic_ai import RunContext
from telegram import InlineKeyboardMarkup

from home_agent.agent import AgentDeps
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager, UserProfile
from home_agent.tools.telegram_tools import (
    TMDB_IMAGE_BASE,
    send_confirmation_keyboard,
    send_poster_image,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_deps(
    mock_config: AppConfig,
    test_db: Path,
    telegram_bot: object | None = None,
    telegram_chat_id: int | None = 12345,
) -> AgentDeps:
    """Build AgentDeps with optional telegram_bot for tool testing."""
    profile = UserProfile(
        user_id=123,
        name="Test User",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )
    return AgentDeps(
        config=mock_config,
        profile_manager=ProfileManager(test_db),
        history_manager=HistoryManager(test_db),
        user_profile=profile,
        telegram_bot=telegram_bot,  # type: ignore[arg-type]
        telegram_chat_id=telegram_chat_id,
    )


def make_run_context(deps: AgentDeps) -> RunContext[AgentDeps]:
    """Create a minimal RunContext with given deps."""
    ctx = MagicMock(spec=RunContext)
    ctx.deps = deps
    return ctx


# ---------------------------------------------------------------------------
# send_confirmation_keyboard tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_confirmation_keyboard_sends_message(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_confirmation_keyboard calls bot.send_message with InlineKeyboardMarkup."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_confirmation_keyboard(
        ctx,
        mediaId=27205,
        mediaType="movie",
        title="Troy",
        year=2004,
        quality="4K",
    )

    mock_bot.send_message.assert_called_once()
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert call_kwargs["chat_id"] == 12345
    assert "Troy" in call_kwargs["text"]
    assert "4K" in call_kwargs["text"]
    assert isinstance(call_kwargs["reply_markup"], InlineKeyboardMarkup)
    assert "keyboard sent" in result.lower() or "Confirmation" in result


@pytest.mark.asyncio
async def test_send_confirmation_keyboard_callback_data_format(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Callback data follows 'confirm:{mediaId}:{mediaType}' format."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    await send_confirmation_keyboard(
        ctx,
        mediaId=42,
        mediaType="tv",
        title="Breaking Bad",
        year=2008,
        quality="1080p",
    )

    call_kwargs = mock_bot.send_message.call_args.kwargs
    keyboard: InlineKeyboardMarkup = call_kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    # First button: confirm
    assert buttons[0].callback_data == "confirm:42:tv"
    # Second button: cancel
    assert buttons[1].callback_data == "cancel"


@pytest.mark.asyncio
async def test_send_confirmation_keyboard_yes_no_labels(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Confirm keyboard has ✅ Yes and ❌ No buttons."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    await send_confirmation_keyboard(
        ctx, mediaId=1, mediaType="movie", title="Test", year=None, quality="1080p"
    )

    keyboard: InlineKeyboardMarkup = mock_bot.send_message.call_args.kwargs["reply_markup"]
    buttons = keyboard.inline_keyboard[0]
    assert "Yes" in buttons[0].text
    assert "No" in buttons[1].text


@pytest.mark.asyncio
async def test_send_confirmation_keyboard_no_year(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_confirmation_keyboard handles year=None gracefully."""
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_confirmation_keyboard(
        ctx, mediaId=1, mediaType="movie", title="Unknown", year=None, quality="1080p"
    )

    assert result is not None
    # No year in parentheses should appear
    call_kwargs = mock_bot.send_message.call_args.kwargs
    assert "(None)" not in call_kwargs["text"]


@pytest.mark.asyncio
async def test_send_confirmation_keyboard_no_bot_returns_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_confirmation_keyboard returns fallback text when bot is None."""
    deps = make_deps(mock_config, test_db, telegram_bot=None)
    ctx = make_run_context(deps)

    result = await send_confirmation_keyboard(
        ctx, mediaId=1, mediaType="movie", title="Troy", year=2004, quality="4K"
    )

    assert "Troy" in result
    # No exception should be raised
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# send_poster_image tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_poster_image_constructs_tmdb_url(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image constructs correct TMDB CDN URL from posterPath."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    await send_poster_image(ctx, posterPath="/abc123.jpg")

    mock_bot.send_photo.assert_called_once()
    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert call_kwargs["photo"] == f"{TMDB_IMAGE_BASE}/abc123.jpg"
    assert call_kwargs["chat_id"] == 12345


@pytest.mark.asyncio
async def test_send_poster_image_none_path_returns_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image returns fallback when posterPath is None."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_poster_image(ctx, posterPath=None)

    mock_bot.send_photo.assert_not_called()
    assert "No poster" in result or "available" in result.lower()


@pytest.mark.asyncio
async def test_send_poster_image_empty_path_returns_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image returns fallback when posterPath is empty string."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_poster_image(ctx, posterPath="")

    mock_bot.send_photo.assert_not_called()
    assert isinstance(result, str)


@pytest.mark.asyncio
async def test_send_poster_image_send_photo_failure_returns_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image falls back gracefully when send_photo raises."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock(side_effect=Exception("Network error"))

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_poster_image(ctx, posterPath="/poster.jpg")

    # Should not raise; should return fallback string
    assert "unavailable" in result.lower() or "could not" in result.lower()


@pytest.mark.asyncio
async def test_send_poster_image_with_caption(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image passes caption to send_photo."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    await send_poster_image(ctx, posterPath="/poster.jpg", caption="<b>Troy</b> (2004)")

    call_kwargs = mock_bot.send_photo.call_args.kwargs
    assert call_kwargs["caption"] == "<b>Troy</b> (2004)"


@pytest.mark.asyncio
async def test_send_poster_image_no_bot_returns_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image returns fallback when bot is None."""
    deps = make_deps(mock_config, test_db, telegram_bot=None)
    ctx = make_run_context(deps)

    result = await send_poster_image(ctx, posterPath="/poster.jpg")

    assert isinstance(result, str)
    assert "could not" in result.lower() or "no bot" in result.lower()


@pytest.mark.asyncio
async def test_send_poster_image_returns_confirmation(
    mock_config: AppConfig, test_db: Path
) -> None:
    """send_poster_image returns confirmation string on success."""
    mock_bot = MagicMock()
    mock_bot.send_photo = AsyncMock()

    deps = make_deps(mock_config, test_db, telegram_bot=mock_bot)
    ctx = make_run_context(deps)

    result = await send_poster_image(ctx, posterPath="/poster.jpg")

    assert "sent" in result.lower() or "poster" in result.lower()
