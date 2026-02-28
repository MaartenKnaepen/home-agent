# Home Agent — Phase 1 & 2 Code Review

> **Reviewer:** Rovo Dev  
> **Date:** 2026-02-27  
> **Scope:** All source code, tests, and task plans for Phases 1 (Core Infrastructure) and 2 (User Experience & Profile)  
> **Verification status:** ✅ 104 tests pass, ty clean, 7/7 import-linter contracts green

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [File-by-File Source Review](#2-file-by-file-source-review)
3. [Test Suite Review](#3-test-suite-review)
4. [Plan Quality Review](#4-plan-quality-review)
5. [Architecture & Design Decisions](#5-architecture--design-decisions)
6. [What Was Done Well](#6-what-was-done-well)
7. [Issues & Improvements Needed](#7-issues--improvements-needed)
8. [Suboptimal Plan Suggestions](#8-suboptimal-plan-suggestions)
9. [Recommendations for Phase 3](#9-recommendations-for-phase-3)

---

## 1. Executive Summary

Phases 1 and 2 deliver a solid, well-architected Telegram bot backed by PydanticAI with MCP integration. The codebase follows the project's coding guidelines consistently: async-first I/O, type hints everywhere, Google-style docstrings, proper import layering, and Pydantic models for structured data. The 104-test suite covers core logic, edge cases, and integration flows. The project is in excellent shape for Phase 3.

**Overall quality: Strong.** The main areas for improvement are minor: some defensive coding gaps in `db.py`, a few inconsistencies in profile tool mutation patterns, and several plan files that suggested suboptimal designs that were correctly rejected during implementation.

---

## 2. File-by-File Source Review

### `src/home_agent/config.py` — Application Configuration

**Responsibility:** Loads all application settings from environment variables using `pydantic-settings`. Defines `AppConfig` with secrets (`SecretStr`), optional Jellyseerr quality profile IDs, LLM retry settings, and a cached `get_config()` singleton.

**What's good:**
- `SecretStr` used for all sensitive fields (`telegram_bot_token`, `openrouter_api_key`, `jellyseerr_api_key`) — prevents accidental logging of secrets
- `field_validator` for Jellyseerr profile IDs rejects zero and negative values with a single decorator covering both fields
- `lru_cache` on `get_config()` ensures singleton pattern
- `db_path` uses `Path` type — follows pathlib guideline
- All fields have sensible defaults, making the bot work out of the box

**Improvements needed:**
- `lru_cache` on `get_config()` makes it impossible to reconfigure in tests without calling `get_config.cache_clear()` first. Tests already do this (see `test_config.py:37`), but it's fragile. Consider documenting this or providing a `reset_config()` helper.
- No validation on `llm_model` string format — an invalid model string will only fail at runtime on first request. Acceptable given lazy resolution, but a regex validator could catch typos early.

---

### `src/home_agent/db.py` — Async Database Layer

**Responsibility:** Low-level async SQLite operations using `aiosqlite`. Provides `init_db()`, `save_message()`, `get_history()`, `save_profile()`, and `get_profile()` functions.

**What's good:**
- Clean separation — pure data access, no business logic
- `init_db()` creates parent directories with `mkdir(parents=True, exist_ok=True)`
- Upsert pattern for `save_profile()` using `ON CONFLICT ... DO UPDATE`
- `get_history()` with optional `limit` uses a subquery to get the *last* N messages sorted correctly
- All functions accept `str | Path` for flexibility

**Improvements needed:**
- **Connection-per-call pattern is inefficient.** Every function opens and closes a new `aiosqlite.connect()`. For a home server with light load this is acceptable, but a connection pool or shared connection would be more robust. This is a known trade-off documented in the architecture decisions.
- **No error chaining.** If `aiosqlite.connect()` fails, the raw exception propagates. Per coding guidelines, exceptions should be chained with `from e`. Example: `except aiosqlite.Error as e: raise RuntimeError("DB connection failed") from e`
- **No index on `conversations.user_id`.** As history grows, `get_history()` will become slow. Adding `CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id)` in `init_db()` would be a cheap improvement.
- `cursor.close()` is called manually — this could be replaced by using the cursor as an async context manager for cleaner resource management.

---

### `src/home_agent/profile.py` — User Profile Models & Manager

**Responsibility:** Defines `MediaPreferences` and `UserProfile` Pydantic models, the `ProfileManager` class for DB persistence with auto-creation of default profiles, and `resolve_language()` for Telegram locale mapping.

**What's good:**
- Clean model hierarchy: `MediaPreferences` nested inside `UserProfile`
- `resolve_language()` is a pure function with simple locale-to-language mapping — easy to test and extend
- Language code handles region suffixes (e.g., `"en-US"` → `"en"` → `"English"`)
- `ProfileManager.get()` accepts `language_code` as keyword-only arg — preserves backward compatibility
- Migration strategy is elegant: Pydantic v2 ignores unknown fields on deserialization, old fields vanish on next save
- `model_copy()` used for immutable updates — follows the Pydantic best practice
- `model_dump(mode="json")` ensures datetime serialization to ISO strings

**Improvements needed:**
- **`datetime.now()` used without timezone.** Both `_create_default_profile()` and `save()` use `datetime.now()` which returns naive datetimes. Should use `datetime.now(tz=timezone.utc)` for consistency, especially if the bot ever runs in a different timezone than the server.
- **`ProfileManager.get()` reconstructs `MediaPreferences` manually** (lines 142-151). This is fragile — if new nested models are added, the reconstruction logic must be updated. Using `UserProfile.model_validate(profile_dict)` instead of `UserProfile(**profile_dict)` would let Pydantic handle nested model construction automatically.
- The `default_profile` template in `__init__` creates a profile with `user_id=0` — this is a sentinel value that could theoretically conflict with a real user ID. Consider using a negative sentinel or a factory pattern instead.

---

### `src/home_agent/history.py` — Conversation History & Processor

**Responsibility:** `HistoryManager` wraps `db.py` for conversation history CRUD. `sliding_window_processor()` returns a closure compatible with PydanticAI's `history_processors`, keeping only the last N request/response pairs while preserving trailing unpaired requests.

**What's good:**
- `sliding_window_processor` is a well-designed closure — configurable via `n` parameter, returns a PydanticAI-compatible processor
- Correctly handles edge cases: empty history, history smaller than window, trailing unpaired `ModelRequest`
- Tool-call/tool-result pairs are never split — the processor treats them as part of complete request/response pairs
- The trailing message preservation ensures PydanticAI's contract (result must end with `ModelRequest`) is satisfied

**Improvements needed:**
- The `sliding_window_processor` skips orphan `ModelResponse` messages (line 113-114: `i += 1`). This silently drops data. A `logger.warning()` here would help with debugging unexpected history structures.
- `HistoryManager` is a thin wrapper around `db.py` — it adds only logging. This is fine for now, but as the project grows, it might benefit from a method to clear history for a user or export/import history.

---

### `src/home_agent/agent.py` — PydanticAI Agent Definition

**Responsibility:** Defines `AgentDeps` dataclass, `create_agent()` factory function, dynamic system prompt injection, `update_user_note` tool, and registration of profile tools. Also provides `get_agent_toolsets()` helper.

**What's good:**
- `create_agent()` factory pattern is excellent — allows different configurations for production vs tests
- `RetryingModel` is imported lazily inside the function to avoid circular imports
- System prompt is well-structured with Markdown headers (`## Media Requests`, `## Language`, `## Tool Usage`, `## Preferences`)
- The SEARCH → DISAMBIGUATE → QUALITY → CONFIRM flow is clearly specified with concrete examples
- Dynamic prompt uses list-join pattern for clean multi-line construction
- Profile tools registered via `agent_instance.tool(fn)` — explicit and traceable
- `defer_model_check=True` defers API key validation to first request — essential for testing

**Improvements needed:**
- **System prompt is very long (50+ lines).** While structured, it could become unwieldy as more services are added. Consider extracting it to a separate file or constant module in Phase 3.
- `get_agent_toolsets()` is a trivial one-line delegation. It exists for testability but could be replaced by direct `registry.get_toolsets()` calls — marginal benefit vs. added indirection.
- The `update_user_note` tool mutates `profile.notes` in place (`profile.notes.append(note)`) which mutates the Pydantic model. While it works, this is inconsistent with the `model_copy()` pattern used in profile tools. Consider `profile = profile.model_copy(update={"notes": [*profile.notes, note]})` for consistency.

---

### `src/home_agent/bot.py` — Telegram Bot Wiring

**Responsibility:** Telegram message handling using `python-telegram-bot`. Enforces user whitelist, sends typing indicators, calls the PydanticAI agent, persists conversation history, and handles errors (including rate limit 429s).

**What's good:**
- Clean separation — no business logic, only Telegram wiring
- `make_message_handler()` closure pattern captures dependencies without global state
- Proper error handling hierarchy: `ModelHTTPError` 429 → specific busy message, other `ModelHTTPError` → generic error, `Exception` → generic error with logging
- Empty output guard prevents silent failures
- Error handler registered via `app.add_error_handler(_error_handler)`
- History persisted *after* successful agent response — failed requests don't pollute history
- `language_code` passed through from `update.effective_user` for auto-detection

**Improvements needed:**
- **History conversion logic (lines 93-106) duplicates knowledge** of how PydanticAI messages work. This could be extracted to a `convert_history_to_messages()` function in `history.py` for reuse and testing.
- **Telegram message length limit (4096 chars) not enforced.** If the agent returns a very long response, `reply_text()` will fail. Should add message splitting or truncation.
- `run_bot()` function (lines 179-196) calls `create_application(...).run_polling()` which is a blocking call. This is fine for standalone use but conflicts with the `main.py` approach which uses `async with app:` + `app.updater.start_polling()`. The `run_bot()` function appears to be dead code — it's never called.
- The `make_message_handler` return type annotation is missing — should be `-> Callable[..., Coroutine]` or similar.

---

### `src/home_agent/main.py` — Composition Root

**Responsibility:** Wires together config, database, MCP registry, agent, and Telegram bot. Manages the MCP connection lifecycle (`async with agent:`) for the bot's entire lifetime.

**What's good:**
- True composition root — only place where all components are assembled
- `async with agent:` at startup keeps MCP connections open for the bot lifetime (lesson learned LL-006)
- `setup_logging()` handles the edge case where `basicConfig` is a no-op
- Clean async lifecycle: config → logging → DB → managers → MCP → agent → bot
- `asyncio.Event().wait()` for blocking — correct pattern for async polling

**Improvements needed:**
- **No graceful shutdown.** `asyncio.Event().wait()` blocks forever. When `KeyboardInterrupt` is caught in `main()`, the bot doesn't call `app.updater.stop()` or `app.stop()`. The `async with app:` context manager handles this, but the `asyncio.Event().wait()` may prevent proper shutdown signal handling.
- `assert app.updater is not None` on line 88 is a runtime assertion — would be better as an explicit check with a descriptive error: `if app.updater is None: raise RuntimeError("Updater not initialized")`
- The `DB_PATH` parent directory is created both in `main.py` (line 56) and in `init_db()` (line 18 of `db.py`) — redundant but harmless.

---

### `src/home_agent/mcp/registry.py` — MCP Server Registry

**Responsibility:** Manages MCP server configurations and creates `FastMCPToolset` instances for enabled servers.

**What's good:**
- Simple and focused — register configs, get toolsets, get names
- Disabled servers are excluded from toolset creation
- Clean iteration pattern

**Improvements needed:**
- No `unregister()` or `disable()` method — not needed now but will be useful when dynamically managing services
- `get_toolsets()` creates new `FastMCPToolset` instances on every call. If called multiple times, this could create duplicate connections. Consider caching.

---

### `src/home_agent/mcp/servers.py` — MCP Server Configurations

**Responsibility:** Defines `ServerConfig` dataclass and `get_jellyseerr_config()` factory.

**What's good:**
- `ServerConfig` as a plain dataclass — lightweight, no validation overhead needed
- `MCP_HOST` read from `os.environ` — correct for Docker-specific overrides
- `/sse` path used correctly (lesson learned LL-003)

**Improvements needed:**
- `os.environ.get("MCP_HOST", "localhost")` reads the environment at function call time, not at module import time — this is correct. But it means the function must be called *after* environment setup in Docker, which is implicitly guaranteed but not documented.

---

### `src/home_agent/models/retry_model.py` — Rate Limit Retry Wrapper

**Responsibility:** PydanticAI `Model` wrapper that intercepts HTTP 429 errors and retries with exponential backoff. Lazy model resolution from string via `infer_model()`.

**What's good:**
- Model-level retry is the correct extension point — avoids double tool execution risk
- Lazy resolution via `infer_model()` defers API key validation
- `request_stream()` correctly delegates without retry — streaming is stateful
- `on_retry` callback is well-designed for future extension (e.g., Telegram notification)
- `@asynccontextmanager` for `request_stream()` matches PydanticAI's `Model` protocol
- Unreachable sentinel uses `RuntimeError` instead of `AssertionError` — better semantics
- 0-indexed `attempt` in callback — more Pythonic

**Improvements needed:**
- **No maximum backoff cap.** With `max_retries=10` and `base_delay=1.0`, the last retry waits 512 seconds (~8.5 minutes). Adding a `max_delay` parameter (e.g., 30s) would prevent excessive waits.
- The `system` property (line 94-100) triggers lazy model resolution just to get the provider name. This could be problematic if called before the API key is available. Consider returning a static string when the inner model hasn't been resolved yet.

---

### `src/home_agent/tools/profile_tools.py` — Profile Update Tools

**Responsibility:** Four agent-callable tools for updating user preferences: `set_movie_quality`, `set_series_quality`, `set_reply_language`, `set_confirmation_mode`.

**What's good:**
- All tools are async, return confirmation strings, and persist via `ProfileManager`
- Rich tool docstrings help the LLM understand when to call each tool
- `RunContext[Any]` avoids circular imports with `agent.py` (import-linter Layer 2 constraint)
- Confirmation messages are user-friendly and include the new value

**Improvements needed:**
- **Inconsistent mutation patterns.** `set_movie_quality` and `set_series_quality` mutate `profile.media_preferences` via `model_copy()` on the nested model but leave `ctx.deps.user_profile` pointing to the same object. `set_reply_language` and `set_confirmation_mode` use `model_copy()` on the top-level profile and reassign `ctx.deps.user_profile`. Both work, but the asymmetry is confusing and could cause bugs if someone copies the wrong pattern. Recommendation: standardize on the top-level `model_copy()` + reassign pattern for all four tools.
- `set_reply_language` accepts any string — no validation. A user could set their language to "asdf". Consider validating against the `_LOCALE_TO_LANGUAGE` values or at least normalizing the input (capitalize first letter).

---

### `src/home_agent/__init__.py` — Package Init

**Responsibility:** Empty package marker.

No issues. Correctly left empty — no implicit imports.

---

### `src/home_agent/mcp/__init__.py` — MCP Package Init

**Responsibility:** Re-exports `MCPRegistry` for convenience.

Clean and correct — provides `__all__` for explicit public API.

---

### `src/home_agent/models/__init__.py` — Models Package Init

**Responsibility:** Package marker with module docstring.

No issues.

---

### `src/home_agent/tools/__init__.py` — Tools Package Init

**Responsibility:** Package marker with module docstring.

No issues.

---

## 3. Test Suite Review

### Overall Assessment

The test suite is **comprehensive and well-structured** with 104 tests across 14 files. Tests follow project conventions: `TestModel` for agent tests, `tmp_path` for file I/O, `AsyncMock` for Telegram mocking, real DB roundtrips for persistence verification.

### Test Coverage by Module

| Module | Test File | Tests | Coverage Quality |
|--------|-----------|-------|-----------------|
| `config.py` | `test_config.py` | 9 | ✅ Strong — covers defaults, parsing, validation, singleton, retry config |
| `db.py` | `test_db.py` | 3 | ⚠️ Adequate — covers CRUD but no error cases or concurrent access |
| `profile.py` | `test_profile.py` | 14 | ✅ Strong — defaults, serialization, migration, language detection, manager CRUD |
| `history.py` | `test_history.py` | 12 | ✅ Excellent — manager CRUD, sliding window edge cases, tool-call pairs, trailing requests |
| `agent.py` | `test_agent.py` | 12 | ✅ Strong — instantiation, tools, dynamic prompt, quality/language/confirmation injection |
| `bot.py` | `test_bot.py` | 6 | ✅ Good — whitelist, typing, agent response, language detection, rate limit, existing user |
| `main.py` | `test_main.py` | 3 | ⚠️ Adequate — wiring and shutdown, but no full lifecycle test |
| `mcp/registry.py` | `test_mcp_registry.py` | 4 | ✅ Good — register, toolsets, disabled filtering, name listing |
| `mcp/servers.py` | `test_mcp_servers.py` | 4 | ✅ Good — config creation, URL construction, env var override |
| `models/retry_model.py` | `test_retry_model.py` | 6 | ✅ Excellent — success, retry, backoff, exhaustion, non-429, callback |
| `tools/profile_tools.py` | `test_profile_tools.py` | 8 | ✅ Strong — all four tools with DB roundtrip + agent integration |
| Docker | `test_docker.py` | 6 | ✅ Good — file existence, YAML validation, config checks |
| Integration | `test_integration.py` | 7 | ✅ Strong — message flow, auth, deps, locale, quality tools, confirmation, language switch |

### What's Good in Tests

- **Real database roundtrips** in profile and profile tools tests — not just mocking, actual SQLite writes and reads
- **`TestModel(call_tools=["set_movie_quality"])` usage** correctly simulates the agent calling tools without a real LLM
- **System prompt assertion pattern** (extracting `SystemPromptPart` from `all_messages()`) is thorough and reusable
- **Proper `async` test fixtures** with `pytest-asyncio` auto mode
- **Test isolation** — each test creates its own DB in `tmp_path`, no shared state

### Improvements Needed in Tests

- **Missing `@pytest.mark.asyncio` on some async tests.** Tests in `test_agent.py` and `test_retry_model.py` are async but lack the `@pytest.mark.asyncio` marker. They pass because `asyncio_mode = "auto"` is set in `pyproject.toml`, but explicit markers are more robust and self-documenting.
- **`test_db.py` has only 3 tests.** Missing coverage for: error handling on invalid DB path, concurrent writes, saving/retrieving empty content, special characters in content.
- **`conftest.py` `test_db` fixture duplicated.** Both `conftest.py` and `test_history.py` define their own `test_db` fixture. The one in `conftest.py` should be sufficient — `test_history.py`'s local fixture shadows it unnecessarily. Same for `test_profile.py`.
- **`test_config.py` test `test_missing_required_vars` is fragile.** It passes `None` with `# type: ignore` to trigger validation — this tests Pydantic's validation, not the app's behavior. A more realistic test would clear the environment and instantiate without arguments.
- **No negative tests for profile tools.** What happens if `ProfileManager.save()` fails? The tools don't handle exceptions — tests should verify error propagation.
- **`test_retry_model.py` has a RuntimeWarning** about an unawaited coroutine (`_async_main`). This is a test pollution issue from the mock setup in `test_non_429_http_error_not_retried` — should be cleaned up.
- **Integration tests don't test the full agent + bot pipeline.** They either use a mock agent (for deps verification) or a real agent with `TestModel` (for tool verification), but never test the complete `handle_message → agent.run → tool call → response` flow in a single test.

---

## 4. Plan Quality Review

### Overall Assessment

The 17 plan files (step-1.3 through step-2.7b) are **well-structured** with clear goals, task breakdowns, code snippets, and verification criteria. They follow a consistent YAML format with `context`, `tasks`, and `verification` sections.

### What's Good in Plans

- **Each plan specifies exact files to modify/create** — no ambiguity about scope
- **Code snippets in plans serve as guidance, not copy-paste** — implementers adapted them to actual project patterns
- **Verification sections require `verify.sh` to pass** — ensures quality gate
- **Dependencies and references are explicit** — plans link to relevant code and docs
- **Incremental progression** — each step builds on the previous one with clear boundaries
- **`memory.yaml` is excellent** — provides a living record of decisions, issues, and lessons learned

### Plan Execution Fidelity

Most plans were implemented faithfully. Key deviations (all improvements):

| Plan | Deviation | Assessment |
|------|-----------|------------|
| Step 1.3 | Plan suggested `Optional[str]` for `created_at` — implementation uses `datetime` type | ✅ Better — proper types |
| Step 1.5 | Plan suggested class-based `TelegramBot` — implementation uses closure pattern | ✅ Better — follows AGENTS.md guidelines |
| Step 2.1 | Plan suggested removing `MediaPreferences` entirely — implementation kept it as nested model | ✅ Better — cleaner separation of quality preferences |
| Step 2.1 | Plan suggested filtering old fields in `get()` — implementation relies on Pydantic v2 `extra='ignore'` | ✅ Better — simpler, less code to maintain |
| Step 2.7b | Plan used `AssertionError` for unreachable sentinel — implementation uses `RuntimeError` | ✅ Better — correct semantics |
| Step 2.7b | Plan used 1-indexed `on_retry(attempt)` — implementation uses 0-indexed | ✅ Better — more Pythonic |
| Step 2.7b | Plan suggested `infer_model()` upfront — implementation defers via lazy `inner` property | ✅ Better — cleaner deferred validation |

---

## 5. Architecture & Design Decisions

### Layer Architecture (Import Linter)

The 7-contract import linter setup is **excellent**:

```
Layer 0: config (no internal imports)
Layer 1: db (imports config only)
Layer 1b: history (imports config, db)
Layer 2: tools, mcp, models (no agent/bot/main imports)
Layer 3: agent (no bot/main), bot (no main)
Layer 4: main (composition root — nobody imports it)
```

This enforces a clean dependency DAG and prevents circular imports. The tools → agent boundary is particularly well-handled: tools use `RunContext[Any]` to avoid importing `AgentDeps`.

### Key Architecture Decisions — Assessment

| Decision | Assessment |
|----------|------------|
| PydanticAI over LangGraph | ✅ Good — Telegram's message flow IS the human-in-the-loop |
| MCP for service integration | ✅ Good — standard protocol, decoupled, community servers available |
| OpenRouter free tier | ⚠️ Risky — frequent 429s, mitigated by RetryingModel |
| SQLite for persistence | ✅ Good — zero-dependency, sufficient for home server |
| Model-level retry (not bot-level) | ✅ Excellent — avoids double tool execution |
| `async with agent:` at startup | ✅ Good — MCP connections stay open for bot lifetime |
| Closure pattern for bot handler | ✅ Good — captures deps without global state |

---

## 5b. Import Linter Setup — Detailed Review

### Configuration (from `pyproject.toml`)

The project enforces architectural boundaries via 7 `import-linter` contracts using the `forbidden` contract type. All 7 pass in CI via `verify.sh`.

#### Contract 1: "config is independent" (Layer 0)
```
source:    home_agent.config
forbidden: db, profile, history, agent, bot, tools, mcp
```
**Assessment:** ✅ Correct. Config is the leaf dependency — it should never import anything else from the project.

#### Contract 2: "db only imports config and shared" (Layer 1)
```
source:    home_agent.db
forbidden: profile, history, agent, bot, tools, mcp
```
**Assessment:** ✅ Correct. The database layer depends only on config (for `Path` types) and stdlib. Notably, `home_agent.models` is not in the forbidden list — this is fine since `db.py` doesn't import from it, but see improvement #1 below.

#### Contract 3: "history only imports config and db" (Layer 1b)
```
source:    home_agent.history
forbidden: agent, bot, tools, mcp
```
**Assessment:** ✅ Correct. History can import config, db, and profile (for type references). The forbidden list correctly blocks upward imports.

#### Contract 4: "tools, mcp and models do not import agent or bot" (Layer 2)
```
source:    home_agent.tools, home_agent.mcp, home_agent.models
forbidden: home_agent.agent, home_agent.bot, home_agent.main
```
**Assessment:** ✅ Well-designed. This is the most important contract — it prevents circular imports between tools/mcp and the agent that registers them. The consolidation of three packages into a single contract is pragmatic (originally separate contracts were merged in step 2.4). This is why `profile_tools.py` uses `RunContext[Any]` instead of `RunContext[AgentDeps]`.

#### Contract 5: "agent does not import bot or main" (Layer 3a)
```
source:    home_agent.agent
forbidden: home_agent.bot, home_agent.main
```
**Assessment:** ✅ Correct. Agent can import from all lower layers but never from bot or main.

#### Contract 6: "bot does not import main" (Layer 3b)
```
source:    home_agent.bot
forbidden: home_agent.main
```
**Assessment:** ✅ Correct. Bot can import agent (to call `agent.run()`) but never main.

#### Contract 7: "other modules do not import main" (Layer 4)
```
source:    config, db, profile, history, agent, bot, mcp, tools, models
forbidden: home_agent.main
```
**Assessment:** ✅ Correct. Main is the composition root — nothing should import it. Every relevant module is listed in `source_modules`.

### Dependency DAG (enforced)

```
main.py (Layer 4 — composition root)
  ├── bot.py (Layer 3b)
  │     └── agent.py (Layer 3a)
  │           ├── tools/ (Layer 2)
  │           ├── mcp/ (Layer 2)
  │           └── models/ (Layer 2)
  ├── profile.py (Layer 1b — allowed by history contract, peer of history)
  ├── history.py (Layer 1b)
  │     └── db.py (Layer 1)
  │           └── config.py (Layer 0)
  └── config.py (Layer 0)
```

### Improvements Suggested

1. **`home_agent.models` missing from contracts 1–3 forbidden lists.** Contracts 1 (config), 2 (db), and 3 (history) don't forbid importing `home_agent.models`. Currently nothing breaks because config/db/history don't import from models, but a future developer could accidentally add such an import without the linter catching it. **Fix:** Add `"home_agent.models"` to the `forbidden_modules` lists of contracts 1, 2, and 3.

2. **`home_agent.profile` is not forbidden in contract 2 (db).** The db layer could theoretically import profile models, which would create a circular dependency since profile imports db. Currently `db.py` doesn't do this, but it's not enforced. **Fix:** Add `"home_agent.profile"` to contract 2's forbidden list (it's already implicitly forbidden by the fact that `db.py` is Layer 1 and profile is Layer 1b, but making it explicit is safer).

3. **No contract prevents `profile` from importing `history`.** Both are at Layer 1b. Currently neither imports the other, but this boundary is unenforced. **Fix:** Add a contract: `source: home_agent.profile, forbidden: home_agent.history` (and vice versa if they should be true peers).

4. **Contract names could include layer numbers.** Names like `"config is independent"` are descriptive, but `"L0: config is independent"` would make it easier to map contracts to the architecture diagram when scanning `verify.sh` output.

5. **Consider a `layers` contract type.** `import-linter` supports a `layers` contract type that can express the entire hierarchy in one contract instead of 7 separate `forbidden` contracts. This would be more maintainable:
   ```toml
   [[tool.importlinter.contracts]]
   name = "Architecture layers"
   type = "layers"
   layers = [
       "home_agent.main",
       "home_agent.bot",
       "home_agent.agent",
       "home_agent.tools | home_agent.mcp | home_agent.models",
       "home_agent.profile | home_agent.history",
       "home_agent.db",
       "home_agent.config",
   ]
   ```
   However, the current `forbidden` approach gives more granular error messages and allows exceptions — it's more verbose but also more explicit. This is a trade-off, not a clear improvement.

---

## 6. What Was Done Well

### 🏆 Top Highlights

1. **Disciplined architecture enforcement.** The 7 import-linter contracts are not just documented — they're enforced in CI via `verify.sh`. This prevents architectural erosion as the project grows.

2. **Comprehensive `memory.yaml`.** The living document tracking every step, decision, lesson learned, and known issue is invaluable for onboarding new agents or returning to the project after a break. The "lessons learned" section (LL-001 through LL-008) is particularly useful.

3. **RetryingModel design.** Implementing retry at the Model level (not bot or agent level) is a sophisticated decision that avoids the double-tool-execution problem. The lazy resolution, exponential backoff, and callback hook are all production-quality.

4. **Profile migration strategy.** Using Pydantic v2's built-in `extra='ignore'` behavior for schema evolution is elegant — no migration scripts, no version numbers, old data degrades gracefully.

5. **Test quality.** Tests use real DB roundtrips, `TestModel` for agent tests, and proper async fixtures. The sliding window processor tests cover edge cases thoroughly (empty, larger-than-window, tool-call pairs, trailing requests).

6. **Separation of concerns.** The bot layer is truly just Telegram wiring. The agent layer is just PydanticAI configuration. The tools layer is just profile operations. No leaky abstractions.

7. **System prompt engineering.** The SEARCH → DISAMBIGUATE → QUALITY → CONFIRM flow with concrete examples (Troy 2004 vs Troy: Fall of a City 2018) is well-designed for LLM instruction following.

8. **Docker deployment.** Multi-stage build, non-root user, health checks, volume-mounted patched `main.py` for the community MCP server — production-ready containerization.

9. **Consistent coding style.** Every file follows the same patterns: `from __future__ import annotations`, `logging.getLogger(__name__)`, Google-style docstrings, keyword-only args with `*`, type hints on everything.

10. **Defensive error handling in bot.py.** The hierarchy of `ModelHTTPError` 429 → `ModelHTTPError` other → generic `Exception` with appropriate user-facing messages is well thought out.

---

## 7. Issues & Improvements Needed

### 🔴 High Priority

1. **Naive datetimes throughout.** `datetime.now()` is used in `profile.py` (lines 115, 119, 163, 169, 182) without timezone info. If the server timezone changes or the bot moves to a cloud deployment, timestamps become inconsistent. **Fix:** Use `datetime.now(tz=timezone.utc)` everywhere.

2. **`run_bot()` in `bot.py` is dead code.** It's defined (lines 179-196) but never called — `main.py` uses `create_application()` + manual lifecycle management instead. This function uses `run_polling()` which conflicts with the `async with app:` pattern. **Fix:** Remove it or mark it as a convenience function for standalone testing.

3. **No Telegram message length splitting.** Telegram limits messages to 4096 characters. Long LLM responses will cause `reply_text()` to fail silently or raise an exception. **Fix:** Add message splitting in `bot.py` before `reply_text()`.

### 🟡 Medium Priority

4. **Connection-per-call in `db.py`.** Each database operation opens and closes a connection. Under load (multiple rapid messages), this could cause file locking issues. **Fix:** Consider a connection pool or singleton connection pattern — even a simple module-level `aiosqlite.connect()` cached per `db_path`.

5. **No database index on `conversations.user_id`.** History queries will slow down as the table grows. **Fix:** Add `CREATE INDEX IF NOT EXISTS` in `init_db()`.

6. **Inconsistent profile mutation patterns in tools.** `set_movie_quality` mutates the nested `media_preferences` via `model_copy()` without reassigning the top-level profile on `ctx.deps`. `set_reply_language` creates a new top-level profile and reassigns `ctx.deps.user_profile`. **Fix:** Standardize all tools to use the `model_copy()` + reassign pattern.

7. **`update_user_note` tool in `agent.py` mutates in place.** `profile.notes.append(note)` mutates the Pydantic model's list directly, which is inconsistent with the `model_copy()` pattern. **Fix:** Use `profile = profile.model_copy(update={"notes": [*profile.notes, note]})`.

8. **History-to-ModelMessage conversion duplicated.** The logic in `bot.py` (lines 93-106) for converting raw history dicts to `ModelRequest`/`ModelResponse` objects should be in `history.py` as a reusable function.

### 🟢 Low Priority

9. **`test_db` fixture defined in three places.** `conftest.py`, `test_history.py`, and `test_profile.py` each define their own `test_db` fixture. The local fixtures shadow the shared one. **Fix:** Remove the local fixtures and use the shared one from `conftest.py` (adjust DB filenames if isolation is needed).

10. **No retry backoff cap.** `RetryingModel` doubles the delay indefinitely. With `max_retries=10`, the last delay would be 512 seconds. **Fix:** Add `max_delay: float = 30.0` parameter and cap with `delay = min(delay, self.max_delay)`.

11. **`get_agent_toolsets()` is trivial indirection.** The one-line function just calls `registry.get_toolsets()`. It exists for "future extensibility" but adds indirection without current benefit. Consider inlining.

12. **RuntimeWarning in test suite.** `test_non_429_http_error_not_retried` produces a warning about an unawaited `_async_main` coroutine. This is test pollution from mock setup that should be cleaned up.

---

## 8. Suboptimal Plan Suggestions

These are plan suggestions that were correctly rejected or improved during implementation:

### Step 1.3 — User Profile Model

**Plan suggested:** `Optional[str]` for `created_at` and `updated_at` with string ISO format.  
**Implementation chose:** `datetime` type with `model_dump(mode='json')` for serialization.  
**Why the plan was suboptimal:** Using strings for timestamps loses type safety and makes comparison/sorting harder. The `datetime` type with JSON-mode serialization gives the best of both worlds.

### Step 1.3 — ProfileManager

**Plan suggested:** Direct mutation of profile fields (`profile.updated_at = datetime.now().isoformat()`).  
**Implementation chose:** `model_copy(update={...})` for immutable updates.  
**Why the plan was suboptimal:** Direct mutation of Pydantic models is an anti-pattern — it bypasses validation and makes change tracking harder.

### Step 1.5 — Telegram Bot

**Plan suggested:** A class-based `TelegramBot` with `self.config = get_config()` — tight coupling to the global singleton.  
**Implementation chose:** `make_message_handler()` closure pattern with dependency injection.  
**Why the plan was suboptimal:** The class approach couples the bot to the global config singleton, making testing harder. The closure pattern captures dependencies explicitly, following AGENTS.md guidelines.

### Step 2.1 — Simplify UserProfile

**Plan suggested:** Removing `MediaPreferences` entirely and putting `movie_quality`/`series_quality` directly on `UserProfile`.  
**Implementation chose:** Keeping `MediaPreferences` as a nested model with the simplified fields.  
**Why the plan was suboptimal:** Flattening removes the logical grouping. As more media preferences are added (e.g., `preferred_resolution`, `audio_language`), having a nested model keeps `UserProfile` organized.

### Step 2.1 — Migration

**Plan suggested:** Explicitly filtering out old fields in `ProfileManager.get()` with a hardcoded exclusion list: `k not in ('notification_prefs', 'stats', 'media_preferences')`.  
**Implementation chose:** Relying on Pydantic v2's built-in `extra='ignore'` behavior.  
**Why the plan was suboptimal:** The hardcoded filter is fragile — every future field removal requires updating the filter. Pydantic handles this automatically.

### Step 2.7b — Retry Model

**Plan suggested:** `infer_model(model)` called upfront in `create_agent()` before wrapping.  
**Implementation chose:** Lazy resolution via a `@property` on `RetryingModel`.  
**Why the plan was suboptimal:** Upfront resolution triggers API key validation at agent creation time, which fails in tests without environment variables. Lazy resolution defers this to the first actual request, honoring `defer_model_check=True`.

### Step 2.7b — Retry Model (streaming)

**Plan suggested:** `async for chunk in self.inner.request_stream(...)` — treating streaming as an async iterator.  
**Implementation chose:** `@asynccontextmanager` with `async with ... as stream: yield stream`.  
**Why the plan was suboptimal:** PydanticAI's `Model.request_stream()` returns an async context manager, not an async iterator. The plan's approach would have been a runtime error.

### Step 2.7b — Unreachable Sentinel

**Plan suggested:** `raise AssertionError("unreachable")`.  
**Implementation chose:** `raise RuntimeError("Retry loop exited unexpectedly")`.  
**Why the plan was suboptimal:** `AssertionError` is semantically wrong — assertions are for programmer errors during development. `RuntimeError` is the correct choice for "this should never happen" situations in production code.

---

## 9. Recommendations for Phase 3

Based on this review, here are recommendations for Phase 3 (Polish & Advanced Features):

1. **Address the naive datetime issue** before adding any time-sensitive features (notifications, scheduling).

2. **Add message splitting in `bot.py`** before implementing rich Telegram formatting (step 3.1) — formatted messages are even more likely to exceed 4096 chars.

3. **Extract system prompt to a separate module** (e.g., `src/home_agent/prompts.py`) before adding more service-specific instructions — the current inline string in `agent.py` is already 50+ lines.

4. **Consider a connection pool for `db.py`** before adding multi-user support — the connection-per-call pattern won't scale.

5. **Add the `conversations.user_id` index** — trivial to add, prevents future performance issues.

6. **Clean up `run_bot()` dead code** — remove it or clearly document it as a standalone convenience.

7. **Standardize the profile mutation pattern** across all tools before adding more tools — pick one pattern and document it in AGENTS.md.

8. **Add a `max_delay` cap to `RetryingModel`** — essential before increasing `max_retries` beyond 3.

---

*End of review.*

