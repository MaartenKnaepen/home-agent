"""Tests for async database helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from home_agent.db import get_history, get_profile, save_message, save_profile


@pytest.mark.asyncio
async def test_message_roundtrip(test_db: Path) -> None:
    """Messages saved to DB can be retrieved."""
    await save_message(test_db, user_id=123, role="user", content="hello")
    await save_message(test_db, user_id=123, role="assistant", content="hi there")

    history = await get_history(test_db, user_id=123)

    assert history == [
        {"role": "user", "content": "hello"},
        {"role": "assistant", "content": "hi there"},
    ]


@pytest.mark.asyncio
async def test_history_limit(test_db: Path) -> None:
    """History limit returns only the requested number of rows."""
    await save_message(test_db, user_id=456, role="user", content="one")
    await save_message(test_db, user_id=456, role="assistant", content="two")
    await save_message(test_db, user_id=456, role="assistant", content="three")

    history = await get_history(test_db, user_id=456, limit=2)

    assert history == [
        {"role": "assistant", "content": "two"},
        {"role": "assistant", "content": "three"},
    ]


@pytest.mark.asyncio
async def test_profile_roundtrip(test_db: Path) -> None:
    """Profiles can be saved and loaded."""
    assert await get_profile(test_db, user_id=999) is None

    payload = {"name": "Rovo", "prefs": {"theme": "dark"}}
    await save_profile(test_db, user_id=999, data=payload)

    stored = await get_profile(test_db, user_id=999)

    assert stored == payload
