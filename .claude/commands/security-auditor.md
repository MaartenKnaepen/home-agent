# Security Auditor — Security-Focused Code Review

Expert security review for this Python async Telegram bot with MCP integrations.

**Use when:** reviewing new code before merge, auditing a module for vulnerabilities, assessing a new MCP server integration, or validating authentication and data handling.
**Do not use when:** you need formal compliance certification or penetration testing of live infrastructure.

---

## Step 1 — Define Scope

Confirm what is being reviewed:
- Specific file(s) or module?
- New MCP server integration?
- Authentication/authorization flow?
- Data handling or storage?
- Full codebase audit?

Read `CLAUDE.md` and `docs/LLM/memory.yaml` for existing security decisions before starting.

---

## Step 2 — Threat Model (This Project)

Key attack surfaces for this project:

| Surface | Threat | Control |
|---------|--------|---------|
| Telegram webhook/polling | Unauthorized users sending messages | Whitelist in `ALLOWED_TELEGRAM_IDS` |
| MCP tool execution | Agent executing unintended tools | `GuardedToolset` approval flow |
| SQLite database | SQL injection, data exposure | `aiosqlite` parameterized queries |
| External MCP servers | Malicious responses, injection via tool results | Input not trusted as code |
| Environment variables | Secret exposure in logs or errors | `SecretStr` from pydantic-settings |
| LLM responses | Prompt injection, data leakage | System prompt design, output validation |
| Docker containers | Container escape, exposed ports | Docker Compose network isolation |

---

## Step 3 — Code Review Checklist

### Authentication & Authorization
- [ ] All Telegram handlers check `ALLOWED_TELEGRAM_IDS` before processing
- [ ] No user can escalate privileges via crafted messages
- [ ] `GuardedToolset` approval is per-call, not shared across users
- [ ] GuardedToolset is stateless — no instance-level approved_tools state

### Injection
- [ ] All database queries use parameterized statements (never f-string SQL)
- [ ] MCP tool results treated as untrusted data — not eval'd or exec'd
- [ ] No shell=True in subprocess calls
- [ ] No `eval()` or `exec()` anywhere

### Secret Management
- [ ] All secrets loaded from `.env` via `pydantic-settings`
- [ ] `SecretStr` used for API keys and tokens (prevents accidental logging)
- [ ] No secrets in log output (check `logger.info/debug` calls near secrets)
- [ ] No secrets hardcoded in source, Docker Compose, or test files

### Async Safety
- [ ] No shared mutable state between concurrent request handlers
- [ ] `GuardedToolset` approved tools passed per-call, not stored on instance
- [ ] Database connections properly scoped (not shared across coroutines unsafely)

### Error Handling
- [ ] Exceptions don't leak internal details to Telegram users
- [ ] Stack traces not sent to users — only friendly error messages
- [ ] `SecretStr` values not accidentally included in exception messages

### MCP Server Security
- [ ] Self-built MCP servers validate all inputs
- [ ] API keys for external services loaded from env, not hardcoded
- [ ] HTTP clients use `raise_for_status()` — errors not silently swallowed
- [ ] Timeouts configured on external HTTP calls (no indefinite hangs)

### Docker / Deployment
- [ ] Sensitive env vars not logged during container startup
- [ ] Internal services not exposed on 0.0.0.0 unnecessarily
- [ ] No `privileged: true` in Docker Compose without documented reason
- [ ] Volumes don't expose host paths with sensitive data

### Dependencies
- [ ] Run `uv pip list` and check for known CVEs in key dependencies
- [ ] Pinned versions in `pyproject.toml` (prevents supply chain drift)

---

## Step 4 — OWASP Top 10 Relevance for This Project

| OWASP Category | Relevance | Check |
|----------------|-----------|-------|
| A01 Broken Access Control | High — Telegram whitelist bypass | Every handler checks user ID |
| A02 Cryptographic Failures | Medium — secrets in transit/rest | HTTPS for Telegram, SecretStr |
| A03 Injection | High — SQL, prompt injection | Parameterized queries, no eval |
| A04 Insecure Design | Medium — GuardedToolset bypass | Stateless, per-call approval |
| A05 Security Misconfiguration | Medium — Docker, env vars | No defaults for secrets |
| A06 Vulnerable Components | Low-Medium — dependency CVEs | Pin and audit deps |
| A09 Security Logging | Medium — leaking secrets in logs | SecretStr, scrub logs |

---

## Step 5 — Output

Produce a security review report with:

### Findings

For each finding:
- **Severity**: Critical / High / Medium / Low / Informational
- **Location**: exact file and line number
- **Description**: what the vulnerability is
- **Impact**: what an attacker could do
- **Remediation**: exact code change needed

### Summary
- Count of findings by severity
- Overall risk assessment
- Top 3 recommended fixes in priority order

### Safe to Merge?
End with a clear recommendation: **APPROVE**, **APPROVE WITH FIXES** (list required), or **BLOCK** (list blockers).
