"""Tests for MCP server configurations."""

import os
from unittest.mock import patch

from home_agent.mcp.servers import ServerConfig, get_seerr_config


def test_get_seerr_config_returns_server_config() -> None:
    """get_seerr_config returns a ServerConfig."""
    config = get_seerr_config(mcp_port=8085)
    assert isinstance(config, ServerConfig)


def test_seerr_config_has_correct_url() -> None:
    """Seerr config has expected MCP endpoint URL when MCP_HOST is not set."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MCP_HOST", None)
        config = get_seerr_config(mcp_port=8085)
    assert config.name == "seerr"
    assert config.url == "http://localhost:8085/mcp"
    assert config.enabled is True


def test_seerr_config_url_uses_port_parameter() -> None:
    """Seerr config URL uses the provided port parameter."""
    with patch.dict(os.environ, {}, clear=False):
        os.environ.pop("MCP_HOST", None)
        config = get_seerr_config(mcp_port=9000)
    assert config.url == "http://localhost:9000/mcp"


def test_seerr_config_url_uses_mcp_host_env_var() -> None:
    """Seerr config URL uses MCP_HOST env var when set."""
    with patch.dict(os.environ, {"MCP_HOST": "seerr-mcp"}):
        config = get_seerr_config(mcp_port=8085)
    assert config.url == "http://seerr-mcp:8085/mcp"
