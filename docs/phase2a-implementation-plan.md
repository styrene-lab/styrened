# Phase 2a Implementation Plan: LXMF Feature Parity

## Overview

This plan implements critical LXMF-native features to achieve ~70% feature parity.

## Work Streams (Parallel Execution)

### Stream 1: Message Model Enhancement
**Files:** `src/styrened/models/messages.py`

Add new columns to Message model:
- `delivery_method` (str): "direct" | "propagated" | None
- `delivery_attempts` (int): Count of send attempts
- `lxmf_hash` (str): LXMF message hash for correlation
- `signature_valid` (bool | None): LXMF signature validation result
- `transport_encrypted` (bool | None): Transport encryption status

Update `MessageStatus` constants:
- Add SENDING = "sending"
- Add REJECTED = "rejected"
- Add CANCELLED = "cancelled"

### Stream 2: LXMF Service Propagation Support
**Files:** `src/styrened/services/lxmf_service.py`

Enhance `send_message()`:
- Add `delivery_method` parameter ("direct" | "propagated" | "auto")
- Implement propagation stamp request via `LXMF.LXMessage`
- Set `message.desired_method` before sending
- Capture `message.method` after delivery for tracking
- Return enhanced result with method used

Add new method `send_message_propagated()`:
- Dedicated propagation path for store-and-forward
- Request propagation stamp with configurable cost/timeout
- Fall back to direct if propagation unavailable

### Stream 3: Conversation Service Updates
**Files:** `src/styrened/services/conversation_service.py`

Update `save_outgoing_message()`:
- Accept `delivery_method`, `lxmf_hash` parameters
- Store in database

Update `MessageInfo` dataclass:
- Add `delivery_method` field
- Add `delivery_attempts` field
- Add `lxmf_hash` field
- Ensure `signature_valid` and `transport_encrypted` are populated

Update message retrieval to populate new fields.

### Stream 4: IPC Protocol & Handlers
**Files:** `src/styrened/ipc/protocol.py`, `src/styrened/ipc/messages.py`, `src/styrened/ipc/handlers.py`

Add delivery method to `CmdSendChatRequest`:
- New field: `delivery_method: str = "auto"`

Update `handle_cmd_send_chat`:
- Pass delivery_method to lxmf_service
- Return delivery_method used in response

Wire `EVENT_MESSAGE` subscription:
- Define `MessageEventPayload` dataclass
- Implement subscription handler registration
- Push events on message arrival and status changes

### Stream 5: Daemon Integration
**Files:** `src/styrened/daemon.py`

Update `_handle_chat_message_for_conversation`:
- Extract `signature_validated` from LXMF message
- Extract `transport_encrypted` from LXMF message
- Pass to conversation service

Update `_broadcast_chat_event`:
- Include delivery_method in event payload
- Include security fields in event payload

## Database Migration Strategy

Since this is pre-production, we'll use schema recreation:
1. Add new columns with defaults
2. SQLAlchemy `create_all()` handles additive changes
3. For production: would need Alembic migration

## Testing Strategy

Each stream produces unit tests for new functionality:
- Model tests for new columns
- Service tests for propagation logic
- Handler tests for new IPC fields
- Integration test for full flow

## Execution Order

Streams 1-4 can execute in parallel (no dependencies).
Stream 5 depends on Streams 1-4 completion.
Final consolidation validates all streams integrate correctly.
