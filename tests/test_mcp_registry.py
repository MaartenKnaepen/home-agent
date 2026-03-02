"""Tests for MCP registry."""

import logging
from unittest.mock import MagicMock, patch

import pytest

from home_agent.mcp.guarded_toolset import GuardedToolset
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
        name="seerr",
        url="http://localhost:8085/mcp",
        enabled=True,
    )
    registry.register(config)
    assert len(registry.servers) == 1
    assert "seerr" in registry.servers


def test_get_toolsets_returns_guarded_toolsets() -> None:
    """get_toolsets() returns GuardedToolset-wrapped instances."""
    registry = MCPRegistry()
    config = ServerConfig(
        name="seerr",
        url="http://localhost:8085/mcp",
        enabled=True,
    )
    registry.register(config)
    with patch("home_agent.mcp.registry.FastMCPToolset") as mock_fastmcp:
        mock_inner = MagicMock()
        mock_fastmcp.return_value = mock_inner
        toolsets = registry.get_toolsets()

    assert len(toolsets) == 1
    assert isinstance(toolsets[0], GuardedToolset)
    mock_fastmcp.assert_called_once_with("http://localhost:8085/mcp")
    # The GuardedToolset should wrap the inner FastMCPToolset
    assert toolsets[0].inner_toolset is mock_inner


def test_get_toolsets_excludes_disabled_servers() -> None:
    """get_toolsets() excludes disabled servers."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="seerr", url="http://localhost:8085/mcp", enabled=True)
    )
    registry.register(
        ServerConfig(name="glances", url="http://localhost:5057/mcp", enabled=False)
    )
    with patch("home_agent.mcp.registry.FastMCPToolset"):
        toolsets = registry.get_toolsets()
        assert len(toolsets) == 1


def test_get_toolsets_all_disabled_returns_empty() -> None:
    """get_toolsets() returns empty list when all servers are disabled."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="seerr", url="http://localhost:8085/mcp", enabled=False)
    )
    with patch("home_agent.mcp.registry.FastMCPToolset"):
        toolsets = registry.get_toolsets()
        assert toolsets == []


def test_get_toolsets_multiple_enabled_wraps_all() -> None:
    """get_toolsets() wraps each enabled server in a GuardedToolset."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="seerr", url="http://localhost:8085/mcp", enabled=True)
    )
    registry.register(
        ServerConfig(name="glances", url="http://localhost:5057/mcp", enabled=True)
    )
    with patch("home_agent.mcp.registry.FastMCPToolset"):
        toolsets = registry.get_toolsets()

    assert len(toolsets) == 2
    assert all(isinstance(ts, GuardedToolset) for ts in toolsets)


def test_get_toolsets_logs_debug_when_wrapping(caplog: pytest.LogCaptureFixture) -> None:
    """get_toolsets() logs at DEBUG level when wrapping each toolset."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="seerr", url="http://localhost:8085/mcp", enabled=True)
    )
    with patch("home_agent.mcp.registry.FastMCPToolset"):
        with caplog.at_level(logging.DEBUG, logger="home_agent.mcp.registry"):
            registry.get_toolsets()

    assert any("GuardedToolset" in record.message for record in caplog.records)


def test_get_tool_names_returns_enabled_names() -> None:
    """get_tool_names() returns names of enabled servers."""
    registry = MCPRegistry()
    registry.register(
        ServerConfig(name="seerr", url="http://localhost:8085/mcp", enabled=True)
    )
    registry.register(
        ServerConfig(name="glances", url="http://localhost:5057/mcp", enabled=False)
    )
    names = registry.get_tool_names()
    assert names == ["seerr"]
