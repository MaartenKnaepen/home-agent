# Deployment

This folder contains Docker Compose configurations for MCP servers.

## Jellyseerr MCP Server

### Prerequisites

1. Jellyseerr instance running and accessible
2. Jellyseerr API key (get from Jellyseerr Settings > API)

### Configuration

Copy `.env.example` to `.env` and set:

```bash
JELLYSEERR_URL=http://host.docker.internal:5055
JELLYSEERR_API_KEY=your-api-key-here
MCP_PORT=5056
```

**Note for Linux users:** If `host.docker.internal` doesn't work, use your host IP:
```bash
JELLYSEERR_URL=http://172.17.0.1:5055
```

Or add the following to your docker-compose.yml under the service:
```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

### Start the Server

Docker Compose needs the `.env` from the project root. Run from the **project root**:

```bash
docker compose -f deployment/docker-compose.yml --env-file .env up -d
```

Or create a symlink so you can run from the `deployment/` folder:

```bash
cd deployment && ln -s ../.env .env
docker compose up -d
```

### Verify

Check logs:
```bash
docker logs -f jellyseerr-mcp
```

Health check:
```bash
curl http://localhost:5056/health
```

### Connect Agent

The agent connects via `FastMCPToolset("http://localhost:5056/mcp")`.
See `src/home_agent/mcp/servers.py` for configuration.

### Troubleshooting

**Connection refused to Jellyseerr:**
- Ensure JELLYSEERR_URL is correct
- Check if Jellyseerr is running
- Add `extra_hosts: - "host.docker.internal:host-gateway"` to docker-compose.yml

**Invalid API key:**
- Regenerate API key in Jellyseerr Settings > API
- Restart the MCP container after changing the key

**Port already in use:**
- Change MCP_PORT in .env to a different port (e.g., 5057)
- Restart the container
