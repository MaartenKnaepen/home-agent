# Home Server Telegram Agent — Implementation Tasks

---

## 🏗️ Phase 1: MVP — Telegram + Jellyseerr
**Focus:** A working bot that can search and request media via natural language conversation.

- [ ] **Step 1.1: Project Scaffolding**
    - **Goal:** Runnable Python project with validated config loading.
    - **Files:** `pyproject.toml`, `src/home_agent/__init__.py`, `src/home_agent/config.py`, `.env.example`
    - **Scope:** `src/` package layout; `pydantic-settings` `AppConfig` model with fields for `TELEGRAM_BOT_TOKEN`, `OPENROUTER_API_KEY`, `JELLYSEERR_URL`, `JELLYSEERR_API_KEY`, `ALLOWED_TELEGRAM_IDS`; `.env.example` with all keys documented.
    - **Test:** `test_config.py` — Config loads from env vars; missing required vars raise `ValidationError`; `ALLOWED_TELEGRAM_IDS` parses comma-separated list of ints.

- [ ] **Step 1.2: SQLite Database Layer**
    - **Goal:** Async database with schema migrations for conversations and profiles.
    - **File:** `src/home_agent/db.py`
    - **Scope:** `aiosqlite` connection manager; `init_db()` creates tables (`conversations`, `user_profiles`); helper functions: `save_message()`, `get_history()`, `save_profile()`, `get_profile()`.
    - **Test:** `test_db.py` — `init_db()` creates tables; `save_message()` + `get_history()` round-trips messages per user; `save_profile()` + `get_profile()` round-trips a profile JSON blob; empty history returns empty list.

- [ ] **Step 1.3: User Profile Model**
    - **Goal:** Pydantic models for user profile with serialization to/from SQLite.
    - **File:** `src/home_agent/profile.py`
    - **Scope:** `UserProfile`, `MediaPreferences`, `NotificationPrefs` Pydantic models; `ProfileManager` class that reads/writes profiles via `db.py`; default profile creation for new users.
    - **Test:** `test_profile.py` — Default profile has sensible defaults; profile serializes to JSON and deserializes back identically; `ProfileManager` creates default profile for unknown user; `ProfileManager` updates and persists profile fields.

- [ ] **Step 1.4: Conversation History & Processor**
    - **Goal:** Store full history in SQLite, send only a sliding window to the LLM.
    - **File:** `src/home_agent/history.py`
    - **Scope:** `HistoryManager` class wrapping `db.py` for message CRUD; `sliding_window_processor` compatible with PydanticAI's `history_processors` — keeps last N message pairs; user profile injected into system prompt context.
    - **Test:** `test_history.py` — Full history preserved in DB; sliding window with N=5 returns only last 5 message pairs from a 20-message history; tool-call/tool-result pairs are not split across the window boundary.

- [ ] **Step 1.5: Telegram Bot Skeleton**
    - **Goal:** Bot connects to Telegram, receives messages, enforces user whitelist.
    - **File:** `src/home_agent/bot.py`
    - **Scope:** `python-telegram-bot` Application setup with polling (webhook later); message handler that receives text; user whitelist check against `ALLOWED_TELEGRAM_IDS`; unauthorized users get a rejection message; typing indicator while processing.
    - **Test:** `test_bot.py` — Whitelisted user's message is forwarded to handler; non-whitelisted user gets rejection; bot sends typing action before responding.

- [ ] **Step 1.6: PydanticAI Agent Setup**
    - **Goal:** Agent configured with OpenRouter, system prompt, dependency injection.
    - **File:** `src/home_agent/agent.py`
    - **Scope:** PydanticAI `Agent` with OpenRouter model (free tier); system prompt template that includes user profile context and confirmation rules; `AgentDeps` dataclass with `profile_manager`, `history_manager`, `config`; profile update tool registered on the agent.
    - **Test:** `test_agent.py` — Agent instantiates without error; system prompt contains user profile data when provided; profile update tool modifies profile via `ProfileManager`.

- [ ] **Step 1.7: Jellyseerr MCP Server**
    - **Goal:** MCP server exposing Jellyseerr search and request capabilities.
    - **Scope:** Search for existing community MCP server first. If none found/working, build with FastMCP. Core tools: `search_media(query)` → list of results; `get_media_details(id)` → full details; `request_media(id, quality)` → submit request; `get_request_status(id)` → check status.
    - **File:** `mcp_servers/jellyseerr/server.py` (only if self-built)
    - **Test:** `test_jellyseerr_mcp.py` — MCP server starts and lists expected tools; `search_media` returns structured results against a mock Jellyseerr API; `request_media` sends correct POST to Jellyseerr API; invalid media ID returns an error, not a crash.

- [ ] **Step 1.8: MCP Registry & Lifecycle**
    - **Goal:** Central place to configure, start, and stop MCP server connections.
    - **Files:** `src/home_agent/mcp/registry.py`, `src/home_agent/mcp/servers.py`
    - **Scope:** `MCPRegistry` class that holds MCP server configs; `start()` / `stop()` lifecycle methods; servers configured via `AppConfig`; registry passed to agent as toolsets.
    - **Test:** `test_mcp_registry.py` — Registry starts and stops MCP servers without error; registry exposes tool list from connected servers; agent can call tools through registry.

- [ ] **Step 1.9: Wire It Together**
    - **Goal:** End-to-end flow: Telegram message → Agent → MCP tools → Telegram reply.
    - **File:** `src/home_agent/main.py`
    - **Scope:** `main()` entry point that initializes config, DB, registry, agent, and bot; message handler passes user text + history to agent, returns response to Telegram; conversation persisted after each exchange; graceful shutdown of MCP servers and DB.
    - **Test:** `test_integration.py` — Simulated message flow: user sends "search for Inception" → agent calls Jellyseerr search tool → response contains movie info; conversation is persisted in DB after exchange.

- [ ] **Step 1.10: Docker Deployment**
    - **Goal:** Single-command deployment on home server.
    - **Files:** `Dockerfile`, `docker-compose.yml`
    - **Scope:** Multi-stage Dockerfile (build + runtime); `docker-compose.yml` with env_file, volume for SQLite persistence, restart policy; health check endpoint (optional).
    - **Test:** `docker build` succeeds; `docker-compose up` starts the bot without errors; container logs show successful Telegram connection.

---

## 📊 Phase 2: Glances Integration
**Focus:** Add system monitoring via Glances MCP server.

- [ ] **Step 2.1: Find or Build Glances MCP Server**
    - **Goal:** MCP server exposing Glances system metrics.
    - **Scope:** Search GitHub / MCP registries for existing Glances MCP server. Evaluate if it covers: CPU, memory, disk, network, per-container stats. If none found, build with FastMCP wrapping Glances REST API. Core tools: `get_system_overview()`, `get_cpu()`, `get_memory()`, `get_disk()`, `get_network()`, `get_containers()`.
    - **File:** `mcp_servers/glances/server.py` (only if self-built)
    - **Test:** `test_glances_mcp.py` — MCP server starts and lists expected tools; `get_system_overview` returns structured CPU/mem/disk data against a mock Glances API; handles Glances API being unreachable gracefully.

- [ ] **Step 2.2: Register Glances in MCP Registry**
    - **Goal:** Glances MCP server loads alongside Jellyseerr on agent startup.
    - **File:** `src/home_agent/mcp/servers.py` (update)
    - **Scope:** Add Glances server config; `GLANCES_URL` added to `AppConfig`; registry starts both servers.
    - **Test:** `test_mcp_registry.py` (update) — Registry with two servers starts both; agent tool list includes both Jellyseerr and Glances tools.

- [ ] **Step 2.3: System Prompt Update**
    - **Goal:** Agent knows how to use system monitoring and formats stats readably.
    - **File:** `src/home_agent/agent.py` (update)
    - **Scope:** System prompt extended with monitoring capabilities and formatting guidance (e.g., use emoji for status indicators, warn if disk > 80%).
    - **Test:** `test_agent.py` (update) — Agent presented with "how's my server?" generates a response that includes CPU/memory stats (mocked MCP); agent flags high disk usage when disk > 80%.

---

## 🔌 Phase 3: Expand Services
**Focus:** Add MCP servers one at a time. Each follows the same pattern: find existing → evaluate → connect → test.

- [ ] **Step 3.1: Immich MCP Server**
    - **Goal:** Photo management via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `search_photos(query, date_range)`, `get_album_list()`, `get_storage_stats()`. System prompt update for photo-related queries.
    - **Test:** `test_immich_mcp.py` — Tools return structured data from mock API; search with date range filters correctly; agent responds to "show me photos from last weekend" with photo results.

- [ ] **Step 3.2: Mealie MCP Server**
    - **Goal:** Recipe and meal plan management via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `search_recipes(query)`, `get_meal_plan(date)`, `add_to_meal_plan(recipe_id, date)`, `get_shopping_list()`. System prompt update.
    - **Test:** `test_mealie_mcp.py` — Recipe search returns results; meal plan queries return structured daily plan; adding to meal plan sends correct request.

- [ ] **Step 3.3: BabyBuddy MCP Server**
    - **Goal:** Baby tracking via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `log_feeding(type, amount, time)`, `log_diaper(type, time)`, `log_sleep(start, end)`, `get_last_event(type)`, `get_daily_summary()`. System prompt update.
    - **Test:** `test_babybuddy_mcp.py` — Logging events sends correct data; `get_last_event("diaper")` returns most recent entry; daily summary aggregates correctly.

- [ ] **Step 3.4: Paperless-ngx MCP Server**
    - **Goal:** Document search and management via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `search_documents(query)`, `get_document(id)`, `add_tag(doc_id, tag)`, `get_tags()`. System prompt update.
    - **Test:** `test_paperless_mcp.py` — Document search returns results with title, date, tags; tag operations modify document metadata correctly.

- [ ] **Step 3.5: Vikunja MCP Server**
    - **Goal:** Task management via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `get_tasks(list, filter)`, `create_task(title, list, due_date)`, `complete_task(id)`, `get_lists()`. System prompt update.
    - **Test:** `test_vikunja_mcp.py` — Task creation returns task with ID; listing tasks returns structured list; completing a task updates its status.

- [ ] **Step 3.6: Uptime Kuma MCP Server**
    - **Goal:** Service uptime monitoring via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `get_monitors()`, `get_monitor_status(id)`, `get_heartbeat(id)`. System prompt update.
    - **Test:** `test_uptimekuma_mcp.py` — Monitor list returns all configured monitors with status; heartbeat returns uptime percentage; agent responds to "is everything online?" with a summary.

- [ ] **Step 3.7: Portainer MCP Server**
    - **Goal:** Docker container management via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `list_containers()`, `get_container(name)`, `restart_container(name)`, `get_container_logs(name, lines)`. System prompt update. **Confirmation required** for restart/stop actions.
    - **Test:** `test_portainer_mcp.py` — Container listing returns names and statuses; restart sends correct API call; agent asks for confirmation before restarting.

- [ ] **Step 3.8: Duplicati MCP Server**
    - **Goal:** Backup status monitoring via natural language.
    - **Scope:** Find existing MCP server. Tools needed: `list_backups()`, `get_backup_status(id)`, `get_last_run(id)`. System prompt update.
    - **Test:** `test_duplicati_mcp.py` — Backup listing returns backup jobs with last run time; status shows healthy/warning/error state.

- [ ] **Step 3.9: Tool Filtering & Context-Aware Loading**
    - **Goal:** Only load relevant MCP servers per conversation to reduce token cost.
    - **File:** `src/home_agent/mcp/registry.py` (update)
    - **Scope:** Classify incoming message to determine which MCP servers are relevant; lazy-connect only those servers for the agent call; disconnect idle servers after timeout.
    - **Test:** `test_tool_filtering.py` — Message "search for a movie" only loads Jellyseerr tools; message "how's my server" only loads Glances tools; message "is everything online" only loads Uptime Kuma tools; ambiguous message loads all tools.

---

## ✨ Phase 4: Polish & Advanced Features
**Focus:** Rich UX, proactive behavior, multi-user, and extended capabilities.

- [ ] **Step 4.1: Rich Telegram Formatting**
    - **Goal:** Responses use inline keyboards, images, and formatted text.
    - **File:** `src/home_agent/tools/telegram_tools.py`
    - **Scope:** Agent tool to send inline keyboard buttons (e.g., confirm/deny); agent tool to send images (movie posters fetched from TMDB/Jellyseerr); Markdown formatting for structured responses.
    - **Test:** `test_telegram_tools.py` — Inline keyboard tool produces correct Telegram markup; image tool fetches and sends a photo message; Markdown output is valid Telegram MarkdownV2.

- [ ] **Step 4.2: Proactive Notifications**
    - **Goal:** Bot notifies user when downloads complete or issues arise.
    - **File:** `src/home_agent/notifications.py`
    - **Scope:** Periodic poller (or Jellyseerr webhook receiver) that checks for completed downloads; pushes notification to user via Telegram; respects `quiet_hours` from user profile.
    - **Test:** `test_notifications.py` — Completed download triggers a Telegram message; notification suppressed during quiet hours; duplicate notifications are not sent.

- [ ] **Step 4.3: Multi-User Support**
    - **Goal:** Multiple users with separate profiles and permission levels.
    - **File:** `src/home_agent/profile.py`, `src/home_agent/bot.py` (update)
    - **Scope:** Per-user profile isolation; permission levels (admin, user, read-only); admin can manage other users' permissions via chat.
    - **Test:** `test_multi_user.py` — Two users have separate profiles and histories; read-only user can search but not request; admin can modify permissions.

- [ ] **Step 4.4: Voice Message Support**
    - **Goal:** User sends voice message, agent processes it as text.
    - **File:** `src/home_agent/bot.py` (update)
    - **Scope:** Voice message handler that downloads audio; transcription via Whisper (local or API); transcribed text fed to agent as normal message.
    - **Test:** `test_voice.py` — Voice message handler extracts audio file; transcription produces text; agent receives transcribed text and responds normally.

- [ ] **Step 4.5: IT Tools / BentoPDF / Vert Integration**
    - **Goal:** File conversion capabilities via natural language.
    - **Scope:** Find existing MCP servers. Tools needed: `convert_file(input_path, output_format)`, `list_supported_formats()`. Agent can receive a file via Telegram, convert it, and send back the result.
    - **Test:** `test_conversion_mcp.py` — Supported formats list is returned; conversion request sends correct payload; agent handles unsupported format gracefully with a helpful message.
