# Lint and Validate — Lightweight Quality Checks

Run after every code change. Do not report a task as done until all checks pass.

---

## Primary Check — verify.sh

Always run this first:

```bash
bash verify.sh
```

This runs in sequence:
1. `uv run ty check src/` — type checker (Astral ty)
2. `uv run lint-imports` — import-linter architecture contracts
3. `uv run pytest tests/ -q` — full test suite

**All three must pass with exit code 0.** If any fail, fix before proceeding.

---

## Targeted Checks (When verify.sh Is Too Slow)

During active development, run only the relevant check:

```bash
# Types only
uv run ty check src/

# Architecture boundaries only
uv run lint-imports

# Single test file
uv run pytest tests/test_X.py -xvs

# Single test
uv run pytest tests/test_X.py::test_name -xvs

# Tests matching a keyword
uv run pytest -k "profile" -xvs
```

---

## Post-Implementation Code Review

After all checks pass, review the changed code against CLAUDE.md section 8:

- **Function length**: any function over 30 lines? If so, does it do too much?
- **Duplication**: is any logic repeated more than twice? Extract to utility.
- **Type safety**: any `Any` from `typing`, bare `dict`, or missing return type? Replace with concrete type or Pydantic model.
- **Too many parameters**: function with more than 4 parameters where several are related? Group into `dataclass` or Pydantic model.
- **Unguarded async**: any `await` on HTTP, DB, or file I/O without a `try/except`?

Then run `/simplify` before presenting the code to the user.

---

## Error Handling

| Check | Failure | Fix |
|-------|---------|-----|
| `ty` | Type error | Fix the type annotation or implementation — do not add `# type: ignore` without explanation |
| `lint-imports` | Import violation | Fix the import — do not remove the contract |
| `pytest` | Test failure | Fix the implementation — do not weaken the test |
| `pytest` | Missing coverage | Write the missing test |

**Never:**
- Use `# type: ignore` to suppress a real type error
- Remove or weaken an import-linter contract
- Rewrite a test to make it pass instead of fixing the implementation

---

## If verify.sh Cannot Be Fixed

After 3 attempts, stop and report:
- What was implemented successfully
- The exact error from verify.sh
- Your diagnosis of the root cause

Use `/debugging-strategies` to investigate systematically rather than thrashing.
