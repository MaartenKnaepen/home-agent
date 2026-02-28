"""Async database helpers for Home Agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import aiosqlite


async def init_db(db_path: str | Path) -> None:
    """Initialize the SQLite database schema.

    Args:
        db_path: File path to the SQLite database.
    """
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)"
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_profiles (
                user_id INTEGER PRIMARY KEY,
                data TEXT NOT NULL
            )
            """
        )
        await db.commit()


async def save_message(db_path: str | Path, *, user_id: int, role: str, content: str) -> None:
    """Save a message to the database.

    Args:
        db_path: File path to the SQLite database.
        user_id: Telegram user ID.
        role: Message role (user/assistant/system).
        content: Message content.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO conversations (user_id, role, content) VALUES (?, ?, ?)",
            (user_id, role, content),
        )
        await db.commit()


async def get_history(db_path: str | Path, *, user_id: int, limit: int | None = None) -> list[dict[str, str]]:
    """Fetch recent conversation history for a user.

    Args:
        db_path: File path to the SQLite database.
        user_id: Telegram user ID.
        limit: Optional max number of messages to return.

    Returns:
        List of messages sorted from oldest to newest.
    """
    if limit is not None:
        query = """
            SELECT role, content FROM (
                SELECT role, content, id FROM conversations
                WHERE user_id = ?
                ORDER BY id DESC
                LIMIT ?
            ) ORDER BY id ASC
            """
        params = (user_id, limit)
    else:
        query = "SELECT role, content FROM conversations WHERE user_id = ? ORDER BY id ASC"
        params = (user_id,)
    async with aiosqlite.connect(db_path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(query, params)
        rows = await cursor.fetchall()
        await cursor.close()
    return [{"role": row["role"], "content": row["content"]} for row in rows]


async def save_profile(db_path: str | Path, *, user_id: int, data: dict[str, Any]) -> None:
    """Persist a user profile payload.

    Args:
        db_path: File path to the SQLite database.
        user_id: Telegram user ID.
        data: Profile data to store.
    """
    async with aiosqlite.connect(db_path) as db:
        await db.execute(
            "INSERT INTO user_profiles (user_id, data) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET data = excluded.data",
            (user_id, json.dumps(data)),
        )
        await db.commit()


async def get_profile(db_path: str | Path, *, user_id: int) -> dict[str, Any] | None:
    """Retrieve a stored user profile payload.

    Args:
        db_path: File path to the SQLite database.
        user_id: Telegram user ID.

    Returns:
        Stored profile data, or None if missing.
    """
    async with aiosqlite.connect(db_path) as db:
        cursor = await db.execute("SELECT data FROM user_profiles WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        await cursor.close()
    if row is None:
        return None
    return json.loads(row[0])
