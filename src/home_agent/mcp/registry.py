"""MCP server registry and lifecycle management.

Manages MCP server connections and exposes toolsets to the agent.
"""

import logging

from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from home_agent.mcp.guarded_toolset import GuardedToolset
from home_agent.mcp.servers import ServerConfig

logger = logging.getLogger(__name__)


class MCPRegistry:
    """Registry for MCP servers.

    Manages server configurations and creates GuardedToolset-wrapped
    FastMCPToolset instances for the PydanticAI agent.

    Attributes:
        servers: Dict mapping server names to ServerConfig instances.
    """

    def __init__(self) -> None:
        """Initialize the MCP registry."""
        self.servers: dict[str, ServerConfig] = {}

    def register(self, config: ServerConfig) -> None:
        """Register an MCP server configuration.

        Args:
            config: Server configuration to register.
        """
        self.servers[config.name] = config

    def get_toolsets(self) -> list[GuardedToolset]:
        """Create GuardedToolset-wrapped instances for all enabled servers.

        Each FastMCPToolset is wrapped in a GuardedToolset that enforces
        quality and confirmation gates before forwarding tool calls.

        Returns:
            List of GuardedToolset instances for enabled servers.
        """
        toolsets = []
        for server in self.servers.values():
            if server.enabled:
                inner_toolset = FastMCPToolset(server.url)
                guarded = GuardedToolset(inner_toolset)
                toolsets.append(guarded)
                logger.debug(
                    "Wrapped MCP toolset in GuardedToolset",
                    extra={"server": server.name},
                )
        return toolsets

    def get_tool_names(self) -> list[str]:
        """Get list of enabled server names.

        Returns:
            List of server names that are enabled.
        """
        return [s.name for s in self.servers.values() if s.enabled]
