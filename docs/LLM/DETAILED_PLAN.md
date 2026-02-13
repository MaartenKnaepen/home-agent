# Home Server Telegram Agent — Detailed Implementation Plan

## Executive Summary

A production-quality Telegram bot that lets you manage your home server via natural language. Built with **PydanticAI** as the agent framework, **MCP (Model Context Protocol)** for service integration, and **python-telegram-bot** for the Telegram interface. All LLM calls use **free-tier models** via OpenRouter ($10 top-up for 1000 free requests/day).

The agent is **personalized** — it maintains an evolving user profile that tracks preferences, viewing habits, and behavioral patterns, making every interaction feel tailored.

---

## 1. Architecture Overview

```
┌─────────────┐     ┌──────────────────┐     ┌──────────────────────┐
│  Telegram    │────▶│  python-telegram  │────▶│   PydanticAI Agent   │
│  User Chat   │◀────│  -bot (async)     │◀────│                      │
└─────────────┘     └──────────────────┘     │  ┌────────────────┐  │
                                              │  │ User Profile    │  │
                                              │  │ (evolving)      │  │
                                              │  └────────────────┘  │
                                              │                      │
                                              │  ┌────────────────┐  │
                                              │  │ History         │  │
                                              │  │ Processor       │  │
                                              │  └────────────────┘  │
                                              └──────────┬───────────┘
                                                         │
                                              ┌──────────▼───────────┐
                                              │   MCP Client Layer   │
                                              │                      │
                                              │  ┌───┐ ┌───┐ ┌───┐  │
                                              │  │ J │ │ G │ │...│  │
                                              │  └─┬─┘ └─┬─┘ └─┬─┘  │
                                              └────┼─────┼─────┼────┘
                                                   │     │     │
                                              ┌────▼─┐ ┌─▼──┐ ┌▼────┐
                                              │Jelly-│ │Gla-│ │Other│
                                              │seerr │ │nces│ │MCPs │
                                              └──────┘ └────┘ └─────┘
```

**Key principle**: The agent connects to **existing MCP servers** for each home server service. We only build our own MCP server if no community alternative exists or works.

### Services Inventory (eventual scope)

| Service | Purpose | MCP Server Strategy |
|---------|---------|---------------------|
| **Jellyseerr** | Media requests & discovery | Find existing or build |
| **Glances** | System monitoring | Find existing or build |
| **Immich** | Photo management | Find existing or build |
| **Mealie** | Recipe management | Find existing or build |
| **BabyBuddy** | Baby tracking | Find existing or build |
| **Paperless-ngx** | Document management | Find existing or build |
| **Vikunja** | Task management | Find existing or build |
| **Portainer** | Docker management | Find existing or build |
| **Duplicati** | Backup management | Find existing or build |
| **Uptime Kuma** | Uptime monitoring | Find existing or build |
| **IT Tools** | Utility tools (future) | Find existing or build |
| **BentoPDF/Vert** | File conversion (future) | Find existing or build |

---

## 2. Core Technology Stack

### 2.1 Agent Framework: PydanticAI

**Why PydanticAI over LangGraph/Haystack:**

- **Model-agnostic**: Switch between OpenRouter, Groq, Ollama with one line
- **First-class MCP support**: `FastMCPToolset` as native toolset (stdio subprocess, HTTP, or JSON config)
- **Dependency injection**: Clean way to pass user profile, DB connections, service clients
- **`history_processors`**: Built-in sliding window + summarization for token cost control
- **Pythonic**: Type-safe, less magic, easier to debug
- **Lightweight**: Fewer dependencies than LangGraph's entire LangChain ecosystem

**Why NOT LangGraph**: Telegram's message flow *is* the human-in-the-loop mechanism. LangGraph's `interrupt()` / graph / checkpointer adds complexity without benefit for a single-agent conversational bot.

**Why NOT Haystack**: PydanticAI + MCP gives us everything we need. Haystack's pipeline model is optimized for RAG, not conversational agents with tool calling.

### 2.2 Telegram: python-telegram-bot (v21+)

- Async-native, well-maintained, excellent docs
- `ConversationHandler` for multi-step flows (confirmations)
- Webhook mode for production (no polling overhead)

### 2.3 LLM Provider: OpenRouter (free tier only)

- $10 top-up → 1000 free requests/day
- Access to free models: Llama 3.1, Mistral, Gemma, DeepSeek, etc.
- Single API, model switching is just a string change
- **No fallback to paid models** — we stay within free tier constraints and optimize around them

### 2.4 Persistence: SQLite

- Conversation history per user
- User profiles (evolving)
- No external DB dependency — single file on disk

### 2.5 Configuration: pydantic-settings

- `.env` file for secrets (API keys, Telegram token, service URLs)
- Type-safe, validated config

---

## 3. User Profile System

The agent maintains an **evolving user profile** per Telegram user that makes interactions feel personalized.

### 3.1 Profile Structure

```python
class MediaPreferences(BaseModel):
    preferred_genres: list[str] = []
    preferred_quality: str = "1080p"
    preferred_language: str = "en"
    avoid_genres: list[str] = []

class NotificationPrefs(BaseModel):
    notify_on_download_complete: bool = True
    quiet_hours: tuple[int, int] | None = None  # e.g., (23, 7)

class UserProfile(BaseModel):
    telegram_id: int
    name: str

    # Preferences
    preferred_language: str = "en"
    media_preferences: MediaPreferences = MediaPreferences()
    notification_preferences: NotificationPrefs = NotificationPrefs()

    # Behavioral patterns
    common_requests: list[str] = []       # "usually searches for 4K", "prefers dubbed"
    interaction_style: str = "default"    # "brief", "detailed", "casual"

    # Context
    last_active: datetime
    total_interactions: int = 0
    notes: list[str] = []                 # Agent-managed free-form notes about the user

    # Service-specific
    jellyseerr_defaults: dict = {}        # e.g., default quality profile
```

### 3.2 Profile Evolution

The profile updates **implicitly** based on interactions:

- Agent observes patterns: "User always picks 1080p over 4K" → updates `media_preferences`
- Agent notes context: "User mentioned they have a baby" → adds to `notes`
- A **profile update tool** is available to the agent so it can write observations back

The profile is injected into the system prompt as context, so the agent always "remembers" the user without replaying full history.

### 3.3 How It Feels

```
User: Get me that new Marvel movie
Agent: Found "Thunderbolts*" (2025). Want me to request it in 1080p
       like usual, or go for 4K this time? 🎬
```

The agent knows "like usual" because the profile says `preferred_quality: "1080p"`.

---

## 4. Conversation & Token Management

### 4.1 History Processing Pipeline

PydanticAI's `history_processors` let us control what goes into each LLM call:

```
Full History (SQLite)
    → Sliding Window (last N messages)
    → User Profile Injection (system prompt)
    → LLM Call
```

**Strategy:**

1. **SQLite** stores the complete conversation history per user
2. **Sliding window** sends only the last ~10-20 messages to the LLM
3. **User profile** is always in the system prompt — this is the "memory" that persists beyond the window
4. **Periodic summarization** (optional): Every N messages, the agent summarizes key facts and adds them to the user profile `notes`

### 4.2 Token Budget

With free-tier models (typically 8K-32K context):

- System prompt + user profile: ~500-1000 tokens
- Tool definitions (from MCP): ~500-1500 tokens (depending on active servers)
- Conversation window: ~2000-4000 tokens
- Response budget: ~1000-2000 tokens

This keeps us well within free-tier limits even with smaller context windows.

---

## 5. MCP Integration Strategy

### 5.1 Approach: Prefer Existing, Build If Needed

For each service:

1. **Search** for existing community MCP servers (GitHub, MCP registries)
2. **Evaluate**: Does it work? Does it cover our needs?
3. **Use it** if functional, even if imperfect
4. **Build our own** only as a last resort, using FastMCP (~100-300 lines per server)

### 5.2 MCP Transport

PydanticAI's `FastMCPToolset` (from `pydantic_ai.toolsets.fastmcp`) supports multiple transport modes:

- **Phase 1**: Stdio (subprocess) — `FastMCPToolset("uvx", args=["server-name"])`. MCP servers run as subprocesses. Simple, no networking.
- **Later**: HTTP — `FastMCPToolset("http://localhost:8000/mcp")`. For independently deployable MCP server containers.
- **Multi-server**: JSON config — `FastMCPToolset({"mcpServers": {...}})`. Define multiple servers in one config.

### 5.3 Tool Filtering

When multiple MCP servers are connected, the total tool count can get large (increasing token cost). Strategy:

- **Context-aware loading**: Only connect MCP servers relevant to the current conversation topic
- **Tool description optimization**: Keep tool descriptions concise
- **Lazy connection**: Connect to an MCP server only when the agent decides it needs it

---

## 6. Confirmation Flow (Human-in-the-Loop)

Telegram's conversational nature naturally provides human-in-the-loop:

```
User: "Download Inception"
Agent: [calls jellyseerr search tool]
Agent: "Found Inception (2010) ⭐8.8. Request in 1080p? [Yes / No / 4K instead]"
User: "Yes"
Agent: [calls jellyseerr request tool]
Agent: "Done! ✅ I'll let you know when it's ready."
```

### Implementation

The **agent itself** decides when to ask for confirmation vs. acting directly, guided by the system prompt:

```
Rules:
- ALWAYS confirm before: requesting media, deleting anything, modifying settings
- NEVER need confirmation for: searching, checking status, reading info
```

This is simpler and more flexible than LangGraph's programmatic interrupt mechanism — the LLM handles it conversationally.

---

## 7. Project Structure

```
home-agent/
├── src/
│   └── home_agent/
│       ├── __init__.py
│       ├── main.py              # Entry point, starts bot
│       ├── config.py            # pydantic-settings config
│       ├── agent.py             # PydanticAI agent definition
│       ├── bot.py               # python-telegram-bot setup & handlers
│       ├── profile.py           # UserProfile model & persistence
│       ├── history.py           # Conversation history & processors
│       ├── db.py                # SQLite connection & migrations
│       ├── tools/
│       │   ├── __init__.py
│       │   ├── profile_tools.py # Tools for the agent to update user profile
│       │   └── telegram_tools.py# Tools for rich replies (images, buttons)
│       └── mcp/
│           ├── __init__.py
│           ├── registry.py      # MCP server registry & lifecycle
│           └── servers.py       # MCP server configurations
├── mcp_servers/                 # Only for self-built MCP servers (last resort)
│   └── README.md                # Notes on when/why we built our own
├── tests/
│   ├── test_agent.py
│   ├── test_profile.py
│   └── test_history.py
├── docs/
│   └── LLM/
│       ├── DETAILED_PLAN.md     # This document (architecture & phases)
│       ├── IMPLEMENTATION.md    # Task-level steps with test criteria
│       ├── AGENTS.md            # Coding standards and patterns
│       ├── API.md               # Function registry
│       ├── ARCHITECT.md         # System prompt for architect LLM
│       └── MEMORY.md            # Project history & decisions
├── .env.example
├── pyproject.toml
├── Dockerfile
└── docker-compose.yml
```

---

## 8. Phased Implementation

### Phase 1: MVP — Telegram + Jellyseerr (Weeks 1-2)

**Goal**: A working bot that can search and request media via natural language.

| Step | Task | Details |
|------|------|---------|
| 1.1 | Project scaffolding | `pyproject.toml`, `src/` layout, `pydantic-settings` config, `.env.example` |
| 1.2 | Telegram bot skeleton | `python-telegram-bot` with webhook/polling, basic message handler, user whitelist |
| 1.3 | PydanticAI agent setup | Agent with system prompt, OpenRouter free model, dependency injection |
| 1.4 | Jellyseerr MCP server | Find existing or build with FastMCP. Core tools: search, get details, request |
| 1.5 | Wire it together | Telegram message → Agent → MCP tools → response back to Telegram |
| 1.6 | Confirmation flow | Agent asks for confirmation before requesting media |
| 1.7 | SQLite persistence | Conversation history stored per user |
| 1.8 | User profile (basic) | Profile creation, preference tracking, profile injected into system prompt |
| 1.9 | History processor | Sliding window to control token costs |
| 1.10 | Docker | Dockerfile + docker-compose for deployment on home server |

**Deliverable**: Bot you can message "Get me Inception" and it searches Jellyseerr, confirms, and submits the request.

### Phase 2: Glances Integration (Week 3)

**Goal**: Add system monitoring capabilities.

| Step | Task | Details |
|------|------|---------|
| 2.1 | Find/build Glances MCP server | Search for existing, build if needed |
| 2.2 | Connect to agent | Add Glances MCP server to the registry |
| 2.3 | System prompt update | Teach the agent about system monitoring capabilities |

**Deliverable**: "How's my server doing?" → CPU/RAM/disk/network stats in natural language.

### Phase 3: Expand Services (Weeks 4+)

Add MCP servers one at a time, prioritized by usage:

| Priority | Service | Example Interactions |
|----------|---------|---------------------|
| 1 | **Immich** | "Show me photos from last weekend", "How much storage is Immich using?" |
| 2 | **Mealie** | "What's for dinner?", "Add chicken tikka to the meal plan" |
| 3 | **BabyBuddy** | "Log a feeding", "When was the last diaper change?" |
| 4 | **Paperless-ngx** | "Find my electricity bill from January", "Tag this document" |
| 5 | **Vikunja** | "Add a task: fix the leaky faucet", "What's on my todo list?" |
| 6 | **Uptime Kuma** | "Is everything online?", "What went down today?" |
| 7 | **Portainer** | "Restart the Jellyfin container", "Which containers are running?" |
| 8 | **Duplicati** | "When was the last backup?", "Is my backup healthy?" |

Each service follows the same pattern:

1. Search for existing MCP server
2. Evaluate & test
3. Connect to agent
4. Update system prompt
5. Test end-to-end

### Phase 4: Polish & Advanced Features (Ongoing)

- **Rich Telegram formatting**: Inline keyboards, images (movie posters from Jellyseerr), progress bars
- **Proactive notifications**: "Your download of Inception is complete! 🍿"
- **Multi-user**: Different profiles, different permissions
- **IT Tools / BentoPDF / Vert**: File conversion capabilities
- **Voice messages**: Whisper transcription → agent → response

---

## 9. Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Agent framework | PydanticAI | Model-agnostic, MCP-native, Pythonic, lightweight |
| Service integration | MCP via `FastMCPToolset` (prefer existing servers) | Standard protocol, decoupled, reusable |
| LLM provider | OpenRouter free tier only | $10 top-up for 1000 req/day, model flexibility, no paid fallback |
| Human-in-the-loop | Telegram conversation | Natural, no framework overhead |
| Memory | User Profile + sliding window | Token-efficient, personalized |
| Persistence | SQLite | Zero-dependency, single file, sufficient for single/few users |
| Deployment | Docker Compose | Consistent with existing home server setup |

---

## 10. Dependencies (Phase 1)

```toml
[project]
dependencies = [
    "pydantic-ai[openai,fastmcp]",       # Agent framework + OpenAI-compatible client (for OpenRouter) + FastMCP toolset
    "python-telegram-bot[webhooks]",     # Telegram bot
    "pydantic-settings",                 # Config management
    "aiosqlite",                         # Async SQLite
    "fastmcp",                           # For building custom MCP servers (only if needed)
]
```

---

## 11. Security

- **Telegram user ID whitelist** — only authorized users can interact
- **API keys in `.env`** — never exposed to the LLM or logged
- **MCP servers as subprocesses** (`stdio`) — no network exposure
- **Confirmation required** for all mutating actions

---

## 12. Open Questions (to resolve during implementation)

1. **Jellyseerr MCP**: Does a community one exist? If not, the Jellyseerr API is well-documented, FastMCP wrapper should be ~200 lines.
2. **Webhook vs Polling**: Webhook is better for production but requires HTTPS endpoint. If home server isn't publicly exposed, polling with `asyncio` is fine.
3. **Movie posters**: Fetch from TMDB or Jellyseerr's cache? Send as Telegram photos for richer UX.
4. **Proactive notifications**: Jellyseerr webhooks → agent push notification, or periodic polling?
