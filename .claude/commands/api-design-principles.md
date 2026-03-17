# API Design Principles — Shape, Consistency, Versioning

Use when designing new MCP tools, FastAPI endpoints (for self-built MCP servers), or reviewing API contracts before implementation.

**Do not use when:** only doing internal refactoring with no change to public interfaces.

---

## Step 1 — Define Consumers and Constraints

Before any design:
- Who calls this API? (The PydanticAI agent, Telegram bot, external HTTP client?)
- What are the use cases? List 3–5 concrete calls the consumer will make.
- What cannot change? (Breaking changes to MCP tool signatures affect the agent's behavior.)
- What is the transport? (MCP stdio, MCP HTTP, FastAPI HTTP)

---

## Step 2 — MCP Tool Design (Primary Pattern for This Project)

MCP tools are the main API surface. Design principles:

**Naming**
- Use `verb_noun` format: `search_media`, `request_movie`, `get_system_status`
- Be specific: `search_jellyseerr` not `search` if there are multiple search tools
- Names must be stable — the LLM learns them and they appear in prompts

**Parameters**
- All parameters must have clear types and docstrings (FastMCP uses these for the LLM)
- Optional parameters should have sensible defaults
- Group related parameters if a function has more than 4
- Prefer explicit over clever: `media_type: Literal["movie", "tv"]` not `media_type: str`

**Return values**
- Always return `str` (PydanticAI requirement)
- Return structured data as JSON string when the agent needs to parse it
- Include enough context for the LLM to give a good response — not just IDs, include names
- On error: return a human-readable error string, do not raise (let the agent handle it gracefully)

**Template:**
```python
@mcp.tool()
async def search_media(
    query: str,
    media_type: Literal["movie", "tv", "both"] = "both",
    limit: int = 5,
) -> str:
    """Search for movies or TV shows.

    Args:
        query: Search terms (title, actor, genre).
        media_type: Filter results by type. Use "both" for mixed results.
        limit: Maximum number of results to return (1-20).

    Returns:
        JSON string with list of results, each containing title, year, type, and status.
    """
```

---

## Step 3 — FastAPI Endpoint Design (Self-Built MCP Servers)

When building a FastAPI wrapper around an external service:

**Resource modelling**
- Use nouns for resources, HTTP verbs for actions
- `GET /search?q=...` not `POST /do-search`
- Nested resources: `GET /users/{id}/requests`

**Response shape**
```python
# Always use Pydantic models for responses
class SearchResult(BaseModel):
    id: int
    title: str
    year: int
    media_type: Literal["movie", "tv"]
    status: str

class SearchResponse(BaseModel):
    results: list[SearchResult]
    total: int
```

**Error handling**
```python
# Use appropriate HTTP status codes
# 400 — bad input (validation error)
# 404 — resource not found
# 502 — upstream service error
# 503 — upstream service unavailable

from fastapi import HTTPException

raise HTTPException(status_code=404, detail=f"Media {media_id} not found")
```

**Pagination** (for list endpoints returning >20 items)
```python
class PaginatedResponse(BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
```

---

## Step 4 — Versioning Strategy

For MCP tools:
- Prefer additive changes (new optional parameter with default) over breaking changes
- If a breaking change is unavoidable, add a new tool with a new name and deprecate the old one
- Document the change in `docs/LLM/memory.yaml`

For FastAPI endpoints (internal, used only by MCP layer):
- No versioning needed — change freely since it's not a public API
- Update the MCP server to match immediately

---

## Step 5 — Consistency Checklist

Before finalising:
- [ ] All tool names follow `verb_noun` pattern
- [ ] All parameters have types and docstrings
- [ ] Return type is always `str` for MCP tools
- [ ] Error cases return human-readable strings, not raise exceptions (MCP tools)
- [ ] Error cases raise `HTTPException` with appropriate status code (FastAPI)
- [ ] New tools added to `docs/LLM/api.yaml`
- [ ] Tool docstrings are clear enough for the LLM to use the tool correctly without trial and error
- [ ] Breaking changes noted in `docs/LLM/memory.yaml`

---

## Step 6 — Review with Examples

For each new tool or endpoint, write out 3 example calls:
1. The happy path
2. An edge case (empty result, optional param used)
3. An error case (invalid input, service down)

If any example reveals an awkward interface, redesign before implementing.
