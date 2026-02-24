"""Tests for HistoryManager and sliding_window_processor."""

from __future__ import annotations

from pathlib import Path

import pytest

from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, UserPromptPart, TextPart, ToolCallPart, ToolReturnPart

from home_agent.db import init_db
from home_agent.history import HistoryManager, sliding_window_processor


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
async def test_db(tmp_path: Path) -> Path:
    """Create a temporary SQLite database for history tests.

    Args:
        tmp_path: Pytest temporary directory.

    Returns:
        Path to the initialised test database.
    """
    db_path = tmp_path / "test_history.db"
    await init_db(db_path)
    return db_path


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_pair(user_text: str = "hello", assistant_text: str = "hi") -> tuple[ModelRequest, ModelResponse]:
    """Create a matching ModelRequest/ModelResponse pair.

    Args:
        user_text: Content for the user prompt part.
        assistant_text: Content for the assistant text part.

    Returns:
        A (ModelRequest, ModelResponse) tuple.
    """
    req = ModelRequest(parts=[UserPromptPart(content=user_text)])
    resp = ModelResponse(parts=[TextPart(content=assistant_text)])
    return req, resp


def _make_messages(num_pairs: int) -> list[ModelMessage]:
    """Build a flat list of alternating ModelRequest/ModelResponse messages.

    Args:
        num_pairs: Number of request/response pairs to create.

    Returns:
        Flat list with num_pairs * 2 ModelMessage objects.
    """
    messages: list[ModelMessage] = []
    for i in range(num_pairs):
        req, resp = _make_pair(f"user message {i}", f"assistant reply {i}")
        messages.append(req)
        messages.append(resp)
    return messages


# ── HistoryManager tests ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_history_manager_save_and_retrieve(test_db: Path) -> None:
    """Save messages via HistoryManager.save_message(), retrieve with get_history()."""
    manager = HistoryManager(test_db)

    await manager.save_message(user_id=1, role="user", content="hello")
    await manager.save_message(user_id=1, role="assistant", content="hi there")

    history = await manager.get_history(user_id=1)

    assert len(history) == 2
    assert history[0] == {"role": "user", "content": "hello"}
    assert history[1] == {"role": "assistant", "content": "hi there"}


@pytest.mark.asyncio
async def test_history_manager_empty_history(test_db: Path) -> None:
    """get_history() for unknown user returns empty list."""
    manager = HistoryManager(test_db)

    history = await manager.get_history(user_id=99999)

    assert history == []


@pytest.mark.asyncio
async def test_history_manager_full_history_preserved(test_db: Path) -> None:
    """Save 20+ messages — all are stored (no truncation at manager level)."""
    manager = HistoryManager(test_db)
    user_id = 42

    num_messages = 25
    for i in range(num_messages):
        role = "user" if i % 2 == 0 else "assistant"
        await manager.save_message(user_id=user_id, role=role, content=f"message {i}")

    history = await manager.get_history(user_id=user_id)

    assert len(history) == num_messages
    # Verify order: oldest first
    assert history[0]["content"] == "message 0"
    assert history[-1]["content"] == f"message {num_messages - 1}"


@pytest.mark.asyncio
async def test_history_manager_limit(test_db: Path) -> None:
    """get_history() with limit returns only the last N messages."""
    manager = HistoryManager(test_db)
    user_id = 7

    for i in range(10):
        await manager.save_message(user_id=user_id, role="user", content=f"msg {i}")

    history = await manager.get_history(user_id=user_id, limit=3)

    assert len(history) == 3
    assert history[0]["content"] == "msg 7"
    assert history[2]["content"] == "msg 9"


@pytest.mark.asyncio
async def test_history_manager_isolates_users(test_db: Path) -> None:
    """Messages for different users are stored and retrieved independently."""
    manager = HistoryManager(test_db)

    await manager.save_message(user_id=1, role="user", content="user one message")
    await manager.save_message(user_id=2, role="user", content="user two message")

    history_1 = await manager.get_history(user_id=1)
    history_2 = await manager.get_history(user_id=2)

    assert len(history_1) == 1
    assert history_1[0]["content"] == "user one message"
    assert len(history_2) == 1
    assert history_2[0]["content"] == "user two message"


# ── sliding_window_processor tests ───────────────────────────────────────────


def test_sliding_window_returns_last_n_pairs() -> None:
    """Apply sliding_window_processor(n=5) to 10 pairs; only last 5 pairs returned."""
    messages = _make_messages(10)
    processor = sliding_window_processor(n=5)

    result = processor(messages)

    assert len(result) == 10  # 5 pairs × 2 messages each
    # The last 5 pairs correspond to messages[10:] from original list
    assert result == messages[10:]


def test_sliding_window_does_not_split_pairs() -> None:
    """Window boundary never leaves a lone ModelRequest without its ModelResponse."""
    messages = _make_messages(6)  # 6 complete pairs
    processor = sliding_window_processor(n=3)

    result = processor(messages)

    # Result must contain complete pairs only
    assert len(result) % 2 == 0
    for i in range(0, len(result), 2):
        assert isinstance(result[i], ModelRequest), f"Expected ModelRequest at index {i}"
        assert isinstance(result[i + 1], ModelResponse), f"Expected ModelResponse at index {i + 1}"


def test_sliding_window_n_larger_than_history() -> None:
    """When n > available pairs, all messages are returned unchanged."""
    messages = _make_messages(3)
    processor = sliding_window_processor(n=10)

    result = processor(messages)

    assert result == messages
    assert len(result) == 6  # 3 pairs × 2


def test_sliding_window_empty_history() -> None:
    """Empty list in, empty list out."""
    processor = sliding_window_processor(n=5)

    result = processor([])

    assert result == []


def test_sliding_window_n_equals_pairs() -> None:
    """When n equals the number of pairs, all messages are returned."""
    messages = _make_messages(4)
    processor = sliding_window_processor(n=4)

    result = processor(messages)

    assert result == messages


def test_sliding_window_n_one() -> None:
    """With n=1, only the last pair is returned."""
    messages = _make_messages(5)
    processor = sliding_window_processor(n=1)

    result = processor(messages)

    assert len(result) == 2
    assert isinstance(result[0], ModelRequest)
    assert isinstance(result[1], ModelResponse)
    # Should be the very last pair
    assert result == messages[-2:]


def test_sliding_window_tool_call_pairs_not_split() -> None:
    """Tool-call/tool-result pairs within a request/response are never split across the window boundary.

    A ModelRequest containing a ToolCallPart must always appear with its paired
    ModelResponse containing the ToolReturnPart — the window must not cut between them.
    """
    # Build a history where some pairs contain tool-call/tool-result interactions
    messages: list[ModelMessage] = []

    # First 3 pairs: plain user/assistant exchanges
    for i in range(3):
        req = ModelRequest(parts=[UserPromptPart(content=f"user {i}")])
        resp = ModelResponse(parts=[TextPart(content=f"assistant {i}")])
        messages.append(req)
        messages.append(resp)

    # 4th pair: tool-call request + tool-return response
    tool_req = ModelRequest(parts=[
        UserPromptPart(content="search for Inception"),
        ToolCallPart(tool_name="search_media", args='{"query": "Inception"}', tool_call_id="tc-1"),
    ])
    tool_resp = ModelResponse(parts=[
        ToolReturnPart(tool_name="search_media", content='[{"title": "Inception"}]', tool_call_id="tc-1"),
        TextPart(content="Found Inception (2010)."),
    ])
    messages.append(tool_req)
    messages.append(tool_resp)

    # 5th pair: another plain exchange
    final_req = ModelRequest(parts=[UserPromptPart(content="great, request it")])
    final_resp = ModelResponse(parts=[TextPart(content="Requested!")])
    messages.append(final_req)
    messages.append(final_resp)

    # Apply window of 3 — should capture pairs 3, 4 (tool), 5
    processor = sliding_window_processor(n=3)
    result = processor(messages)

    assert len(result) == 6  # 3 pairs × 2 messages each

    # The tool-call pair must be present and intact (pair index 1 in result)
    tool_req_result = result[2]
    tool_resp_result = result[3]
    assert isinstance(tool_req_result, ModelRequest)
    assert isinstance(tool_resp_result, ModelResponse)
    assert any(isinstance(p, ToolCallPart) for p in tool_req_result.parts)
    assert any(isinstance(p, ToolReturnPart) for p in tool_resp_result.parts)

    # Verify overall integrity: every even index is a Request, every odd is a Response
    for i in range(0, len(result), 2):
        assert isinstance(result[i], ModelRequest), f"Expected ModelRequest at index {i}"
        assert isinstance(result[i + 1], ModelResponse), f"Expected ModelResponse at index {i + 1}"


def test_sliding_window_trailing_unpaired_request_preserved() -> None:
    """A trailing ModelRequest without a paired ModelResponse is preserved.

    PydanticAI calls history_processors on every model step, including the first
    step where the current user message is an unpaired ModelRequest at the end.
    The processor must preserve it so PydanticAI's contract (result ends with a
    ModelRequest) is satisfied.
    """
    messages = _make_messages(3)
    # Append an unpaired request at the end (simulates the current user message)
    lone_req = ModelRequest(parts=[UserPromptPart(content="lone request")])
    messages.append(lone_req)

    processor = sliding_window_processor(n=5)
    result = processor(messages)

    # 3 complete pairs (6 messages) + the trailing unpaired request = 7
    assert len(result) == 7
    assert result[-1] is lone_req
    # All except the last should form complete pairs
    for i in range(0, len(result) - 1, 2):
        assert isinstance(result[i], ModelRequest)
        assert isinstance(result[i + 1], ModelResponse)
