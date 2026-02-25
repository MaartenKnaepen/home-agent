"""MCP server registry and lifecycle management.

Manages MCP server connections and exposes toolsets to the agent.
"""

from pydantic_ai.toolsets.fastmcp import FastMCPToolset

from home_agent.mcp.servers import ServerConfig


class MCPRegistry:
    """Registry for MCP servers.

    Manages server configurations and creates FastMCPToolset instances
    for the PydanticAI agent.

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

    def get_toolsets(self) -> list[FastMCPToolset]:
        """Create FastMCPToolset instances for all enabled servers.

        Returns:
            List of FastMCPToolset instances for enabled servers.
        """
        toolsets = []
        for server in self.servers.values():
            if server.enabled:
                toolset = FastMCPToolset(server.url)
                toolsets.append(toolset)
        return toolsets

    def get_tool_names(self) -> list[str]:
        """Get list of enabled server names.

        Returns:
            List of server names that are enabled.
        """
        return [s.name for s in self.servers.values() if s.enabled]
