"""MCP server configurations.

Defines connection details for each MCP server (URL, enabled state).
"""

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for an MCP server.

    Attributes:
        name: Server identifier (e.g., 'jellyseerr').
        url: HTTP endpoint URL for the MCP server.
        enabled: Whether this server is active.
    """

    name: str
    url: str
    enabled: bool = True


def get_jellyseerr_config(mcp_port: int = 5056) -> ServerConfig:
    """Create Jellyseerr MCP server configuration.

    Args:
        mcp_port: Port number for the MCP server HTTP endpoint.
            When running in Docker Compose, set MCP_HOST=jellyseerr-mcp
            via the environment to use the Docker network service name.

    Returns:
        ServerConfig for the Jellyseerr MCP server.
    """
    mcp_host = os.environ.get("MCP_HOST", "localhost")
    return ServerConfig(
        name="jellyseerr",
        url=f"http://{mcp_host}:{mcp_port}/sse",
        enabled=True,
    )
