"""Core dialogue primitives operating through TestHarness abstraction.

These primitives are backend-agnostic (SSH or K8s) and provide the
building blocks for executing dialogue scripts between styrened instances.
"""

from __future__ import annotations

import json
import logging
import time
from typing import TYPE_CHECKING, Any

from .models import DialogueScript, DialogueTurn, TurnDirection
from .results import DialogueResult, TurnResult

if TYPE_CHECKING:
    from tests.harness.base import TestHarness

logger = logging.getLogger(__name__)


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
) -> TurnResult:
    """Send a message and verify receipt.

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

    Returns:
        TurnResult with all metrics.
    """
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
        return TurnResult(
            turn_index=turn_index,
            success=False,
            send_success=False,
            send_duration=send_duration,
            content_verified=False,
            verification_duration=0.0,
            error=f"Send failed: {send_result.stderr[:200]}",
        )

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

    return TurnResult(
        turn_index=turn_index,
        success=success,
        send_success=send_success,
        send_duration=send_duration,
        content_verified=content_verified,
        verification_duration=verification_duration,
        error=None if success else "Verification timed out",
    )


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
        logger.info(
            "Turn %d/%d: %s -> %s",
            i + 1, len(script.turns),
            node_a if turn.direction == TurnDirection.A_TO_B else node_b,
            node_b if turn.direction == TurnDirection.A_TO_B else node_a,
        )

        result = execute_dialogue_turn(
            harness=harness,
            turn=turn,
            turn_index=i,
            node_a=node_a,
            node_b=node_b,
            identity_a=identity_a,
            identity_b=identity_b,
            lxmf_a=lxmf_a,
            lxmf_b=lxmf_b,
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

    total_duration = time.time() - dialogue_start
    turns_succeeded = sum(1 for r in turn_results if r.success)
    turns_failed = sum(1 for r in turn_results if not r.success)

    dialogue_result = DialogueResult(
        script_name=script.name,
        success=turns_failed == 0,
        turns=turn_results,
        total_duration=total_duration,
        turns_succeeded=turns_succeeded,
        turns_failed=turns_failed,
    )

    logger.info(
        "Dialogue '%s' complete: %d/%d turns passed (%.1fs)",
        script.name, turns_succeeded, len(script.turns), total_duration,
    )

    return dialogue_result
