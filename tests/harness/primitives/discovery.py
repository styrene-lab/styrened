"""Discovery test primitives."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from .base import PrimitiveResult

if TYPE_CHECKING:
    from ..base import NodeInfo, TestHarness

logger = logging.getLogger(__name__)


def discover_peers(
    harness: TestHarness,
    node: str | NodeInfo,
    wait_seconds: int = 10,
    min_expected: int = 0,
) -> PrimitiveResult:
    """Discover mesh peers from a node.

    Args:
        harness: Test harness instance
        node: Node to run discovery from
        wait_seconds: Time to wait for announces
        min_expected: Minimum expected peer count

    Returns:
        PrimitiveResult with discovered devices
    """
    start = time.time()
    node_name = node if isinstance(node, str) else node.name

    logger.info(
        "[%s] Discovering peers (wait=%ds, min_expected=%d)...",
        node_name,
        wait_seconds,
        min_expected,
    )

    devices = harness.discover_devices(node, wait_seconds)
    duration = time.time() - start

    success = len(devices) >= min_expected

    if success:
        logger.info(
            "[%s] Discovery PASSED: found %d devices (expected >= %d) in %.2fs",
            node_name,
            len(devices),
            min_expected,
            duration,
        )
        for i, device in enumerate(devices):
            identity = device.get("identity", device.get("hash", "unknown"))
            logger.debug("[%s]   [%d] %s", node_name, i, identity[:16] if identity else "unknown")
    else:
        logger.warning(
            "[%s] Discovery FAILED: found %d devices (expected >= %d) in %.2fs",
            node_name,
            len(devices),
            min_expected,
            duration,
        )

    return PrimitiveResult(
        success=success,
        name="discover_peers",
        node=node_name,
        duration=duration,
        message=f"Found {len(devices)} devices (expected >= {min_expected})",
        data={"devices": devices, "count": len(devices)},
        error=None if success else f"Found {len(devices)}, expected >= {min_expected}",
    )


def check_bidirectional_discovery(
    harness: TestHarness,
    node_a: str | NodeInfo,
    node_b: str | NodeInfo,
    wait_seconds: int = 15,
) -> PrimitiveResult:
    """Verify two nodes can discover each other.

    Args:
        harness: Test harness instance
        node_a: First node
        node_b: Second node
        wait_seconds: Time to wait for discovery

    Returns:
        PrimitiveResult indicating bidirectional discovery status
    """
    start = time.time()
    node_a_name = node_a if isinstance(node_a, str) else node_a.name
    node_b_name = node_b if isinstance(node_b, str) else node_b.name
    pair_name = f"{node_a_name}<->{node_b_name}"

    logger.info("[%s] Checking bidirectional discovery (wait=%ds)...", pair_name, wait_seconds)

    # Get identities
    logger.debug("[%s] Getting identity for %s...", pair_name, node_a_name)
    id_a = harness.get_identity(node_a)
    logger.debug("[%s] Getting identity for %s...", pair_name, node_b_name)
    id_b = harness.get_identity(node_b)

    if not id_a or not id_b:
        duration = time.time() - start
        logger.error(
            "[%s] Cannot check discovery - missing identities: A=%s, B=%s", pair_name, id_a, id_b
        )
        return PrimitiveResult(
            success=False,
            name="bidirectional_discovery",
            node=pair_name,
            duration=duration,
            error=f"Could not get identities: A={id_a}, B={id_b}",
            data={"id_a": id_a, "id_b": id_b},
        )

    logger.debug("[%s] Identity A: %s", pair_name, id_a[:16] if id_a else None)
    logger.debug("[%s] Identity B: %s", pair_name, id_b[:16] if id_b else None)

    # A discovers B
    logger.debug("[%s] Checking if A (%s) sees B...", pair_name, node_a_name)
    devices_a = harness.discover_devices(node_a, wait_seconds)
    a_sees_b = _identity_in_devices(id_b, devices_a)
    logger.debug("[%s] A sees B: %s (found %d devices)", pair_name, a_sees_b, len(devices_a))

    # B discovers A
    logger.debug("[%s] Checking if B (%s) sees A...", pair_name, node_b_name)
    devices_b = harness.discover_devices(node_b, wait_seconds)
    b_sees_a = _identity_in_devices(id_a, devices_b)
    logger.debug("[%s] B sees A: %s (found %d devices)", pair_name, b_sees_a, len(devices_b))

    success = a_sees_b and b_sees_a
    duration = time.time() - start

    if success:
        logger.info(
            "[%s] Bidirectional discovery PASSED (%.2fs): A->B=%s, B->A=%s",
            pair_name,
            duration,
            a_sees_b,
            b_sees_a,
        )
    else:
        logger.warning(
            "[%s] Bidirectional discovery FAILED (%.2fs): A->B=%s, B->A=%s",
            pair_name,
            duration,
            a_sees_b,
            b_sees_a,
        )
        if not a_sees_b:
            logger.warning(
                "[%s]   A's devices: %s", pair_name, [d.get("identity", "?")[:8] for d in devices_a]
            )
        if not b_sees_a:
            logger.warning(
                "[%s]   B's devices: %s", pair_name, [d.get("identity", "?")[:8] for d in devices_b]
            )

    return PrimitiveResult(
        success=success,
        name="bidirectional_discovery",
        node=pair_name,
        duration=duration,
        message=f"A->B: {a_sees_b}, B->A: {b_sees_a}",
        data={
            "a_sees_b": a_sees_b,
            "b_sees_a": b_sees_a,
            "id_a": id_a,
            "id_b": id_b,
            "devices_a_count": len(devices_a),
            "devices_b_count": len(devices_b),
        },
        error=None if success else f"Incomplete: A->B={a_sees_b}, B->A={b_sees_a}",
    )


def _identity_in_devices(identity: str, devices: list[dict[str, Any]]) -> bool:
    """Check if identity is in device list (prefix match)."""
    # Use first 8 chars for prefix matching (truncated hash format)
    prefix = identity[:8] if len(identity) >= 8 else identity

    for device in devices:
        # Check all possible identity field names
        device_id = (
            device.get("identity_hash", "") or device.get("identity", "") or device.get("hash", "")
        )
        if device_id and (device_id.startswith(prefix) or prefix in device_id):
            return True
    return False
