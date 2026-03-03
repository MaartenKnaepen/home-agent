"""Smoke tests for Docker deployment configuration."""

from pathlib import Path

import yaml
import pytest


@pytest.fixture
def compose_config() -> dict:
    """Load docker-compose.yml as a dict.

    Returns:
        Parsed docker-compose configuration.
    """
    compose_file = Path("deployment/docker-compose.yml")
    return yaml.safe_load(compose_file.read_text())


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


def test_qwen3_asr_service_exists(compose_config: dict) -> None:
    """docker-compose has qwen3-asr service."""
    assert "qwen3-asr" in compose_config["services"]


def test_qwen3_asr_has_no_gpu_config(compose_config: dict) -> None:
    """qwen3-asr has no GPU/NVIDIA runtime config — CPU only."""
    service = compose_config["services"]["qwen3-asr"]
    assert "runtime" not in service
    assert "deploy" not in service or "resources" not in service.get("deploy", {})
    # No nvidia-related entries
    env = service.get("environment", [])
    env_str = str(env)
    assert "NVIDIA" not in env_str


def test_qwen3_asr_has_healthcheck(compose_config: dict) -> None:
    """qwen3-asr has a healthcheck with adequate start_period."""
    service = compose_config["services"]["qwen3-asr"]
    assert "healthcheck" in service
    # start_period should be present to allow model loading
    healthcheck = service["healthcheck"]
    assert "start_period" in str(healthcheck)


def test_qwen3_asr_has_huggingface_volume(compose_config: dict) -> None:
    """qwen3-asr mounts huggingface_cache volume."""
    service = compose_config["services"]["qwen3-asr"]
    volumes = service.get("volumes", [])
    assert any("huggingface_cache" in str(v) for v in volumes)


def test_qwen3_asr_has_asr_model_env(compose_config: dict) -> None:
    """qwen3-asr service has ASR_MODEL env var."""
    service = compose_config["services"]["qwen3-asr"]
    env = service.get("environment", [])
    assert any("ASR_MODEL" in str(e) for e in env)


def test_home_agent_depends_on_qwen3_asr(compose_config: dict) -> None:
    """home-agent service waits for qwen3-asr to be healthy."""
    depends = compose_config["services"]["home-agent"].get("depends_on", {})
    assert "qwen3-asr" in depends
