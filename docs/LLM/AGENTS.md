# 📜 Home Agent Coding Guidelines for LLM Agents

> **Purpose:** Enable LLM agents to generate code that matches this project's patterns exactly on the first try.
> **History & Decisions:** See `MEMORY.md` for project history, decisions made, and lessons learned.

---

## 🏗️ 1. Architecture: Agent + MCP + Bot

**Never put business logic in the Telegram handler or the PydanticAI agent definition.** Follow this separation:

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Bot** | `src/home_agent/bot.py` | Telegram wiring only: receive messages, send replies, whitelist check, typing indicators |
| **Agent** | `src/home_agent/agent.py` | PydanticAI agent definition: system prompt, tools, dependency injection, model config |
| **Tools** | `src/home_agent/tools/*.py` | Agent-callable tools: profile updates, Telegram rich replies |
| **MCP** | `src/home_agent/mcp/*.py` | MCP server registry, configs, lifecycle management |
| **Core** | `src/home_agent/config.py`, `db.py`, `profile.py`, `history.py` | Config, persistence, user profiles, history processing — pure logic, no framework coupling |

### Agent Definition Template
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

### MCP Server Connection Template
```python
"""MCP server integration with PydanticAI agent."""

from pydantic_ai import Agent
from pydantic_ai.toolsets.fastmcp import FastMCPToolset

# Option 1: Connect to an HTTP MCP server (preferred for containerized services)
jellyseerr_toolset = FastMCPToolset("http://localhost:5055/mcp")

# Option 2: Connect via stdio (subprocess)
jellyseerr_toolset = FastMCPToolset(
    "uvx",
    args=["jellyseerr-mcp-server"],
    env={"JELLYSEERR_URL": "http://localhost:5055", "JELLYSEERR_API_KEY": "..."},
)

# Option 3: JSON config for multiple servers
mcp_config = {
    "mcpServers": {
        "jellyseerr": {
            "command": "uvx",
            "args": ["jellyseerr-mcp-server"],
        },
        "glances": {
            "command": "python",
            "args": ["mcp_servers/glances/server.py"],
        },
    }
}
multi_toolset = FastMCPToolset(mcp_config)

# Agent uses toolsets
agent = Agent(
    "openrouter:free-model-name",
    toolsets=[jellyseerr_toolset],
)

# Lifecycle: use async context manager
async def main() -> None:
    async with agent:
        result = await agent.run("Search for Inception")
        print(result.output)
```

---

## ⚠️ 2. PydanticAI Critical Rules

These cause runtime errors if violated:

| Rule | Why |
|------|-----|
| **✅ ALWAYS** use `async with agent:` to manage MCP/toolset lifecycle | Starts/stops MCP connections properly |
| **❌ NEVER** use deprecated `agent.run_mcp_servers()` or `mcp_servers=` param | Use `async with agent:` and `toolsets=` instead |
| **✅ ALWAYS** use `FastMCPToolset` from `pydantic_ai.toolsets.fastmcp` | Current API for MCP integration (replaces `MCPServerStdio`) |
| **✅ ALWAYS** define `deps_type` on the agent if using dependency injection | PydanticAI validates deps at runtime |
| **✅ ALWAYS** use `RunContext[AgentDeps]` as first param in tool functions | Required for dependency access |
| **✅ ALWAYS** return strings from tool functions | PydanticAI expects string tool results |
| **✅ Use** `agent.override(model=TestModel())` in tests | Never call real LLMs in tests |

---

## 📊 3. Data Types: Pydantic Models

**Use Pydantic `BaseModel` for all structured data. Use `dict` only at serialization boundaries (DB, JSON).**

```python
# In profile.py or types.py
from pydantic import BaseModel


class MediaPreferences(BaseModel):
    """User's media consumption preferences.

    Attributes:
        preferred_genres: Genres the user likes.
        preferred_quality: Default quality for media requests.
        preferred_language: Preferred audio/subtitle language.
        avoid_genres: Genres the user dislikes.
    """

    preferred_genres: list[str] = []
    preferred_quality: str = "1080p"
    preferred_language: str = "en"
    avoid_genres: list[str] = []
```

---

## 🔧 4. Configuration & Logging

### Configuration (via pydantic-settings)
```python
from home_agent.config import get_config

config = get_config()
# Access: config.telegram_bot_token, config.openrouter_api_key, etc.
# Add new settings to src/home_agent/config.py
# All secrets loaded from .env, never hardcoded
```

### Config Model Template
```python
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class AppConfig(BaseSettings):
    """Application configuration loaded from environment variables.

    Attributes:
        telegram_bot_token: Telegram Bot API token.
        openrouter_api_key: OpenRouter API key for LLM access.
        allowed_telegram_ids: Comma-separated list of authorized Telegram user IDs.
        jellyseerr_url: Jellyseerr instance URL.
        jellyseerr_api_key: Jellyseerr API key.
        db_path: Path to SQLite database file.
    """

    telegram_bot_token: str
    openrouter_api_key: str
    allowed_telegram_ids: list[int]
    jellyseerr_url: str
    jellyseerr_api_key: str
    db_path: str = Field(default="data/home_agent.db")

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")
```

### Logging (stdlib `logging`)
```python
import logging

logger = logging.getLogger(__name__)

# Simple structured logging
logger.info("Processing message", extra={"user_id": 12345, "message_length": 42})

# For async operations
logger.debug("MCP server connected", extra={"server": "jellyseerr", "tools_count": 4})
```

---

## 🐍 5. Python Style Rules

### Async-First
```python
# ✅ All I/O operations are async
async def get_user_history(user_id: int) -> list[dict[str, str]]:
    """Fetch conversation history for a user."""
    ...

# ❌ Never use sync I/O in async context
# requests.get(...)  # Use httpx or aiohttp instead
```

### Type Hints (Required Everywhere)
```python
from collections.abc import AsyncIterator


async def stream_responses(
    messages: list[dict[str, str]],
    *,  # Force keyword-only args after this
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

### Exception Handling (Chain Everything)
```python
try:
    data = await response.json()
except ValueError as e:
    logger.error("JSON parse failed", extra={"status": response.status})
    raise RuntimeError(f"Invalid response from Jellyseerr: {e}") from e  # Always chain!
```

### Path Handling (pathlib Only)
```python
from pathlib import Path

db_path = Path("data") / "home_agent.db"  # ✅
# NOT: os.path.join("data", "home_agent.db")  # ❌
```

### Imports (Absolute, Grouped)
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

### Docstrings (Google Style)
```python
async def search_media(
    query: str,
    *,
    media_type: str | None = None,
    limit: int = 10,
) -> list[dict[str, str]]:
    """Search for movies or TV shows via Jellyseerr.

    Args:
        query: The search query text.
        media_type: Filter by "movie" or "tv". None for both.
        limit: Maximum number of results.

    Returns:
        List of media items with title, year, and overview.

    Raises:
        ConnectionError: If Jellyseerr is unreachable.
        ValueError: If query is empty.
    """
```

---

## 🧪 6. Testing Patterns

### PydanticAI Agent Tests (TestModel)
**Always use `TestModel` — never call real LLMs in tests.**

```python
import pytest
from pydantic_ai.models.test import TestModel

from home_agent.agent import agent, AgentDeps


@pytest.fixture
def mock_deps() -> AgentDeps:
    """Create mock dependencies for agent testing."""
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
    # Verify tools were registered
    assert m.last_model_request_parameters is not None
    tool_names = [t.name for t in m.last_model_request_parameters.function_tools]
    assert "update_user_note" in tool_names
```

### Custom Output Testing
```python
@pytest.mark.asyncio
async def test_agent_custom_response(mock_deps: AgentDeps) -> None:
    """Agent returns custom text when configured."""
    m = TestModel(custom_output_text="Here are your search results for Inception")
    with agent.override(model=m):
        result = await agent.run("search for Inception", deps=mock_deps)
        assert "Inception" in result.output
```

### MCP Server Tests (Mock the API, not MCP)
```python
from unittest.mock import AsyncMock, patch


@pytest.mark.asyncio
async def test_jellyseerr_search(mock_jellyseerr_api: AsyncMock) -> None:
    """Jellyseerr MCP search tool returns structured results."""
    mock_jellyseerr_api.get.return_value = {
        "results": [{"title": "Inception", "year": 2010, "mediaType": "movie"}]
    }
    # Test the MCP server tool function directly
    result = await search_media("Inception")
    assert len(result) == 1
    assert result[0]["title"] == "Inception"
```

### Telegram Bot Tests (python-telegram-bot mocks)
```python
from unittest.mock import AsyncMock, MagicMock

from telegram import Update, User, Message, Chat


def make_test_update(text: str, user_id: int = 12345) -> Update:
    """Create a mock Telegram Update for testing.

    Args:
        text: Message text.
        user_id: Telegram user ID.

    Returns:
        Mock Update object.
    """
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

### Database Tests (Use tmp_path + aiosqlite)
```python
import pytest

from home_agent.db import init_db, save_message, get_history


@pytest.fixture
async def test_db(tmp_path: Path):
    """Create a temporary test database.

    Args:
        tmp_path: Pytest temporary directory.

    Yields:
        Path to the test database.
    """
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

### Async Fixtures (pytest-asyncio)
```python
# conftest.py
import pytest


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio backend for all async tests."""
    return "asyncio"
```

### The Import Path Rule
**Patch where imported, not where defined:**
```python
# Testing bot.py which imports handle_message from agent
@patch("home_agent.bot.agent")  # ✅ Patch where used
# NOT: @patch("home_agent.agent.agent")  # ❌ Patch where defined
```

### File System (Use tmp_path)
```python
def test_db_creation(tmp_path: Path) -> None:
    """Database file is created on init."""
    db_path = tmp_path / "test.db"
    assert not db_path.exists()
    asyncio.run(init_db(str(db_path)))
    assert db_path.exists()
```

---

## 📁 7. File Organization Reference

```
src/home_agent/
├── __init__.py
├── main.py                  # Entry point: init config, DB, MCP, agent, bot; start polling
├── config.py                # pydantic-settings AppConfig
├── agent.py                 # PydanticAI Agent definition, system prompt, tool registration
├── bot.py                   # python-telegram-bot handlers, whitelist, message routing
├── profile.py               # UserProfile model, ProfileManager (CRUD via db.py)
├── history.py               # HistoryManager, sliding_window_processor
├── db.py                    # aiosqlite connection, init_db(), message & profile CRUD
├── tools/
│   ├── __init__.py
│   ├── profile_tools.py     # Agent tools for updating user profile
│   └── telegram_tools.py    # Agent tools for rich Telegram replies (keyboards, images)
└── mcp/
    ├── __init__.py
    ├── registry.py           # MCPRegistry: configure, start, stop MCP servers
    └── servers.py            # MCP server configs (URLs, env vars, transport)

mcp_servers/                  # Only for self-built MCP servers (last resort)
└── <service>/
    ├── __init__.py
    └── server.py             # FastMCP server wrapping the service API

tests/
├── conftest.py               # Shared fixtures: mock_deps, test_db, make_test_update
├── test_config.py
├── test_db.py
├── test_profile.py
├── test_history.py
├── test_agent.py
├── test_bot.py
├── test_mcp_registry.py
└── test_integration.py       # End-to-end: Telegram → Agent → MCP → response
```

---

## 🔌 8. MCP Server Guidelines

### When Adding a New Service

1. **Search first**: Check GitHub, MCP registries for existing servers
2. **Evaluate**: Install, connect to agent, test with real service — does it work?
3. **Use if functional**: Even if imperfect, prefer existing over custom
4. **Build only as last resort**: Use FastMCP, keep to ~100-300 lines

### Self-Built MCP Server Template (FastMCP)
```python
"""MCP server for <ServiceName>.

Only built because no community MCP server was found/working.
See mcp_servers/README.md for rationale.
"""

from fastmcp import FastMCP
import httpx

mcp = FastMCP("<ServiceName>")

# Configure via environment variables
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

### MCP Transport Decision
- **Default**: `FastMCPToolset("command", args=[...])` — stdio subprocess, no networking, simplest
- **If shared across agents**: `FastMCPToolset("http://host:port/mcp")` — HTTP, independently deployable

---

## ✅ 9. Pre-Implementation Checklist

Before generating code, verify:

1. **Architecture:** Business logic in core modules (`profile.py`, `history.py`, `db.py`), not in `bot.py` or `agent.py`?
2. **Async:** All I/O is async (`aiosqlite`, `httpx`, `asyncio`)?
3. **Agent:** `deps_type` defined? Tools use `RunContext[AgentDeps]`? Tools return `str`?
4. **MCP:** Using `async with agent:` for lifecycle? Not using deprecated `run_mcp_servers()`?
5. **Config:** All secrets from `.env` via `pydantic-settings`? Nothing hardcoded?
6. **Types:** Pydantic `BaseModel` for structured data? Type hints on every function?
7. **Exceptions:** Chained with `from e`?
8. **Paths:** Using `pathlib.Path`?
9. **Docstrings:** Google-style with Args/Returns/Raises?
10. **Logging:** Using `logging.getLogger(__name__)`, not `print()`?
11. **Tests:** Using `TestModel` for agent? Mocking at import location? `tmp_path` for file I/O?
12. **MCP servers:** Searched for existing first? Built custom only as last resort?
