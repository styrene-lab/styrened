"""Unit tests for dialogue primitives.

Tests with mock harness (run_styrened returns canned CommandResult).
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from tests.dialogues.models import DialogueScript, DialogueTurn, TurnDirection
from tests.dialogues.primitives import (
    _extract_content,
    execute_dialogue,
    query_messages_via_cli,
    send_and_verify,
    verify_message_received,
)
from tests.dialogues.results import DialogueResult, OvernightSummary, TurnResult
from tests.harness.base import CommandResult, ExecutionBackend, NodeInfo


def _make_harness(
    nodes: list[NodeInfo] | None = None,
    run_styrened_side_effect=None,
    run_styrened_return=None,
) -> MagicMock:
    """Create a mock TestHarness."""
    harness = MagicMock()
    harness.get_nodes.return_value = nodes or []
    harness.backend = ExecutionBackend.SSH

    if run_styrened_side_effect:
        harness.run_styrened.side_effect = run_styrened_side_effect
    elif run_styrened_return:
        harness.run_styrened.return_value = run_styrened_return

    return harness


def _success_result(stdout: str = "") -> CommandResult:
    return CommandResult(
        success=True, stdout=stdout, stderr="", return_code=0,
        duration=0.1, backend=ExecutionBackend.SSH, target="test",
    )


def _failure_result(stderr: str = "error") -> CommandResult:
    return CommandResult(
        success=False, stdout="", stderr=stderr, return_code=1,
        duration=0.1, backend=ExecutionBackend.SSH, target="test",
    )


class TestExtractContent:
    """Tests for _extract_content JSON unwrapping."""

    def test_plain_text_passthrough(self):
        """Plain text content should pass through unchanged."""
        assert _extract_content("hello world") == "hello world"

    def test_json_wrapped_chat_content(self):
        """JSON-wrapped chat messages should extract nested content."""
        raw = json.dumps({"type": "chat", "protocol": "chat", "content": "actual message"})
        assert _extract_content(raw) == "actual message"

    def test_empty_string(self):
        """Empty string should return empty string."""
        assert _extract_content("") == ""

    def test_malformed_json(self):
        """Malformed JSON should return raw string."""
        assert _extract_content("{not valid json") == "{not valid json"

    def test_json_without_content_key(self):
        """JSON without 'content' key should return raw string."""
        raw = json.dumps({"type": "chat", "data": "something"})
        assert _extract_content(raw) == raw


class TestQueryMessagesViaCli:
    """Tests for query_messages_via_cli."""

    def test_parses_json_output(self):
        """Should parse JSON message list from CLI output."""
        messages = [
            {"id": 1, "content": "Hello", "timestamp": 1700000000.0},
            {"id": 2, "content": "World", "timestamp": 1700000001.0},
        ]
        stdout = f"2 message(s) with abcd1234...:\n\n{json.dumps(messages)}"
        harness = _make_harness(run_styrened_return=_success_result(stdout))

        result = query_messages_via_cli(harness, "node-a", "abcd1234")
        assert len(result) == 2
        assert result[0]["content"] == "Hello"
        assert result[1]["content"] == "World"

    def test_handles_empty_output(self):
        """Should return empty list for no messages."""
        harness = _make_harness(run_styrened_return=_success_result("No messages"))

        result = query_messages_via_cli(harness, "node-a", "abcd1234")
        assert result == []

    def test_handles_failure(self):
        """Should return empty list on command failure."""
        harness = _make_harness(run_styrened_return=_failure_result())

        result = query_messages_via_cli(harness, "node-a", "abcd1234")
        assert result == []

    def test_handles_malformed_json(self):
        """Should return empty list on malformed JSON."""
        harness = _make_harness(run_styrened_return=_success_result("[{invalid json"))

        result = query_messages_via_cli(harness, "node-a", "abcd1234")
        assert result == []


class TestVerifyMessageReceived:
    """Tests for verify_message_received."""

    def test_finds_message_on_first_poll(self):
        """Should find message immediately if present."""
        messages = [{"content": "hello", "timestamp": time.time()}]
        stdout = json.dumps(messages)
        harness = _make_harness(run_styrened_return=_success_result(stdout))

        found, elapsed = verify_message_received(
            harness, "receiver", "sender_hash", "hello",
            reference_timestamp=time.time() - 10,
            timeout=5.0, poll_interval=0.1,
        )
        assert found is True
        assert elapsed < 2.0

    def test_finds_message_after_retries(self):
        """Should find message after polling."""
        call_count = 0
        ref_ts = time.time()

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return _success_result("[]")
            messages = [{"content": "hello", "timestamp": ref_ts + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        found, elapsed = verify_message_received(
            harness, "receiver", "sender_hash", "hello",
            reference_timestamp=ref_ts,
            timeout=10.0, poll_interval=0.1,
        )
        assert found is True
        assert call_count >= 3

    def test_times_out(self):
        """Should return False on timeout."""
        harness = _make_harness(run_styrened_return=_success_result("[]"))

        found, elapsed = verify_message_received(
            harness, "receiver", "sender_hash", "hello",
            reference_timestamp=time.time(),
            timeout=0.5, poll_interval=0.1,
        )
        assert found is False
        assert elapsed >= 0.5

    def test_finds_json_wrapped_content(self):
        """Should match content inside JSON-wrapped chat messages."""
        wrapped = json.dumps({"type": "chat", "protocol": "chat", "content": "hello"})
        messages = [{"content": wrapped, "timestamp": time.time()}]
        stdout = json.dumps(messages)
        harness = _make_harness(run_styrened_return=_success_result(stdout))

        found, elapsed = verify_message_received(
            harness, "receiver", "sender_hash", "hello",
            reference_timestamp=time.time() - 10,
            timeout=5.0, poll_interval=0.1,
        )
        assert found is True

    def test_ignores_old_messages(self):
        """Should not match messages with timestamp before reference."""
        old_timestamp = time.time() - 100
        messages = [{"content": "hello", "timestamp": old_timestamp}]
        harness = _make_harness(
            run_styrened_return=_success_result(json.dumps(messages))
        )

        found, elapsed = verify_message_received(
            harness, "receiver", "sender_hash", "hello",
            reference_timestamp=time.time(),
            timeout=0.5, poll_interval=0.1,
        )
        assert found is False


class TestSendAndVerify:
    """Tests for send_and_verify."""

    def test_success_metrics(self):
        """Should track metrics on successful send+verify."""
        ref_ts = time.time()
        call_count = 0

        def side_effect(node, cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "send " in cmd:
                return _success_result("Message sent successfully")
            # messages query
            messages = [{"content": "hello", "timestamp": ref_ts + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=10.0, verification_timeout=5.0,
        )

        assert result.success is True
        assert result.send_success is True
        assert result.content_verified is True
        assert result.send_duration > 0
        assert result.error is None

    def test_send_failure(self):
        """Should track failure when send fails."""
        harness = _make_harness(run_styrened_return=_failure_result("No path"))

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=1.0,
        )

        assert result.success is False
        assert result.send_success is False
        assert result.content_verified is False
        assert "Send failed" in result.error

    def test_verification_failure(self):
        """Should track failure when verification times out."""
        call_count = 0

        def side_effect(node, cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "send " in cmd:
                return _success_result("Message sent successfully")
            return _success_result("[]")

        harness = _make_harness(run_styrened_side_effect=side_effect)

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=0.5,
        )

        assert result.success is False
        assert result.send_success is True
        assert result.content_verified is False
        assert "timed out" in result.error.lower()


class TestExecuteDialogue:
    """Tests for execute_dialogue."""

    def _make_script(self, turns: int = 2) -> DialogueScript:
        """Create a simple dialogue script."""
        turn_list = []
        for i in range(turns):
            direction = TurnDirection.A_TO_B if i % 2 == 0 else TurnDirection.B_TO_A
            turn_list.append(
                DialogueTurn(
                    direction=direction,
                    content=f"turn-{i}",
                    delivery_timeout=5.0,
                    verification_timeout=1.0,
                )
            )
        return DialogueScript(
            name="test_script",
            description="Test",
            turns=turn_list,
            setup_delay=0.0,
            inter_turn_delay=0.0,
        )

    def test_all_turns_succeed(self):
        """Should report success when all turns pass."""
        ref_ts = time.time()

        def side_effect(node, cmd, **kwargs):
            if "send " in cmd:
                return _success_result("Message sent successfully")
            # Return all possible turn messages so verification can match any
            messages = [
                {"content": f"turn-{i}", "timestamp": ref_ts + 1}
                for i in range(10)
            ]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_script(turns=2)

        result = execute_dialogue(
            harness, script, "node-a", "node-b",
            "id_a", "id_b", "lxmf_a", "lxmf_b",
        )

        assert result.script_name == "test_script"
        assert result.turns_succeeded == 2
        assert result.turns_failed == 0
        assert result.success is True
        assert len(result.turns) == 2

    def test_continues_after_failure(self):
        """Failed turns should not stop execution."""
        call_count = 0

        def side_effect(node, cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "send " in cmd:
                # First send fails, second succeeds
                if call_count <= 1:
                    return _failure_result("No path")
                return _success_result("Message sent successfully")
            # Verification always returns matching message
            messages = [{"content": "turn-1", "timestamp": time.time() + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_script(turns=2)

        result = execute_dialogue(
            harness, script, "node-a", "node-b",
            "id_a", "id_b", "lxmf_a", "lxmf_b",
        )

        # First turn fails, second succeeds
        assert len(result.turns) == 2
        assert result.turns[0].success is False
        assert result.turns[1].success is True
        assert result.turns_succeeded == 1
        assert result.turns_failed == 1
        assert result.success is False

    def test_calculates_total_duration(self):
        """Should calculate total duration across all turns."""
        harness = _make_harness(run_styrened_return=_failure_result())
        script = self._make_script(turns=1)

        result = execute_dialogue(
            harness, script, "node-a", "node-b",
            "id_a", "id_b", "lxmf_a", "lxmf_b",
        )

        assert result.total_duration > 0


class TestOvernightSummary:
    """Tests for OvernightSummary aggregation."""

    def test_from_dialogue_results(self):
        """Should aggregate metrics from multiple dialogue results."""
        results = [
            DialogueResult(
                script_name="script_a",
                success=True,
                turns=[
                    TurnResult(0, True, True, 1.0, True, 0.5),
                    TurnResult(1, True, True, 1.5, True, 0.8),
                ],
                total_duration=5.0,
                turns_succeeded=2,
                turns_failed=0,
            ),
            DialogueResult(
                script_name="script_b",
                success=False,
                turns=[
                    TurnResult(0, True, True, 2.0, True, 1.0),
                    TurnResult(1, False, True, 1.0, False, 60.0, retry_count=3, error="timeout"),
                ],
                total_duration=65.0,
                turns_succeeded=1,
                turns_failed=1,
            ),
        ]

        summary = OvernightSummary.from_dialogue_results(results, 70.0)

        assert summary.total_dialogues == 2
        assert summary.total_turns == 4
        assert summary.turns_succeeded == 3
        assert summary.turns_failed == 1
        assert summary.total_retries == 3
        assert summary.duration_seconds == 70.0
        # avg_send_latency: (1.0 + 1.5 + 2.0 + 1.0) / 4 = 1.375
        assert abs(summary.avg_send_latency - 1.375) < 0.01
        # avg_verification_latency: (0.5 + 0.8 + 1.0) / 3 = 0.7667
        assert abs(summary.avg_verification_latency - 0.7667) < 0.01

    def test_to_dict(self):
        """to_dict should produce JSON-serializable output."""
        summary = OvernightSummary(
            total_dialogues=1,
            total_turns=2,
            turns_succeeded=1,
            turns_failed=1,
            total_retries=0,
            avg_send_latency=1.0,
            avg_verification_latency=0.5,
            dialogues=[],
            duration_seconds=10.0,
        )

        d = summary.to_dict()
        assert d["total_dialogues"] == 1
        assert d["total_turns"] == 2
        # Ensure it's JSON-serializable
        import json
        json.dumps(d)

    def test_empty_results(self):
        """Should handle empty result list."""
        summary = OvernightSummary.from_dialogue_results([], 0.0)

        assert summary.total_dialogues == 0
        assert summary.total_turns == 0
        assert summary.avg_send_latency == 0.0
        assert summary.avg_verification_latency == 0.0
