"""Core dialogue primitives operating through TestHarness abstraction.

These primitives are backend-agnostic (SSH or K8s) and provide the
building blocks for executing dialogue scripts between styrened instances.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .models import (
    DialogueScript,
    DialogueTurn,
    MultiNodeDialogueScript,
    MultiNodeDialogueTurn,
    TurnDirection,
)
from .results import DialogueResult, TurnResult

if TYPE_CHECKING:
    from tests.harness.base import TestHarness

logger = logging.getLogger(__name__)


def stamp_content(template: str, cycle_id: str, turn_index: int) -> str:
    """Append dynamic identifiers to message content for unique verification.

    Args:
        template: Original content string.
        cycle_id: Unique cycle identifier (e.g., "c0001").
        turn_index: Turn index within the dialogue.

    Returns:
        Stamped content string with appended metadata.
    """
    ts_ms = int(time.time() * 1000)
    return f"{template}|cid={cycle_id}|tidx={turn_index}|ts={ts_ms}"


@dataclass
class HealthCheckResult:
    """Result of a daemon health check across nodes."""

    all_healthy: bool
    statuses: dict[str, bool]
    restarted: set[str] = field(default_factory=set)


def ensure_daemons_healthy(
    harness: TestHarness,
    nodes: list[str],
    restart_timeout: int = 60,
) -> HealthCheckResult:
    """Check daemon health on all nodes, restarting failures.

    Args:
        harness: Test harness instance.
        nodes: List of node names to check.
        restart_timeout: Seconds to wait for daemon after restart.

    Returns:
        HealthCheckResult with status of each node.
    """
    statuses: dict[str, bool] = {}
    restarted: set[str] = set()

    for node in nodes:
        running = harness.is_daemon_running(node)
        if running:
            statuses[node] = True
            continue

        logger.warning("Daemon not running on %s, attempting restart", node)
        result = harness.start_daemon(node)
        if not result.success:
            logger.error("Failed to start daemon on %s: %s", node, result.stderr[:200])
            statuses[node] = False
            continue

        responsive = harness.wait_for_daemon(node, timeout=restart_timeout)
        statuses[node] = responsive
        if responsive:
            restarted.add(node)
            logger.info("Daemon restarted successfully on %s", node)
        else:
            logger.error("Daemon on %s not responsive after restart", node)

    all_healthy = all(statuses.values())
    return HealthCheckResult(
        all_healthy=all_healthy,
        statuses=statuses,
        restarted=restarted,
    )


def _extract_content(raw: str) -> str:
    """Extract plain text content from a message content field.

    Chat messages are stored as JSON: {"type":"chat","protocol":"chat","content":"actual text"}.
    This extracts the nested content if present, otherwise returns the raw string.
    """
    if not raw or not raw.startswith("{"):
        return raw
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict) and "content" in parsed:
            return parsed["content"]
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def resolve_lxmf_hashes(
    harness: TestHarness,
    node_a: str,
    node_b: str,
    wait: int = 15,
) -> tuple[str, str]:
    """Resolve LXMF destination hashes for a pair of nodes.

    Runs `styrened devices -w {wait} --json` on each node and extracts
    the other node's lxmf_destination_hash from the device list.

    Args:
        harness: Test harness instance.
        node_a: Name of the first node.
        node_b: Name of the second node.
        wait: Discovery wait time in seconds.

    Returns:
        Tuple of (b_lxmf_hash_as_seen_by_a, a_lxmf_hash_as_seen_by_b).

    Raises:
        RuntimeError: If hashes cannot be resolved.
    """
    # Get identity hashes from registry for matching
    node_a_info = None
    node_b_info = None
    for node in harness.get_nodes():
        if node.name == node_a:
            node_a_info = node
        elif node.name == node_b:
            node_b_info = node

    if not node_a_info or not node_b_info:
        raise RuntimeError(f"Could not find node info for {node_a} and/or {node_b}")

    id_a = node_a_info.identity_hash
    id_b = node_b_info.identity_hash

    if not id_a or not id_b:
        raise RuntimeError(
            f"Identity hashes not configured: {node_a}={id_a}, {node_b}={id_b}"
        )

    # A discovers B
    b_lxmf_hash = _find_lxmf_hash(harness, node_a, id_b, wait)
    if not b_lxmf_hash:
        raise RuntimeError(
            f"{node_a} could not resolve LXMF hash for {node_b} (identity={id_b[:16]})"
        )

    # B discovers A
    a_lxmf_hash = _find_lxmf_hash(harness, node_b, id_a, wait)
    if not a_lxmf_hash:
        raise RuntimeError(
            f"{node_b} could not resolve LXMF hash for {node_a} (identity={id_a[:16]})"
        )

    logger.info(
        "LXMF hash resolution: %s->%s=%s, %s->%s=%s",
        node_a, node_b, b_lxmf_hash[:16],
        node_b, node_a, a_lxmf_hash[:16],
    )

    return b_lxmf_hash, a_lxmf_hash


def _find_lxmf_hash(
    harness: TestHarness,
    source_node: str,
    target_identity: str,
    wait: int,
) -> str | None:
    """Find a device's LXMF destination hash from another node's perspective."""
    devices = harness.discover_devices(source_node, wait_seconds=wait)
    prefix = target_identity[:16]

    for device in devices:
        identity = device.get("identity_hash", "") or device.get("identity", "")
        if identity and identity.startswith(prefix):
            lxmf_hash = device.get("lxmf_destination_hash", "")
            if lxmf_hash:
                return lxmf_hash
            # Fall back to destination_hash if no LXMF hash
            dest_hash = device.get("destination_hash", "")
            if dest_hash:
                return dest_hash

    return None


def query_messages_via_cli(
    harness: TestHarness,
    node: str,
    peer_hash: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Query messages via styrened CLI.

    Args:
        harness: Test harness instance.
        node: Node to query from.
        peer_hash: LXMF destination hash of the peer.
        limit: Maximum messages to return.

    Returns:
        List of message dicts, or empty list on failure.
    """
    result = harness.run_styrened(
        node,
        f"messages {peer_hash} -n {limit} --json",
        timeout=30.0,
    )

    if not result.success or not result.stdout.strip():
        return []

    try:
        # Handle output that may have prefix text before JSON
        stdout = result.stdout
        json_start = stdout.find("[")
        if json_start != -1:
            return json.loads(stdout[json_start:])
        # Try parsing as-is (might be "No messages" or similar)
        return []
    except json.JSONDecodeError:
        logger.debug("Failed to parse messages JSON from %s: %s", node, result.stdout[:200])
        return []


def verify_message_received(
    harness: TestHarness,
    receiver: str,
    sender_lxmf_hash: str,
    expected_content: str,
    reference_timestamp: float,
    timeout: float = 60.0,
    poll_interval: float = 3.0,
) -> tuple[bool, float]:
    """Poll for a message with matching content on the receiver.

    Args:
        harness: Test harness instance.
        receiver: Node to check for the message.
        sender_lxmf_hash: LXMF hash of the sender (used as peer_hash).
        expected_content: Expected message content to match.
        reference_timestamp: Only match messages with timestamp >= this.
        timeout: Maximum seconds to poll.
        poll_interval: Seconds between poll attempts.

    Returns:
        Tuple of (found, elapsed_seconds).
    """
    start = time.time()
    while time.time() - start < timeout:
        messages = query_messages_via_cli(harness, receiver, sender_lxmf_hash)
        for msg in messages:
            msg_content = _extract_content(msg.get("content", ""))
            msg_timestamp = msg.get("timestamp", 0.0)
            if msg_content == expected_content and msg_timestamp >= reference_timestamp:
                elapsed = time.time() - start
                logger.debug(
                    "Message verified on %s after %.1fs: %s",
                    receiver, elapsed, expected_content[:40],
                )
                return True, elapsed
        time.sleep(poll_interval)

    elapsed = time.time() - start
    logger.warning(
        "Message verification timed out on %s after %.1fs: %s",
        receiver, elapsed, expected_content[:40],
    )
    return False, elapsed


def send_and_verify(
    harness: TestHarness,
    sender: str,
    receiver: str,
    receiver_identity_hash: str,
    sender_lxmf_hash: str,
    content: str,
    turn_index: int = 0,
    delivery_timeout: float = 120.0,
    verification_timeout: float = 60.0,
    max_retries: int = 0,
) -> TurnResult:
    """Send a message and verify receipt, with optional retries.

    Args:
        harness: Test harness instance.
        sender: Sending node name.
        receiver: Receiving node name.
        receiver_identity_hash: Identity hash of the receiver (for send command).
        sender_lxmf_hash: LXMF hash of sender (for receiver's message query).
        content: Message content to send.
        turn_index: Index of this turn in the dialogue.
        delivery_timeout: Timeout for the send command.
        verification_timeout: Timeout for verifying receipt.
        max_retries: Number of retry attempts (0 = no retries).

    Returns:
        TurnResult with all metrics.
    """
    started_at = time.time()
    attempts = 0
    last_result: TurnResult | None = None

    while attempts <= max_retries:
        if attempts > 0:
            backoff = min(5 * (2 ** (attempts - 1)), 30)
            logger.info(
                "Turn %d: retry %d/%d after %.0fs backoff",
                turn_index, attempts, max_retries, backoff,
            )
            time.sleep(backoff)

        reference_timestamp = time.time()

        # Send
        send_start = time.time()
        escaped_content = content.replace("'", "'\\''")
        send_result = harness.run_styrened(
            sender,
            f"send {receiver_identity_hash} '{escaped_content}'",
            timeout=delivery_timeout,
        )
        send_duration = time.time() - send_start
        send_success = send_result.success

        if not send_success:
            logger.warning(
                "Turn %d: send failed from %s to %s: %s",
                turn_index, sender, receiver, send_result.stderr[:200],
            )
            last_result = TurnResult(
                turn_index=turn_index,
                success=False,
                send_success=False,
                send_duration=send_duration,
                content_verified=False,
                verification_duration=0.0,
                retry_count=attempts,
                error=f"Send failed: {send_result.stderr[:200]}",
                started_at=started_at,
            )
            attempts += 1
            continue

        # Verify
        content_verified, verification_duration = verify_message_received(
            harness=harness,
            receiver=receiver,
            sender_lxmf_hash=sender_lxmf_hash,
            expected_content=content,
            reference_timestamp=reference_timestamp,
            timeout=verification_timeout,
        )

        success = send_success and content_verified

        if not content_verified:
            logger.warning(
                "Turn %d: verification failed from %s to %s (sent OK, not received)",
                turn_index, sender, receiver,
            )

        last_result = TurnResult(
            turn_index=turn_index,
            success=success,
            send_success=send_success,
            send_duration=send_duration,
            content_verified=content_verified,
            verification_duration=verification_duration,
            retry_count=attempts,
            error=None if success else "Verification timed out",
            started_at=started_at,
        )

        if success:
            return last_result

        attempts += 1

    # Exhausted retries — return last result
    assert last_result is not None
    return last_result


def execute_dialogue_turn(
    harness: TestHarness,
    turn: DialogueTurn,
    turn_index: int,
    node_a: str,
    node_b: str,
    identity_a: str,
    identity_b: str,
    lxmf_a: str,
    lxmf_b: str,
    max_retries: int = 0,
) -> TurnResult:
    """Execute a single dialogue turn.

    Args:
        harness: Test harness instance.
        turn: The dialogue turn to execute.
        turn_index: Index of this turn.
        node_a: Name of node A.
        node_b: Name of node B.
        identity_a: Identity hash of node A.
        identity_b: Identity hash of node B.
        lxmf_a: LXMF destination hash of A as seen by B.
        lxmf_b: LXMF destination hash of B as seen by A.
        max_retries: Override for max retries (0 = no retries).

    Returns:
        TurnResult with metrics.
    """
    if turn.direction == TurnDirection.A_TO_B:
        sender, receiver = node_a, node_b
        receiver_identity = identity_b
        sender_lxmf = lxmf_a
    else:
        sender, receiver = node_b, node_a
        receiver_identity = identity_a
        sender_lxmf = lxmf_b

    # Turn metadata can override max_retries
    effective_retries = turn.metadata.get("max_retries", max_retries)

    return send_and_verify(
        harness=harness,
        sender=sender,
        receiver=receiver,
        receiver_identity_hash=receiver_identity,
        sender_lxmf_hash=sender_lxmf,
        content=turn.content,
        turn_index=turn_index,
        delivery_timeout=turn.delivery_timeout,
        verification_timeout=turn.verification_timeout,
        max_retries=effective_retries,
    )


def execute_dialogue(
    harness: TestHarness,
    script: DialogueScript,
    node_a: str,
    node_b: str,
    identity_a: str,
    identity_b: str,
    lxmf_a: str,
    lxmf_b: str,
    cycle_id: str | None = None,
    cycle_index: int = 0,
    default_max_retries: int = 0,
) -> DialogueResult:
    """Execute a complete dialogue script.

    Runs all turns sequentially with log-and-continue on failure.
    Failed turns are recorded but do not stop execution.

    Args:
        harness: Test harness instance.
        script: Dialogue script to execute.
        node_a: Name of node A.
        node_b: Name of node B.
        identity_a: Identity hash of node A.
        identity_b: Identity hash of node B.
        lxmf_a: LXMF destination hash of A as seen by B.
        lxmf_b: LXMF destination hash of B as seen by A.
        cycle_id: When set, stamps each turn's content for unique verification.
        cycle_index: Cycle number for temporal tracking.
        default_max_retries: Default max retries for turns without explicit setting.

    Returns:
        DialogueResult with all turn results and summary.
    """
    logger.info(
        "Executing dialogue '%s' (%d turns) between %s and %s",
        script.name, len(script.turns), node_a, node_b,
    )

    dialogue_start = time.time()
    turn_results: list[TurnResult] = []

    # Setup delay
    if script.setup_delay > 0:
        time.sleep(script.setup_delay)

    for i, turn in enumerate(script.turns):
        # Stamp content if cycle_id is set (creates new turn, leaves original untouched)
        effective_turn = turn
        if cycle_id is not None:
            stamped = stamp_content(turn.content, cycle_id, i)
            effective_turn = DialogueTurn(
                direction=turn.direction,
                content=stamped,
                delivery_timeout=turn.delivery_timeout,
                verification_timeout=turn.verification_timeout,
                metadata=turn.metadata,
            )

        logger.info(
            "Turn %d/%d: %s -> %s",
            i + 1, len(script.turns),
            node_a if effective_turn.direction == TurnDirection.A_TO_B else node_b,
            node_b if effective_turn.direction == TurnDirection.A_TO_B else node_a,
        )

        result = execute_dialogue_turn(
            harness=harness,
            turn=effective_turn,
            turn_index=i,
            node_a=node_a,
            node_b=node_b,
            identity_a=identity_a,
            identity_b=identity_b,
            lxmf_a=lxmf_a,
            lxmf_b=lxmf_b,
            max_retries=default_max_retries,
        )
        turn_results.append(result)

        status = "OK" if result.success else "FAIL"
        logger.info(
            "Turn %d: %s (send=%.1fs, verify=%.1fs)",
            i + 1, status, result.send_duration, result.verification_duration,
        )

        # Inter-turn delay (skip after last turn)
        if i < len(script.turns) - 1 and script.inter_turn_delay > 0:
            time.sleep(script.inter_turn_delay)

    completed_at = time.time()
    total_duration = completed_at - dialogue_start
    turns_succeeded = sum(1 for r in turn_results if r.success)
    turns_failed = sum(1 for r in turn_results if not r.success)

    dialogue_result = DialogueResult(
        script_name=script.name,
        success=turns_failed == 0,
        turns=turn_results,
        total_duration=total_duration,
        turns_succeeded=turns_succeeded,
        turns_failed=turns_failed,
        cycle_index=cycle_index,
        started_at=dialogue_start,
        completed_at=completed_at,
    )

    logger.info(
        "Dialogue '%s' complete: %d/%d turns passed (%.1fs)",
        script.name, turns_succeeded, len(script.turns), total_duration,
    )

    return dialogue_result


# ---------------------------------------------------------------------------
# Multi-node primitives
# ---------------------------------------------------------------------------


def resolve_multi_node_lxmf_hashes(
    harness: TestHarness,
    nodes: list[str],
    wait: int = 15,
) -> dict[tuple[str, str], str]:
    """Resolve LXMF destination hashes for all directional pairs in a node set.

    For N nodes, resolves N*(N-1) hashes: for each (observer, target) pair,
    finds target's LXMF hash as seen by observer.

    Args:
        harness: Test harness instance.
        nodes: List of node names.
        wait: Discovery wait time in seconds.

    Returns:
        Dict mapping (observer, target) -> LXMF destination hash.

    Raises:
        RuntimeError: If identity hashes are not configured or resolution fails.
    """
    # Build identity map
    node_infos = {n.name: n for n in harness.get_nodes()}
    identities: dict[str, str] = {}

    for name in nodes:
        info = node_infos.get(name)
        if not info or not info.identity_hash:
            raise RuntimeError(f"Identity hash not configured for node '{name}'")
        identities[name] = info.identity_hash

    # Resolve all directional pairs
    hashes: dict[tuple[str, str], str] = {}

    for observer in nodes:
        for target in nodes:
            if observer == target:
                continue

            target_id = identities[target]
            lxmf_hash = _find_lxmf_hash(harness, observer, target_id, wait)
            if not lxmf_hash:
                raise RuntimeError(
                    f"{observer} could not resolve LXMF hash for {target} "
                    f"(identity={target_id[:16]})"
                )
            hashes[(observer, target)] = lxmf_hash

    logger.info(
        "Multi-node LXMF resolution complete: %d hashes for %d nodes",
        len(hashes), len(nodes),
    )

    return hashes


def execute_multi_node_dialogue_turn(
    harness: TestHarness,
    turn: MultiNodeDialogueTurn,
    turn_index: int,
    role_to_node: dict[str, str],
    node_identities: dict[str, str],
    lxmf_hashes: dict[tuple[str, str], str],
    max_retries: int = 0,
) -> TurnResult:
    """Execute a single multi-node dialogue turn.

    Args:
        harness: Test harness instance.
        turn: The multi-node dialogue turn.
        turn_index: Index of this turn.
        role_to_node: Maps role names (e.g. "A") to node names.
        node_identities: Maps node names to identity hashes.
        lxmf_hashes: Maps (observer, target) to LXMF hash.
        max_retries: Max retry attempts.

    Returns:
        TurnResult with metrics.
    """
    sender_node = role_to_node[turn.sender]
    receiver_node = role_to_node[turn.receiver]
    receiver_identity = node_identities[receiver_node]
    sender_lxmf = lxmf_hashes[(receiver_node, sender_node)]

    effective_retries = turn.metadata.get("max_retries", max_retries)

    return send_and_verify(
        harness=harness,
        sender=sender_node,
        receiver=receiver_node,
        receiver_identity_hash=receiver_identity,
        sender_lxmf_hash=sender_lxmf,
        content=turn.content,
        turn_index=turn_index,
        delivery_timeout=turn.delivery_timeout,
        verification_timeout=turn.verification_timeout,
        max_retries=effective_retries,
    )


def execute_multi_node_dialogue(
    harness: TestHarness,
    script: MultiNodeDialogueScript,
    role_to_node: dict[str, str],
    node_identities: dict[str, str],
    lxmf_hashes: dict[tuple[str, str], str],
    cycle_id: str | None = None,
    cycle_index: int = 0,
    default_max_retries: int = 0,
) -> DialogueResult:
    """Execute a complete multi-node dialogue script.

    Same log-and-continue pattern as execute_dialogue().

    Args:
        harness: Test harness instance.
        script: Multi-node dialogue script.
        role_to_node: Maps role names to node names.
        node_identities: Maps node names to identity hashes.
        lxmf_hashes: Maps (observer, target) to LXMF hash.
        cycle_id: When set, stamps each turn's content.
        cycle_index: Cycle number for temporal tracking.
        default_max_retries: Default max retries for turns.

    Returns:
        DialogueResult with all turn results.
    """
    logger.info(
        "Executing multi-node dialogue '%s' (%d turns, roles=%s)",
        script.name, len(script.turns), list(role_to_node.keys()),
    )

    dialogue_start = time.time()
    turn_results: list[TurnResult] = []

    if script.setup_delay > 0:
        time.sleep(script.setup_delay)

    for i, turn in enumerate(script.turns):
        # Stamp content if cycle_id is set
        effective_turn = turn
        if cycle_id is not None:
            stamped = stamp_content(turn.content, cycle_id, i)
            effective_turn = MultiNodeDialogueTurn(
                sender=turn.sender,
                receiver=turn.receiver,
                content=stamped,
                delivery_timeout=turn.delivery_timeout,
                verification_timeout=turn.verification_timeout,
                metadata=turn.metadata,
            )

        sender_node = role_to_node[effective_turn.sender]
        receiver_node = role_to_node[effective_turn.receiver]

        logger.info(
            "Turn %d/%d: %s(%s) -> %s(%s)",
            i + 1, len(script.turns),
            effective_turn.sender, sender_node,
            effective_turn.receiver, receiver_node,
        )

        result = execute_multi_node_dialogue_turn(
            harness=harness,
            turn=effective_turn,
            turn_index=i,
            role_to_node=role_to_node,
            node_identities=node_identities,
            lxmf_hashes=lxmf_hashes,
            max_retries=default_max_retries,
        )
        turn_results.append(result)

        status = "OK" if result.success else "FAIL"
        logger.info(
            "Turn %d: %s (send=%.1fs, verify=%.1fs)",
            i + 1, status, result.send_duration, result.verification_duration,
        )

        if i < len(script.turns) - 1 and script.inter_turn_delay > 0:
            time.sleep(script.inter_turn_delay)

    completed_at = time.time()
    total_duration = completed_at - dialogue_start
    turns_succeeded = sum(1 for r in turn_results if r.success)
    turns_failed = sum(1 for r in turn_results if not r.success)

    dialogue_result = DialogueResult(
        script_name=script.name,
        success=turns_failed == 0,
        turns=turn_results,
        total_duration=total_duration,
        turns_succeeded=turns_succeeded,
        turns_failed=turns_failed,
        cycle_index=cycle_index,
        started_at=dialogue_start,
        completed_at=completed_at,
    )

    logger.info(
        "Multi-node dialogue '%s' complete: %d/%d turns passed (%.1fs)",
        script.name, turns_succeeded, len(script.turns), total_duration,
    )

    return dialogue_result
