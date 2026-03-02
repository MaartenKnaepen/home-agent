# PydanticAI Agent Tool Control — Overview

> Goal: enforce workflow order and add gates (e.g. quality check before request) for Overseerr now, with room to expand to other MCP servers and custom tools later.

---

## The Core Problem

Prompts are **suggestions**. Tool return values are **facts** the model must respond to.  
Gates belong in code, not in prompts. Use prompts for happy-path guidance; use tool guards for hard stops.

---

## Option A — Wrapper Tools (no raw MCP exposure)

**How it works:** Don't give the agent direct access to MCP tools. Register your own `@agent.tool` functions that run guard logic first, then forward to the MCP server via the client stored in `RunContext.deps`.

```python
@agent.tool
async def request_media(ctx: RunContext[Deps], mediaType: str, mediaId: int, is4k: bool, seasons: str | list = "all"):
    if mediaType == "movie" and not ctx.deps.movie_quality:
        return "STOP: movie_quality not set. Ask the user: '4K or 1080p for movies?'"
    if mediaType == "tv" and not ctx.deps.series_quality:
        return "STOP: series_quality not set. Ask the user: '4K or 1080p for series?'"

    return await ctx.deps.mcp_client.call_tool("request_media", {
        "mediaType": mediaType, "mediaId": mediaId,
        "is4k": is4k, "seasons": seasons
    })
```

**Pros:**
- Full control per tool
- Easy to read and debug
- Gate logic lives next to the tool definition
- Works for MCP tools and future custom tools identically

**Cons:**
- Must enumerate every tool you want to gate (manual, but fine for a known set like Overseerr)
- Schema must match what the model expects

**Best for:** Known, small tool sets (Overseerr). Recommended starting point.

---

## Option B — Subclassed MCP Client (transparent middleware)

**How it works:** Subclass the MCP `ClientSession` and override `call_tool`. All tool calls pass through your middleware regardless of how many tools are exposed.

```python
class GuardedMCPClient(ClientSession):
    def __init__(self, *args, state: AgentState, **kwargs):
        super().__init__(*args, **kwargs)
        self.state = state

    async def call_tool(self, name: str, arguments: dict):
        if name == "request_media":
            if arguments.get("mediaType") == "movie" and not self.state.movie_quality:
                return ToolResult(content="STOP: movie_quality not set.")
        return await super().call_tool(name, arguments)
```

**Pros:**
- Intercepts all MCP tools automatically — no need to enumerate them
- Great when adding new MCP servers; guards apply globally
- Model still sees native MCP tool schemas

**Cons:**
- Slightly more complex to set up
- Return type must match MCP `ToolResult` format
- Harder to apply tool-specific logic cleanly

**Best for:** Multiple MCP servers with many tools, or when you don't want to maintain wrapper stubs.

---

## Option C — Structured Pipeline (staged agents)

**How it works:** Break the workflow into explicit stages in your application code. Each stage invokes the agent with only the tools relevant to that step.

```
Stage 1: search_agent     → tools: [search_media]           → returns SearchResult
Stage 2: quality_agent    → tools: [set_movie_quality]      → returns QualityPref
Stage 3: confirm_agent    → tools: [request_media]          → returns RequestResult
```

```python
# Pseudocode
search_result = await search_agent.run(user_query)
quality = await quality_agent.run(search_result)
final = await request_agent.run(quality)
```

**Pros:**
- Hardest possible enforcement — model literally cannot call the wrong tool
- Very predictable, easy to test each stage in isolation

**Cons:**
- More boilerplate
- Less flexible for open-ended conversations
- Harder to let the user change their mind mid-flow

**Best for:** High-stakes or highly structured workflows where correctness matters more than conversational flexibility.

---

## Option D — State tracking via message hooks

**How it works:** Use PydanticAI's message stream or post-processing to track which tools have been called. Inject corrective system messages if the agent skips a required step.

```python
async for chunk in agent.run_stream(user_input):
    if chunk.tool_call and chunk.tool_call.name == "request_media":
        if "search_media" not in called_tools:
            # Inject correction into next turn
            inject_message("You must call search_media before request_media.")
    called_tools.add(chunk.tool_call.name)
```

**Pros:**
- Non-invasive — no changes to tool definitions
- Can enforce sequencing rules post-hoc

**Cons:**
- Reactive, not preventive — the wrong call may have already gone through
- More complex async handling
- Fragile if the agent is fast or batches calls

**Best for:** Soft enforcement / logging / auditing rather than hard gates.

---

## Comparison Table

| Option | Enforcement | MCP compatible | Scales to new tools | Complexity |
|--------|-------------|----------------|---------------------|------------|
| A — Wrapper tools | Hard (return error) | ✅ via client.call_tool | Manual per tool | Low |
| B — Subclassed client | Hard (intercept) | ✅ native | Automatic | Medium |
| C — Staged pipeline | Absolute (no access) | ✅ per stage | Per stage | High |
| D — Message hooks | Soft (corrective) | ✅ | Automatic | Medium |

---

## Recommended Approach for This Project

### Now (Overseerr only)
Use **Option A** as the foundation:
- Wrap `request_media`, `search_media`, `set_movie_quality`, `set_series_quality`
- Store all state (`movie_quality`, `series_quality`, `confirmation_mode`, `last_search_results`) in a `Deps` dataclass on `RunContext`
- Return plain English error strings from guards — the model will relay them naturally

### Later (expanding to more MCP servers / custom tools)
Layer in **Option B** on top:
- Move global guards (rate limiting, auth checks, logging) into a subclassed client
- Keep per-tool business logic in Option A wrappers
- Add new MCP servers without touching guard code

### If you need absolute reliability for a specific flow
Add **Option C** for that specific workflow only (e.g., the full media request sequence), while keeping the rest conversational.

---

## State Dataclass (starting point)

```python
from dataclasses import dataclass, field

@dataclass
class AgentDeps:
    mcp_client: MCPClient
    movie_quality: str | None = None      # "4k" | "1080p" | None
    series_quality: str | None = None     # "4k" | "1080p" | None
    confirmation_mode: str = "always"     # "always" | "never"
    reply_language: str = "English"
    last_search_results: list = field(default_factory=list)  # store for disambiguation
    called_tools: set = field(default_factory=set)           # optional: for Option D
```

---

## Key Rule

> **Prompts change what the model *wants* to do.  
> Tool return values change what it *can* do next.**

Always put hard gates in tool code. Use the prompt only for happy-path guidance and tone.

# PydanticAI Agent — Stateful Workflow with Guarded MCP Client

> Implements the Overseerr media request workflow: **search → disambiguate → quality gate → confirm → request**  
> Architecture scales cleanly to additional MCP servers (PDF, file utilities, etc.) with zero changes to the core pattern.

---

## Core Principle

The workflow is a **state machine**. The guarded MCP client checks state on every tool call and either:
- **Blocks** the call and returns an error string the model must react to
- **Advances** the state and passes the call through to the MCP server
- **Passes through** unguarded tools (e.g. PDF/file utilities) without touching them

Prompts handle happy-path guidance. Code handles hard gates.

---

## Workflow States

```python
from enum import Enum

class WorkflowState(Enum):
    IDLE = "idle"
    SEARCHED = "searched"           # search_media called, results stored
    DISAMBIGUATED = "disambiguated" # user picked one result
    QUALITY_SET = "quality_set"     # quality preference confirmed
    CONFIRMED = "confirmed"         # user confirmed the request
```

---

## Deps / State Dataclass

```python
from dataclasses import dataclass, field

@dataclass
class AgentDeps:
    mcp_client: GuardedMCPClient
    workflow: WorkflowState = WorkflowState.IDLE

    # Search stage
    last_search_results: list = field(default_factory=list)
    selected_media: dict | None = None      # the item the user picked

    # Quality stage
    movie_quality: str | None = None        # "4k" | "1080p"
    series_quality: str | None = None       # "4k" | "1080p"

    # Confirmation stage
    confirmation_mode: str = "always"       # "always" | "never"
    pending_request: dict | None = None     # arguments waiting for confirmation
```

---

## Guarded MCP Client (Option B backbone)

```python
from mcp import ClientSession, ToolResult

def error(msg: str) -> ToolResult:
    return ToolResult(content=msg)

def parse_results(raw_result) -> list:
    # Parse MCP tool result into a list of dicts with at least title, year, mediaType, mediaId
    # Implementation depends on what search_media returns from your MCP server
    ...

class GuardedMCPClient(ClientSession):
    def __init__(self, *args, deps: AgentDeps, **kwargs):
        super().__init__(*args, **kwargs)
        self.deps = deps

    async def call_tool(self, name: str, arguments: dict):

        # ── request_media: all gates must pass ──────────────────────────────
        if name == "request_media":

            # Gate 1: search must have been called
            if self.deps.workflow == WorkflowState.IDLE:
                return error("You must call search_media before request_media.")

            # Gate 2: user must have selected a result
            if not self.deps.selected_media:
                return error(
                    "No media selected. Present the search results as a numbered list "
                    "and ask the user to pick one before calling request_media."
                )

            # Gate 3: quality preference must be set
            media_type = arguments.get("mediaType")
            if media_type == "movie" and not self.deps.movie_quality:
                return error(
                    "STOP: movie_quality is not set. "
                    "Ask the user: 'Do you prefer 4K or 1080p for movies?' "
                    "then call set_movie_quality before proceeding."
                )
            if media_type == "tv" and not self.deps.series_quality:
                return error(
                    "STOP: series_quality is not set. "
                    "Ask the user: 'Do you prefer 4K or 1080p for series?' "
                    "then call set_series_quality before proceeding."
                )

            # Gate 4: confirmation (when required)
            if (
                self.deps.confirmation_mode == "always"
                and self.deps.workflow != WorkflowState.CONFIRMED
            ):
                self.deps.pending_request = arguments
                title = self.deps.selected_media.get("title", "Unknown")
                year = self.deps.selected_media.get("year", "")
                quality = (
                    self.deps.movie_quality if media_type == "movie"
                    else self.deps.series_quality
                )
                seasons = arguments.get("seasons", "")
                season_str = f", seasons: {seasons}" if seasons else ""
                return error(
                    f"STOP: confirmation required. "
                    f"Ask the user: 'Request {title} ({year}) in {quality}{season_str}?' "
                    f"Wait for yes, then call confirm_request()."
                )

            # All gates passed — reset workflow and forward
            self.deps.workflow = WorkflowState.IDLE
            self.deps.selected_media = None
            self.deps.pending_request = None

        # ── search_media: always allowed, capture results ───────────────────
        elif name == "search_media":
            result = await super().call_tool(name, arguments)
            self.deps.last_search_results = parse_results(result)
            self.deps.workflow = WorkflowState.SEARCHED
            self.deps.selected_media = None     # clear any previous selection
            return result

        # ── All other tools: no gates, pass straight through ────────────────
        # manage_media_requests, get_media_details, PDF tools, file converters, etc.
        return await super().call_tool(name, arguments)
```

---

## Thin Wrapper Tools (Option A — only where conversation needs to signal state)

These are the only `@agent.tool` wrappers needed. They exist purely to let the model
register conversational outcomes (user picked item X, user said yes) back into state.

```python
from pydantic_ai import Agent, RunContext

agent = Agent(...)

@agent.tool
async def select_media(ctx: RunContext[AgentDeps], index: int) -> str:
    """Call this when the user picks an item from the search results list."""
    results = ctx.deps.last_search_results
    if not results:
        return "No search results available. Call search_media first."
    if index < 0 or index >= len(results):
        return f"Invalid selection. Valid range: 0–{len(results) - 1}."
    ctx.deps.selected_media = results[index]
    ctx.deps.workflow = WorkflowState.DISAMBIGUATED
    item = results[index]
    return f"Selected: {item['title']} ({item['year']}) — {item['mediaType']}"


@agent.tool
async def confirm_request(ctx: RunContext[AgentDeps]) -> str:
    """Call this when the user confirms they want to proceed with the pending request."""
    if not ctx.deps.pending_request:
        return "No pending request to confirm."
    ctx.deps.workflow = WorkflowState.CONFIRMED
    return "Confirmed. You may now call request_media."


@agent.tool
async def set_movie_quality(ctx: RunContext[AgentDeps], quality: str) -> str:
    """Call this after asking the user their movie quality preference."""
    if quality.lower() not in ("4k", "1080p"):
        return "Invalid quality. Use '4k' or '1080p'."
    ctx.deps.movie_quality = quality.lower()
    return f"Movie quality set to {quality}."


@agent.tool
async def set_series_quality(ctx: RunContext[AgentDeps], quality: str) -> str:
    """Call this after asking the user their series quality preference."""
    if quality.lower() not in ("4k", "1080p"):
        return "Invalid quality. Use '4k' or '1080p'."
    ctx.deps.series_quality = quality.lower()
    return f"Series quality set to {quality}."
```

---

## Full Request Flow (step by step)

```
User: "Get me The Matrix"

1. Model calls search_media(query="The Matrix")
   → GuardedMCPClient: allowed, results stored, state = SEARCHED

2. Model presents numbered list to user:
   "1. The Matrix (1999) — sci-fi film with Keanu Reeves
    2. The Matrix Reloaded (2003) — sequel
    3. The Matrix Resurrections (2021) — sequel
    Which one would you like?"

3. User: "the first one"
   Model calls select_media(index=0)
   → state = DISAMBIGUATED, selected_media = {Matrix 1999}

4. movie_quality is None
   → model asks "Do you prefer 4K or 1080p for movies?"
   User: "4K"
   → model calls set_movie_quality("4k")
   → deps.movie_quality = "4k"

5. Model calls request_media(mediaType="movie", mediaId=..., is4k=True)
   → GuardedMCPClient checks:
      ✅ state != IDLE
      ✅ selected_media set
      ✅ movie_quality set
      ❌ confirmation_mode == "always" and state != CONFIRMED
   → returns STOP error with confirmation prompt

6. Model asks: "Request The Matrix (1999) in 4K?"
   User: "yes"
   → model calls confirm_request()
   → state = CONFIRMED

7. Model retries request_media(...)
   → GuardedMCPClient checks:
      ✅ state != IDLE
      ✅ selected_media set
      ✅ movie_quality set
      ✅ state == CONFIRMED
   → all gates pass, forwarded to MCP server ✅
   → state reset to IDLE
```

---

## Adding More MCP Servers

When adding PDF utilities, file converters, or any other MCP server:

1. **No new gates needed** — `call_tool` passes unknown tool names straight through
2. **New gates if required** — add `elif name == "your_tool"` blocks in `call_tool`
3. **No new wrapper stubs** — the model sees the MCP server's native schemas directly
4. **Shared state** — all servers share the same `AgentDeps` if cross-server state is needed

```python
# Example: adding a gate for a hypothetical PDF tool
async def call_tool(self, name: str, arguments: dict):

    if name == "request_media":
        ...  # existing Overseerr gates

    elif name == "search_media":
        ...  # existing

    elif name == "convert_pdf":
        # example gate for a future PDF MCP server
        if not arguments.get("output_format"):
            return error("output_format is required. Ask the user: 'What format do you want?'")

    # everything else: pass straight through
    return await super().call_tool(name, arguments)
```

---

## Architecture Summary

| Concern | Where it lives | Scales? |
|---|---|---|
| Hard workflow gates | `GuardedMCPClient.call_tool` | ✅ one place for all servers |
| Conversational state signals | Thin `@agent.tool` wrappers | ✅ only add when needed |
| Unguarded tools (PDF, file utils) | Passthrough in `call_tool` | ✅ zero extra code |
| Shared session state | `AgentDeps` dataclass | ✅ one object, all tools |
| New MCP server added | Add `elif` block if gates needed | ✅ otherwise automatic |

---

## Key Rules

> **Prompts change what the model *wants* to do.**  
> **Tool return values change what it *can* do next.**

- Return plain English error strings from gates — the model treats them as instructions
- Keep `WorkflowState` transitions explicit and linear
- Reset state to `IDLE` after a successful request so the next request starts clean
- Never expose `mediaId`, `tmdbId`, or any internal identifiers in error messages or confirmations