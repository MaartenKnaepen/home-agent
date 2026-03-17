# I built a structured multi-agent coding workflow with Rovo Dev and now I'm migrating to Claude Code — looking for feedback and optimization tips

Hey r/ClaudeAI,

I recently switched to **Claude Code** from ACLI RovoDev and I'm a bit overwhelmed by how many more options it gives me. I'd love feedback on my existing workflow and suggestions for how to improve or restructure it for Claude Code.

This is a long post because I want to give enough detail for useful feedback. TL;DR at the bottom.

---

## Background: What I Was Doing with Rovo Dev

Rovo Dev is Atlassian's AI CLI (think "Claude Code but for Atlassian's platform"). It has a subagents system where you define specialized agents in `.rovodev/subagents/*.md` files, each with its own model, tools, and system prompt. You invoke them manually: "run planner on step 3.2", wait, "run implementer", wait, "run reviewer", etc.

The workflow I built around this is basically a **4-stage pipeline per feature step, plus a phase-level review**. Here's the full thing.

---

## The Workflow

### Stage 0: Planning Documents (written once per phase, manually with the LLM)

Before any code is written I produce two documents collaboratively with the LLM:

**`docs/LLM/DETAILED_PLAN.md`** — a high-level architecture document. Executive summary, architecture diagram, technology decisions, service inventory, design principles. This is the "why" and the "what" of the whole project.

**`docs/LLM/implementation.yaml`** — the machine-readable execution plan. Every feature is broken into numbered steps (e.g. `3.1`, `3.2`, `3.review`). Each step has:

```yaml
- id: '3.2'
  name: GuardedToolset Stateless Refactor
  status: done
  goal: Make GuardedToolset stateless so concurrent users don't leak state
  files:
    - src/home_agent/mcp/guarded_toolset.py
    - tests/test_guarded_toolset.py
  scope: |
    - Remove instance-level _approved_tools state
    - Accept approved_tools as parameter to run_tool()
    - Update all callers in bot.py
  notes: ''
  test: |
    - test_guarded_toolset.py covers stateless behavior
    - Concurrent calls with different approved sets don't interfere
```

**`docs/LLM/api.yaml`** — a living catalog of every public function, class, and tool in the codebase. Agents read this before writing new code so they never duplicate existing functionality. Updated after every step.

**`docs/LLM/memory.yaml`** — a living project memory. Tracks completed steps, decisions made, issues encountered, current state. Every agent reads this before starting so it has full context even in a fresh session.

---

### Stage 1: Step Planner (Sonnet)

The `planner` subagent takes a step ID (e.g. `3.review`) and produces a `docs/LLM/plans/step-3.review.rovo-plan.yaml` file. This is the **implementation contract** — a detailed, unambiguous plan that the implementer follows without needing to make decisions.

**Full planner system prompt:**

```
You are a Principal Software Architect specialising in turning implementation
steps into detailed, actionable execution plans for a coding agent.

Your single job: read a step from docs/LLM/implementation.yaml and produce a
.rovo-plan.yaml file that a coding agent can follow without ambiguity.

Input context — you must read ALL of these:
1. docs/LLM/implementation.yaml — find the step by ID
2. docs/LLM/api.yaml — what already exists, never duplicate
3. docs/LLM/memory.yaml — decisions made, issues encountered in prior steps
4. AGENTS.md — project conventions the implementer must follow
5. Every source file listed in the step's `files` list — read them thoroughly.
   Your plan must be grounded in ACTUAL code, not assumptions.
6. Related test files — understand existing test patterns

Output format (YAML front matter + Markdown body):
---
step: "3.review"
title: "..."
goal: "verbatim from implementation.yaml"
approach: |
  2-4 paragraphs: WHY you're taking this approach, key decisions, trade-offs.
  This is the most important section — it tells the implementer WHY, not WHAT.
---

## Key Files
### New Files / Modified Files / Deleted Files
(one-line description each)

## Step-by-Step Implementation
### 1. Short Title
**File:** path/to/file.py
[description, exact function names, signatures, import changes]
[code snippet for anything non-trivial — complete, copy-pasteable]
**Design notes:** [non-obvious decisions, references to AGENTS.md patterns]

## Success Criteria
- verify.sh passes: ty + lint-imports + pytest all green
- [specific criteria from implementation.yaml's test field]

Rules:
- Be unambiguous. The implementer should never have to guess.
- Stay in scope. Only tasks from this step.
- Check api.yaml. If a function exists, reference it — don't recreate it.
- Check memory.yaml. Respect established patterns.
- Ground in source code. Read every file you're planning to modify.
- Include import-linter impact if new modules are created.
- Code snippets for complex tasks — full function signatures.
- Order tasks logically — dependencies first.
```

The output plan is usually 200-400 lines of YAML+Markdown with exact function signatures, code snippets, and a clear rationale. The implementer agent reads this as its contract and is not supposed to deviate.

---

### Stage 2: Implementer (Sonnet)

The `implementer` subagent reads the rovo-plan and implements it. The tools it has access to are: file open/edit/create/delete/move, grep, and bash.

**Full implementer system prompt:**

```
You are an expert software engineer implementing a specific development step.

Core workflow:
1. Read the .rovo-plan.yaml — this is your implementation contract. Follow exactly.
2. Read docs/LLM/AGENTS.md — project conventions you must follow.
3. Read docs/LLM/api.yaml — check what exists before writing anything new.
4. Implement all tasks in the plan. Stay within the defined scope.

Import architecture:
This project uses import-linter to enforce architectural boundaries.
When creating a new module:
1. Read pyproject.toml [tool.importlinter.contracts] to understand the rules.
2. If your new module needs a contract, add it.
3. Only import from layers below yours — never import upward.
4. Run `uv run lint-imports` to verify before proceeding.

Verification — MANDATORY:
When you believe implementation is complete:
1. Run `bash verify.sh` — type checker, import linter, and tests.
2. If it fails, read the error carefully, fix the code, and run again.
3. If it fails 3 times total, STOP. Report:
   - What you implemented successfully
   - What verify.sh error you cannot resolve
   - What you think the root cause is
   This allows escalation to Opus for a plan revision.

Rules:
- Do NOT rewrite or simplify tests to make them pass. Fix the implementation.
- Do NOT remove or weaken import-linter contracts.
- Do NOT modify verify.sh.
```

---

### Stage 3: Step Reviewer (Opus)

After implementation, the `reviewer` subagent runs in two modes:

**Review mode** — checks the implementation against the plan:

```
Evaluate:
- Plan adherence: Does the implementation match the plan? Missing or out of scope?
- Code quality: Naming, error handling, typing, architecture boundaries.
- Import architecture: Are import-linter contracts correct?
- Test quality (CRITICAL — be ruthless):
  * Empty tests: assert nothing or only assert True
  * Tautological tests: testing the mock, not the code
  * Weakened tests: rewritten to be simpler just to pass
  * Missing edge cases: only happy path
  * Shallow assertions: only checking return type, not value

End with VERDICT: DONE or VERDICT: REDO with specific instructions.
```

**Finalize mode** — after DONE verdict:
- Updates `docs/LLM/api.yaml` with new/changed/removed entries
- Updates `docs/LLM/memory.yaml` with a completed_step entry: step id, date, summary, decisions made, issues encountered

---

### Stage 4: Phase Reviewer (Opus)

After all steps in a phase are done, a separate `phase_reviewer` agent does a **big-picture cross-cutting review** of the entire codebase. This is different from the step reviewer — it's NOT checking plan adherence. It's looking for things that only become visible at scale:

```
What to look for (in priority order):
1. Code duplication — repeated logic that should be extracted
2. Implementation efficiency — manual loops vs. comprehensions, reinventing
   stdlib/framework features, unnecessary indirection
3. Inconsistencies — mutation patterns, error handling styles, naming
4. Architecture & design — layer violations, misplaced responsibilities,
   missing abstractions, import-linter contract accuracy
5. Test quality (big picture) — coverage gaps, weak assertions, isolation issues

Output: a full Markdown report saved to docs/LLM/reviews/phase-X-review.md
with file-by-file source review, test suite review, architecture review,
and prioritised issues (🔴 high / 🟡 medium / 🟢 low).
```

This review then feeds into the next phase's `implementation.yaml` — high-priority issues become steps.

---

### The verification gate: `verify.sh`

This is the lynchpin of the whole workflow. Every implementer invocation ends with running this script. It runs three things in sequence:

```bash
#!/bin/bash
set -e
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}$(pwd)/src"

echo "🔍 Running verification checks..."

echo "  ▸ Type checker (ty)..."
uv run ty check src/

echo "  ▸ Import linter (architecture contracts)..."
uv run lint-imports

echo "  ▸ Tests (pytest)..."
uv run pytest tests/ -q

echo "✅ All checks passed!"
```

- **`ty`** — Astral's new type checker (fast, strict)
- **`lint-imports`** — import-linter enforces architectural boundaries via contracts in `pyproject.toml`. For example: "bot layer may not import from mcp layer directly, only via the registry". This prevents the codebase from turning into spaghetti even as multiple AI agents touch it.
- **`pytest`** — full test suite, currently 244 tests

The 3-strikes rule matters: if verify.sh fails 3 times, the implementer stops and escalates rather than thrashing. This prevents the "LLM weakens tests to make them pass" failure mode. The reviewer catches test quality separately with the ruthless test review criteria above.

---

### The AGENTS.md file

This is the project constitution. Every agent reads it at the start. It covers:
- Architecture layers and what can import from what
- Framework-specific patterns (how to use PydanticAI, FastMCP, python-telegram-bot)
- File naming conventions
- Testing conventions (what must be mocked, fixture patterns, what NOT to test)
- What the import-linter contracts mean and when to update them

---

## Specific Questions I Have

**1. Subagent model assignment**
In Rovo Dev, planner=Sonnet, implementer=Sonnet, reviewer=Opus, phase_reviewer=Opus. Does this still make sense? Is there a case for using Haiku anywhere (e.g. as the implementer for trivial steps)?

**2. Should the planner stage still exist?**
In Claude Code, the orchestrator (the main conversation) already has full file access and can see the whole codebase. Is it still worth having a separate Plan agent write a rovo-plan.yaml, or should I just have the orchestrator produce the plan inline and hand off directly to an implementer agent?

**3. Worktree isolation for implementers**
Claude Code's `Agent` tool supports `isolation: "worktree"`. Should I always use this for implementer subagents? My concern is: if the implementer writes to a worktree branch, how does the merge back to main get handled? Does Claude Code handle that automatically or do I need to orchestrate it?

**4. Custom commands (skills) — what's the right granularity?**
Should I have one `/implement-step` skill that orchestrates all 4 stages, or separate `/plan-step`, `/implement-step`, `/review-step` commands? I currently like having manual checkpoints between stages (so I can reject a bad plan before implementation starts), but I don't know if that's the right call in Claude Code's model.

**5. `api.yaml` and `memory.yaml` — still worth it?**
These are project-level context files that agents read to avoid duplicating work and to understand past decisions. In Claude Code, is there a better mechanism for this? The `MEMORY.md` in `.claude/memory/` feels like it overlaps with `memory.yaml`. Should I consolidate?

**6. The 3-strikes rule**
In Rovo Dev this was hard-coded into the implementer prompt because I had no way to intervene mid-run. In Claude Code, the implementer is a subagent and could theoretically signal back to the orchestrator. Is there a pattern for "implementer signals failure → orchestrator spawns reviewer in plan-revision mode → new plan → re-run implementer" without manual intervention?

**7. Phase reviewer cadence**
I currently run it once after each phase (4-8 steps). Should this be more frequent? Could it run automatically after every step and just be lighter-weight?

---

## TL;DR

I built a structured pipeline for AI-assisted feature development:
1. Write `implementation.yaml` (feature breakdown) + `DETAILED_PLAN.md` (architecture) manually with LLM
2. Per step: **Planner (Sonnet)** writes a detailed rovo-plan.yaml with exact code snippets
3. **Implementer (Sonnet)** follows the plan, must pass `verify.sh` (ty + lint-imports + pytest) within 3 attempts
4. **Step Reviewer (Opus)** checks plan adherence and test quality, updates `api.yaml` + `memory.yaml`
5. Per phase: **Phase Reviewer (Opus)** does cross-cutting review of the whole codebase

This worked well in Rovo Dev. Now I'm on Claude Code and have way more options (Agent tool, worktrees, custom skills, plan mode, background tasks, CLAUDE.md, memory files, etc.) but I'm not sure how to best adapt or improve the workflow. Any feedback appreciated — especially from people who've built similar structured multi-agent pipelines in Claude Code.


