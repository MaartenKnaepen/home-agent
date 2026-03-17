Find the first incomplete step in `docs/LLM/implementation.yaml` (first step where `status` is not `done`) and run the full implementation pipeline for it.

## Step 1 — Find the step and confirm

Read `docs/LLM/implementation.yaml`. Scan all phases and steps in order. Pick the first step where `status != done`.

If all steps are done, report that and stop.

Otherwise, show the user:
- Step ID and name
- Goal
- Files listed in the step

Then **explicitly ask**: "Proceed with implementing this step?" and wait for confirmation before continuing. Do not spawn any subagents until the user confirms.

---

## Step 2 — Plan (Sonnet)

Spawn a **Plan** subagent with `model: sonnet` and the following instructions:

```
You are a Principal Software Architect writing an implementation plan.

Read these files in full before writing anything:
1. docs/LLM/implementation.yaml — find step {STEP_ID}, read its goal, files, scope, notes, and test criteria
2. docs/LLM/api.yaml — what already exists; never duplicate or conflict
3. docs/LLM/memory.yaml — decisions made in prior steps, issues encountered
4. CLAUDE.md — project conventions the implementer must follow
5. docs/LLM/templates.md — code templates for this project
6. Every file listed in the step's `files` field — read each one in full; your plan must be grounded in actual current code, not assumptions
7. Related test files — understand existing test patterns

Write a single file to docs/LLM/plans/step-{STEP_ID}.rovo-plan.yaml using this format:

---
step: "{STEP_ID}"
title: "{step name from implementation.yaml}"
goal: "{goal verbatim from implementation.yaml}"

approach: |
  2-4 paragraphs explaining WHY you're taking this approach, key decisions, and trade-offs.
  This is the most important section — it tells the implementer WHY, not just WHAT.

---

## Key Files

### New Files
- `path/to/new_file.py` — one-line description

### Modified Files
- `path/to/existing_file.py` — one-line description of changes

### Deleted Files
- `path/to/removed_file.py` — why it's being removed

---

## Step-by-Step Implementation

### 1. Short Title

**File:** `path/to/file.py`

Description of what to do: exact function/class names, signatures, imports, what to add/modify/remove.

```python
# Code snippet for anything non-trivial — complete, copy-pasteable
```

**Design notes:**
- Non-obvious decisions
- References to CLAUDE.md patterns if applicable

[Continue for all tasks...]

---

## Success Criteria

- bash verify.sh passes: ty + lint-imports + pytest all green
- [Specific criteria from implementation.yaml's test field]

Rules to follow:
- Be unambiguous. The implementer should never have to guess.
- Stay in scope. Only tasks from this step — nothing from other steps.
- Check api.yaml. If a function exists, reference it, don't recreate it.
- Check memory.yaml. Respect established patterns and decisions.
- Ground in actual source code. Read every file before planning changes.
- Include import-linter impact if creating new modules.
- Code snippets for anything non-trivial — full function signatures.
- Order tasks so dependencies come first.
```

Wait for the Plan subagent to complete and confirm the plan file was written before proceeding.

---

## Step 3 — Implement (Sonnet, worktree)

Spawn a **general-purpose** subagent with `model: sonnet` and `isolation: worktree` and the following instructions:

```
You are an expert software engineer implementing a specific development step.

Read these files before writing any code:
1. docs/LLM/plans/step-{STEP_ID}.rovo-plan.yaml — your implementation contract; follow it exactly
2. CLAUDE.md — project conventions you must follow
3. docs/LLM/templates.md — code templates for this project
4. docs/LLM/api.yaml — what already exists; never duplicate

Import architecture:
This project uses import-linter to enforce architectural boundaries. When creating a new module:
- Read pyproject.toml [tool.importlinter.contracts]
- Add a contract if your new module needs one
- Only import from layers below yours — never import upward
- Run `uv run lint-imports` to verify

Verification — MANDATORY:
When you believe implementation is complete:
1. Run `bash verify.sh` — type checker, import linter, and tests must all pass
2. If it fails, read the error carefully, fix the code, run again
3. If it fails 3 times, STOP. Report:
   - What you implemented successfully
   - The exact verify.sh error you cannot resolve
   - Your diagnosis of the root cause
   Do not weaken tests or remove import-linter contracts to force a pass.
```

Wait for the Implement subagent to complete.

- If it reports a verify.sh failure it could not resolve: stop and show the user the error report. Do not proceed to review.
- If it succeeded: note the worktree branch name returned in the agent result. Proceed to Step 3a.

---

## Step 3a — Merge worktree branch

After the implementer completes successfully, merge its changes into main:

```bash
git merge --no-ff {WORKTREE_BRANCH}
```

If the merge fails (unexpected conflict), stop and report the conflict to the user. Do not proceed.

If the merge succeeds, confirm `bash verify.sh` still passes in main before continuing.

---

## Step 4 — Review (Opus)

Spawn a **general-purpose** subagent with `model: opus` with the following instructions:

```
You are a principal engineer performing a code review. Your job is to identify problems
and produce a precise fix list. You do NOT write code — a separate Sonnet agent will
implement your instructions.

Read:
1. docs/LLM/plans/step-{STEP_ID}.rovo-plan.yaml — the implementation contract
2. CLAUDE.md — project conventions
3. Run: git diff HEAD~1 HEAD  (or git log to identify the merge commit and diff from its parent)

Evaluate ruthlessly across these dimensions:

**Plan adherence**
- Does the implementation match the plan? Anything missing or out of scope?

**Code quality**
- Naming, error handling, typing, architecture boundaries

**Import architecture**
- Are import-linter contracts correct? New modules properly integrated?

**Test quality — be ruthless**
- Empty tests: assert nothing or only assert True
- Tautological tests: testing the mock, not the code
- Weakened tests: rewritten to be simpler just to pass
- Missing edge cases: only happy path tested
- Shallow assertions: only checking return type, not value
- Framework boundary violations: MagicMock where a real instance is required (see CLAUDE.md)

---

If no issues: output VERDICT: DONE

If issues found: output VERDICT: FIX followed by a numbered fix list. Each item must be:
- Specific: exact file, function, and line reference
- Actionable: tell the implementer exactly what to change, including the correct code where non-trivial
- Scoped: one change per item, ordered so dependencies come first

Example fix list format:
VERDICT: FIX

1. `tests/test_guarded_toolset.py:45` — `test_concurrent_calls` uses `MagicMock(spec=GuardedToolset)`
   instead of a real instance. Replace with a real `GuardedToolset` wrapping a mocked inner toolset.
   See CLAUDE.md framework boundary pattern.

2. `src/home_agent/mcp/guarded_toolset.py:23` — `call_tool` signature is missing the `tool` parameter.
   Correct signature: `async def call_tool(self, name, tool_args, ctx, tool) -> str`

Do not include vague feedback. Every item must be something a Sonnet implementer can execute
without making any decisions.
```

---

## Step 5 — Fix (Sonnet, only if VERDICT: FIX)

If the reviewer returned VERDICT: FIX, spawn a **general-purpose** subagent with `model: sonnet` and the following instructions:

```
You are an expert software engineer applying a precise set of fixes identified by a code reviewer.

Read:
1. The fix list provided below — implement every item exactly as specified
2. CLAUDE.md — project conventions
3. Each file referenced in the fix list before modifying it

Fix list:
{REVIEWER_FIX_LIST}

Rules:
- Implement every fix exactly as described. Do not deviate or improve beyond what is listed.
- Do not modify anything not referenced in the fix list.
- After all fixes are applied, run `bash verify.sh` and confirm it passes.
- If verify.sh fails after applying the fixes, report the error — do not attempt to work around it
  by weakening tests or removing contracts.
```

Wait for the Fix subagent to complete and confirm verify.sh passes before proceeding.

---

## Step 6 — Finalize (Opus)

Once VERDICT: DONE is reached (either directly from Step 4 or after Step 5), spawn a **general-purpose**
subagent with `model: opus` with the following instructions:

```
You are a principal engineer finalizing a completed implementation step.

Read:
1. docs/LLM/plans/step-{STEP_ID}.rovo-plan.yaml — what was planned
2. Run: git diff HEAD~1 HEAD  to see what was actually implemented
3. docs/LLM/api.yaml — current state, to be updated
4. docs/LLM/memory.yaml — current state, to be updated

Update docs/LLM/api.yaml:
- Add entries for every new function, class, or tool introduced
- Remove entries for anything deleted or renamed
- Follow the exact YAML schema and style of existing entries

Update docs/LLM/memory.yaml:
- Add a new entry under completed_steps: step id, name, date, summary, decisions, issues
- Update current_state to reflect the new state of the project
- Follow the exact YAML schema and style of existing entries

Update docs/LLM/implementation.yaml:
- Set status: done for step {STEP_ID}
```

---

## Step 7 — Report back

Report to the user: step ID, name, whether fixes were needed, and a one-paragraph summary of what was implemented.
