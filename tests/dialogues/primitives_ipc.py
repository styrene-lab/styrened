"""Async IPC-native dialogue primitives for Docker mesh tests.

Reuses existing helpers from the dialogue framework and IPC client
but operates through ControlClient IPC calls instead of CLI subprocesses.
Returns the same TurnResult/DialogueResult types for consistent reporting.
"""

from __future__ import annotations

import asyncio
import logging
import time

from styrened.ipc.client import ControlClient
from tests.harness.ipc_client import poll_for_message

from .models import DialogueScript, DialogueTurn, TurnDirection
from .primitives import stamp_content
from .results import DialogueResult, TurnResult

logger = logging.getLogger(__name__)


async def send_and_verify_ipc(
    sender: ControlClient,
    receiver: ControlClient,
    receiver_lxmf: str,
    sender_lxmf: str,
    content: str,
    turn_index: int = 0,
    verification_timeout: float = 60.0,
    max_retries: int = 0,
) -> TurnResult:
    """Send a chat message via IPC and verify receipt on the receiver.

    Args:
        sender: ControlClient for the sending node.
        receiver: ControlClient for the receiving node.
        receiver_lxmf: LXMF destination hash of the receiver (peer_hash for send).
        sender_lxmf: LXMF destination hash of the sender (for receiver's query).
        content: Message content to send.
        turn_index: Index of this turn in the dialogue.
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
            await asyncio.sleep(backoff)

        # Send via IPC
        send_start = time.time()
        send_success = False
        error_msg = None
        try:
            result = await sender.send_chat(peer_hash=receiver_lxmf, content=content)
            send_success = result.get("message_id") is not None
            if not send_success:
                error_msg = f"send_chat returned no message_id: {result}"
        except Exception as e:
            error_msg = f"send_chat exception: {e}"
        send_duration = time.time() - send_start

        if not send_success:
            logger.warning(
                "Turn %d: send failed: %s", turn_index, error_msg,
            )
            last_result = TurnResult(
                turn_index=turn_index,
                success=False,
                send_success=False,
                send_duration=send_duration,
                content_verified=False,
                verification_duration=0.0,
                retry_count=attempts,
                error=error_msg,
                started_at=started_at,
            )
            attempts += 1
            continue

        # Verify receipt via polling
        verify_start = time.time()
        received = await poll_for_message(
            receiver, content=content, timeout=verification_timeout,
        )
        verification_duration = time.time() - verify_start
        content_verified = received is not None

        success = send_success and content_verified
        if not content_verified:
            logger.warning(
                "Turn %d: verification failed (sent OK, not received within %.0fs)",
                turn_index, verification_timeout,
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

    assert last_result is not None
    return last_result


async def execute_dialogue_turn_ipc(
    turn: DialogueTurn,
    turn_index: int,
    client_a: ControlClient,
    client_b: ControlClient,
    lxmf_a: str,
    lxmf_b: str,
    max_retries: int = 0,
) -> TurnResult:
    """Execute a single dialogue turn via IPC.

    Args:
        turn: The dialogue turn to execute.
        turn_index: Index of this turn.
        client_a: ControlClient for node A.
        client_b: ControlClient for node B.
        lxmf_a: LXMF destination hash of A.
        lxmf_b: LXMF destination hash of B.
        max_retries: Max retry attempts.

    Returns:
        TurnResult with metrics.
    """
    if turn.direction == TurnDirection.A_TO_B:
        sender, receiver = client_a, client_b
        receiver_lxmf = lxmf_b
        sender_lxmf = lxmf_a
    else:
        sender, receiver = client_b, client_a
        receiver_lxmf = lxmf_a
        sender_lxmf = lxmf_b

    effective_retries = turn.metadata.get("max_retries", max_retries)

    return await send_and_verify_ipc(
        sender=sender,
        receiver=receiver,
        receiver_lxmf=receiver_lxmf,
        sender_lxmf=sender_lxmf,
        content=turn.content,
        turn_index=turn_index,
        verification_timeout=turn.verification_timeout,
        max_retries=effective_retries,
    )


async def execute_dialogue_ipc(
    script: DialogueScript,
    client_a: ControlClient,
    client_b: ControlClient,
    lxmf_a: str,
    lxmf_b: str,
    cycle_id: str | None = None,
    cycle_index: int = 0,
    default_max_retries: int = 0,
) -> DialogueResult:
    """Execute a complete dialogue script via IPC.

    Runs all turns sequentially with log-and-continue on failure.

    Args:
        script: Dialogue script to execute.
        client_a: ControlClient for node A.
        client_b: ControlClient for node B.
        lxmf_a: LXMF destination hash of A.
        lxmf_b: LXMF destination hash of B.
        cycle_id: When set, stamps each turn's content for unique verification.
        cycle_index: Cycle number for temporal tracking.
        default_max_retries: Default max retries for turns.

    Returns:
        DialogueResult with all turn results and summary.
    """
    logger.info(
        "Executing dialogue '%s' (%d turns) via IPC",
        script.name, len(script.turns),
    )

    dialogue_start = time.time()
    turn_results: list[TurnResult] = []

    if script.setup_delay > 0:
        await asyncio.sleep(script.setup_delay)

    for i, turn in enumerate(script.turns):
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

        direction_str = "A->B" if effective_turn.direction == TurnDirection.A_TO_B else "B->A"
        logger.info("Turn %d/%d: %s", i + 1, len(script.turns), direction_str)

        result = await execute_dialogue_turn_ipc(
            turn=effective_turn,
            turn_index=i,
            client_a=client_a,
            client_b=client_b,
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

        if i < len(script.turns) - 1 and script.inter_turn_delay > 0:
            await asyncio.sleep(script.inter_turn_delay)

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
