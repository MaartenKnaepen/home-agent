# Home Agent Coding Guidelines

> **Code templates** (agent, MCP, testing patterns): `docs/LLM/templates.md`
> **Project history and decisions**: `docs/LLM/memory.yaml`
> **Existing public API — check before writing anything new**: `docs/LLM/api.yaml`

---

## 1. Architecture Layers

**Never put business logic in the Telegram handler or PydanticAI agent definition.**

| Layer | Location | Responsibility |
|-------|----------|----------------|
| **Bot** | `src/home_agent/bot.py` | Telegram wiring only: receive messages, send replies, whitelist check, typing indicators |
| **Agent** | `src/home_agent/agent.py` | PydanticAI agent definition: system prompt, tools, dependency injection, model config |
| **Tools** | `src/home_agent/tools/*.py` | Agent-callable tools: profile updates, Telegram rich replies |
| **MCP** | `src/home_agent/mcp/*.py` | MCP server registry, configs, lifecycle management |
| **Core** | `config.py`, `db.py`, `profile.py`, `history.py` | Config, persistence, profiles, history — pure logic, no framework coupling |

Import-linter enforces these boundaries. Read `pyproject.toml [tool.importlinter.contracts]` before adding new modules or cross-layer imports. Run `uv run lint-imports` to verify.

---

## 2. PydanticAI Critical Rules

These cause runtime errors if violated:

| Rule | Why |
|------|-----|
| **✅ ALWAYS** use `async with agent:` to manage MCP/toolset lifecycle | Starts/stops MCP connections properly |
| **❌ NEVER** use deprecated `agent.run_mcp_servers()` or `mcp_servers=` param | Use `async with agent:` and `toolsets=` instead |
| **✅ ALWAYS** use `FastMCPToolset` from `pydantic_ai.toolsets.fastmcp` | Current API (replaces `MCPServerStdio`) |
| **✅ ALWAYS** define `deps_type` on the agent if using dependency injection | PydanticAI validates deps at runtime |
| **✅ ALWAYS** use `RunContext[AgentDeps]` as first param in tool functions | Required for dependency access |
| **✅ ALWAYS** return strings from tool functions | PydanticAI expects string tool results |
| **✅ Use** `agent.override(model=TestModel())` in tests | Never call real LLMs in tests |
| **✅ ALWAYS** subclass `AbstractToolset` for custom toolset wrappers | Plain wrapper classes cause `TypeError: object is not callable` |
| **✅ ALWAYS** match `call_tool(name, tool_args, ctx, tool)` exactly | Wrong arity crashes at runtime |

---

## 3. Python Style Rules

- **Async-first**: All I/O uses `async`/`await`. Never `requests`, always `httpx` or `aiohttp`.
- **Type hints everywhere**: Every function parameter and return type annotated.
- **Pydantic `BaseModel`** for all structured data. `dict` only at serialization boundaries (DB, JSON).
- **Exceptions**: Always chain with `raise X from e`.
- **Paths**: `pathlib.Path` only, never `os.path`.
- **Imports**: Absolute only, grouped (stdlib → third-party → local). No relative imports.
- **Docstrings**: Google-style with Args/Returns/Raises on every public function.
- **Logging**: `logging.getLogger(__name__)`, never `print()`.
- **Config**: All secrets via `.env` through `pydantic-settings`. Nothing hardcoded.

See `docs/LLM/templates.md` for code examples of each pattern.

---

## 4. Testing Rules

- **Never call real LLMs**: Use `agent.override(model=TestModel())`.
- **Patch at import location**: `@patch("home_agent.bot.agent")` not `@patch("home_agent.agent.agent")`.
- **Database tests**: Always use real `tmp_path` DB, never mock `aiosqlite`.
- **Do NOT rewrite tests to make them pass.** Fix the implementation instead.

### ⚠️ Framework Boundary Rule

> `MagicMock(spec=SomeClass)` bypasses every framework protocol check. Green tests, broken production.

For every class that integrates with a framework, **at least one test must run it through the real framework call path**.

| Integration point | Required real test |
|---|---|
| `GuardedToolset` / custom toolsets | Pass real instance to real `Agent()`, call `agent.run()` |
| `@agent.tool` functions | `agent.run()` with `TestModel()` that triggers the tool |
| `RetryingModel` / custom models | `agent.run()` with real wrapper around `TestModel()` |
| Telegram handlers | Real `Update` with real `User`/`Chat` objects |
| `aiosqlite` queries | Real `tmp_path` DB in all tests |

See `docs/LLM/templates.md` for correct and incorrect patterns for each.

---

## 5. File Organization

```
src/home_agent/
├── main.py                  # Entry point
├── config.py                # pydantic-settings AppConfig
├── agent.py                 # PydanticAI Agent, system prompt, tools
├── bot.py                   # python-telegram-bot handlers, whitelist
├── profile.py               # UserProfile model, ProfileManager
├── history.py               # HistoryManager, sliding_window_processor
├── db.py                    # aiosqlite, init_db(), CRUD
├── tools/
│   ├── profile_tools.py     # Agent tools: profile updates
│   └── telegram_tools.py    # Agent tools: rich Telegram replies
└── mcp/
    ├── registry.py          # MCPRegistry
    └── servers.py           # MCP server configs

mcp_servers/<service>/server.py  # Self-built MCP servers (last resort only)

tests/
├── conftest.py              # Shared fixtures
├── test_integration.py      # End-to-end: Telegram → Agent → MCP
└── test_*.py                # Per-module tests
```

---

## 6. MCP Server Guidelines

1. **Search first**: Check GitHub/MCP registries for existing servers.
2. **Evaluate**: Install, connect, test with real service.
3. **Use if functional**: Prefer existing over custom even if imperfect.
4. **Build only as last resort**: Use FastMCP, keep to ~100-300 lines.

Transport: stdio subprocess by default. HTTP only if the server must be shared across multiple agents.

See `docs/LLM/templates.md` for the FastMCP server template.

---

## 7. Verification Gate

**You are not done until `bash verify.sh` passes.**

Runs: `ty` (type checker) → `lint-imports` (architecture contracts) → `pytest` (all tests).

If verify.sh fails 3 times: stop, report what you implemented, what error you cannot resolve, and your diagnosis. Do not weaken tests or remove import-linter contracts to force a pass.

---

## 8. Post-Implementation Code Review

Before presenting code to the user, run `/simplify` and check:

- **Function length**: longer than 30 lines likely does too much — split it
- **Duplication**: logic repeated more than twice — extract to a utility function
- **Type safety**: any use of `Any` from `typing`, untyped `dict`, or missing return type — replace with a concrete type or Pydantic model
- **Too many parameters**: function with more than 4 parameters where several are related — group into a `dataclass` or Pydantic model
- **Unguarded async**: `await` calls without error handling on operations that can fail (HTTP, DB, file I/O) — wrap in `try/except`

---

## 9. Pre-Implementation Checklist

1. Read `docs/LLM/api.yaml` — does this already exist?
2. Read `docs/LLM/memory.yaml` — any relevant decisions or prior issues?
3. Architecture: business logic in core modules, not `bot.py` or `agent.py`?
4. Async: all I/O is `async`?
5. Agent: `deps_type` defined? Tools use `RunContext[AgentDeps]`? Tools return `str`?
6. MCP: `async with agent:` for lifecycle? Not using deprecated `run_mcp_servers()`?
7. Types: Pydantic `BaseModel` for structured data? Type hints everywhere?
8. Config: secrets from `.env` only?
9. Exceptions: chained with `from e`?
10. Paths: `pathlib.Path`?
11. Docstrings: Google-style?
12. Logging: `getLogger(__name__)`?
13. Tests: `TestModel` for agent? Mocked at import location? `tmp_path` for file I/O?
14. MCP servers: searched for an existing one first?
15. Framework boundaries: real instance in at least one test per integration point?
16. Custom toolsets: subclasses `AbstractToolset`? `call_tool` has exact 4-arg signature?
17. Import-linter: does the new module need a contract? Run `uv run lint-imports`.
