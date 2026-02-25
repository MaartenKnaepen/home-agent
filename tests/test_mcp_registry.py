"""Tests for MCP registry."""

from unittest.mock import patch

from home_agent.mcp.registry import MCPRegistry
from home_agent.mcp.servers import ServerConfig


def test_registry_starts_empty() -> None:
    """Registry starts with no servers."""
    registry = MCPRegistry()
    assert len(registry.servers) == 0


def test_register_adds_server() -> None:
    """register() adds server to registry."""
    registry = MCPRegistry()
    config = ServerConfig(
        name="jellyseerr",
        url="http://localhost:5056/mcp",
        enabled=True,
    )
    registry.register(config)
    assert len(registry.servers) == 1
    assert "jellyseerr" in registry.servers


def test_get_toolsets_returns_toolsets() -> None:
    """get_toolsets() returns FastMCPToolset instances."""
    registry = MCPRegistry()
    config = ServerConfig(
        name="jellyseerr",
        url="http://localhost:5056/mcp",
        enabled=True,
    )
    registry.register(config)
    with patch("home_agent.mcp.registry.FastMCPToolset") as mock_toolset:
        toolsets = registry.get_toolsets()
        assert len(toolsets) == 1
        mock_toolset.assert_called_once_with("http://localhost:5056/mcp")


def test_get_toolsets_excludes_disabled_servers() -> None:
    """get_toolsets() excludes disabled servers."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="jellyseerr", url="http://localhost:5056/mcp", enabled=True)
    )
    registry.register(
        ServerConfig(name="glances", url="http://localhost:5057/mcp", enabled=False)
    )
    with patch("home_agent.mcp.registry.FastMCPToolset"):
        toolsets = registry.get_toolsets()
        assert len(toolsets) == 1


def test_get_tool_names_returns_enabled_names() -> None:
    """get_tool_names() returns names of enabled servers."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="jellyseerr", url="http://localhost:5056/mcp", enabled=True)
    )
    registry.register(
        ServerConfig(name="glances", url="http://localhost:5057/mcp", enabled=False)
    )
    names = registry.get_tool_names()
    assert names == ["jellyseerr"]
