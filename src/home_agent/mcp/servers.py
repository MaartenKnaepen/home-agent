"""MCP server configurations.

Defines connection details for each MCP server (URL, enabled state).
"""

import os
from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for an MCP server.

    Attributes:
        name: Server identifier (e.g., 'seerr').
        url: HTTP endpoint URL for the MCP server.
        enabled: Whether this server is active.
    """

    name: str
    url: str
    enabled: bool = True


def get_seerr_config(mcp_port: int = 8085) -> ServerConfig:
    """Create Overseerr/Seerr MCP server configuration.

    Args:
        mcp_port: Port number for the MCP server HTTP endpoint.
            When running in Docker Compose, set MCP_HOST=seerr-mcp
            via the environment to use the Docker network service name.

    Returns:
        ServerConfig for the Seerr MCP server.
    """
    mcp_host = os.environ.get("MCP_HOST", "localhost")
    return ServerConfig(
        name="seerr",
        url=f"http://{mcp_host}:{mcp_port}/mcp",
        enabled=True,
    )
