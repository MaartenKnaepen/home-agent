# UX Plan: User Profile, Confirmation Flow & Reply Language

## Goal

Make the agent feel like it genuinely knows each user — asking the right questions before
acting, remembering preferences forever, and communicating in the user's preferred language.
The first version targets Jellyseerr only. The design must scale cleanly as more MCP servers
are added.

---

## Problems to Solve

### 1. Agent is too trigger-happy
When asked "add Troy", the agent immediately called `request_media` in 1080p without:
- Confirming it found the right movie (Troy 2004, not another Troy)
- Asking what quality the user wants
- Noting that movies default to 4K and series to 1080p for this user

### 2. Quality preferences are wrong and hardcoded
`MediaPreferences.preferred_quality = "1080p"` is a single flat field. Reality:
- Movies → user prefers 4K
- Series → user prefers 1080p
- Other users on the same bot may have different limits (4K streaming not feasible for all)
- Codecs, release groups, audio tracks → managed by Radarr/Sonarr/Recyclarr, NOT the agent

### 3. Agent replies in English regardless of user preference
`reply_language` doesn't exist yet. Users should be able to say "from now on talk to me in
Dutch" and have it stick permanently.

### 4. Profile model has dead weight
`preferred_genres`, `avoid_genres`, `preferred_language` (media), `NotificationPrefs`,
`stats` — none of these are used by any tool or system prompt. They add noise and false
promises.

---

## Design Decisions

### What the agent manages
| Concern | Who manages it |
|---|---|
| Movie quality (4K vs 1080p) | Agent asks user once, stores in profile |
| Series quality (4K vs 1080p) | Agent asks user once, stores in profile |
| Codecs (H.264 vs H.265) | Radarr/Sonarr/Recyclarr — NOT the agent |
| Audio language of media | arr-stack — NOT the agent |
| Subtitle preferences | arr-stack — NOT the agent |
| Agent reply language | UserProfile.reply_language |
| Free-form user notes | UserProfile.notes (unchanged) |

### What "quality" means for Jellyseerr
Jellyseerr accepts a `quality_profile_id` when requesting media. The agent does NOT expose
this complexity to users. Instead:
- "4K" → agent passes the 4K quality profile ID configured in AppConfig
- "1080p" → agent passes the 1080p quality profile ID configured in AppConfig
- Profile IDs are admin config (`.env`), not user-facing

---

## Phase 1: Jellyseerr Only

### 1.1 Simplify UserProfile

**Remove** dead fields, **add** what's actually needed:

```python
class MediaPreferences(BaseModel):
    movie_quality: Literal["4k", "1080p"] | None = None   # None = not yet asked
    series_quality: Literal["4k", "1080p"] | None = None  # None = not yet asked

class UserProfile(BaseModel):
    user_id: int
    name: str | None = None
    created_at: datetime
    updated_at: datetime
    reply_language: str = "english"           # language for agent replies
    media_preferences: MediaPreferences = MediaPreferences()
    notes: list[str] = []
```

**Remove:** `preferred_genres`, `avoid_genres`, `preferred_language` (media),
`NotificationPrefs`, `stats`.

> **Migration note:** Existing DB profiles will deserialize fine — Pydantic ignores unknown
> fields. The removed fields simply disappear on next save.

### 1.2 Admin config in AppConfig

```python
# .env
JELLYSEERR_4K_PROFILE_ID=7       # Jellyseerr quality profile ID for 4K
JELLYSEERR_1080P_PROFILE_ID=6    # Jellyseerr quality profile ID for 1080p
```

The admin sets these once. The agent never exposes profile IDs to users.

### 1.3 New agent tools

```python
@agent.tool
async def set_movie_quality(ctx, quality: Literal["4k", "1080p"]) -> str:
    """Store the user's preferred movie download quality."""

@agent.tool  
async def set_series_quality(ctx, quality: Literal["4k", "1080p"]) -> str:
    """Store the user's preferred series download quality."""

@agent.tool
async def set_reply_language(ctx, language: str) -> str:
    """Update the language the agent uses to reply to this user."""
```

### 1.4 System prompt additions

Three new behaviors injected via the dynamic system prompt:

**Confirmation before requesting:**
```
Before calling request_media, always confirm with the user:
- The exact title and year you found
- The quality you will request
Example: "I found Troy (2004) directed by Wolfgang Petersen. Request it in 4K?"
Only proceed after the user confirms.
```

**Quality onboarding:**
```
If the user asks to download a movie and movie_quality is not set, ask:
"What quality do you prefer for movies — 4K or 1080p?"
Store their answer with set_movie_quality before proceeding.
Apply the same pattern for series using set_series_quality.
```

**Reply language:**
```
Always reply in: {profile.reply_language}.
If the user asks you to switch language (e.g. "speak Dutch from now on"),
call set_reply_language with the new language, then switch immediately.
```

### 1.5 Dynamic system prompt update

The `inject_user_profile` function already injects profile data. Extend it:

```python
quality_part = (
    f"Movie quality preference: {prefs.movie_quality or 'NOT SET — ask before first request'}. "
    f"Series quality preference: {prefs.series_quality or 'NOT SET — ask before first request'}."
)
language_part = f"Always reply in {profile.reply_language}."
```

---

## Phase 2: Scaling to Multiple MCP Servers

When new MCP servers are added (e.g. Home Assistant, Navidrome, Glances), the profile
design scales as follows:

### No new profile fields needed for most servers
Most MCP servers don't need user preferences at all:
- **Glances** (monitoring) — no preferences, just show stats
- **Home Assistant** — preferences live in HA itself, not the agent profile
- **Navidrome** (music) — playlist/quality preferences could follow same pattern

### Pattern for servers that DO need preferences
If a new server needs user preferences, follow this pattern:

1. Add a new `<Service>Preferences` Pydantic model (like `MediaPreferences`)
2. Add it as an optional field on `UserProfile` with `None` default
3. Add `set_<service>_preference()` tool in the relevant tools file
4. Inject into system prompt via `inject_user_profile`
5. Add admin config (profile IDs, limits) to `AppConfig`

### Example: Adding music quality preference (Navidrome, future)
```python
class MusicPreferences(BaseModel):
    bitrate: Literal["320kbps", "lossless"] | None = None

class UserProfile(BaseModel):
    ...
    music_preferences: MusicPreferences = MusicPreferences()
```

The agent asks "lossless or 320kbps?" the first time the user requests music — same pattern
as movie quality.

### Confirmation policy is universal
The confirmation-before-action pattern applies to ALL MCP servers:
- Media request → confirm title + quality
- Smart home action → confirm device + action ("Turn off living room lights?")
- Music queue → confirm ("Add all Radiohead albums to queue?")

This is a system prompt rule, not server-specific code.

---

## Implementation Order

1. **Simplify `UserProfile`** — remove dead fields, add `reply_language`, split quality by type
2. **Add admin config** — `JELLYSEERR_4K_PROFILE_ID`, `JELLYSEERR_1080P_PROFILE_ID` to AppConfig
3. **Add tools** — `set_movie_quality`, `set_series_quality`, `set_reply_language`
4. **Update system prompt** — confirmation policy, quality onboarding, language instruction
5. **Update tests** — profile tests, agent tool tests, bot integration tests
6. **Verify end-to-end** — test quality onboarding flow, confirmation flow, language switch

---

## Open Questions for Sparring

1. Should confirmation be skippable? E.g. a "power user mode" flag in the profile that
   skips confirmation and goes straight to requesting?

2. Should `reply_language` default to auto-detecting from the user's Telegram locale
   (`update.effective_user.language_code`) rather than hardcoding "english"?

3. For quality onboarding — should the agent ask both movie AND series quality upfront in
   one go ("What quality for movies? And for series?"), or lazily one at a time when first
   needed?

4. When the user has no quality preference set and we ask — should we suggest the admin
   default ("Most users pick 4K for movies — is that good for you too?") or ask open-ended?

5. Should `set_reply_language` accept locale codes ("nl", "fr") or natural language names
   ("Dutch", "French")? Natural language is friendlier but less precise.

---

## Proposals and Decisions

### Proposal 1: Add `confirmation_mode` field to UserProfile

**Decision: ✅ Accept with changes**

The three-tier model is good in principle, but `"smart"` is speculative — we don't have the
data or logic to know when it's safe to skip confirmation. YAGNI. Ship `"always"` and
`"never"` only. Add `"smart"` later if real users ask for it.

```python
class UserProfile(BaseModel):
    ...
    confirmation_mode: Literal["always", "never"] = "always"
```

Also, the tool to change this should be explicit:

```python
@agent.tool
async def set_confirmation_mode(ctx, mode: Literal["always", "never"]) -> str:
    """Toggle whether the agent confirms before requesting media."""
```

---

### Proposal 2: Auto-detect `reply_language` from Telegram user locale

**Decision: ✅ Accept**

This is a clear UX win. First-time users get their language automatically.
Implementation is clean — bot.py already has access to `update.effective_user.language_code`.

**Mapping should be minimal** — only languages the admin actually expects their users to
speak. For this project: `nl → Dutch`, `en → English`, fallback to `English`. No need for
a giant table of 50 languages. Extend as needed.

> **Note:** Telegram's `language_code` is the **app language**, not necessarily the user's
> preferred chat language. A Dutch user with Telegram set to English would get English replies.
> This is acceptable because `set_reply_language` exists as an escape hatch.

---

### Proposal 3: Lazy quality onboarding (ask when needed, not upfront)

**Decision: ✅ Accept (this was already the plan)**

This was already specified in section 1.4 ("If the user asks to download a movie and
movie_quality is not set, ask..."). The proposal just makes it more explicit. Agreed: ask
lazily, one at a time, in context.

---

### Proposal 4: Suggest admin default with opt-out

**Decision: ❌ Reject**

This adds complexity for marginal UX gain. The agent is already asking a simple binary
question: "4K or 1080p?" Adding "Most users pick X — is that good for you?" introduces:
- An admin config for the "default suggestion" (more `.env` vars)
- Ambiguity if the user says "sure" (sure to the suggestion, or sure they want to pick?)
- An opinion where neutrality is better

A simple "Do you prefer 4K or 1080p for movies?" is clear, fast, and unbiased. The agent
can still add context from `notes` if it has observed the user's preferences.

---

### Proposal 5: Natural language for `set_reply_language`

**Decision: ✅ Accept with simplification**

Natural language names are the right input. But the `LANGUAGE_ALIASES` mapping table is
unnecessary. The LLM already understands that "nl" means "Dutch" and "français" means
"French". The tool just stores whatever string the LLM passes — the system prompt reads
better as "Reply in Dutch" than "Reply in nl".

```python
@agent.tool
async def set_reply_language(ctx: RunContext[AgentDeps], language: str) -> str:
    """Update the language the agent uses to reply.

    Accepts natural language names: "Dutch", "French", "German", "English", etc.
    The agent will normalize the input (e.g. "nl" → "Dutch").
    """
```

The "normalization" happens in the LLM, not in code. Store `"Dutch"` not `"nl"` because
the system prompt reads better as "Reply in Dutch".

---

### Proposal 6: Add `last_quality_asked` tracking to avoid nagging

**Decision: ❌ Reject**

This is over-engineering a problem that doesn't exist yet. The system prompt already handles
this naturally:
- The prompt says "ask about quality when the user requests media and quality is not set"
- If the user changes topic, the agent won't keep asking — it follows the conversation
- LLMs are naturally good at not nagging

Adding a `last_quality_asked` field creates state management complexity for something the
model handles for free via conversational context. If nagging becomes a real problem in
practice, we can add tracking then. For now, trust the LLM.

---

### Proposal 7: Quality profile ID validation on startup

**Decision: ✅ Accept partially**

Pydantic positive integer validation is a good idea — cheap and prevents obvious
misconfiguration. **Accept** the `@field_validator` on `AppConfig`.

**Reject** the startup validation against Jellyseerr API. The agent starts without MCP
connections being open, and we don't want startup to fail if Jellyseerr is temporarily
down. Let it fail at request time with a clear error in the tool result — the agent will
relay it to the user.

Also: make profile IDs `int | None = None` with `None` meaning "use Jellyseerr's default
profile". This way the bot works out of the box without requiring the admin to look up
profile IDs.

```python
class AppConfig(BaseSettings):
    jellyseerr_4k_profile_id: int | None = None
    jellyseerr_1080p_profile_id: int | None = None

    @field_validator("jellyseerr_4k_profile_id", "jellyseerr_1080p_profile_id")
    @classmethod
    def validate_profile_ids(cls, v: int | None) -> int | None:
        if v is not None and v < 1:
            raise ValueError("Jellyseerr profile IDs must be positive integers")
        return v
```

---

## Final Implementation Order (Agreed)

1. **Simplify `UserProfile`** — remove dead fields, add `reply_language`,
   `confirmation_mode: Literal["always", "never"]`, split quality by media type
2. **Auto-detect language** — bot.py passes Telegram `language_code` to ProfileManager on
   first profile creation, mapped to natural language name
3. **Add admin config** — `JELLYSEERR_4K_PROFILE_ID`, `JELLYSEERR_1080P_PROFILE_ID`
   (both `int | None = None`) with positive-int validation
4. **Add tools** — `set_movie_quality`, `set_series_quality`, `set_reply_language`,
   `set_confirmation_mode`
5. **Update system prompt** — confirmation policy (check `confirmation_mode`), lazy quality
   onboarding, language instruction
6. **Update tests** — profile model, tools, bot locale detection, agent prompt injection
7. **Verify end-to-end** — test onboarding, confirmation, language switch, skip-confirm mode
