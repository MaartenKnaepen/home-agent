Run a big-picture cross-cutting code quality review across all completed phases, then fix all high-priority issues.

This is NOT a step-level review. Do not check plan adherence. Look at the codebase as a whole and find issues that only become visible at scale: duplication, inconsistencies, architectural drift, test gaps.

---

## Step 1 — Review (Opus)

Spawn a **general-purpose** subagent with `model: opus` with the following instructions:

```
You are a principal engineer performing a big-picture code quality review.

Read ALL of the following before writing anything:
1. CLAUDE.md — coding conventions and architecture guidelines
2. docs/LLM/memory.yaml — current state, completed phases, decisions made
3. Every source file under src/ — open and read each one in full
4. Every source file under mcp_servers/ — open and read each one in full
5. All files under deployment/ — Docker Compose, Dockerfiles, deployment docs
6. Every test file under tests/ — open and read each one in full
7. pyproject.toml [tool.importlinter] section — verify contracts match current module structure
8. Run `bash verify.sh` and note the result

Determine the current phase number from docs/LLM/memory.yaml field `current_state.phase`.
Save the report to docs/LLM/reviews/phase-{N}-review.md where {N} is that phase number.

---

## What to look for (in priority order)

### Code duplication
- Repeated logic across files that should be extracted into a shared helper
- Duplicated fixtures or test helpers that should be in conftest.py
- Repeated error handling patterns

### Implementation efficiency
- Overly complex logic where a simpler approach exists
- Unnecessary indirection: wrapper functions that just delegate without adding value
- Better data structures: set vs. list, dataclass vs. dict, enum vs. string constants
- Reinventing something the framework (PydanticAI, python-telegram-bot, Pydantic) already provides

### Inconsistencies
- Mutation patterns: some code using model_copy(), other code mutating in place
- Error handling styles: some chaining exceptions with `from e`, others not
- Naming conventions: inconsistent names across modules for similar concepts

### Architecture & design
- Layer violations or near-violations: passes import-linter but violates the spirit
- Misplaced responsibilities: business logic in the wrong layer
- Missing abstractions: helpers or protocols that would reduce coupling
- Import-linter contract accuracy: do contracts still match the current module structure?
  Check for: new modules missing from contracts, stale module references, missing contracts for new boundaries

### Test quality (big picture)
- Coverage gaps: modules or code paths with no test coverage
- Weak assertions: tests that pass but don't verify meaningful behavior
- Missing edge cases: only happy paths tested across the entire suite
- Test isolation issues: shared state, fixture shadowing, ordering dependencies
- Framework boundary violations: MagicMock where a real instance is required (see CLAUDE.md)

---

## Report format

Save to docs/LLM/reviews/phase-{N}-review.md with this structure:

# Home Agent — Phase {N} Code Review

> **Reviewer:** Claude Code
> **Date:** {today}
> **Scope:** {describe what was reviewed}
> **Verification status:** {result of bash verify.sh}

---

## 1. Executive Summary
[2-3 paragraphs: overall quality, main themes, biggest opportunities]

---

## 2. File-by-File Source Review

### `path/to/file.py` — [Short Responsibility Description]

**Responsibility:** [One sentence]

**What's good:**
- [Specific positives]

**Improvements needed:**
- [Specific issues with file/line references and concrete fix suggestions]

[Repeat for every source file under src/ and mcp_servers/]

### Deployment (`deployment/`)
[Review Docker Compose, Dockerfiles: hardcoded values, missing health checks,
volume issues, service dependency ordering, image pinning, consistency with app requirements]

---

## 3. Test Suite Review

### Overall Assessment

### Test Coverage by Module
| Module | Test File | Coverage Quality |
|--------|-----------|-----------------|
| ... | ... | ✅/⚠️/❌ |

### What's Good / Improvements Needed

---

## 4. Architecture & Design

### Import-Linter Contract Review
[For each contract: still correct? needs new modules? references stale modules? missing contracts?]

---

## 5. What Was Done Well

### Top Highlights
[Numbered list — patterns others should follow, clever solutions, good discipline]

---

## 6. Issues & Improvements

### 🔴 High Priority
[Bugs, correctness issues, missing defensive coding, dead code]

### 🟡 Medium Priority
[Duplication, inconsistencies, efficiency issues]

### 🟢 Low Priority
[Minor naming, trivial indirection, test cleanup]

---

## 7. Recommendations for Next Phase
[Ordered by impact. Reference specific issues from section 6.]

---
*End of review.*

---

Important guidelines:
- Be specific. Reference exact file names, line numbers, function names, code snippets.
- Every improvement must have a concrete suggestion — don't just flag problems.
- Prioritize ruthlessly. Use the 🔴/🟡/🟢 system honestly.
- Acknowledge what's good. Recognizing good patterns helps maintain them.
- Do NOT check plan adherence. Focus on the code as it exists now.
- Think cross-cutting. Your unique value is finding issues that span multiple files.

In section 6, format every 🔴 High Priority issue as a self-contained, actionable fix item with:
- Exact file and line reference
- What is wrong
- Exactly what to change, including correct code for non-trivial fixes

These items will be passed verbatim to a Sonnet implementer.
```

---

## Step 2 — Fix high-priority issues (Sonnet)

After the Opus review subagent completes:

1. Read the review file it just wrote (path: `docs/LLM/reviews/phase-{N}-review.md`, where N is `current_state.phase` from `docs/LLM/memory.yaml`)
2. Extract all items listed under section 6 **🔴 High Priority**

If there are no high-priority items, skip to Step 3.

Otherwise spawn a **general-purpose** subagent with `model: sonnet` and the following instructions:

```
You are an expert software engineer applying a precise set of fixes identified by a code reviewer.

Read:
1. CLAUDE.md — project conventions
2. Each file referenced in the fix list before modifying it

Fix list:
{HIGH_PRIORITY_ITEMS_FROM_REVIEW}

Rules:
- Implement every fix exactly as described. Do not deviate or improve beyond what is listed.
- Do not modify anything not referenced in the fix list.
- After all fixes are applied, run `bash verify.sh` and confirm it passes.
- If verify.sh fails after applying the fixes, report the error — do not attempt to work around it
  by weakening tests or removing contracts.
```

Wait for the Fix subagent to complete and confirm verify.sh passes.

---

## Step 3 — Report back

Report to the user:
- Path to the review file
- The executive summary
- Count of high/medium/low priority issues found, and how many high-priority items were fixed
- Top 3 recommendations for the next phase
