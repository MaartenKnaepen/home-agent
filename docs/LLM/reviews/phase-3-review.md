# Home Agent — Phase 3 Code Review

> **Reviewer:** Rovo Dev
> **Date:** 2026-03-04
> **Scope:** All source code (src/, mcp_servers/, deployment/), tests, and import-linter contracts
> **Verification status:** ✅ All checks passed (ty: 2 warnings, import-linter: 8 kept, pytest: 238 passed)

---

## 1. Executive Summary

Phase 3 of the Home Agent project demonstrates **strong architectural discipline and solid engineering fundamentals**. The codebase successfully enforces clean layer separation via import-linter, achieves comprehensive test coverage (238 tests), and maintains consistent coding patterns across 19 source files.

**Key strengths:**
- **Excellent architecture enforcement:** All 8 import-linter contracts pass, validating strict separation between bot/agent layers, tools/MCP layers, and core modules.
- **Strong test quality:** 238 tests with thoughtful use of `TestModel`, proper fixture design, and framework boundary testing (e.g., real `GuardedToolset` instances passed to agent, not mocked).
- **Clean async patterns:** Consistent use of async/await, proper context managers for MCP lifecycle, and defensive error handling.
- **Readable codebase:** Google-style docstrings, clear naming, and intentional code organization.

**Main improvement areas:**
1. **Type annotation warnings:** Two unused `type: ignore` directives in `formatting.py` (harmless but inconsistent with strict typing goals).
2. **Code duplication:** The `_invoke_agent()` function in `bot.py` is called from two places but handles both text and voice flows — could be refactored with better separation of concerns.
3. **Missing deployment docs:** `deployment/README.md` references "Jellyseerr MCP Server" but the codebase uses "Seerr/Overseerr" — documentation is stale.
4. **Test isolation minor issue:** Some tests create profiles with pre-saved state while others rely on auto-creation — inconsistent test setup patterns.

---

## 2. File-by-File Source Review

### `src/home_agent/config.py` — Configuration Management

**Responsibility:** Load and cache application configuration from environment variables using Pydantic Settings.

**What's good:**
- ✅ Proper use of `@lru_cache` to avoid re-parsing env vars multiple times.
- ✅ `SecretStr` for sensitive fields (API keys) — correct security practice.
- ✅ Clear default values and field documentation.
- ✅ Supports all required settings: LLM model, MCP port, retry delays, ASR URL.

**Improvements needed:**
- None identified. This module is well-designed and follows all guidelines.

---

### `src/home_agent/db.py` — Database Layer

**Responsibility:** Async SQLite operations for conversation history and user profile persistence.

**What's good:**
- ✅ Proper async/await with `aiosqlite`, no blocking I/O.
- ✅ Indexed `user_id` for efficient history queries.
- ✅ Defensive schema creation (CREATE TABLE IF NOT EXISTS).
- ✅ Type hints on all public functions.

**Improvements needed:**
- ⚠️ **Minor:** Functions like `get_history()` and `get_profile()` could benefit from more granular error handling — currently any exception bubbles up. Consider catching `aiosqlite.OperationalError` and logging context.
- ⚠️ **Minor:** `get_history()` builds the query twice (with and without LIMIT). Could be refactored to a single query builder to avoid duplication.

---

### `src/home_agent/profile.py` — User Profile Management

**Responsibility:** Pydantic models for user profiles and a `ProfileManager` for CRUD operations with database persistence.

**What's good:**
- ✅ Excellent use of `model_copy()` for immutable updates — consistent with Pydantic best practices.
- ✅ Smart auto-detection of Telegram language code to set initial reply language.
- ✅ Role resolution logic (`_resolve_role()`) properly enforces admin_telegram_ids at retrieval time, allowing dynamic promotion.
- ✅ Profile reconstruction from stored dict data handles nested `MediaPreferences` correctly.
- ✅ Comprehensive docstrings explaining all fields and edge cases.

**Improvements needed:**
- None identified. This module is exemplary.

---

### `src/home_agent/history.py` — Conversation History Management

**Responsibility:** High-level wrapper around `db.py` for conversation history, and a sliding-window history processor for PydanticAI.

**What's good:**
- ✅ Clean abstraction over raw database operations.
- ✅ `sliding_window_processor()` correctly handles incomplete pairs at window boundaries — preserves trailing incomplete sequences as required by PydanticAI's contract.
- ✅ `convert_history_to_messages()` carefully skips unknown roles instead of crashing.
- ✅ Well-commented logic explaining the windowing algorithm.

**Improvements needed:**
- ⚠️ **Minor:** `sliding_window_processor()` could add a doctest showing the window boundary behavior to clarify how trailing pairs are preserved.

---

### `src/home_agent/agent.py` — PydanticAI Agent Definition

**Responsibility:** Agent instantiation, system prompt injection, tool registration, and MCP toolset integration.

**What's good:**
- ✅ Proper `deps_type=AgentDeps` and dependency injection pattern.
- ✅ Dynamic system prompt injection via `@agent_instance.system_prompt(dynamic=True)` with user profile context.
- ✅ All tools return strings as required by PydanticAI.
- ✅ `RetryingModel` wrapper provides intelligent rate-limit retry logic.
- ✅ History processors configured with `sliding_window_processor(n=20)`.
- ✅ GuardedToolset instances properly passed (not mocked) to ensure PydanticAI validates the toolset protocol.

**Improvements needed:**
- ⚠️ **Minor:** `create_agent()` has 5 parameters for retry logic (`max_retries`, `base_delay`, `max_delay`) that mirror `RetryingModel`'s parameters. These could be bundled into a dataclass to reduce parameter count and improve readability.
- ⚠️ **Minor:** `get_agent_toolsets()` is a simple one-liner that just delegates to `registry.get_toolsets()`. It adds no value — consider removing and calling `registry.get_toolsets()` directly in `main.py`.

---

### `src/home_agent/bot.py` — Telegram Bot Wiring

**Responsibility:** Message handlers, voice transcription, callback queries, and reply formatting. **No business logic — pure framework wiring.**

**What's good:**
- ✅ Excellent separation: handlers are factories that return closures with captured state.
- ✅ Proper whitelist enforcement before any I/O (ASR call in voice handler).
- ✅ TCP keepalive socket options configured to prevent idle connection timeouts (great for long-running agent calls).
- ✅ Comprehensive error handling with specific messages for different failure modes (rate limit, ASR timeout, etc.).
- ✅ Message splitting respects Telegram's 4096-char limit and avoids breaking HTML tags.

**Improvements needed:**
- 🔴 **Code duplication — HIGH PRIORITY:** `_invoke_agent()` is called identically from `handle_message()` and `handle_voice()` with the same parameters. This function is 100+ lines and handles the entire agent lifecycle. The duplication creates maintenance burden. **Suggestion:** The function is already shared — this is actually fine. However, the separation between message and voice handlers could be clearer. Consider adding a comment at the call site explaining why both flows use the same invocation.
- ⚠️ **Minor:** `_split_message()` could use a list comprehension instead of the manual loop for clarity, though the current approach is defensible for HTML tag awareness.
- ⚠️ **Inconsistency:** Voice handler creates a fresh `_pending_confirmations = {}` (line 293) while message handler uses a captured reference. This is intentional (voice has no prior context) but the comment explains it — good.

---

### `src/home_agent/main.py` — Composition Root

**Responsibility:** Wire all components together and start the bot.

**What's good:**
- ✅ Clean lifecycle: config → logging → DB init → managers → MCP registry → agent → bot → polling.
- ✅ Proper `async with agent:` to manage MCP connections.
- ✅ Proper `async with app:` for Telegram application lifecycle.
- ✅ Logging at each major step for debuggability.
- ✅ Graceful shutdown via KeyboardInterrupt.

**Improvements needed:**
- None identified. This module is well-designed.

---

### `src/home_agent/prompts.py` — System Prompt

**Responsibility:** Define the static system prompt for the agent.

**What's good:**
- ✅ Comprehensive media request workflow documented clearly (search → disambiguate → quality → confirm → request).
- ✅ Clear instructions on tool usage (search_media always requires query, request_media requires mediaType/mediaId, etc.).
- ✅ Guidance on quality handling and language preferences.

**Improvements needed:**
- ⚠️ **Minor:** The prompt is 72 lines of multi-line strings. Consider breaking it into smaller logical sections with comments (e.g., "## Media Requests", "## Language", "## Tool Usage") to make future edits easier.

---

### `src/home_agent/formatting.py` — Markdown to Telegram HTML Conversion

**Responsibility:** Convert LLM Markdown output to Telegram-safe HTML.

**What's good:**
- ✅ Robust token-based parsing using markdown-it-py instead of regex — avoids fragile string patterns.
- ✅ Graceful fallback to plain text on parse errors.
- ✅ Proper HTML escaping to prevent injection.
- ✅ Telegram tag whitelist enforced (supports b, i, u, s, code, pre, a, tg-spoiler, blockquote).

**Improvements needed:**
- 🔴 **Type annotation warning — HIGH PRIORITY:** Two unused `type: ignore[type-arg]` and `type: ignore[attr-defined]` directives at lines 61 and 180. These should be removed or the underlying type issue fixed. **Suggestion:** The function signature `def _render_token(token: object, out: list[str]) -> None:` with `# type: ignore[type-arg]` is odd — consider properly typing `token` as a protocol or union type from markdown-it-py's public API.

---

### `src/home_agent/tools/profile_tools.py` — Profile Update Tools

**Responsibility:** Agent tools for updating user preferences (quality, language, confirmation mode).

**What's good:**
- ✅ All tools follow the pattern: read profile, create updated copy via `model_copy()`, persist, return confirmation.
- ✅ Proper use of `RunContext[Any]` to access dependencies without circular imports.
- ✅ Clear docstrings explaining when and why to call each tool.
- ✅ Consistent logging at INFO level for audit trail.

**Improvements needed:**
- None identified. Clean and consistent.

---

### `src/home_agent/tools/telegram_tools.py` — Telegram Rich UX Tools

**Responsibility:** Agent tools for sending confirmation keyboards and poster images.

**What's good:**
- ✅ `send_confirmation_keyboard()` properly constructs inline keyboards with callback data.
- ✅ `send_poster_image()` safely constructs TMDB CDN URLs from partial paths.
- ✅ Defensive fallback messages when bot context is unavailable (e.g., in tests).
- ✅ Exception handling for image send failures (network, bad URL, etc.).

**Improvements needed:**
- ⚠️ **Minor:** `send_poster_image()` silently skips if posterPath is None, but logs at DEBUG. Consider logging at INFO for visibility, since this is a deliberate fallback.

---

### `src/home_agent/mcp/registry.py` — MCP Server Registry

**Responsibility:** Manage MCP server configurations and create GuardedToolset-wrapped FastMCPToolsets.

**What's good:**
- ✅ Simple registry pattern — register servers, get toolsets.
- ✅ Properly wraps each FastMCPToolset in GuardedToolset, enforcing quality/confirmation/role gates.
- ✅ Filtering by `enabled` flag allows disabling servers without code changes.

**Improvements needed:**
- None identified. Well-designed.

---

### `src/home_agent/mcp/servers.py` — MCP Server Configuration

**Responsibility:** Define ServerConfig dataclass and factory for Seerr MCP server.

**What's good:**
- ✅ Clean dataclass design with sensible defaults.
- ✅ `get_seerr_config()` reads MCP_HOST from environment, allowing Docker Compose to override via `MCP_HOST=seerr-mcp`.
- ✅ Default to `localhost` for local development.

**Improvements needed:**
- None identified. Well-designed.

---

### `src/home_agent/mcp/guarded_toolset.py` — MCP Tool Call Middleware

**Responsibility:** Wrap FastMCPToolset and enforce gates on tool calls (quality, role, confirmation).

**What's good:**
- ✅ **Excellent design:** Properly subclasses `AbstractToolset` so PydanticAI validates the contract — not bypassed by mocks.
- ✅ Stateless design — all per-user state read from `ctx.deps` created fresh per message.
- ✅ Clear gate order and error messages that the LLM understands.
- ✅ Tracks successful tool calls in `ctx.deps.called_tools`.
- ✅ Resets `confirmed` after successful `request_media` to require fresh confirmation for next request.

**Improvements needed:**
- None identified. This is exemplary middleware.

---

### `src/home_agent/models/retry_model.py` — Retry Model Wrapper

**Responsibility:** Wrap any PydanticAI Model and retry on HTTP 429 with exponential backoff.

**What's good:**
- ✅ Lazy model resolution from string (honouring `defer_model_check` semantics).
- ✅ Exponential backoff with configurable `max_delay` cap.
- ✅ Optional `on_retry` callback for observability.
- ✅ Properly delegates streaming without retry (stateful, can't replay).
- ✅ Excellent docstrings explaining retry semantics.

**Improvements needed:**
- None identified. Well-designed.

---

### MCP Servers (`mcp_servers/`)

#### `mcp_servers/qwen3_asr/server.py` — Qwen3 ASR Service

**Responsibility:** FastMCP server wrapping Hugging Face's Qwen3-ASR model for audio transcription.

**What's good:**
- ✅ Simple, focused service — one tool (`transcribe`) that does one thing well.
- ✅ Proper error handling for file operations and model inference.
- ✅ Health check endpoint for Docker Compose readiness.
- ✅ Caches model in memory to avoid reload-per-request.

**Improvements needed:**
- None identified for Phase 3 scope.

#### `mcp_servers/seerr/` — Seerr (Overseerr) MCP Server

**Responsibility:** TypeScript/Node MCP server wrapping the Seerr API for media search and request management.

**What's good:**
- ✅ Well-structured TypeScript project with proper types.
- ✅ Implements search, request, and details tools.
- ✅ Cache and retry utilities for resilience.

**Improvements needed:**
- This is a contributed/external project — no Python-specific review needed for Phase 3.

---

### Deployment (`deployment/`)

#### `deployment/docker-compose.yml` — Docker Compose Configuration

**Responsibility:** Orchestrate home-agent, seerr-mcp, and qwen3-asr services.

**What's good:**
- ✅ Proper health checks on ASR and MCP services before starting agent.
- ✅ Volume persistence for database and HuggingFace model cache.
- ✅ Environment variable injection from `.env`.
- ✅ TCP keepalive configuration in home-agent service (inherited from bot.py improvements).
- ✅ Network modes and extra_hosts configured for Docker → host connectivity.

**Improvements needed:**
- ⚠️ **Minor:** Home-agent uses `network_mode: host` which disables Docker network isolation. This is documented as a trade-off but worth revisiting if the original TCP timeout issue is fixed in future versions of python-telegram-bot.
- ⚠️ **Documentation mismatch:** README references "Jellyseerr" but compose file uses "Seerr" — see deployment/README.md section below.

#### `deployment/README.md` — Deployment Documentation

**Responsibility:** Guide operators through deployment.

**What's good:**
- ✅ Clear prerequisites and configuration steps.
- ✅ Troubleshooting section covers common issues.

**Improvements needed:**
- 🔴 **STALE DOCUMENTATION — HIGH PRIORITY:** 
  - Line 4: "## Jellyseerr MCP Server" should be "## Seerr (Overseerr) MCP Server"
  - Line 16: `JELLYSEERR_URL` and `JELLYSEERR_API_KEY` should be `SEERR_URL` and `SEERR_API_KEY`
  - Line 61: URL references port 5056 but the codebase uses 8085 by default (MCP_PORT env var)
  - Update all references to match the actual Seerr service name

---

## 3. Test Suite Review

### Overall Assessment

**Excellent test quality across 238 tests spanning 19 test files. The suite demonstrates sophisticated understanding of framework boundary testing and proper use of test doubles.**

Key statistics:
- **Total tests:** 238
- **Passing:** 238 (100%)
- **Average test file size:** ~270 lines
- **Key files:** `test_agent.py` (590 lines), `test_bot.py` (483 lines), `test_guarded_toolset.py` (690 lines)

### Test Coverage by Module

| Module | Test File | Tests | Coverage Quality |
|--------|-----------|-------|-----------------|
| config | test_config.py | ~10 | ✅ Solid (env parsing, defaults) |
| db | test_db.py | ~15 | ✅ Good (CRUD, temp DB via tmp_path) |
| profile | test_profile.py | ~20 | ✅ Excellent (auto-creation, language resolution, role assignment) |
| history | test_history.py | ~12 | ✅ Good (message persistence, sliding window) |
| agent | test_agent.py | ~25 | ✅ Excellent (tools, system prompt injection, framework boundary) |
| bot | test_bot.py | ~30 | ✅ Excellent (handlers, authorization, error handling, callback queries) |
| guarded_toolset | test_guarded_toolset.py | ~35 | ✅ Excellent (gates, role enforcement, framework boundary) |
| formatting | test_formatting.py | ~20 | ✅ Good (markdown to HTML, edge cases) |
| tools | test_profile_tools.py, test_telegram_tools.py | ~20 | ✅ Good (tool side-effects, failures) |
| retry_model | test_retry_model.py | ~15 | ✅ Excellent (exponential backoff, 429 handling) |
| mcp_registry | test_mcp_registry.py | ~10 | ✅ Good (toolset wrapping) |
| integration/multi-user | test_integration.py, test_multi_user.py | ~20 | ✅ Good (end-to-end flows, concurrent users) |
| voice | test_voice.py | ~15 | ✅ Good (ASR transcription, error handling) |
| docker | test_docker.py | ~5 | ✅ Sanity (compose file validity) |
| main | test_main.py | ~5 | ✅ Good (wiring, lifecycle) |

### What's Good in Tests

- **🏆 Framework boundary testing:** Tests like `test_create_agent_with_guarded_toolsets()` in test_agent.py use **real GuardedToolset instances** (not mocked) passed to the agent. This exercises PydanticAI's AbstractToolset protocol validation and prevents false-positive test passes.
- **🏆 Fixture design:** conftest.py provides reusable `mock_config`, `test_db`, and helper functions like `make_test_update()`. Reduces boilerplate and improves test readability.
- **🏆 TestModel usage:** All agent tests use `TestModel()` from PydanticAI — never real LLMs. Tests configure `custom_output_text`, `call_tools`, and inspect `last_model_request_parameters`.
- **🏆 Database isolation:** All DB tests use `tmp_path` for isolated test databases, avoiding cross-test pollution.
- **🏆 Comprehensive error scenarios:** Tests cover rate limits (429), ASR timeouts, authorization failures, empty agent output, and malformed callback data.
- **🏆 Message splitting verified:** Tests confirm long replies are split at 4096-char boundaries while preserving HTML tags.
- **🏆 Role-based access control:** GuardedToolset tests verify read_only users cannot call request_media, and quality gates block requests when preferences aren't set.

### Improvements Needed in Tests

- ⚠️ **Minor inconsistency:** Some tests pre-save profiles (`await profile_manager.save(profile)`) while others rely on auto-creation in the first `profile_manager.get()` call. This works but creates two test patterns. **Suggestion:** Standardize on either auto-creation or explicit save, document the pattern in conftest.py.
- ⚠️ **Missing test:** No test for the scenario where a user calls `send_poster_image()` with a valid path but the TMDB CDN URL returns a 404. Currently the exception is silently caught and logged — a test would verify this graceful fallback works.
- ⚠️ **Missing edge case:** No test for the `_split_message()` function when a single line exceeds 4096 chars (line 172-178 in bot.py handles this case but isn't tested explicitly).

---

## 4. Architecture & Design Decisions

### Import-Linter Contract Review

Read the `[tool.importlinter]` section in `pyproject.toml` (lines 37-133). All 8 contracts are **correct and up-to-date**:

| Contract | Status | Notes |
|----------|--------|-------|
| config is independent | ✅ KEPT | Correct — config imports no internal modules |
| db only imports config and shared | ✅ KEPT | Correct — db is layer 1 |
| history only imports config and db | ✅ KEPT | Correct — history is layer 1b |
| profile does not import history | ✅ KEPT | Correct — peer modules kept separate |
| tools, mcp and models do not import agent or bot | ✅ KEPT | Correct — tools are layer 2, cannot import layer 3+ |
| agent does not import bot or main | ✅ KEPT | Correct — prevents circular dependencies |
| bot does not import main | ✅ KEPT | Correct — bot is layer 3 |
| other modules do not import main | ✅ KEPT | Correct — main is composition root, no dependencies on it |

**Assessment:** The contracts perfectly reflect the intended architecture. No gaps, no stale entries, no new modules that need contract coverage.

### Architecture Strengths

1. **Layer enforcement:** Bot/Agent are cleanly separated. Business logic lives in core modules (profile, history, config). Tools are pure functions without framework coupling.
2. **Dependency injection:** AgentDeps captures per-user state without coupling tool functions to framework details.
3. **Stateless middleware:** GuardedToolset is reusable across all users because it reads state from ctx.deps.
4. **Lifecycle management:** Proper use of async context managers (`async with agent:`, `async with app:`) ensures MCP and Telegram connections are opened/closed correctly.

### Architecture Near-Issues (None identified)

The architecture is sound. No layer violations detected, no business logic in handlers, proper separation of concerns throughout.

---

## 5. What Was Done Well

### 🏆 Top Highlights

1. **Framework boundary testing discipline** — Tests for classes that integrate with PydanticAI (GuardedToolset, agent tools) exercise real instances, not mocks. This catches protocol violations that mocks would hide.

2. **Stateless, concurrent-safe design** — GuardedToolset and tools store no user state. All state comes from ctx.deps created fresh per message. This enables safe multi-user concurrency without locks.

3. **Defensive error handling with specific messaging** — When quality is not set, GuardedToolset returns "STOP: movie_quality not set. Ask the user..." — the LLM reads this and responds appropriately. No silent failures.

4. **Lazy model resolution** — `RetryingModel` resolves the inner model from a string on first use, deferring API key validation. This allows tests to run without real API credentials.

5. **Comprehensive system prompt** — The static prompt in `prompts.py` guides the agent through a clear media-request workflow (search → disambiguate → quality → confirm → request) with specific tool usage rules.

6. **TCP keepalive configuration** — `bot.py` configures socket-level TCP keepalive probes to prevent connection timeouts during long agent runs. This is a sophisticated solution to a real deployment problem.

7. **Message splitting respects HTML** — The `_split_message()` function splits by newline only, never within tags, preventing broken Telegram output.

8. **Clean composition root** — `main.py` wires all components in a clear, logical sequence with logging at each step.

---

## 6. Issues & Improvements Needed

### 🔴 High Priority

1. **Stale deployment documentation** (`deployment/README.md` lines 4, 16, 61)
   - **Problem:** References "Jellyseerr" and outdated port/URL config; actual codebase uses "Seerr/Overseerr" and port 8085.
   - **Impact:** Operators may follow incorrect setup instructions.
   - **Fix:** Update all references in deployment/README.md to match current service names and default ports. Reference the actual `SEERR_URL` and `SEERR_API_KEY` env vars from docker-compose.yml.

2. **Type annotation warnings in formatting.py** (lines 61, 180)
   - **Problem:** Unused `type: ignore[type-arg]` and `type: ignore[attr-defined]` directives. These suppress warnings that are no longer triggered, creating technical debt.
   - **Impact:** Type checking verbosity; future maintainers may assume these are needed when they aren't.
   - **Fix:** Remove the type: ignore comments and verify types pass. If markdown-it-py's token types are weak, consider typing the function parameter as a protocol or using `TYPE_CHECKING` imports.

### 🟡 Medium Priority

3. **Code duplication opportunity in retry parameters** (`agent.py`, lines 76-78)
   - **Problem:** `create_agent()` takes 3 separate parameters (`max_retries`, `base_delay`, `max_delay`) that are immediately passed to `RetryingModel()`. These could be bundled.
   - **Impact:** Slightly harder to read function signature; must remember the parameter order.
   - **Fix:** Create a dataclass (e.g., `RetryConfig`) or named tuple to bundle these, reducing parameter count and improving clarity.

4. **Unnecessary wrapper function** (`agent.py`, lines 195-204)
   - **Problem:** `get_agent_toolsets(registry)` is a one-liner that delegates to `registry.get_toolsets()`. It adds no value.
   - **Impact:** Extra indirection; future readers must trace the call to understand what's happening.
   - **Fix:** Remove `get_agent_toolsets()` and call `registry.get_toolsets()` directly in `main.py` (line 72).

5. **Minor error handling gaps in db.py**
   - **Problem:** Functions like `get_history()` and `get_profile()` don't explicitly catch `aiosqlite.OperationalError` or other DB exceptions. Any error bubbles up.
   - **Impact:** Caller must handle DB errors; limited context if something goes wrong.
   - **Fix:** Add try/except blocks with specific error logging, or document that callers must handle exceptions.

6. **Test setup inconsistency**
   - **Problem:** Some tests pre-save profiles with `await profile_manager.save(profile)` while others rely on auto-creation in `profile_manager.get()`. Two patterns exist.
   - **Impact:** Makes test intent unclear; new test writers may choose the wrong pattern.
   - **Fix:** Document the preferred pattern in conftest.py with a comment explaining when to pre-save vs. auto-create.

### 🟢 Low Priority

7. **Minor clarity improvement in bot.py comments**
   - **Problem:** `_invoke_agent()` is shared between text and voice handlers. A one-liner comment would clarify why.
   - **Impact:** Code is already clear, but a comment would help future maintainers.
   - **Fix:** Add comment above the call to `_invoke_agent()` in both handlers: "Both handlers converge on the same agent invocation logic here."

8. **Logging level inconsistency in telegram_tools.py**
   - **Problem:** `send_poster_image()` logs at DEBUG when posterPath is None (line 118), but this is a deliberate fallback path that might be worth INFO.
   - **Impact:** Operators may miss visibility into why posters aren't being sent.
   - **Fix:** Change `logger.debug()` to `logger.info()` on line 118 for better observability.

9. **History processor doctest**
   - **Problem:** `sliding_window_processor()` could benefit from a doctest showing the boundary behavior (how trailing incomplete pairs are handled).
   - **Impact:** Future maintainers must read the full function to understand the windowing algorithm.
   - **Fix:** Add a doctest example showing a window with an incomplete trailing pair.

---

## 7. Recommendations for Next Phase

### Priority-Ordered Action Items

1. **Fix stale deployment docs (HIGH)** — Update `deployment/README.md` to reference Seerr, correct port numbers, and actual env var names. This unblocks operators following the guide.

2. **Remove type: ignore warnings (HIGH)** — Clean up the two unused directives in `formatting.py` so type checking output is clean and future warnings are visible.

3. **Refactor retry parameters into dataclass (MEDIUM)** — Bundle `max_retries`, `base_delay`, `max_delay` into a `RetryConfig` dataclass. Improves `create_agent()` signature clarity and makes retry logic portable.

4. **Remove `get_agent_toolsets()` wrapper (MEDIUM)** — Call `registry.get_toolsets()` directly in `main.py` to remove unnecessary indirection.

5. **Standardize test setup patterns (MEDIUM)** — Document whether tests should pre-save profiles or rely on auto-creation. Add a helper function in conftest.py if needed.

6. **Add missing edge-case test (LOW)** — Test `_split_message()` with a single line exceeding 4096 chars to verify the fallback path (lines 172-178 in bot.py).

7. **Improve observability in telegram_tools.py (LOW)** — Change `send_poster_image()` debug log to info when posterPath is None.

### Future Phase Considerations

- **Database: Consider adding a migration system** if schema changes become common (e.g., Alembic for aiosqlite).
- **Monitoring: Instrument guarded_toolset gate failures** with metrics (Prometheus, StatsD) to track how often quality/confirmation gates are triggered.
- **Testing: Add integration tests that exercise the full stack** (agent ↔ MCP ↔ mock Seerr API) to catch cross-layer issues.
- **Documentation: Create an architecture decision record (ADR)** explaining why GuardedToolset is stateless and how it enables concurrency.

---

*End of review.*
