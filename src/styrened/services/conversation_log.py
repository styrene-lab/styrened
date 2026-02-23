"""Structured conversation logging for VictoriaLogs ingestion.

Prints JSON lines to stdout for Fluent Bit to parse (Merge_Log On)
and forward to VictoriaLogs as queryable fields.

Privacy: logs content_length, never content.
"""

import json
import time


def log_conversation_event(
    *,
    direction: str,
    source_hash: str,
    destination_hash: str,
    content_length: int,
    message_type: str = "chat",
    display_name: str | None = None,
    message_id: int | None = None,
) -> None:
    """Emit a structured JSON log line for a conversation event.

    Args:
        direction: "incoming", "outgoing", "delivery", or "failure"
        source_hash: LXMF source destination hash
        destination_hash: LXMF destination hash
        content_length: Length of message content (not content itself)
        message_type: Message type ("chat", "chatbot", etc.)
        display_name: Resolved display name of the peer, if available
        message_id: Database message ID, if available
    """
    record = {
        "event": "conversation",
        "direction": direction,
        "source_hash": source_hash,
        "destination_hash": destination_hash,
        "content_length": content_length,
        "message_type": message_type,
        "ts": time.time(),
    }
    if display_name is not None:
        record["display_name"] = display_name
    if message_id is not None:
        record["message_id"] = message_id
    print(json.dumps(record), flush=True)
