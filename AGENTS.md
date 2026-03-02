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
| **✅ ALWAYS** subclass `AbstractToolset` for custom toolset wrappers | Plain wrapper classes passed to `toolsets=` cause `TypeError: object is not callable` — PydanticAI treats non-`AbstractToolset` objects as callable factories |
| **✅ ALWAYS** match `call_tool(name, tool_args, ctx, tool)` exactly | Wrong arity is silently absorbed by mocks but crashes at runtime |

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

**Testing tip:** For list fields like `allowed_telegram_ids`, set env values as JSON arrays in tests (e.g., `ALLOWED_TELEGRAM_IDS="[123,456]"`). This prevents `SettingsError` parsing failures.

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

### ⚠️ Framework Boundary Testing — The Most Important Rule

> **`MagicMock(spec=SomeClass)` bypasses every framework protocol check. Green tests, broken production.**

**The anti-pattern:** Mocking a class that plugs into a framework means the framework never validates it. Method signatures, return types, abstract base classes, lifecycle hooks — all invisible to your tests.

**The rule:** For every class that integrates with a framework (PydanticAI, python-telegram-bot, aiosqlite), **at least one test must exercise it through the real framework call path**.

#### What "framework boundary" means in this project

| Integration point | Framework validates | Safe mock level | Required real test |
|---|---|---|---|
| `GuardedToolset` / custom toolsets | `AbstractToolset` subclass, `call_tool` arity, `get_tools` return type | Inner `FastMCPToolset` only | Pass real `GuardedToolset` to real `Agent()`, call `agent.run()` |
| `@agent.tool` functions | Return type is `str`, `RunContext` first arg, async | None — call through agent only | `agent.run()` with `TestModel()` that triggers the tool |
| `RetryingModel` / custom models | PydanticAI model protocol | Inner model only | `agent.run()` with real `RetryingModel` wrapping `TestModel()` |
| Telegram handlers | `Update` structure, handler signature | `MagicMock(spec=Update)` is OK for handler logic | One test with real `Application` dispatching a real `Update` |
| `aiosqlite` queries | SQL syntax, column names, types | In-memory or `tmp_path` DB — never mock | All DB tests use real `tmp_path` DB |

#### The correct pattern for toolset wrappers

```python
# ❌ WRONG — MagicMock bypasses AbstractToolset check entirely
mock_toolset = MagicMock(spec=GuardedToolset)
agent = create_agent(config, toolsets=[mock_toolset])  # Passes! But production crashes.

# ✅ RIGHT — use a real instance with a mocked inner toolset
from unittest.mock import AsyncMock, MagicMock
from pydantic_ai.toolsets.abstract import ToolsetTool

inner = MagicMock()
inner.id = "test-server"
inner.__aenter__ = AsyncMock(return_value=inner)
inner.__aexit__ = AsyncMock(return_value=None)
inner.get_tools = AsyncMock(return_value={})
inner.call_tool = AsyncMock(return_value="mock result")

guarded = GuardedToolset(inner)  # Real instance — AbstractToolset contract enforced

async with agent:  # Lifecycle runs through real __aenter__/__aexit__
    result = await agent.run("test", deps=deps)  # PydanticAI validates toolset protocol
```

#### The correct pattern for agent tools

```python
# ❌ WRONG — calling tool function directly bypasses PydanticAI validation
result = await update_user_note(ctx, "some note")  # Return type? RunContext type? Never checked.

# ✅ RIGHT — use TestModel to exercise the tool through agent.run()
@pytest.mark.asyncio
async def test_update_user_note_tool(mock_deps):
    """update_user_note tool is callable via agent and returns a string."""
    m = TestModel(custom_result_args={"tool_name": "update_user_note", "args": {"note": "likes action movies"}})
    with agent.override(model=m):
        result = await agent.run("remember I like action movies", deps=mock_deps)
    assert result.output is not None
    # Verify the tool was actually called by checking side effects
    mock_deps.profile_manager.save.assert_called_once()
```

#### The correct pattern for Telegram handlers

```python
# ❌ WRONG — MagicMock(spec=Update) allows any attribute access, no Telegram validation
update = MagicMock(spec=Update)
update.effective_user.id = 99999  # Works in test, but real Telegram Update is immutable

# ✅ RIGHT — construct real Telegram objects
from telegram import Update, User, Message, Chat
from telegram.ext import Application

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

#### Checklist: before writing any test involving a framework class

1. **Is this class passed to a framework constructor or decorator?** → Must use real instance in at least one test.
2. **Does this class subclass a framework ABC?** → Must verify the subclass is correct, not just that mocks pass.
3. **Does this class have methods called by the framework with specific signatures?** → Must verify arity matches exactly, not just that the method exists.
4. **Is the test only exercising internal logic?** → Unit tests with mocks are fine, **but there must also be a separate integration test** that runs through the framework.

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

## ✅ 9. Verification: You Are Not Done Until verify.sh Passes

After implementing a step, **always run `verify.sh` before reporting done**:

```bash
bash verify.sh
```

This runs:
1. **`ty`** — type checker. Fix all type errors.
2. **`lint-imports`** — architecture contract checker. Fix any forbidden imports.
3. **`pytest`** — all tests must pass. Fix failures or write missing tests.

**Only report the step as complete when all three pass with exit code 0.**
If you cannot fix a failing check after multiple attempts, explain the blocker clearly.

---

## ✅ 10. Pre-Implementation Checklist

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
13. **Framework boundaries:** For every class that integrates with a framework (PydanticAI toolset, Telegram handler, aiosqlite), is there at least one test that runs it through the real framework call path (not just `MagicMock(spec=...)`)?
14. **Custom toolsets:** If writing a toolset wrapper, does it subclass `AbstractToolset`? Does `call_tool` have the exact 4-arg signature `(name, tool_args, ctx, tool)`?

## 11. cache.overflow — Verified Knowledge Exchange
cache.overflow is a shared knowledge base of verified solutions for software and coding problems. Use it to avoid re-solving problems that other agents have already solved, and to contribute solutions back for future agents.
When to use cache.overflow:

A build or test is failing and you have a concrete error message to search with
You're seeing unexpected behavior and aren't sure why
You're configuring a tool, library, or environment for the first time (e.g. MCP transport setup, pytest-asyncio modes, pydantic-settings env parsing)
You're facing an architecture decision that other agents working on similar home-agent/PydanticAI/Telegram projects have likely encountered
Any problem that took more than 2 tool calls to resolve — search first, and publish after

When NOT to use cache.overflow: trivial one-liners, well-known stdlib patterns, anything you can resolve confidently in a single step.
Follow this loop exactly:
### 1. Search FIRST (find_solution)
BEFORE attempting any non-trivial task manually, search with the error message or problem description.
Mandatory when: build/test fails, unexpected behavior, configuring tools/libraries/environments, architecture decisions, or any problem another agent has likely solved.
### 2. Unlock (unlock_solution)
When find_solution returns a match without solution_body, it is locked. Call unlock_solution with the solution_id to unlock and retrieve the full solution.
### 3. Rate (submit_feedback)
After applying ANY solution, call submit_feedback (is_useful: true/false). No exceptions.
### 4. Publish (publish_solution)
After solving any non-trivial problem (>2 tool calls to resolve), call publish_solution before moving on.
Format: query_title = "Fix [error] in [tech]" or "Configure [tool] for [goal]", solution_body = problem + solution + working code.
Keep the solution as concise as possible. Use Markdown format.