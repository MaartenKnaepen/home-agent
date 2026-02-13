# 🗂️ Home Agent — API & Function Registry

> **Purpose:** Single source of truth for every function, class, and tool in the project. Before writing new code, **search this file first** to reuse or adapt existing functionality. Keep this file updated whenever you add, rename, or remove a function.
>
> **Rule:** If what you need already exists here — use it. If it almost fits — adapt it. Only create new functions when nothing here covers the use case.

---

## 📦 Modules Overview

| Module | Path | Purpose |
|--------|------|---------|
| `config` | `src/home_agent/config.py` | App configuration via pydantic-settings |
| `db` | `src/home_agent/db.py` | SQLite async database layer |
| `profile` | `src/home_agent/profile.py` | User profile models and persistence |
| `history` | `src/home_agent/history.py` | Conversation history and processors |
| `agent` | `src/home_agent/agent.py` | PydanticAI agent definition |
| `bot` | `src/home_agent/bot.py` | Telegram bot handlers |
| `main` | `src/home_agent/main.py` | Entry point, wiring |
| `tools.profile_tools` | `src/home_agent/tools/profile_tools.py` | Agent tools for profile updates |
| `tools.telegram_tools` | `src/home_agent/tools/telegram_tools.py` | Agent tools for rich Telegram replies |
| `mcp.registry` | `src/home_agent/mcp/registry.py` | MCP server lifecycle management |
| `mcp.servers` | `src/home_agent/mcp/servers.py` | MCP server configurations |

---

## `config.py` — Configuration

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `AppConfig` | `class(BaseSettings)` | — | App config model with all env vars |
| `get_config` | `() -> AppConfig` | `AppConfig` | Singleton config accessor |
-->

---

## `db.py` — Database Layer

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `init_db` | `async (db_path: str) -> None` | `None` | Creates tables if not exist |
| `save_message` | `async (db_path: str, user_id: int, role: str, content: str) -> None` | `None` | Persist a conversation message |
| `get_history` | `async (db_path: str, user_id: int, limit: int | None) -> list[dict]` | `list[dict]` | Retrieve messages for a user |
| `save_profile` | `async (db_path: str, user_id: int, profile_json: str) -> None` | `None` | Persist user profile blob |
| `get_profile` | `async (db_path: str, user_id: int) -> str | None` | `str | None` | Retrieve user profile JSON |
-->

---

## `profile.py` — User Profiles

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `MediaPreferences` | `class(BaseModel)` | — | Genre, quality, language prefs |
| `NotificationPrefs` | `class(BaseModel)` | — | Notification settings |
| `UserProfile` | `class(BaseModel)` | — | Full user profile with prefs, notes, stats |
| `ProfileManager` | `class(db_path: str)` | — | CRUD operations for user profiles |
| `ProfileManager.get` | `async (user_id: int) -> UserProfile` | `UserProfile` | Get or create default profile |
| `ProfileManager.save` | `async (profile: UserProfile) -> None` | `None` | Persist profile to DB |
-->

---

## `history.py` — Conversation History

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `HistoryManager` | `class(db_path: str)` | — | Conversation CRUD via db.py |
| `HistoryManager.add` | `async (user_id: int, role: str, content: str) -> None` | `None` | Append message to history |
| `HistoryManager.get` | `async (user_id: int, limit: int | None) -> list[dict]` | `list[dict]` | Get conversation history |
| `sliding_window_processor` | `(messages: list, *, window_size: int) -> list` | `list` | PydanticAI history_processor: keeps last N pairs |
-->

---

## `agent.py` — PydanticAI Agent

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `AgentDeps` | `@dataclass` | — | Dependencies: config, profile_manager, history_manager, user_profile |
| `agent` | `Agent(deps_type=AgentDeps)` | — | The PydanticAI agent instance |
| `inject_user_profile` | `@agent.system_prompt(dynamic=True)` | `str` | Injects user profile into system prompt |
-->

---

## `bot.py` — Telegram Bot

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `create_application` | `(config: AppConfig) -> Application` | `Application` | Build and configure the telegram bot |
| `handle_message` | `async (update: Update, context: ContextTypes) -> None` | `None` | Main message handler: whitelist → agent → reply |
| `is_authorized` | `(user_id: int, config: AppConfig) -> bool` | `bool` | Check if user is in whitelist |
-->

---

## `tools/profile_tools.py` — Profile Agent Tools

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `update_user_note` | `@agent.tool async (ctx, note: str) -> str` | `str` | Add observation to user profile notes |
| `update_preference` | `@agent.tool async (ctx, key: str, value: str) -> str` | `str` | Update a specific user preference |
-->

---

## `tools/telegram_tools.py` — Telegram Agent Tools

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `send_inline_keyboard` | `@agent.tool async (ctx, text: str, buttons: list) -> str` | `str` | Send message with inline keyboard buttons |
| `send_image` | `@agent.tool async (ctx, url: str, caption: str) -> str` | `str` | Send image message to user |
-->

---

## `mcp/registry.py` — MCP Server Registry

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `MCPRegistry` | `class(config: AppConfig)` | — | Manages MCP server lifecycle |
| `MCPRegistry.get_toolsets` | `() -> list[FastMCPToolset]` | `list` | Get configured MCP toolset instances |
-->

---

## `mcp/servers.py` — MCP Server Configs

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `create_jellyseerr_toolset` | `(config: AppConfig) -> FastMCPToolset` | `FastMCPToolset` | Jellyseerr MCP toolset instance |
| `create_glances_toolset` | `(config: AppConfig) -> FastMCPToolset` | `FastMCPToolset` | Glances MCP toolset instance |
-->

---

## `main.py` — Entry Point

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `main` | `async () -> None` | `None` | Initialize everything, start bot |
-->

---

## 🧪 Test Helpers (`tests/conftest.py`)

_Not yet implemented._

<!-- Template for entries:
| Function/Class | Signature | Returns | Description |
|----------------|-----------|---------|-------------|
| `mock_config` | `fixture -> AppConfig` | `AppConfig` | Config with test values |
| `mock_deps` | `fixture -> AgentDeps` | `AgentDeps` | Full mock dependencies for agent tests |
| `test_db` | `fixture async (tmp_path) -> Path` | `Path` | Temporary initialized SQLite DB |
| `make_test_update` | `(text: str, user_id: int) -> Update` | `Update` | Mock Telegram Update object |
| `default_test_profile` | `() -> UserProfile` | `UserProfile` | UserProfile with test defaults |
-->

---

## 📝 How to Maintain This File

**When adding a function/class:**
1. Find the correct module section
2. Uncomment the table if it's the first entry (remove `_Not yet implemented._` and `<!-- -->` wrappers)
3. Add a row with: name, signature, return type, one-line description

**When modifying a function:**
1. Update the signature and description here to match

**When removing a function:**
1. Remove the row
2. If the module is now empty, restore the `_Not yet implemented._` placeholder

**When adding a new module:**
1. Add it to the Modules Overview table at the top
2. Add a new section with the module heading and table
