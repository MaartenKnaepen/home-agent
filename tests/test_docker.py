"""Smoke tests for Docker deployment configuration."""

from pathlib import Path

import yaml


def test_dockerfile_exists() -> None:
    """Dockerfile exists in project root."""
    assert Path("Dockerfile").exists(), "Dockerfile not found in project root"


def test_dockerignore_exists() -> None:
    """.dockerignore exists in project root."""
    assert Path(".dockerignore").exists(), ".dockerignore not found"


def test_docker_compose_exists() -> None:
    """deployment/docker-compose.yml exists and is valid YAML."""
    compose_file = Path("deployment/docker-compose.yml")
    assert compose_file.exists(), "deployment/docker-compose.yml not found"

    config = yaml.safe_load(compose_file.read_text())

    assert "services" in config
    assert "home-agent" in config["services"]
    assert "seerr-mcp" in config["services"]


def test_docker_compose_has_volume() -> None:
    """deployment/docker-compose.yml defines persistent volume."""
    compose_file = Path("deployment/docker-compose.yml")
    config = yaml.safe_load(compose_file.read_text())

    assert "volumes" in config
    assert "home-agent-data" in config["volumes"]


def test_docker_compose_has_network() -> None:
    """deployment/docker-compose.yml defines shared network."""
    compose_file = Path("deployment/docker-compose.yml")
    config = yaml.safe_load(compose_file.read_text())

    assert "networks" in config
    assert "home-agent-network" in config["networks"]


def test_seerr_dockerfile_has_healthcheck() -> None:
    """seerr-mcp Dockerfile defines a HEALTHCHECK instruction."""
    dockerfile = Path("mcp_servers/seerr/Dockerfile")
    assert dockerfile.exists(), "mcp_servers/seerr/Dockerfile not found"
    assert "HEALTHCHECK" in dockerfile.read_text()


def test_docker_compose_home_agent_depends_on_mcp() -> None:
    """home-agent depends_on seerr-mcp."""
    compose_file = Path("deployment/docker-compose.yml")
    config = yaml.safe_load(compose_file.read_text())

    home_agent = config["services"]["home-agent"]
    assert "depends_on" in home_agent
    assert "seerr-mcp" in home_agent["depends_on"]
