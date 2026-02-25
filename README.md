# Home Agent

A Telegram-based home server assistant powered by PydanticAI and MCP.

## Docker Deployment

### Prerequisites

- Docker and Docker Compose installed
- A running [Jellyseerr](https://github.com/Fallenbagel/jellyseerr) instance
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An [OpenRouter](https://openrouter.ai/) API key

### Quick Start

1. Copy `.env.example` to `.env` in the project root and fill in your values:

```bash
cp .env.example .env
```

2. Start the stack from the `deployment/` folder:

```bash
cd deployment
docker compose up -d
```

3. Follow the logs:

```bash
docker compose logs -f home-agent
```

### Configuration

All configuration is loaded from the `.env` file in the project root:

| Variable | Description | Example |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token from @BotFather | `123456:ABC-DEF...` |
| `OPENROUTER_API_KEY` | OpenRouter API key for LLM access | `sk-or-v1-...` |
| `ALLOWED_TELEGRAM_IDS` | JSON array of authorized Telegram user IDs | `[123456789]` |
| `JELLYSEERR_URL` | URL of your Jellyseerr instance | `http://host.docker.internal:5055` |
| `JELLYSEERR_API_KEY` | Jellyseerr API key (Settings → API) | `MTc2...` |
| `MCP_PORT` | Port for the Jellyseerr MCP sidecar | `5056` |
| `DB_PATH` | Path to the SQLite database file | `data/home_agent.db` |
| `LOG_LEVEL` | Logging verbosity | `INFO` |
| `LLM_MODEL` | PydanticAI model string | `openrouter:nvidia/nemotron-3-nano-30b-a3b:free` |

### Persistence

Conversation history and user profiles are stored in a named Docker volume `home-agent-data`, mounted at `/app/data` inside the container. Data survives container restarts and upgrades.

To back up the database:

```bash
docker run --rm -v home-agent-data:/data -v $(pwd):/backup alpine \
  tar czf /backup/home-agent-backup.tar.gz -C /data .
```

### Troubleshooting

**home-agent exits immediately:**
- Check that all required env vars are set in `.env`
- Run `docker compose logs home-agent` to see the error

**Cannot connect to Jellyseerr:**
- Ensure `JELLYSEERR_URL` is reachable from inside the container
- On Linux, `host.docker.internal` may not resolve — the `deployment/docker-compose.yml` adds `extra_hosts: host.docker.internal:host-gateway` automatically
- Verify Jellyseerr is running: `curl $JELLYSEERR_URL/health`

**Invalid Jellyseerr API key:**
- Regenerate the key in Jellyseerr → Settings → API
- Update `.env` and restart: `docker compose restart`

**MCP port already in use:**
- Change `MCP_PORT` in `.env` to an available port (e.g. `5057`)
- Restart the stack: `docker compose up -d`

**Telegram bot not responding:**
- Confirm the bot token is correct
- Ensure your Telegram user ID is in `ALLOWED_TELEGRAM_IDS`
- Check logs: `docker compose logs -f home-agent`
