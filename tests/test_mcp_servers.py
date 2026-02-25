"""Tests for MCP server configurations."""

import os
from unittest.mock import patch

from home_agent.mcp.servers import ServerConfig, get_jellyseerr_config


def test_get_jellyseerr_config_returns_server_config() -> None:
    """get_jellyseerr_config returns a ServerConfig."""
    config = get_jellyseerr_config(mcp_port=5056)
    assert isinstance(config, ServerConfig)


def test_jellyseerr_config_has_correct_url() -> None:
    """Jellyseerr config has expected MCP endpoint URL when MCP_HOST is not set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MCP_HOST", None)
        config = get_jellyseerr_config(mcp_port=5056)
    assert config.name == "jellyseerr"
    assert config.url == "http://localhost:5056/sse"
    assert config.enabled is True


def test_jellyseerr_config_url_uses_port_parameter() -> None:
    """Jellyseerr config URL uses the provided port parameter."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MCP_HOST", None)
        config = get_jellyseerr_config(mcp_port=5057)
    assert config.url == "http://localhost:5057/sse"


def test_jellyseerr_config_url_uses_mcp_host_env_var() -> None:
    """Jellyseerr config URL uses MCP_HOST env var when set."""
    with patch.dict(os.environ, {"MCP_HOST": "jellyseerr-mcp"}):
        config = get_jellyseerr_config(mcp_port=5056)
    assert config.url == "http://jellyseerr-mcp:5056/sse"
