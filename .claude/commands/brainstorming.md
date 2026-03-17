# Brainstorming — Ideas Into Designs

Turn raw ideas into clear, validated designs through structured dialogue **before any implementation begins**.

You are **not allowed** to implement, code, or modify files while this skill is active.

---

## Step 1 — Read Project Context (Mandatory First)

Before asking any questions, read:
- `CLAUDE.md` — architecture constraints and conventions
- `docs/LLM/memory.yaml` — decisions already made, current state
- `docs/LLM/implementation.yaml` — what is already planned
- `docs/LLM/DETAILED_PLAN.md` — overall architecture and direction

Identify what already exists vs. what is being proposed. Note implicit constraints.

**Do not design yet.**

---

## Step 2 — Understand the Idea (One Question at a Time)

Ask **one question per message**. Prefer multiple-choice when possible.

Focus on:
- Purpose — what problem does this solve?
- Users — who benefits?
- Constraints — what must it work within?
- Success criteria — how will we know it worked?
- Non-goals — what is explicitly out of scope?

---

## Step 3 — Non-Functional Requirements (Mandatory)

Explicitly clarify or propose assumptions for:
- Performance expectations
- Scale (messages/day, users, data volume)
- Security or privacy constraints
- Reliability needs
- Fit with existing architecture layers (see CLAUDE.md)

Mark anything unconfirmed as an **assumption**.

---

## Step 4 — Understanding Lock (Hard Gate)

Before proposing any design, produce:

**Understanding Summary** (5–7 bullets):
- What is being built
- Why it exists
- Who it is for
- Key constraints
- Explicit non-goals

**Assumptions** — list all explicitly.

**Open Questions** — list anything unresolved.

Then ask:
> "Does this accurately reflect your intent? Please confirm or correct anything before we move to design."

**Do NOT proceed until explicit confirmation.**

---

## Step 5 — Explore Design Approaches

Once understanding is confirmed, propose **2–3 viable approaches**:
- Lead with your recommended option
- Explain trade-offs: complexity, extensibility, risk, maintenance
- Evaluate fit with existing architecture (import-linter boundaries, layer separation)
- Apply YAGNI ruthlessly — avoid speculative features

This is still not final design.

---

## Step 6 — Present the Design (Incrementally)

Break the design into sections of 200–300 words. After each section ask:
> "Does this look right so far?"

Cover as relevant:
- Architecture and layer placement
- Data flow
- New modules and their import-linter contracts
- Error handling
- Edge cases
- Testing strategy (TestModel for agent tests, tmp_path for DB, etc.)

---

## Step 7 — Decision Log (Mandatory)

Maintain a running **Decision Log** throughout. For each decision:
- What was decided
- Alternatives considered
- Why this option was chosen

---

## After the Design

Once validated, write a design document to `docs/LLM/plans/design-{feature}.md` containing:
- Understanding summary
- Assumptions
- Decision log
- Final design

Then ask:
> "Ready to set up for implementation?"

If yes — create steps in `docs/LLM/implementation.yaml` and hand off to `/implement-step`.

---

## Exit Criteria (Hard Stop)

Only exit brainstorming mode when ALL of the following are true:
- Understanding Lock confirmed
- At least one design approach explicitly accepted
- Major assumptions documented
- Key risks acknowledged
- Decision Log complete

If any criterion is unmet, continue refinement. **Do NOT proceed to implementation.**

---

## Key Principles

- One question at a time
- Assumptions must be explicit
- Explore alternatives
- Validate incrementally
- Prefer clarity over cleverness
- YAGNI ruthlessly
