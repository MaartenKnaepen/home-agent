# Debugging Strategies — Systematic Troubleshooting

Transform debugging from guesswork into systematic problem-solving.

**Use when:** tracking down bugs, investigating test failures, diagnosing unexpected behavior, debugging async/MCP/Telegram issues.
**Do not use when:** there is no reproducible issue or observable symptom.

---

## The Scientific Method (Non-Negotiable)

1. **Observe** — what is the actual behavior vs. expected?
2. **Hypothesize** — what could be causing it?
3. **Experiment** — test one hypothesis at a time
4. **Analyze** — did it prove or disprove your theory?
5. **Repeat** — until root cause is found

**Mindset rules:**
- "It can't be X" — yes it can. Check anyway.
- "I didn't change Y" — verify with `git diff`.
- Question every assumption. Trust nothing unverified.

---

## Phase 1 — Reproduce

Before anything else:
1. Can you reproduce it? Always / sometimes / randomly?
2. What are the exact conditions?
3. Run `bash verify.sh` — is it a test failure, type error, or import violation?
4. Create the minimal reproduction — strip everything unrelated

Document:
- Exact steps to trigger
- Full error message and stack trace
- Environment: Python version, `uv pip list`, relevant env vars

---

## Phase 2 — Gather Information

```
- Full stack trace (not just the last line)
- Which test file and test function
- What changed recently: git log --oneline -20
- Is it failing in CI or only locally?
- Does it affect all users or specific conditions?
```

For async bugs specifically:
- Is there a missing `await`?
- Is there shared mutable state across concurrent calls?
- Is the event loop being blocked by sync I/O?

For MCP/Telegram bugs:
- Is the MCP server running? Check `docker compose ps`
- Is the `async with agent:` lifecycle being used?
- Is the GuardedToolset receiving the right approved_tools per call?

---

## Phase 3 — Form Hypotheses

Based on gathered information, list 3–5 possible causes ranked by likelihood. For each:
- What would confirm this hypothesis?
- What would rule it out?

Common hypothesis categories for this project:
- **Import/architecture violation** — run `uv run lint-imports`
- **Type mismatch** — run `uv run ty check src/`
- **Mock bypassing framework** — is a `MagicMock(spec=X)` hiding a real error?
- **Async race condition** — shared state mutated across concurrent agent calls
- **Test isolation issue** — fixture leaking state between tests
- **Wrong patch target** — patching where defined instead of where imported

---

## Phase 4 — Test Hypotheses (Binary Search)

Test the highest-likelihood hypothesis first. For each test:
1. Make one change
2. Run `bash verify.sh` (or just the failing test: `uv run pytest tests/test_X.py::test_name -xvs`)
3. Did it change the behavior? In what direction?

Narrow scope:
- Comment out half the suspects, rerun
- Add `print()` / `logger.debug()` at key points
- Compare working vs. broken: diff the code paths, diff the test fixtures

For test failures specifically:
- Run with `-xvs` for full output
- Read the actual assertion error, not just "FAILED"
- Check if the test itself is the problem (weak assertion, wrong mock target)

---

## Phase 5 — Fix and Verify

Once root cause is identified:
1. Apply the minimal fix — do not refactor while fixing
2. Run `bash verify.sh` — all three checks must pass
3. Confirm the fix addresses root cause, not just symptoms
4. Add a regression test if one didn't exist

**Never:**
- Weaken a test to make it pass
- Remove an import-linter contract
- Suppress a type error without understanding it

---

## Common Patterns in This Project

### Test passes locally, fails in CI
- Check env var differences (especially `ALLOWED_TELEGRAM_IDS` format)
- Check if test uses real filesystem path vs. `tmp_path`

### MagicMock test passes, production crashes
- See CLAUDE.md Framework Boundary Rule
- Replace `MagicMock(spec=FrameworkClass)` with real instance + mocked internals

### Async test hangs or never completes
- Missing `await` on a coroutine
- Deadlock in event loop — sync call blocking async path
- `pytest-asyncio` mode not set (`anyio_backend` fixture missing)

### Import error at runtime but not in tests
- Wrong patch target in tests (patching where defined, not where imported)
- New module missing from import-linter contract

### LLM/agent behavior changes unexpectedly
- `AgentDeps` not being passed correctly
- Dynamic system prompt returning different data
- History processor not returning expected message window
