"""Unit tests for dialogue primitives.

Tests with mock harness (run_styrened returns canned CommandResult).
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

from tests.dialogues.models import (
    DialogueScript,
    DialogueTurn,
    MultiNodeDialogueScript,
    MultiNodeDialogueTurn,
    TurnDirection,
)
from tests.dialogues.primitives import (
    _extract_content,
    collect_version_info,
    ensure_daemons_healthy,
    execute_dialogue,
    execute_multi_node_dialogue,
    execute_multi_node_dialogue_turn,
    query_messages_via_cli,
    resolve_multi_node_lxmf_hashes,
    send_and_verify,
    stamp_content,
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


class TestStampContent:
    """Tests for stamp_content dynamic content stamping."""

    def test_format(self):
        """Stamped content should contain cycle_id, turn_index, and timestamp."""
        result = stamp_content("hello", "c0001", 3)
        assert result.startswith("hello|cid=c0001|tidx=3|ts=")
        # Timestamp should be numeric
        ts_part = result.split("|ts=")[1]
        assert ts_part.isdigit()

    def test_uniqueness(self):
        """Two calls should produce different timestamps."""
        a = stamp_content("test", "c0001", 0)
        # Tiny sleep to ensure different ms timestamp
        time.sleep(0.002)
        b = stamp_content("test", "c0001", 0)
        assert a != b

    def test_template_preservation(self):
        """Original template should be preserved as prefix."""
        result = stamp_content("original content", "c0042", 7)
        assert result.startswith("original content|")

    def test_different_cycle_ids(self):
        """Different cycle IDs should produce different stamps."""
        a = stamp_content("test", "c0001", 0)
        b = stamp_content("test", "c0002", 0)
        assert "|cid=c0001|" in a
        assert "|cid=c0002|" in b


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
        assert result.started_at > 0

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


class TestSendAndVerifyRetries:
    """Tests for send_and_verify retry logic."""

    def test_retry_on_send_failure(self):
        """Should retry when send fails and succeed on later attempt."""
        call_count = 0
        ref_ts = time.time()

        def side_effect(node, cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "send " in cmd:
                if call_count <= 1:
                    return _failure_result("No path")
                return _success_result("Sent")
            messages = [{"content": "hello", "timestamp": ref_ts + 10}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=5.0,
            max_retries=2,
        )

        assert result.success is True
        assert result.retry_count == 1

    def test_retry_on_verify_failure(self):
        """Should retry when verification fails and succeed on later attempt."""
        attempt = 0
        ref_ts = time.time()

        def side_effect(node, cmd, **kwargs):
            nonlocal attempt
            if "send " in cmd:
                attempt += 1
                return _success_result("Sent")
            if attempt < 2:
                return _success_result("[]")
            messages = [{"content": "hello", "timestamp": ref_ts + 10}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=0.3,
            max_retries=2,
        )

        assert result.success is True
        assert result.retry_count >= 1

    def test_exhausted_retries(self):
        """Should return failure after exhausting all retries."""
        harness = _make_harness(run_styrened_return=_failure_result("No path"))

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=0.3,
            max_retries=1,
        )

        assert result.success is False
        assert result.retry_count == 1

    def test_default_no_retry(self):
        """Default max_retries=0 should not retry."""
        harness = _make_harness(run_styrened_return=_failure_result("No path"))

        result = send_and_verify(
            harness, "sender", "receiver", "recv_id", "sender_lxmf",
            "hello", turn_index=0, delivery_timeout=5.0, verification_timeout=0.3,
        )

        assert result.success is False
        assert result.retry_count == 0


class TestEnsureDaemonsHealthy:
    """Tests for ensure_daemons_healthy."""

    def test_all_healthy(self):
        """Should report all healthy when daemons are running."""
        harness = MagicMock()
        harness.is_daemon_running.return_value = True

        result = ensure_daemons_healthy(harness, ["node-a", "node-b"])

        assert result.all_healthy is True
        assert result.statuses == {"node-a": True, "node-b": True}
        assert result.restarted == set()
        harness.start_daemon.assert_not_called()

    def test_restart_recovery(self):
        """Should restart a failed daemon and report recovery."""
        harness = MagicMock()
        harness.is_daemon_running.side_effect = [False, True]  # node-a down, node-b up
        harness.start_daemon.return_value = _success_result()
        harness.wait_for_daemon.return_value = True

        result = ensure_daemons_healthy(harness, ["node-a", "node-b"])

        assert result.all_healthy is True
        assert result.statuses == {"node-a": True, "node-b": True}
        assert result.restarted == {"node-a"}

    def test_restart_failure(self):
        """Should report unhealthy when restart fails."""
        harness = MagicMock()
        harness.is_daemon_running.return_value = False
        harness.start_daemon.return_value = _failure_result("systemctl error")

        result = ensure_daemons_healthy(harness, ["node-a"])

        assert result.all_healthy is False
        assert result.statuses == {"node-a": False}
        assert result.restarted == set()

    def test_restart_not_responsive(self):
        """Should report unhealthy when daemon starts but doesn't respond."""
        harness = MagicMock()
        harness.is_daemon_running.return_value = False
        harness.start_daemon.return_value = _success_result()
        harness.wait_for_daemon.return_value = False

        result = ensure_daemons_healthy(harness, ["node-a"])

        assert result.all_healthy is False
        assert result.statuses == {"node-a": False}
        assert result.restarted == set()


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

    def test_content_stamping(self):
        """Content should be stamped when cycle_id is provided."""
        sent_contents = []

        def side_effect(node, cmd, **kwargs):
            if "send " in cmd:
                # Extract content from command (between quotes)
                content = cmd.split("'")[1] if "'" in cmd else ""
                sent_contents.append(content)
                return _success_result("Sent")
            return _success_result("[]")

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_script(turns=1)

        execute_dialogue(
            harness, script, "node-a", "node-b",
            "id_a", "id_b", "lxmf_a", "lxmf_b",
            cycle_id="c0001",
        )

        assert len(sent_contents) == 1
        assert "|cid=c0001|" in sent_contents[0]
        assert "|tidx=0|" in sent_contents[0]

    def test_temporal_metadata(self):
        """DialogueResult should have temporal metadata when cycle_index is set."""
        harness = _make_harness(run_styrened_return=_failure_result())
        script = self._make_script(turns=1)

        before = time.time()
        result = execute_dialogue(
            harness, script, "node-a", "node-b",
            "id_a", "id_b", "lxmf_a", "lxmf_b",
            cycle_index=5,
        )
        after = time.time()

        assert result.cycle_index == 5
        assert before <= result.started_at <= after
        assert result.started_at <= result.completed_at <= after


class TestExecuteMultiNodeDialogueTurn:
    """Tests for execute_multi_node_dialogue_turn."""

    def test_role_mapping(self):
        """Should map role names to actual nodes and use correct LXMF hashes."""
        ref_ts = time.time()

        def side_effect(node, cmd, **kwargs):
            if "send " in cmd:
                return _success_result("Sent")
            messages = [{"content": "hello", "timestamp": ref_ts + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        turn = MultiNodeDialogueTurn(sender="A", receiver="B", content="hello")
        role_to_node = {"A": "styrene-node", "B": "t100ta", "C": "minigmk"}
        node_identities = {
            "styrene-node": "id_styrene",
            "t100ta": "id_t100ta",
            "minigmk": "id_minigmk",
        }
        lxmf_hashes = {
            ("styrene-node", "t100ta"): "lxmf_s_to_t",
            ("t100ta", "styrene-node"): "lxmf_t_to_s",
            ("styrene-node", "minigmk"): "lxmf_s_to_m",
            ("minigmk", "styrene-node"): "lxmf_m_to_s",
            ("t100ta", "minigmk"): "lxmf_t_to_m",
            ("minigmk", "t100ta"): "lxmf_m_to_t",
        }

        result = execute_multi_node_dialogue_turn(
            harness, turn, 0, role_to_node, node_identities, lxmf_hashes,
        )

        assert result.success is True
        # Sender should be styrene-node (role A), receiver should be t100ta (role B)
        # The send command should target t100ta's identity
        send_call = harness.run_styrened.call_args_list[0]
        assert send_call[0][0] == "styrene-node"
        assert "id_t100ta" in send_call[0][1]

    def test_correct_lxmf_hash_selection(self):
        """Should use receiver's view of sender for LXMF hash lookup."""
        ref_ts = time.time()
        captured_calls = []

        def side_effect(node, cmd, **kwargs):
            captured_calls.append((node, cmd))
            if "send " in cmd:
                return _success_result("Sent")
            messages = [{"content": "test", "timestamp": ref_ts + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)

        turn = MultiNodeDialogueTurn(sender="B", receiver="C", content="test")
        role_to_node = {"A": "n1", "B": "n2", "C": "n3"}
        node_identities = {"n1": "id1", "n2": "id2", "n3": "id3"}
        lxmf_hashes = {
            ("n1", "n2"): "h12", ("n2", "n1"): "h21",
            ("n1", "n3"): "h13", ("n3", "n1"): "h31",
            ("n2", "n3"): "h23", ("n3", "n2"): "h32",
        }

        execute_multi_node_dialogue_turn(
            harness, turn, 0, role_to_node, node_identities, lxmf_hashes,
        )

        # Sender is n2 (B), receiver is n3 (C)
        # send command goes to n2, targeting n3's identity (id3)
        assert captured_calls[0][0] == "n2"
        assert "id3" in captured_calls[0][1]


class TestExecuteMultiNodeDialogue:
    """Tests for execute_multi_node_dialogue."""

    def _make_multi_script(self) -> MultiNodeDialogueScript:
        return MultiNodeDialogueScript(
            name="multi_test",
            description="Test",
            node_roles=["A", "B"],
            turns=[
                MultiNodeDialogueTurn(sender="A", receiver="B", content="hello",
                                      delivery_timeout=5.0, verification_timeout=1.0),
                MultiNodeDialogueTurn(sender="B", receiver="A", content="world",
                                      delivery_timeout=5.0, verification_timeout=1.0),
            ],
            setup_delay=0.0,
            inter_turn_delay=0.0,
        )

    def test_all_succeed(self):
        """Should report success when all turns pass."""
        ref_ts = time.time()

        def side_effect(node, cmd, **kwargs):
            if "send " in cmd:
                return _success_result("Sent")
            messages = [
                {"content": "hello", "timestamp": ref_ts + 1},
                {"content": "world", "timestamp": ref_ts + 1},
            ]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_multi_script()
        role_to_node = {"A": "n1", "B": "n2"}
        node_identities = {"n1": "id1", "n2": "id2"}
        lxmf_hashes = {
            ("n1", "n2"): "h12", ("n2", "n1"): "h21",
        }

        result = execute_multi_node_dialogue(
            harness, script, role_to_node, node_identities, lxmf_hashes,
        )

        assert result.success is True
        assert result.turns_succeeded == 2
        assert len(result.turns) == 2

    def test_continues_after_failure(self):
        """Failed turns should not stop execution."""
        call_count = 0

        def side_effect(node, cmd, **kwargs):
            nonlocal call_count
            call_count += 1
            if "send " in cmd:
                if call_count <= 1:
                    return _failure_result("fail")
                return _success_result("Sent")
            messages = [{"content": "world", "timestamp": time.time() + 1}]
            return _success_result(json.dumps(messages))

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_multi_script()
        role_to_node = {"A": "n1", "B": "n2"}
        node_identities = {"n1": "id1", "n2": "id2"}
        lxmf_hashes = {("n1", "n2"): "h12", ("n2", "n1"): "h21"}

        result = execute_multi_node_dialogue(
            harness, script, role_to_node, node_identities, lxmf_hashes,
        )

        assert len(result.turns) == 2
        assert result.turns[0].success is False
        assert result.turns[1].success is True

    def test_content_stamping(self):
        """Content should be stamped when cycle_id is provided."""
        sent_contents = []

        def side_effect(node, cmd, **kwargs):
            if "send " in cmd:
                content = cmd.split("'")[1] if "'" in cmd else ""
                sent_contents.append(content)
                return _success_result("Sent")
            return _success_result("[]")

        harness = _make_harness(run_styrened_side_effect=side_effect)
        script = self._make_multi_script()
        role_to_node = {"A": "n1", "B": "n2"}
        node_identities = {"n1": "id1", "n2": "id2"}
        lxmf_hashes = {("n1", "n2"): "h12", ("n2", "n1"): "h21"}

        execute_multi_node_dialogue(
            harness, script, role_to_node, node_identities, lxmf_hashes,
            cycle_id="m0001",
        )

        assert len(sent_contents) == 2
        assert "|cid=m0001|tidx=0|" in sent_contents[0]
        assert "|cid=m0001|tidx=1|" in sent_contents[1]

    def test_temporal_metadata(self):
        """DialogueResult should have temporal metadata."""
        harness = _make_harness(run_styrened_return=_failure_result())
        script = self._make_multi_script()
        role_to_node = {"A": "n1", "B": "n2"}
        node_identities = {"n1": "id1", "n2": "id2"}
        lxmf_hashes = {("n1", "n2"): "h12", ("n2", "n1"): "h21"}

        before = time.time()
        result = execute_multi_node_dialogue(
            harness, script, role_to_node, node_identities, lxmf_hashes,
            cycle_index=3,
        )
        after = time.time()

        assert result.cycle_index == 3
        assert before <= result.started_at <= after
        assert result.started_at <= result.completed_at <= after


class TestResolveMultiNodeLxmfHashes:
    """Tests for resolve_multi_node_lxmf_hashes."""

    def test_resolves_all_pairs(self):
        """3 nodes should produce 6 directional hashes."""
        nodes_info = [
            NodeInfo("n1", "addr1", "id_aaaa", ExecutionBackend.SSH),
            NodeInfo("n2", "addr2", "id_bbbb", ExecutionBackend.SSH),
            NodeInfo("n3", "addr3", "id_cccc", ExecutionBackend.SSH),
        ]

        def discover_side_effect(node, wait_seconds=10):
            # Return all other nodes
            all_devices = {
                "id_aaaa": {"identity_hash": "id_aaaa", "lxmf_destination_hash": "lxmf_a"},
                "id_bbbb": {"identity_hash": "id_bbbb", "lxmf_destination_hash": "lxmf_b"},
                "id_cccc": {"identity_hash": "id_cccc", "lxmf_destination_hash": "lxmf_c"},
            }
            return [d for k, d in all_devices.items()]

        harness = MagicMock()
        harness.get_nodes.return_value = nodes_info
        harness.discover_devices.side_effect = discover_side_effect

        result = resolve_multi_node_lxmf_hashes(harness, ["n1", "n2", "n3"], wait=5)

        # 3 nodes = 6 directional pairs
        assert len(result) == 6
        assert ("n1", "n2") in result
        assert ("n2", "n1") in result
        assert ("n1", "n3") in result
        assert ("n3", "n1") in result
        assert ("n2", "n3") in result
        assert ("n3", "n2") in result

    def test_raises_on_missing_identity(self):
        """Should raise RuntimeError if a node has no identity_hash."""
        nodes_info = [
            NodeInfo("n1", "addr1", "id_aaaa", ExecutionBackend.SSH),
            NodeInfo("n2", "addr2", None, ExecutionBackend.SSH),
        ]
        harness = MagicMock()
        harness.get_nodes.return_value = nodes_info

        import pytest
        with pytest.raises(RuntimeError, match="Identity hash not configured"):
            resolve_multi_node_lxmf_hashes(harness, ["n1", "n2"])


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

    def test_from_dialogue_results_cycle_success_rates(self):
        """Should compute per-cycle success rates from cycle_index."""
        results = [
            DialogueResult(
                script_name="s1", success=True,
                turns=[TurnResult(0, True, True, 1.0, True, 0.5)],
                total_duration=1.0, turns_succeeded=1, turns_failed=0,
                cycle_index=1,
            ),
            DialogueResult(
                script_name="s2", success=True,
                turns=[TurnResult(0, True, True, 1.0, True, 0.5)],
                total_duration=1.0, turns_succeeded=1, turns_failed=0,
                cycle_index=1,
            ),
            DialogueResult(
                script_name="s1", success=False,
                turns=[
                    TurnResult(0, True, True, 1.0, True, 0.5),
                    TurnResult(1, False, True, 1.0, False, 60.0),
                ],
                total_duration=61.0, turns_succeeded=1, turns_failed=1,
                cycle_index=2,
            ),
        ]

        summary = OvernightSummary.from_dialogue_results(results, 100.0)

        # Cycle 1: 2/2 = 1.0, Cycle 2: 1/2 = 0.5
        assert len(summary.cycle_success_rates) == 2
        assert summary.cycle_success_rates[0] == 1.0
        assert summary.cycle_success_rates[1] == 0.5

    def test_to_dict(self):
        """to_dict should produce JSON-serializable output with all fields."""
        vi = {"styrened_versions": {"n1": "0.4.0"}, "test_sha": "abc1234", "test_branch": "main"}
        summary = OvernightSummary(
            total_dialogues=1,
            total_turns=2,
            turns_succeeded=1,
            turns_failed=1,
            total_retries=0,
            avg_send_latency=1.0,
            avg_verification_latency=0.5,
            dialogues=[
                DialogueResult(
                    script_name="s1", success=True,
                    turns=[
                        TurnResult(0, True, True, 1.0, True, 0.5, started_at=1000.0),
                    ],
                    total_duration=1.0, turns_succeeded=1, turns_failed=0,
                    cycle_index=1, started_at=1000.0, completed_at=1001.0,
                ),
            ],
            duration_seconds=10.0,
            cycle_success_rates=[1.0, 0.8],
            version_info=vi,
        )

        d = summary.to_dict()
        assert d["total_dialogues"] == 1
        assert d["total_turns"] == 2
        assert d["cycle_success_rates"] == [1.0, 0.8]
        assert d["version_info"] == vi
        # Check dialogue-level temporal fields
        assert d["dialogues"][0]["cycle_index"] == 1
        assert d["dialogues"][0]["started_at"] == 1000.0
        assert d["dialogues"][0]["completed_at"] == 1001.0
        # Check turn-level started_at
        assert d["dialogues"][0]["turns"][0]["started_at"] == 1000.0
        # Ensure it's JSON-serializable
        json.dumps(d)

    def test_from_dialogue_results_with_version_info(self):
        """version_info kwarg should pass through to the summary."""
        vi = {"styrened_versions": {"n1": "0.4.0"}, "test_sha": "abc", "test_branch": "main"}
        summary = OvernightSummary.from_dialogue_results([], 0.0, version_info=vi)
        assert summary.version_info == vi

    def test_to_dict_version_info_empty_by_default(self):
        """version_info should default to empty dict in to_dict output."""
        summary = OvernightSummary.from_dialogue_results([], 0.0)
        d = summary.to_dict()
        assert d["version_info"] == {}

    def test_empty_results(self):
        """Should handle empty result list."""
        summary = OvernightSummary.from_dialogue_results([], 0.0)

        assert summary.total_dialogues == 0
        assert summary.total_turns == 0
        assert summary.avg_send_latency == 0.0
        assert summary.avg_verification_latency == 0.0
        assert summary.cycle_success_rates == []


class TestCollectVersionInfo:
    """Tests for collect_version_info."""

    def test_collects_versions_from_nodes(self):
        """Should call get_version on each node and return dict."""
        harness = MagicMock()
        harness.get_version.side_effect = lambda node: {"n1": "0.4.0", "n2": "0.3.9"}[node]

        result = collect_version_info(harness, ["n1", "n2"])

        assert result["styrened_versions"] == {"n1": "0.4.0", "n2": "0.3.9"}
        assert harness.get_version.call_count == 2

    def test_handles_none_version(self):
        """Should include None for nodes where get_version returns None."""
        harness = MagicMock()
        harness.get_version.return_value = None

        result = collect_version_info(harness, ["n1"])

        assert result["styrened_versions"] == {"n1": None}

    def test_git_info_populated(self):
        """Should populate test_sha and test_branch from git."""
        harness = MagicMock()
        harness.get_version.return_value = "0.4.0"

        result = collect_version_info(harness, ["n1"])

        # We're in a git repo, so these should be non-empty strings
        assert isinstance(result["test_sha"], str)
        assert isinstance(result["test_branch"], str)
        assert len(result["test_sha"]) > 0
        assert len(result["test_branch"]) > 0

    def test_dict_structure(self):
        """Should return dict with expected top-level keys."""
        harness = MagicMock()
        harness.get_version.return_value = "0.4.0"

        result = collect_version_info(harness, ["n1"])

        assert "styrened_versions" in result
        assert "test_sha" in result
        assert "test_branch" in result
