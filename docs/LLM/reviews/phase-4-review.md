# Phase 4 Code Quality Review

**Phase focus:** Voice messages (Qwen3-ASR) and multi-user agent call workflows
**Date:** 2026-03-17
**Reviewer model:** claude-opus-4-6
**Verification:** `bash verify.sh` passes cleanly -- ty clean, 8 import-linter contracts kept, 237 tests passed in 4.02s.

---

## 1. Executive Summary

Phase 4 delivers two significant features: voice-message transcription via a self-hosted Qwen3-ASR sidecar, and a stateless multi-user agent architecture built around per-message `AgentDeps`. Both features work and are well tested (237 passing tests). The architecture is sound -- GuardedToolset reads all state from `ctx.deps` rather than instance variables, eliminating concurrency hazards. The main structural problem is that the voice handler creates an **isolated** `pending_confirmations` dict (bot.py line 304), which means a voice message can never consume an inline-keyboard confirmation. One missing exception chain in `telegram_tools.py` and an oversized parameter list on `_invoke_agent` are the other high-priority items.

---

## 2. File-by-File Source Review

### `src/home_agent/config.py` (57 lines)
Clean pydantic-settings model. `SecretStr` used for all secrets. `asr_url` default uses Docker service name (`http://qwen3-asr:8086`), overridden by `ASR_URL` env var in docker-compose. No issues.

### `src/home_agent/db.py` (145 lines)
Correct async SQLite CRUD. Exception chaining with `from e` on both query functions. Uses `aiosqlite.Row` for dict-like access. No connection pooling, but acceptable for a single-bot workload.

### `src/home_agent/profile.py` (222 lines)
`UserProfile` Pydantic model with `role: Literal["admin", "user", "read_only"]`. `ProfileManager.get()` auto-resolves admin role from `admin_telegram_ids`. `resolve_language()` maps Telegram locale codes to human-readable names. Clean, well-structured.

### `src/home_agent/history.py` (180 lines)
`HistoryManager` wraps `db.py`. `convert_history_to_messages()` builds PydanticAI `ModelMessage` objects. `sliding_window_processor` correctly preserves trailing incomplete pairs. Includes doctests. No issues.

### `src/home_agent/prompts.py` (73 lines)
Static system prompt extracted to a dedicated module. Contains the full media-request flow (SEARCH, DISAMBIGUATE, QUALITY, CONFIRM). References `send_confirmation_keyboard` correctly. Missing `from __future__ import annotations` -- minor.

### `src/home_agent/formatting.py` (186 lines)
markdown-it-py token stream walker. Handles all Telegram-supported HTML tags. Falls back to `html.escape()` on any exception. Thorough and defensive.

### `src/home_agent/agent.py` (209 lines)
`AgentDeps` dataclass with 11 fields covering per-user, per-message state. `create_agent()` factory wires `RetryingModel`, system prompt, `sliding_window_processor(n=20)`, and all tools. Dynamic prompt injects user profile, quality, language, confirmation mode. Clean separation.

### `src/home_agent/bot.py` (587 lines)
Central wiring module. Key phase 4 additions:

- **`_invoke_agent`** (lines 40-157): Shared entry point for text, voice, and callback handlers. Loads profile, consumes `pending_confirmations`, runs agent, persists history, splits long replies. **9 positional parameters** -- see issue below.
- **`make_voice_handler`** (lines 280-412): Downloads OGG from Telegram, POSTs to ASR, delegates to `_invoke_agent`. Properly handles `TimeoutException`, `HTTPStatusError`, and `RequestError` separately. **Creates isolated `_pending_confirmations: dict = {}` on line 304** -- see critical issue below.
- **`make_callback_handler`** (lines 415-511): Stores confirmation in `pending_confirmations`, then calls `_invoke_agent` which immediately consumes it.
- **`create_application`** (lines 514-587): Creates the shared `pending_confirmations` dict and passes it to message and callback handlers -- but **not** to the voice handler.
- TCP keepalive socket options on HTTPXRequest (lines 549-557) -- well-documented workaround for NAT timeout.

### `src/home_agent/tools/profile_tools.py` (119 lines)
Four tools (`set_movie_quality`, `set_series_quality`, `set_reply_language`, `set_confirmation_mode`). All use `model_copy(update=...)` pattern consistently. Type-safe `Literal` for quality and mode. No issues.

### `src/home_agent/tools/telegram_tools.py` (145 lines)
`send_confirmation_keyboard` builds inline keyboard with `confirm:{mediaId}:{mediaType}` callback data. `send_poster_image` constructs TMDB CDN URL and sends via `bot.send_photo`. **Missing exception chaining on line 141** -- `except Exception as e:` without `from e`.

### `src/home_agent/mcp/guarded_toolset.py` (190 lines)
`AbstractToolset` subclass with 3 gates: role, quality, confirmation. All state read from `ctx.deps` (stateless design). After successful `request_media`, resets `ctx.deps.confirmed`. Gate error messages are plain English for the LLM to read. Clean, well-documented.

### `src/home_agent/mcp/registry.py` (65 lines)
`MCPRegistry` wraps `FastMCPToolset` in `GuardedToolset`. Simple and correct.

### `src/home_agent/mcp/servers.py` (41 lines)
`ServerConfig` dataclass. `get_seerr_config()` reads `MCP_HOST` from env for Docker networking. Clean.

### `src/home_agent/models/retry_model.py` (179 lines)
`RetryingModel` subclasses `Model`, intercepts HTTP 429 with exponential backoff. Lazy model resolution via `infer_model()`. Streaming delegates without retry (documented). `on_retry` callback for test observability. Clean.

### `src/home_agent/main.py` (114 lines)
Composition root: config -> DB -> managers -> MCP registry -> agent -> bot. Uses `async with agent:` for MCP lifecycle. `async with app:` for Telegram lifecycle. Correct.

### `mcp_servers/qwen3_asr/server.py` (166 lines)
FastAPI server with `/health` and `/transcribe` endpoints. bfloat16 fallback to float32. Synchronous `model.transcribe()` runs in thread pool executor. Temp file cleanup in `finally` block. `bare except Exception` on line 54 could be more specific but is acceptable for model loading fallback.

---

## 3. Test Suite Review

| Test file | Lines | Module under test | Quality |
|---|---|---|---|
| `test_agent.py` | 526 | `agent.py` | Thorough: tools registered, system prompt content, quality/language/confirmation in dynamic prompt, GuardedToolset lifecycle |
| `test_bot.py` | 473 | `bot.py` | Good: whitelist, typing indicator, language, rate limit, message splitting, HTML parse_mode, callback handler |
| `test_voice.py` | 337 | `bot.py` (voice handler) | Good: auth, transcription, ASR errors (timeout, HTTP, network), empty transcription, typing indicator |
| `test_multi_user.py` | 268 | `bot.py` + `guarded_toolset.py` | Good: concurrent users, isolated state, pending_confirmations isolation between users |
| `test_guarded_toolset.py` | 479 | `guarded_toolset.py` | Thorough: all 3 gates (role, quality, confirmation), confirmed reset, pass-through, called_tools tracking |
| `test_profile_tools.py` | 414 | `profile_tools.py` | Good: all 4 tools, persistence, model_copy immutability |
| `test_telegram_tools.py` | 303 | `telegram_tools.py` | Good: keyboard layout, poster URL, fallbacks, no-bot context |
| `test_formatting.py` | 280 | `formatting.py` | Thorough: headings, bold, italic, code, links, blockquotes, fence, HR, safe/unsafe HTML |
| `test_retry_model.py` | 228 | `retry_model.py` | Thorough: backoff, max_delay cap, non-429 passthrough, on_retry callback, lazy resolution |
| `test_profile.py` | 281 | `profile.py` | Good: CRUD, language resolve, admin role, model_copy |
| `test_history.py` | 176 | `history.py` | Good: sliding window, convert, save/get roundtrip |
| `test_db.py` | 114 | `db.py` | Good: init, save, get, profile CRUD |
| `test_integration.py` | 128 | End-to-end | Good: full text message -> agent -> reply pipeline |
| `test_config.py` | 33 | `config.py` | Minimal but sufficient |
| `test_main.py` | 40 | `main.py` | Minimal: setup_logging only |
| `test_mcp_registry.py` | 117 | `mcp/registry.py` | Good: register, get_toolsets, GuardedToolset wrapping |
| `test_mcp_servers.py` | 37 | `mcp/servers.py` | Good: config, MCP_HOST env |
| `test_docker.py` | 43 | Dockerfile/compose | Good: file existence, non-root user, healthcheck |

**Notable gap:** No test verifies that `make_voice_handler` receives and uses the shared `pending_confirmations` from `create_application`. The current tests use isolated handler calls where this bug is invisible.

---

## 4. Architecture & Design

**Import-linter contracts (8 total):** All 8 contracts pass. The layering is well-designed:
- Layer 0: `config` -- no internal imports
- Layer 1: `db` -- only config
- Layer 1b: `history` and `profile` -- peers, cannot import each other
- Layer 2: `tools`, `mcp`, `models` -- cannot import agent/bot/main
- Layer 3: `agent` cannot import `bot`; `bot` cannot import `main`
- Layer 4: `main` is the composition root; nothing imports it

**Stateless GuardedToolset pattern:** The key phase 4 architectural decision. `GuardedToolset` stores only `inner_toolset` (set at creation). All per-user state (`confirmed`, `called_tools`, `role`) is read from `ctx.deps`, which is a fresh `AgentDeps` per message. This eliminates race conditions between concurrent users.

**Shared `_invoke_agent` function:** DRY extraction of agent invocation logic used by text, voice, and callback handlers. Good pattern, but the parameter count (9) exceeds the CLAUDE.md guideline of 4.

**pending_confirmations flow:** `create_application` creates one shared dict, passes it to the message handler and callback handler. The callback handler stores `(media_id, media_type)` keyed by `user_id`; `_invoke_agent` consumes it at the start of the next run. Correct design, except the voice handler is excluded.

---

## 5. What Was Done Well

1. **Stateless GuardedToolset** -- The most important phase 4 decision. Reading all per-user state from `ctx.deps` instead of toolset instance variables is the correct pattern for concurrent multi-user access. Well-documented in the class docstring and `AgentDeps` docstring.

2. **Granular ASR error handling** -- `make_voice_handler` distinguishes `TimeoutException`, `HTTPStatusError`, and `RequestError` with user-friendly messages for each. No bare `except` swallowing.

3. **TCP keepalive on Telegram connection pool** -- Well-documented workaround (bot.py lines 542-557) for NAT table expiry causing `ConnectTimeout` after long agent runs.

4. **RetryingModel with lazy resolution** -- Defers API key validation until the first request. `on_retry` callback enables test observability without mocking internals.

5. **Test coverage** -- 237 tests, 19 test files. Every source module has a corresponding test file. Framework boundary tests exist (real `GuardedToolset` in `Agent.run()`, real `User`/`Chat` objects in Telegram tests).

6. **Import-linter contracts** -- 8 contracts enforce clean layer separation. The composition root pattern in `main.py` is correctly isolated.

7. **Sliding window processor** -- Correctly preserves trailing incomplete pairs and never splits tool-call/result pairs.

---

## 6. Issues & Improvements

### :red_circle: High Priority

#### H1. Voice handler does not share `pending_confirmations`

**File:** `src/home_agent/bot.py`, line 304
**Problem:** `make_voice_handler` creates its own empty `_pending_confirmations: dict = {}` instead of receiving the shared dict from `create_application`. This means:
- User searches for a movie via voice -> agent sends confirmation keyboard
- User presses "Yes" -> callback handler stores confirmation in the **shared** dict
- If the user then sends a **voice** message, `_invoke_agent` checks the **voice handler's isolated** dict (always empty) -> confirmation is never consumed
- The text handler works correctly because it receives the shared dict

**In `create_application` (line 568-574):** `make_voice_handler` is called without `pending_confirmations`:
```python
voice_handler = make_voice_handler(
    config, profile_manager, history_manager, agent, _guarded_toolsets,
)
```

**Fix:** Add `pending_confirmations` parameter to `make_voice_handler` signature and pass the shared dict from `create_application`:
1. In `make_voice_handler` (line 280): add `pending_confirmations: dict[int, tuple[int, str]] | None = None` parameter
2. Replace line 304 (`_pending_confirmations: dict[int, tuple[int, str]] = {}`) with: `_pending_confirmations: dict[int, tuple[int, str]] = pending_confirmations if pending_confirmations is not None else {}`
3. In `create_application` (line 568): pass `pending_confirmations=pending_confirmations` to `make_voice_handler`
4. Add a test that creates a voice handler with a pre-populated `pending_confirmations` and verifies the confirmation is consumed.

---

#### H2. Missing exception chaining in `send_poster_image`

**File:** `src/home_agent/tools/telegram_tools.py`, line 141
**Problem:** `except Exception as e:` catches the error but does not re-raise with `from e`. While the function returns a string (so it does not re-raise), the CLAUDE.md standard says "Always chain with `raise X from e`." More importantly, swallowing the exception entirely means the agent never learns the specific failure reason. The `logger.warning` logs it, but the traceback is lost because `logger.warning` does not include `exc_info`.

**Current code:**
```python
except Exception as e:
    logger.warning(
        "send_poster_image failed", extra={"url": url, "error": str(e)}
    )
    return "Could not send poster image (unavailable)."
```

**Fix:** Add `exc_info=True` to the logger call so the full traceback is preserved in logs:
```python
except Exception:
    logger.warning(
        "send_poster_image failed", extra={"url": url}, exc_info=True
    )
    return "Could not send poster image (unavailable)."
```

---

#### H3. `_invoke_agent` has 9 parameters

**File:** `src/home_agent/bot.py`, lines 40-50
**Problem:** `_invoke_agent` takes 9 positional parameters. CLAUDE.md section 8 says: "Too many parameters: function with more than 4 parameters where several are related -- group into a dataclass or Pydantic model." The parameters `config`, `profile_manager`, `history_manager`, `agent`, `guarded_toolsets`, and `pending_confirmations` are all "app context" -- they are the same across every call within a handler.

**Fix:** Create an `InvocationContext` dataclass grouping the 6 app-context params:
```python
@dataclass
class InvocationContext:
    config: AppConfig
    profile_manager: ProfileManager
    history_manager: HistoryManager
    agent: Agent[AgentDeps, str]
    guarded_toolsets: list[GuardedToolset]
    pending_confirmations: dict[int, tuple[int, str]]
```
Then `_invoke_agent` becomes `_invoke_agent(text, update, context, inv_ctx)` -- 4 parameters. Each `make_*_handler` constructs an `InvocationContext` once in the closure.

---

### :yellow_circle: Medium Priority

#### M1. Duplicated test helpers across test files

**Files:**
- `tests/test_guarded_toolset.py`: `make_profile()` helper (lines ~20-35)
- `tests/test_multi_user.py`: `make_profile()` helper (lines ~20-35)
- `tests/test_guarded_toolset.py`, `test_multi_user.py`, `test_agent.py`: `make_deps()` / `make_agent_deps()` variants
- `tests/test_voice.py`: httpx mock setup repeated 6+ times

**Fix:** Extract shared helpers to `tests/conftest.py` or a `tests/helpers.py` module:
- `make_profile(user_id, **overrides) -> UserProfile`
- `make_deps(config, profile_manager, history_manager, **overrides) -> AgentDeps`
- `mock_httpx_asr_response(text) -> fixture/context manager`

---

#### M2. `pytest` and `pytest-asyncio` in main dependencies

**File:** `pyproject.toml`, lines 9, 11
**Problem:** `pytest>=9.0.2` and `pytest-asyncio` are listed under `[project] dependencies` instead of `[dependency-groups] dev`. This means they are installed in production Docker images unnecessarily.

**Fix:** Move both to `[dependency-groups] dev`:
```toml
[dependency-groups]
dev = [
    "import-linter>=2.10",
    "ty>=0.0.17",
    "pyyaml>=6.0",
    "pytest>=9.0.2",
    "pytest-asyncio",
]
```

---

#### M3. `seerr-mcp` healthcheck missing

**File:** `deployment/docker-compose.yml`, lines 31-49
**Problem:** `home-agent` depends on `seerr-mcp` with `condition: service_healthy`, but `seerr-mcp` has no `healthcheck` defined. Docker Compose will treat "healthy" as "started" in this case, which means `home-agent` may start before seerr-mcp is ready to accept MCP connections.

**Fix:** Add a healthcheck to the `seerr-mcp` service:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:${MCP_PORT:-8085}/mcp"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

---

#### M4. `make_callback_handler` missing return type annotation

**File:** `src/home_agent/bot.py`, line 422
**Problem:** `make_callback_handler` is the only handler factory without a return type annotation. Both `make_message_handler` (line 219) and `make_voice_handler` (line 286) have `-> Callable[[Update, ContextTypes.DEFAULT_TYPE], Coroutine[Any, Any, None]]`.

**Fix:** Add the same return type annotation to `make_callback_handler`.

---

#### M5. Broad `RuntimeWarning` suppression in pytest config

**File:** `pyproject.toml`, lines 20-24
**Problem:** `"ignore::RuntimeWarning"` suppresses ALL runtime warnings in all tests, not just the Python 3.10 GC artifact described in the comment. This could hide real issues.

**Fix:** Narrow the filter to match the specific warning message pattern, e.g.:
```toml
"ignore:coroutine.*was never awaited:RuntimeWarning"
```

---

### :green_circle: Low Priority

#### L1. Inconsistent `from __future__ import annotations` usage

**Files without it:** `prompts.py`, `mcp/servers.py`, `mcp/__init__.py`, `models/__init__.py`, `tools/__init__.py`
**Files with it:** `bot.py`, `agent.py`, `config.py`, `db.py`, `formatting.py`, `history.py`, `profile_tools.py`, `telegram_tools.py`, `guarded_toolset.py`, `retry_model.py`

**Impact:** Minimal for runtime, but inconsistent style. Adding it everywhere would make forward-compatible type annotations consistent across the codebase.

---

#### L2. `_load_model` catches overly broad `Exception` on bfloat16 fallback

**File:** `mcp_servers/qwen3_asr/server.py`, line 54
**Problem:** `except (RuntimeError, Exception) as e:` -- `Exception` already covers `RuntimeError`, so the tuple is redundant. A more specific catch (e.g., `RuntimeError`, `TypeError`) would prevent masking unrelated errors during model loading.

---

#### L3. `config.asr_url` docstring placement

**File:** `src/home_agent/config.py`, line 45
**Problem:** The docstring `"""URL of the Qwen3-ASR transcription service."""` is placed after the field definition as a standalone string literal. Pydantic and most tools expect field documentation in the class docstring `Attributes` section (which already has it on line 28). The standalone string is a no-op at runtime.

---

#### L4. `os.environ` used directly in `mcp/servers.py`

**File:** `src/home_agent/mcp/servers.py`, line 36
**Problem:** `os.environ.get("MCP_HOST", "localhost")` reads an env var directly instead of routing through `AppConfig`. All other env-based config goes through pydantic-settings. This is acceptable for a simple string, but breaks the "Config: all secrets via `.env` through `pydantic-settings`" guideline.

---

## 7. Recommendations for Next Phase

1. **Fix H1 before anything else** -- the voice-handler `pending_confirmations` isolation is a functional bug that affects the user experience when combining voice messages with inline keyboard confirmations.

2. **Extract `InvocationContext`** (H3) before adding more handler types (e.g., photo/document handlers, inline query handlers). The 9-parameter function will only grow.

3. **Consider connection pooling for SQLite** -- currently every DB operation opens and closes a new `aiosqlite.connect()`. For a single-user home bot this is fine, but if multi-user load increases, a shared connection or connection pool would reduce overhead.

4. **Add conversation-level integration tests** -- the current integration test (`test_integration.py`) tests a single message->reply cycle. A multi-turn test exercising the full flow (search -> disambiguate -> quality -> confirm -> request) through the agent would catch prompt regressions.

5. **Consolidate test helpers** (M1) to reduce boilerplate as the test suite grows.

6. **Move pytest to dev dependencies** (M2) to keep the production image lean.
