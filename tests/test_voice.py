"""Tests for voice message handling in src/home_agent/bot.py.

Covers authorization, typing indicator, ASR HTTP interaction, transcription
result routing, and error fallback paths.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from telegram import Chat, Message, Update, User, Voice
from telegram.constants import ChatAction, ParseMode

from home_agent.bot import make_voice_handler
from home_agent.config import AppConfig
from home_agent.history import HistoryManager
from home_agent.profile import ProfileManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_voice_update(user_id: int = 123, duration: int = 5) -> tuple[Update, MagicMock]:
    """Create a mock Telegram Update containing a voice message.

    Args:
        user_id: Telegram user ID of the sender.
        duration: Voice message duration in seconds.

    Returns:
        Tuple of (update, context) mocks.
    """
    user = User(id=user_id, is_bot=False, first_name="Test", language_code="en")
    chat = Chat(id=user_id, type="private")

    voice = MagicMock(spec=Voice)
    voice.file_id = "file_abc123"
    voice.duration = duration

    message = MagicMock(spec=Message)
    message.voice = voice
    message.text = None
    message.from_user = user
    message.chat = chat
    message.chat_id = user_id
    message.reply_text = AsyncMock()

    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.effective_chat = MagicMock()
    update.effective_chat.id = user_id
    update.effective_chat.send_action = AsyncMock()
    update.message = message

    # Mock context with bot that can get_file and download
    mock_file = AsyncMock()
    mock_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"ogg_audio_bytes"))

    context = MagicMock()
    context.bot = MagicMock()
    context.bot.get_file = AsyncMock(return_value=mock_file)

    return update, context


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unauthorized_user_rejected_before_asr(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Non-whitelisted user is rejected before any ASR call is made."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    mock_agent = MagicMock()

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)

    update, context = make_voice_update(user_id=99999)  # not in allowed_telegram_ids

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        await handler(update, context)

    # httpx must NOT have been called
    mock_client_cls.assert_not_called()

    # Rejection message must be sent
    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "not authorized" in call_text.lower()


@pytest.mark.asyncio
async def test_typing_indicator_shown(
    mock_config: AppConfig, test_db: Path
) -> None:
    """Typing indicator is sent before ASR transcription for authorized users."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "I'll play Inception right away!"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "play Inception"}
    mock_response.raise_for_status = MagicMock()

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    update.effective_chat.send_action.assert_called_once_with(action=ChatAction.TYPING)


@pytest.mark.asyncio
async def test_ogg_bytes_posted_to_asr_url(
    mock_config: AppConfig, test_db: Path
) -> None:
    """OGG bytes are POSTed to asr_url/transcribe with correct multipart fields."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Agent reply"
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "play Inception"}
    mock_response.raise_for_status = MagicMock()

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    # First positional arg: the URL
    url_arg: str = call_kwargs[0][0]
    assert url_arg.endswith("/transcribe")
    assert mock_config.asr_url in url_arg

    # files kwarg must include 'audio' with OGG content-type
    files_arg = call_kwargs[1].get("files") or call_kwargs[0][1] if len(call_kwargs[0]) > 1 else call_kwargs[1]["files"]
    assert "audio" in files_arg
    filename, content, content_type = files_arg["audio"]
    assert filename == "voice.ogg"
    assert content_type == "audio/ogg"


@pytest.mark.asyncio
async def test_transcribed_text_passed_to_agent(
    mock_config: AppConfig, test_db: Path
) -> None:
    """After successful transcription, the agent is called with the transcribed text."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)

    mock_result = MagicMock()
    mock_result.output = "Sure, adding Inception to your watchlist."
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock(return_value=mock_result)

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": "play Inception"}
    mock_response.raise_for_status = MagicMock()

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    mock_agent.run.assert_called_once()
    run_args = mock_agent.run.call_args
    text_arg: str = run_args[0][0]
    assert text_arg == "play Inception"


@pytest.mark.asyncio
async def test_empty_transcription_sends_message(
    mock_config: AppConfig, test_db: Path
) -> None:
    """ASR returning empty text sends the 'couldn't make out' message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    mock_agent = MagicMock()
    mock_agent.run = AsyncMock()

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    mock_response = MagicMock()
    mock_response.json.return_value = {"text": ""}
    mock_response.raise_for_status = MagicMock()

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    # Agent must NOT be called for empty transcription
    mock_agent.run.assert_not_called()

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "couldn't make out" in call_text or "couldn\u2019t make out" in call_text


@pytest.mark.asyncio
async def test_asr_http_error_sends_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """HTTPStatusError from ASR service sends a user-friendly fallback message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    mock_agent = MagicMock()

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    # Build a realistic HTTPStatusError
    mock_http_response = MagicMock()
    mock_http_response.status_code = 500
    http_error = httpx.HTTPStatusError(
        "Internal Server Error",
        request=MagicMock(),
        response=mock_http_response,
    )

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=http_error)
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "transcription" in call_text.lower() or "unavailable" in call_text.lower()
    assert update.message.reply_text.call_args.kwargs.get("parse_mode") == ParseMode.HTML


@pytest.mark.asyncio
async def test_asr_timeout_sends_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """TimeoutException from ASR service sends a user-friendly fallback message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    mock_agent = MagicMock()

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "timed out" in call_text.lower() or "transcription" in call_text.lower()
    assert update.message.reply_text.call_args.kwargs.get("parse_mode") == ParseMode.HTML


@pytest.mark.asyncio
async def test_asr_request_error_sends_fallback(
    mock_config: AppConfig, test_db: Path
) -> None:
    """RequestError (connection refused etc.) sends a user-friendly fallback message."""
    profile_manager = ProfileManager(test_db)
    history_manager = HistoryManager(test_db)
    mock_agent = MagicMock()

    handler = make_voice_handler(mock_config, profile_manager, history_manager, mock_agent)
    update, context = make_voice_update(user_id=123)

    with patch("home_agent.bot.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)
        mock_client.post = AsyncMock(
            side_effect=httpx.RequestError("Connection refused", request=MagicMock())
        )
        mock_client_cls.return_value = mock_client

        await handler(update, context)

    update.message.reply_text.assert_called_once()
    call_text: str = update.message.reply_text.call_args[0][0]
    assert "unavailable" in call_text.lower() or "transcription" in call_text.lower()
    call_kwargs = update.message.reply_text.call_args.kwargs
    assert call_kwargs.get("parse_mode") == ParseMode.HTML
