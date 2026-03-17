# Home Agent — Code Templates

> Reference templates for agents implementing new features.
> Rules and checklists are in `CLAUDE.md`. This file is for code patterns only.

---

## Agent Definition

```python
"""PydanticAI agent for home server management.

Adheres to home-agent coding standards: type hints, Google-style docstrings, async-first.
"""

from dataclasses import dataclass

from pydantic_ai import Agent, RunContext

from home_agent.config import AppConfig
from home_agent.profile import ProfileManager, UserProfile
from home_agent.history import HistoryManager


@dataclass
class AgentDeps:
    """Dependencies injected into the agent at runtime.

    Attributes:
        config: Application configuration.
        profile_manager: Manages user profile persistence.
        history_manager: Manages conversation history.
        user_profile: The current user's profile.
    """

    config: AppConfig
    profile_manager: ProfileManager
    history_manager: HistoryManager
    user_profile: UserProfile


agent = Agent(
    "openrouter:free-model-name",
    deps_type=AgentDeps,
    system_prompt="You are a home server assistant...",
)


@agent.system_prompt(dynamic=True)
async def inject_user_profile(ctx: RunContext[AgentDeps]) -> str:
    """Inject user profile into the system prompt dynamically."""
    profile = ctx.deps.user_profile
    return f"Current user: {profile.name}. Preferences: {profile.media_preferences.model_dump_json()}"


@agent.tool
async def update_user_note(ctx: RunContext[AgentDeps], note: str) -> str:
    """Add an observation about the user to their profile.

    Args:
        ctx: Runtime context with dependencies.
        note: Free-form note about the user's preferences or behavior.

    Returns:
        Confirmation message.
    """
    profile = ctx.deps.user_profile
    profile.notes.append(note)
    await ctx.deps.profile_manager.save(profile)
    return f"Noted: {note}"
```

---

## MCP Server Connection

```python
from pydantic_ai import Agent
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

# Option 1: HTTP MCP server (preferred for containerized services)
jellyseerr_toolset = FastMCPToolset("http://localhost:5055/mcp")

# Option 2: stdio subprocess
jellyseerr_toolset = FastMCPToolset(
    "uvx",
    args=["jellyseerr-mcp-server"],
    env={"JELLYSEERR_URL": "http://localhost:5055", "JELLYSEERR_API_KEY": "..."},
)

# Option 3: JSON config for multiple servers
mcp_config = {
    "mcpServers": {
        "jellyseerr": {"command": "uvx", "args": ["jellyseerr-mcp-server"]},
        "glances": {"command": "python", "args": ["mcp_servers/glances/server.py"]},
    }
}
multi_toolset = FastMCPToolset(mcp_config)

# Always use async context manager for lifecycle
agent = Agent("openrouter:free-model-name", toolsets=[jellyseerr_toolset])

async def main() -> None:
    async with agent:
        result = await agent.run("Search for Inception")
        print(result.output)
```

---

## Pydantic Data Model

```python
from pydantic import BaseModel


class MediaPreferences(BaseModel):
    """User's media consumption preferences.

    Attributes:
        preferred_genres: Genres the user likes.
        movie_quality: Default quality for movie requests.
        series_quality: Default quality for series requests.
        reply_language: Preferred language for agent replies.
        avoid_genres: Genres the user dislikes.
    """

    preferred_genres: list[str] = []
    movie_quality: str = "1080p"
    series_quality: str = "1080p"
    reply_language: str = "en"
    avoid_genres: list[str] = []
```

---

## Configuration Model

```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration loaded from environment variables.

    Attributes:
        telegram_bot_token: Telegram Bot API token.
        openrouter_api_key: OpenRouter API key for LLM access.
        allowed_telegram_ids: List of authorized Telegram user IDs.
        seerr_url: Jellyseerr instance URL.
        seerr_api_key: Jellyseerr API key.
        db_path: Path to SQLite database file.
    """

    telegram_bot_token: str
    openrouter_api_key: str
    allowed_telegram_ids: list[int]
    seerr_url: str
    seerr_api_key: str
    db_path: str = Field(default="data/home_agent.db")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

**Testing tip:** For list fields like `allowed_telegram_ids`, set env values as JSON arrays in tests (e.g., `ALLOWED_TELEGRAM_IDS="[123,456]"`). This prevents `SettingsError` parsing failures.

---

## Python Style Patterns

### Async I/O
```python
# ✅ All I/O operations are async
async def get_user_history(user_id: int) -> list[dict[str, str]]:
    """Fetch conversation history for a user."""
    ...

# ❌ Never use sync I/O in async context
# requests.get(...)  # Use httpx instead
```

### Type Hints
```python
from collections.abc import AsyncIterator


async def stream_responses(
    messages: list[dict[str, str]],
    *,
    max_tokens: int = 1000,
    temperature: float = 0.7,
) -> AsyncIterator[str]:
    """Stream response tokens from the LLM.

    Args:
        messages: Conversation messages.
        max_tokens: Maximum tokens in response.
        temperature: Sampling temperature.

    Yields:
        Response text chunks.
    """
    ...
```

### Exception Chaining
```python
try:
    data = await response.json()
except ValueError as e:
    logger.error("JSON parse failed", extra={"status": response.status})
    raise RuntimeError(f"Invalid response from Jellyseerr: {e}") from e  # Always chain!
```

### Imports
```python
# 1. Standard library
import logging
from pathlib import Path

# 2. Third-party
from pydantic import BaseModel
from pydantic_ai import Agent, RunContext
from telegram import Update
from telegram.ext import Application, ContextTypes, MessageHandler, filters

# 3. Local application (absolute imports only)
from home_agent.config import get_config
from home_agent.profile import ProfileManager, UserProfile
```

### Logging
```python
import logging

logger = logging.getLogger(__name__)

logger.info("Processing message", extra={"user_id": 12345, "message_length": 42})
logger.debug("MCP server connected", extra={"server": "jellyseerr", "tools_count": 4})
```

---

## Testing Patterns

### PydanticAI Agent — TestModel
```python
import pytest
from pydantic_ai.models.test import TestModel

from home_agent.agent import agent, AgentDeps


@pytest.fixture
def mock_deps() -> AgentDeps:
    return AgentDeps(
        config=mock_config(),
        profile_manager=MockProfileManager(),
        history_manager=MockHistoryManager(),
        user_profile=default_test_profile(),
    )


@pytest.mark.asyncio
async def test_agent_has_tools(mock_deps: AgentDeps) -> None:
    """Agent registers expected tools."""
    m = TestModel()
    with agent.override(model=m):
        result = await agent.run("test", deps=mock_deps)
        assert result.output is not None
    tool_names = [t.name for t in m.last_model_request_parameters.function_tools]
    assert "update_user_note" in tool_names


@pytest.mark.asyncio
async def test_agent_custom_response(mock_deps: AgentDeps) -> None:
    """Agent returns expected text when configured."""
    m = TestModel(custom_output_text="Here are your search results for Inception")
    with agent.override(model=m):
        result = await agent.run("search for Inception", deps=mock_deps)
        assert "Inception" in result.output
```

### MCP Server — Mock the API, not MCP
```python
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_jellyseerr_search(mock_jellyseerr_api: AsyncMock) -> None:
    """Jellyseerr MCP search tool returns structured results."""
    mock_jellyseerr_api.get.return_value = {
        "results": [{"title": "Inception", "year": 2010, "mediaType": "movie"}]
    }
    result = await search_media("Inception")
    assert len(result) == 1
    assert result[0]["title"] == "Inception"
```

### Telegram Bot — Constructing Test Updates
```python
from unittest.mock import AsyncMock, MagicMock
from telegram import Update, User, Message, Chat


def make_test_update(text: str, user_id: int = 12345) -> Update:
    """Create a mock Telegram Update for testing."""
    user = User(id=user_id, is_bot=False, first_name="Test")
    chat = Chat(id=user_id, type="private")
    message = MagicMock(spec=Message)
    message.text = text
    message.from_user = user
    message.chat = chat
    message.reply_text = AsyncMock()
    update = MagicMock(spec=Update)
    update.effective_user = user
    update.effective_message = message
    update.message = message
    return update


@pytest.mark.asyncio
async def test_unauthorized_user_rejected() -> None:
    """Non-whitelisted user receives rejection message."""
    update = make_test_update("hello", user_id=99999)
    context = MagicMock()
    await handle_message(update, context)
    update.message.reply_text.assert_called_once()
    args = update.message.reply_text.call_args
    assert "unauthorized" in args[0][0].lower() or "not authorized" in args[0][0].lower()
```

### Database — tmp_path + aiosqlite
```python
from pathlib import Path
import pytest
from home_agent.db import init_db, save_message, get_history


@pytest.fixture
async def test_db(tmp_path: Path):
    """Create a temporary test database."""
    db_path = tmp_path / "test.db"
    await init_db(str(db_path))
    yield db_path


@pytest.mark.asyncio
async def test_message_roundtrip(test_db: Path) -> None:
    """Messages saved to DB can be retrieved."""
    await save_message(str(test_db), user_id=123, role="user", content="hello")
    await save_message(str(test_db), user_id=123, role="assistant", content="hi there")
    history = await get_history(str(test_db), user_id=123)
    assert len(history) == 2
    assert history[0]["role"] == "user"
    assert history[1]["content"] == "hi there"
```

### Async Fixtures
```python
# conftest.py
import pytest

@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"
```

---

## Framework Boundary Patterns

### Toolset Wrappers
```python
# ❌ WRONG — MagicMock bypasses AbstractToolset check entirely
mock_toolset = MagicMock(spec=GuardedToolset)
agent = create_agent(config, toolsets=[mock_toolset])  # Passes! But production crashes.

# ✅ RIGHT — use a real instance with a mocked inner toolset
from unittest.mock import AsyncMock, MagicMock

inner = MagicMock()
inner.id = "test-server"
inner.__aenter__ = AsyncMock(return_value=inner)
inner.__aexit__ = AsyncMock(return_value=None)
inner.get_tools = AsyncMock(return_value={})
inner.call_tool = AsyncMock(return_value="mock result")

guarded = GuardedToolset(inner)  # Real instance — AbstractToolset contract enforced

async with agent:  # Lifecycle runs through real __aenter__/__aexit__
    result = await agent.run("test", deps=deps)
```

### Agent Tools
```python
# ❌ WRONG — calling tool function directly bypasses PydanticAI validation
result = await update_user_note(ctx, "some note")

# ✅ RIGHT — exercise the tool through agent.run()
@pytest.mark.asyncio
async def test_update_user_note_tool(mock_deps):
    """update_user_note tool is callable via agent and returns a string."""
    m = TestModel(custom_result_args={"tool_name": "update_user_note", "args": {"note": "likes action movies"}})
    with agent.override(model=m):
        result = await agent.run("remember I like action movies", deps=mock_deps)
    assert result.output is not None
    mock_deps.profile_manager.save.assert_called_once()
```

### Telegram Handlers
```python
# ❌ WRONG — MagicMock(spec=Update) allows any attribute access
update = MagicMock(spec=Update)
update.effective_user.id = 99999  # Works in test, real Update is immutable

# ✅ RIGHT — construct real Telegram objects
from telegram import Update, User, Message, Chat

user = User(id=99999, is_bot=False, first_name="Test")
chat = Chat(id=99999, type="private")
message = MagicMock(spec=Message)  # Message internals OK to mock
message.text = "hello"
message.from_user = user
message.chat = chat
message.reply_text = AsyncMock()
update = MagicMock(spec=Update)
update.effective_user = user  # Real User object
update.effective_message = message
update.message = message
```

---

## Self-Built MCP Server (FastMCP)

Only build a custom MCP server when no community server exists or works.

```python
"""MCP server for <ServiceName>.

Only built because no community MCP server was found/working.
"""

import os
from fastmcp import FastMCP
import httpx

mcp = FastMCP("<ServiceName>")

SERVICE_URL = os.environ["SERVICE_URL"]
SERVICE_API_KEY = os.environ["SERVICE_API_KEY"]


@mcp.tool()
async def search(query: str) -> str:
    """Search for items in <ServiceName>.

    Args:
        query: Search query text.

    Returns:
        JSON string with search results.
    """
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{SERVICE_URL}/api/v1/search",
            params={"query": query},
            headers={"X-Api-Key": SERVICE_API_KEY},
        )
        response.raise_for_status()
        return response.text
```
