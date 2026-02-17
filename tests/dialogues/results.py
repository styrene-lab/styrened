"""Result tracking for dialogue test post-mortem analysis."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class TurnResult:
    """Result from executing a single dialogue turn."""

    turn_index: int
    success: bool
    send_success: bool
    send_duration: float
    content_verified: bool
    verification_duration: float
    retry_count: int = 0
    error: str | None = None


@dataclass
class DialogueResult:
    """Result from executing a complete dialogue script."""

    script_name: str
    success: bool
    turns: list[TurnResult]
    total_duration: float
    turns_succeeded: int
    turns_failed: int


@dataclass
class OvernightSummary:
    """Summary of an overnight dialogue test run."""

    total_dialogues: int
    total_turns: int
    turns_succeeded: int
    turns_failed: int
    total_retries: int
    avg_send_latency: float
    avg_verification_latency: float
    dialogues: list[DialogueResult] = field(default_factory=list)
    duration_seconds: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total_dialogues": self.total_dialogues,
            "total_turns": self.total_turns,
            "turns_succeeded": self.turns_succeeded,
            "turns_failed": self.turns_failed,
            "total_retries": self.total_retries,
            "avg_send_latency": self.avg_send_latency,
            "avg_verification_latency": self.avg_verification_latency,
            "duration_seconds": self.duration_seconds,
            "dialogues": [
                {
                    "script_name": d.script_name,
                    "success": d.success,
                    "total_duration": d.total_duration,
                    "turns_succeeded": d.turns_succeeded,
                    "turns_failed": d.turns_failed,
                    "turns": [
                        {
                            "turn_index": t.turn_index,
                            "success": t.success,
                            "send_success": t.send_success,
                            "send_duration": t.send_duration,
                            "content_verified": t.content_verified,
                            "verification_duration": t.verification_duration,
                            "retry_count": t.retry_count,
                            "error": t.error,
                        }
                        for t in d.turns
                    ],
                }
                for d in self.dialogues
            ],
        }

    @classmethod
    def from_dialogue_results(
        cls,
        results: list[DialogueResult],
        duration_seconds: float,
    ) -> OvernightSummary:
        """Build summary from a list of dialogue results.

        Args:
            results: List of completed DialogueResult instances.
            duration_seconds: Total elapsed time.

        Returns:
            OvernightSummary with aggregated metrics.
        """
        total_turns = 0
        turns_succeeded = 0
        turns_failed = 0
        total_retries = 0
        send_latencies: list[float] = []
        verification_latencies: list[float] = []

        for dr in results:
            for tr in dr.turns:
                total_turns += 1
                if tr.success:
                    turns_succeeded += 1
                else:
                    turns_failed += 1
                total_retries += tr.retry_count
                if tr.send_success:
                    send_latencies.append(tr.send_duration)
                if tr.content_verified:
                    verification_latencies.append(tr.verification_duration)

        avg_send = sum(send_latencies) / len(send_latencies) if send_latencies else 0.0
        avg_verify = (
            sum(verification_latencies) / len(verification_latencies)
            if verification_latencies
            else 0.0
        )

        return cls(
            total_dialogues=len(results),
            total_turns=total_turns,
            turns_succeeded=turns_succeeded,
            turns_failed=turns_failed,
            total_retries=total_retries,
            avg_send_latency=avg_send,
            avg_verification_latency=avg_verify,
            dialogues=results,
            duration_seconds=duration_seconds,
        )
