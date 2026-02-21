"""E2E test fixtures and configuration.

These tests require real network connectivity to the Styrene mesh.
Configuration is loaded from tests/e2e_config.yaml (gitignored).
"""

import logging
from pathlib import Path
from typing import Any

import pytest
import yaml

logger = logging.getLogger(__name__)

# Path to e2e config file
E2E_CONFIG_PATH = Path(__file__).parent.parent / "e2e_config.yaml"
E2E_CONFIG_EXAMPLE = Path(__file__).parent.parent / "e2e_config.example.yaml"


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers for e2e tests."""
    config.addinivalue_line(
        "markers",
        "e2e: marks tests as end-to-end (requires real network)",
    )
    config.addinivalue_line(
        "markers",
        "hub_required: marks tests that require the brutus hub to be online",
    )
    config.addinivalue_line(
        "markers",
        "node_q502: marks tests that require the q502 node to be online",
    )
    config.addinivalue_line(
        "markers",
        "slow: marks tests that take >30s (network timeouts)",
    )


def _load_e2e_config() -> dict[str, Any]:
    """Load e2e configuration from YAML file."""
    if not E2E_CONFIG_PATH.exists():
        pytest.skip(
            f"E2E config not found at {E2E_CONFIG_PATH}. "
            f"Copy {E2E_CONFIG_EXAMPLE} and fill in values."
        )

    with open(E2E_CONFIG_PATH) as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="session")
def e2e_config() -> dict[str, Any]:
    """Load e2e test configuration.

    Returns:
        Configuration dictionary with hub, nodes, operator settings.
    """
    return _load_e2e_config()


@pytest.fixture(scope="session")
def hub_config(e2e_config: dict[str, Any]) -> dict[str, Any]:
    """Get hub-specific configuration.

    Returns:
        Hub config with address, tcp_host, tcp_port.
    """
    return e2e_config["hub"]


@pytest.fixture(scope="session")
def timeouts(e2e_config: dict[str, Any]) -> dict[str, int]:
    """Get timeout configuration.

    Returns:
        Timeouts for various operations.
    """
    return e2e_config.get(
        "timeouts",
        {
            "hub_announce_interval": 60,
            "hub_connection_timeout": 90,
            "rpc_timeout": 30,
            "discovery_timeout": 120,
        },
    )


@pytest.fixture(scope="session")
def q502_config(e2e_config: dict[str, Any]) -> dict[str, Any] | None:
    """Get q502 node configuration if available.

    Returns:
        Node config or None if not configured/available.
    """
    nodes = e2e_config.get("nodes", {})
    q502 = nodes.get("q502")

    if not q502:
        return None

    if not q502.get("available", False):
        return None

    if q502.get("destination_hash", "").startswith("<"):
        # Placeholder not filled in
        return None

    return q502


@pytest.fixture
def require_hub(hub_config: dict[str, Any]) -> dict[str, Any]:
    """Fixture that skips test if hub is not configured.

    Use this fixture to mark tests that require hub connectivity.
    """
    if not hub_config.get("address"):
        pytest.skip("Hub address not configured")
    return hub_config


@pytest.fixture
def require_q502(q502_config: dict[str, Any] | None) -> dict[str, Any]:
    """Fixture that skips test if q502 is not available.

    Use this fixture to mark tests that require the q502 node.
    """
    if q502_config is None:
        pytest.skip("q502 node not configured or not available")
    return q502_config


# =============================================================================
# Styrene Service Fixtures
# =============================================================================


@pytest.fixture
def styrene_config():
    """Create Styrene configuration for e2e tests."""
    from styrened.tui.services.config import load_config

    config = load_config()
    # Disable hub auto-connect for controlled testing
    config.reticulum.hub_enabled = False
    return config


@pytest.fixture
async def styrene_lifecycle(styrene_config):
    """Initialize and cleanup Styrene services.

    Yields:
        Initialized StyreneLifecycle instance.
    """
    from styrened.tui.services.app_lifecycle import StyreneLifecycle

    lifecycle = StyreneLifecycle(styrene_config)

    if not lifecycle.initialize():
        pytest.fail("Failed to initialize Styrene services")

    logger.info("Styrene services initialized for e2e test")

    yield lifecycle

    lifecycle.shutdown()
    logger.info("Styrene services shut down")


@pytest.fixture
async def lxmf_service(styrene_lifecycle):
    """Get initialized LXMF service.

    Yields:
        LXMFService instance ready for messaging.
    """
    from styrened.services.lxmf_service import get_lxmf_service

    service = get_lxmf_service()
    if service is None:
        pytest.fail("LXMF service not initialized")

    return service


@pytest.fixture
async def rpc_client(lxmf_service):
    """Create RPC client for e2e tests.

    Yields:
        RPCClient instance.
    """
    from styrened.rpc import RPCClient

    return RPCClient(lxmf_service)


@pytest.fixture
def node_store():
    """Get NodeStore for checking discovered devices.

    Returns:
        NodeStore singleton instance.
    """
    from styrened.services.node_store import get_node_store

    return get_node_store()
