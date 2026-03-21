---
id: daemon-ipc-contract-tests
title: Daemon IPC Contract Tests — Real Handler Coverage
status: decided
parent: tui-smoke-tests
tags: [ipc, daemon, testing, contract, integration]
open_questions: []
priority: 2
---

# Daemon IPC Contract Tests — Real Handler Coverage

## Overview

Test suite that starts a real StyreneDaemon (minimal config, no RNS/LXMF) and exercises all 39 IPC commands end-to-end through a real Unix socket. Verifies handler correctness: response shape matches what TUI consumers expect, error responses are well-formed, write commands produce observable state changes. This is the missing layer between unit tests (mock everything) and K8s scenario tests (full mesh, slow). Lives at tests/integration/test_ipc_contract.py. Target: all 39 commands have at least one real-daemon roundtrip test.

## Research

### Daemon startup without RNS/LXMF

StyreneDaemon can be started in a minimal mode that skips RNS initialization. The terminal integration tests already demonstrate this pattern:

```python
daemon = StyreneDaemon(minimal_config)
start_task = asyncio.create_task(daemon.start())
# wait for IPC socket to be ready
await asyncio.sleep(0.5)
```

For IPC contract tests, `minimal_config` needs:
- `reticulum.mode = "standalone"` with no interfaces (skips RNS bind)
- `rpc.enabled = False` (skips LXMF RPC setup)
- `lxmf.enabled = False` (skips LXMF router)
- Temp dir for socket path, db path, identity path

The IPC server (`ControlServer`) starts independently of RNS — it only needs the daemon object to exist. Handlers that require RNS (QUERY_DEVICES, CMD_EXEC) will return empty results or errors, which is still testable behavior.

Commands that work without RNS: PING, QUERY_STATUS, QUERY_CONFIG, GET_CORE_CONFIG, GET_NODES (empty), GET_HUB_STATUS, QUERY_IDENTITY, SAVE_CORE_CONFIG, QUERY_AUTO_REPLY, CMD_SET_AUTO_REPLY, CMD_SET_CONTACT, CMD_REMOVE_CONTACT, QUERY_CONTACTS, QUERY_CONVERSATIONS, CMD_ANNOUNCE (no-op), CMD_SET_IDENTITY.

Commands requiring RNS/LXMF (should return graceful error, not crash): CMD_SEND, CMD_EXEC, CMD_DEVICE_STATUS, QUERY_DEVICES (live), CMD_SEND_CHAT, DATALINK_*.

### Test fixture design

```python
@pytest.fixture(scope="module")
async def live_daemon():
    """Start a real StyreneDaemon with minimal config, yield a connected IPCBridge."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir = Path(tmpdir)
        config = CoreConfig(...)  # minimal, no RNS
        config.rpc.socket_path = str(tmpdir / "ctrl.sock")
        
        daemon = StyreneDaemon(config)
        task = asyncio.create_task(daemon.start())
        
        # Wait for socket
        for _ in range(20):
            if (tmpdir / "ctrl.sock").exists():
                break
            await asyncio.sleep(0.1)
        
        bridge = IPCBridge(config.rpc.socket_path)
        await bridge.connect()
        yield bridge
        
        await bridge.disconnect()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
```

Module-scoped fixture: daemon starts once per test file, all contract tests share the connection. Avoids per-test startup overhead (~500ms per daemon start).

Each command test asserts:
1. No exception raised
2. Response is not None / not ERROR type
3. Response fields match expected types (not just existence — `isinstance` checks)
4. Write-then-read roundtrip for stateful commands (SET_CONTACT → QUERY_CONTACTS)

### Command grouping and priority

Priority 1 — TUI critical path (what the operator sees on first launch):
- PING / PONG
- QUERY_STATUS → DaemonStatus shape (daemon_version, uptime, hub_connected, mesh_count, etc.)
- QUERY_IDENTITY → identity hash, display_name
- GET_CORE_CONFIG → full CoreConfig round-trip
- GET_NODES → list of MeshDevice (empty ok)
- QUERY_CONVERSATIONS → list (empty ok)
- QUERY_CONTACTS → list (empty ok)
- GET_HUB_STATUS → hub connection dict

Priority 2 — Write + verify roundtrip:
- CMD_SET_CONTACT → QUERY_CONTACTS (contact present, correct fields)
- CMD_REMOVE_CONTACT → QUERY_CONTACTS (contact absent)
- CMD_SET_AUTO_REPLY → QUERY_AUTO_REPLY
- SAVE_CORE_CONFIG → GET_CORE_CONFIG (persisted fields match)
- CMD_SET_IDENTITY → QUERY_IDENTITY

Priority 3 — Graceful failure without RNS:
- CMD_SEND → ERROR response (not crash)
- CMD_EXEC → ERROR response
- QUERY_DEVICES (live) → empty list or ERROR
- DATALINK_* → ERROR (no RNS transport)

Priority 4 — Subscription events:
- SUB_DEVICES → subscribe, receive initial snapshot, UNSUB
- SUB_ACTIVITY → subscribe, trigger an action, receive event

### Rust coverage (2026-03-20)

The Rust daemon now has substantial IPC contract coverage: 18 IPC server integration tests (server_integration.rs: ping_pong, query_status, query_identity, query_devices, unknown_message, concurrent_clients, stop_removes_socket, subscribe_and_event_push), 9 DaemonFacade contract tests (daemon_facade_contract.rs), 1 inbound worker integration test (worker_inbound.rs). 17 message types dispatched through dispatch.rs. Total 303 tests across styrened-rs + styrene-ipc-server. The Python daemon IPC contract tests in this design node may be partially superseded if the Python TUI connects to the Rust daemon for validation.

## Open Questions

*No open questions.*
