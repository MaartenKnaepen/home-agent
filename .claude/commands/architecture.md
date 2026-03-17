# Architecture — System Design and Decision Framework

> "Requirements drive architecture. Trade-offs inform decisions. ADRs capture rationale."
> "Simplicity is the ultimate sophistication — add complexity only when proven necessary."

---

## Step 1 — Read Project Context

Before any design work, read:
- `CLAUDE.md` — existing layer boundaries and import-linter contracts
- `docs/LLM/memory.yaml` — past architectural decisions and lessons learned
- `docs/LLM/DETAILED_PLAN.md` — overall architecture diagram and principles
- `pyproject.toml [tool.importlinter.contracts]` — enforced boundaries

Understand what already exists before proposing changes.

---

## Step 2 — Requirements Analysis

Clarify before designing:

**Functional requirements**
- What behaviour must the system exhibit?
- What are the inputs and outputs?

**Non-functional requirements**
- Performance: latency budgets, throughput targets
- Scale: concurrent users, message volume, data size
- Reliability: what happens when an external service (Telegram, MCP server, LLM) is down?
- Security: authentication, data sensitivity, exposure surface

**Constraints**
- Must fit within existing layer boundaries (Bot → Agent → Tools / MCP → Core)
- Must not introduce circular imports (import-linter enforces this)
- Must remain async-first — no blocking I/O
- External services accessed only via MCP servers or explicit HTTP clients

---

## Step 3 — Evaluate Pattern Options

For each significant decision, consider at least two options and document trade-offs:

| Dimension | Option A | Option B |
|-----------|----------|----------|
| Complexity | | |
| Fit with existing architecture | | |
| Testability | | |
| Extensibility | | |
| Risk | | |

**Default to the simpler option** unless there is a concrete, proven reason to add complexity.

Common patterns relevant to this project:
- **Registry pattern** — for MCP server management (already used in `mcp/registry.py`)
- **Dependency injection** — via `AgentDeps` dataclass (already established)
- **Repository pattern** — for data access via `db.py` functions
- **Toolset wrapper** — for GuardedToolset / custom MCP integrations (must subclass `AbstractToolset`)

---

## Step 4 — Layer Placement Decision

Every new module must have an explicit layer assignment:

| Layer | Location | May import from |
|-------|----------|-----------------|
| Bot | `src/home_agent/bot.py` | Agent, Core |
| Agent | `src/home_agent/agent.py` | Tools, Core |
| Tools | `src/home_agent/tools/` | Core |
| MCP | `src/home_agent/mcp/` | Core |
| Core | `config.py`, `db.py`, `profile.py`, `history.py` | Nothing internal |

If the new module doesn't fit cleanly into a layer, that's a design signal — explore why.

---

## Step 5 — Write Architecture Decision Records (ADRs)

For every significant decision, produce an ADR in `docs/LLM/plans/`:

```markdown
# ADR: {Short Title}

**Date:** {date}
**Status:** Accepted

## Context
What situation or requirement prompted this decision?

## Decision
What was decided?

## Alternatives Considered
- Option A: [description] — rejected because [reason]
- Option B: [description] — rejected because [reason]

## Consequences
- Positive: [what this enables]
- Negative: [what this constrains]
- Neutral: [what this changes without clear valence]

## Import-Linter Impact
Does this require a new contract or changes to `pyproject.toml`?
```

---

## Step 6 — Validation Checklist

Before finalising architecture:

- [ ] Requirements clearly understood and documented
- [ ] Each significant decision has an ADR with trade-off analysis
- [ ] Simpler alternatives were genuinely considered
- [ ] New module has a clear layer assignment
- [ ] Import-linter contracts updated or noted for update
- [ ] Testability considered — is the new component testable without framework mocks?
- [ ] Async boundaries respected — no blocking I/O in async paths
- [ ] Security surface evaluated — new endpoints, new secrets, new external calls?

---

## Output

Produce:
1. ADR(s) in `docs/LLM/plans/`
2. A summary of the architecture decision and its layer placement
3. Recommended next step: brainstorming refinement, or new steps in `implementation.yaml`
