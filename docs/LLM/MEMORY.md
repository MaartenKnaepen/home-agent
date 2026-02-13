# 🧠 Home Agent — Project Memory

> **Purpose:** Living document tracking project history, decisions made, lessons learned, and current state. LLM agents should read this before starting any work to understand context.

---

## 📍 Current State

- **Phase:** Pre-implementation (planning complete)
- **Last Updated:** 2026-02-13
- **Key Documents:**
  - `docs/LLM/DETAILED_PLAN.md` — Architecture decisions and phased breakdown
  - `docs/LLM/IMPLEMENTATION.md` — Task-level implementation steps with test criteria
  - `docs/LLM/AGENTS.md` — Coding standards and patterns
  - `docs/LLM/API.md` — Function registry (every function/class in the project)
  - `docs/LLM/ARCHITECT.md` — System prompt for architect LLM to generate task plans

---

## 🏛️ Architecture Decisions

### AD-001: PydanticAI over LangGraph/Haystack
- **Date:** 2026-02-13
- **Decision:** Use PydanticAI as the agent framework
- **Rationale:** Model-agnostic, native MCP support, `history_processors` for token cost control, dependency injection, Pythonic. LangGraph's `interrupt()` / graph machinery is overkill — Telegram's message flow *is* the human-in-the-loop. Haystack's pipeline model is optimized for RAG, not conversational agents.
- **Status:** ✅ Final

### AD-002: MCP for Service Integration (Prefer Existing)
- **Date:** 2026-02-13
- **Decision:** Use MCP (Model Context Protocol) to connect to home server services. Always search for existing community MCP servers first; build custom only as a last resort.
- **Rationale:** Standard protocol, decoupled, reusable. Avoids hand-writing tool wrappers. PydanticAI has first-class MCP client support.
- **Status:** ✅ Final

### AD-003: OpenRouter Free Tier Only
- **Date:** 2026-02-13
- **Decision:** All LLM calls use free-tier models via OpenRouter. $10 top-up for 1000 free requests/day. No fallback to paid models.
- **Rationale:** Cost constraint. Free models (Llama, Mistral, Gemma, DeepSeek) are capable enough. Token management via sliding window + user profile keeps context small.
- **Status:** ✅ Final

### AD-004: Evolving User Profile for Personalization
- **Date:** 2026-02-13
- **Decision:** Agent maintains a per-user profile that evolves over time. Profile injected into system prompt so the agent always "knows" the user without replaying full history.
- **Rationale:** Token-efficient personalization. Sliding window loses old context, but the profile persists key observations. The agent updates the profile via a tool.
- **Status:** ✅ Final

### AD-005: Telegram Conversation as Human-in-the-Loop
- **Date:** 2026-02-13
- **Decision:** No programmatic interrupt mechanism. The agent itself decides when to ask for confirmation, guided by the system prompt.
- **Rationale:** Natural conversational flow. Simpler than LangGraph's interrupt/resume. Confirmation rules are defined in the system prompt (always confirm before mutating actions).
- **Status:** ✅ Final

### AD-006: SQLite for Persistence
- **Date:** 2026-02-13
- **Decision:** SQLite for conversation history and user profiles.
- **Rationale:** Zero-dependency, single file on disk, sufficient for single/few users on a home server. Async access via `aiosqlite`.
- **Status:** ✅ Final

---

## 📋 Decision Log (Chronological)

| Date | Topic | Decision | Notes |
|------|-------|----------|-------|
| 2026-02-13 | Framework | PydanticAI | Over LangGraph (overkill) and Haystack (RAG-focused) |
| 2026-02-13 | Service integration | MCP (prefer existing) | Build custom MCP servers only as last resort |
| 2026-02-13 | LLM provider | OpenRouter free tier only | $10 top-up, no paid fallback |
| 2026-02-13 | Memory strategy | User Profile + sliding window | Profile in system prompt, history windowed |
| 2026-02-13 | Human-in-the-loop | Telegram conversation | No LangGraph interrupt, agent decides conversationally |
| 2026-02-13 | Persistence | SQLite via aiosqlite | Single file, zero-dependency |
| 2026-02-13 | Deployment | Docker Compose | Consistent with existing home server stack |

---

## 🏠 Home Server Services

Services running on the home server that the agent will eventually integrate with:

| Service | Purpose | MCP Status | Notes |
|---------|---------|------------|-------|
| Jellyseerr | Media requests & discovery | 🔍 Not yet researched | Phase 1 — MVP |
| Glances | System monitoring | 🔍 Not yet researched | Phase 2 |
| Immich | Photo management | 🔍 Not yet researched | Phase 3 |
| Mealie | Recipe management | 🔍 Not yet researched | Phase 3 |
| BabyBuddy | Baby tracking | 🔍 Not yet researched | Phase 3 |
| Paperless-ngx | Document management | 🔍 Not yet researched | Phase 3 |
| Vikunja | Task management | 🔍 Not yet researched | Phase 3 |
| Portainer | Docker management | 🔍 Not yet researched | Phase 3 |
| Duplicati | Backup management | 🔍 Not yet researched | Phase 3 |
| Uptime Kuma | Uptime monitoring | 🔍 Not yet researched | Phase 3 |
| IT Tools | Utility tools | 🔍 Not yet researched | Phase 4 |
| BentoPDF/Vert | File conversion | 🔍 Not yet researched | Phase 4 |

**MCP Status Legend:** 🔍 Not yet researched | 🔎 Researching | ✅ Found existing | 🔨 Building custom | ❌ No MCP needed

---

## 🧪 Lessons Learned

_This section will be populated as implementation progresses._

<!-- Template:
### LL-001: [Title]
- **Date:** YYYY-MM-DD
- **Context:** What were we doing?
- **Problem:** What went wrong?
- **Resolution:** How did we fix it?
- **Takeaway:** What should we do differently next time?
-->

---

## 🚧 Known Issues & Blockers

_This section will be populated as implementation progresses._

<!-- Template:
### Issue: [Title]
- **Status:** Open / Resolved
- **Impact:** What does this block?
- **Workaround:** Temporary fix, if any.
-->

---

## 📝 Update Instructions

When completing a task or making a decision:

1. **Update "Current State"** with the new phase/status
2. **Add to "Decision Log"** if a new architectural choice was made
3. **Add to "Lessons Learned"** if something unexpected happened
4. **Update "Home Server Services"** MCP Status when researching/integrating services
5. **Add to "Known Issues"** if a blocker is discovered
