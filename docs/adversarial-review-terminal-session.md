# Adversarial Review: Terminal Session Implementation

**Date**: 2026-02-02  
**Reviewer**: Automated adversarial analysis  
**Scope**: Recent changes to terminal client/service for session establishment

## Executive Summary

The terminal session implementation is generally sound with good security practices in place. However, the adversarial review identified several issues ranging from **MEDIUM** to **LOW** severity that should be addressed.

## Issues Found

### MEDIUM Severity

#### 1. Blocking `time.sleep()` in async context during identity verification

**Location**: `src/styrened/terminal/service.py:1316-1318`

```python
if attempt < IDENTITY_VERIFICATION_RETRIES - 1:
    ...
    time.sleep(IDENTITY_VERIFICATION_DELAY_MS / 1000.0)
```

**Problem**: Using synchronous `time.sleep()` blocks the entire event loop. With 10 retries × 200ms delay = up to 2 seconds of blocking. During this time, no other async operations can proceed.

**Impact**: Denial of service vector. An attacker could initiate multiple Link connections without sending identity proofs, causing the server to block repeatedly.

**Recommendation**: Use `await asyncio.sleep()` instead, but note this requires making `_on_link_packet` async or deferring the identity verification to an async task.

---

#### 2. Race condition window in session-to-identity association

**Location**: `src/styrened/terminal/service.py:865-882`

```python
source_identity = self._resolve_identity_hash(lxmf_dest_hash)
if source_identity is None:
    ...
    # Fall back to LXMF destination hash (will fail identity verification but allows response)
    source_identity = lxmf_dest_hash
```

**Problem**: When identity resolution fails, the code falls back to using the LXMF destination hash as the source_identity. This creates a mismatch because:
- Session stores `source_identity = lxmf_dest_hash` 
- Link verification expects `link.get_remote_identity().hexhash` (identity hash)
- These will never match, causing the Link to be torn down

**Impact**: If NodeStore/discovered_devices lookup fails (e.g., first-time connection from unknown node), the terminal request appears to succeed (TERMINAL_ACCEPT sent) but the Link association will always fail identity verification.

**Recommendation**: Reject the request immediately if identity resolution fails, rather than proceeding with a value guaranteed to fail later:

```python
if source_identity is None:
    logger.warning(...)
    return create_terminal_reject(
        reason="Could not resolve client identity",
        code=6,
        request_id=request_id,
    )
```

---

#### 3. Client sets `_connected` before server confirms session association

**Location**: `src/styrened/terminal/client.py:254-255`

```python
# Signal that we're connected
self._connected.set()
logger.info("Terminal connection established")
```

**Problem**: The client signals "connected" immediately after sending session_id and version packets, before receiving any confirmation from the server. The server may still reject the session (identity mismatch, unknown session_id, etc.).

**Impact**: The `TerminalClient.connect()` method returns a session that appears connected but may have been rejected server-side. Client code may attempt to send data to a dead session.

**Recommendation**: Wait for server's `VersionInfo` response before setting `_connected`. The client already handles `VersionInfo` in `_on_link_packet`:

```python
elif isinstance(msg, VersionInfo):
    self.remote_version = msg
    logger.debug(f"Server version: {msg.version} ({msg.software})")
    # Mark as connected after version exchange
    self._connected.set()  # <-- This is duplicated, remove the one in _on_link_established
```

Remove `self._connected.set()` from `_on_link_established()`.

---

### LOW Severity

#### 4. Missing validation of `identity_hash` from TERMINAL_ACCEPT

**Location**: `src/styrened/terminal/client.py:521-527`

```python
future.set_result(
    {
        "accepted": True,
        "link_destination": payload["link_destination"],
        "identity_hash": payload.get("identity_hash"),  # Can be None or malformed
        "session_id": ...
    }
)
```

**Problem**: The client trusts `identity_hash` from the server response without validating it's a valid hex string of correct length. A malformed value would cause `bytes.fromhex()` to raise an exception during Link establishment.

**Recommendation**: Validate `identity_hash` format before using:

```python
identity_hash = payload.get("identity_hash")
if identity_hash and (len(identity_hash) != 64 or not all(c in '0123456789abcdef' for c in identity_hash.lower())):
    logger.warning(f"Invalid identity_hash format from server: {identity_hash[:20]}...")
    identity_hash = None
```

---

#### 5. `_send_link_packet` returns False silently on failure

**Location**: `src/styrened/terminal/service.py:395-404`

```python
def _send_link_packet(self, link: "RNS.Link", data: bytes) -> bool:
    ...
    if not link or link.status != RNS.Link.ACTIVE:
        return False  # Silent failure
```

**Problem**: Most callers don't check the return value, leading to silent data loss.

**Impact**: Output data or control messages (CommandExited, VersionInfo) may be silently dropped.

**Recommendation**: Either:
- Log warnings on failure, or
- Raise exceptions, or  
- Ensure all callers check return value

---

#### 6. Potential memory leak in `_pending_packets` during Link association

**Location**: `src/styrened/terminal/service.py:1281-1285`

```python
if not hasattr(link, "_pending_packets"):
    link._pending_packets = []
link._pending_packets.append((data, packet))
```

**Problem**: If identity verification fails and the Link is torn down, `_pending_packets` is never cleared. While the Link object will eventually be garbage collected, there's a window where memory accumulates.

**Recommendation**: Clear `_pending_packets` when Link is torn down:

```python
def _on_link_closed(self, link: "RNS.Link", reason: int) -> None:
    # Clear any pending packets
    if hasattr(link, "_pending_packets"):
        link._pending_packets.clear()
    ...
```

---

#### 7. `_handle_terminal_resize` and `_handle_terminal_signal` use LXMF source_hash directly

**Location**: `src/styrened/terminal/service.py:1633, 1678`

```python
source_identity = message.source_hash  # This is LXMF dest hash, not identity hash!
```

**Problem**: These handlers compare `message.source_hash` (LXMF destination hash) against `session.source_identity` (RNS identity hash). These are different hash types and will never match.

**Impact**: `TERMINAL_RESIZE` and `TERMINAL_SIGNAL` messages will always be ignored with "identity_mismatch" because the comparison is between different hash types.

**Recommendation**: Apply the same fix as `_handle_terminal_request` - resolve the LXMF destination hash to an identity hash:

```python
async def _handle_terminal_resize(self, message: "LXMFMessage", envelope: StyreneEnvelope) -> None:
    lxmf_dest_hash = message.source_hash
    source_identity = self._resolve_identity_hash(lxmf_dest_hash) or lxmf_dest_hash
    ...
```

---

#### 8. Missing `link_destination` validation

**Location**: `src/styrened/terminal/client.py:129`

```python
RNS.Transport.request_path(bytes.fromhex(self.link_destination))
```

**Problem**: No validation that `link_destination` is a valid hex string before calling `bytes.fromhex()`.

**Recommendation**: Validate in `TerminalClientSession` initialization or in `_handle_terminal_accept`.

---

## Security Observations (Positive)

1. **Good**: Signal whitelist with blocked dangerous signals (SIGKILL, SIGSTOP, SIGQUIT)
2. **Good**: Shell/command validation with configurable allowlists
3. **Good**: Rate limiting per identity and globally
4. **Good**: Session idle timeout with background cleanup
5. **Good**: Identity verification before session association
6. **Good**: Fail-closed default when no authorized identities configured

## Recommendations Summary

| Priority | Issue | Fix |
|----------|-------|-----|
| MEDIUM | Blocking `time.sleep()` | Convert to async or use async task |
| MEDIUM | Fallback to LXMF dest hash | Reject immediately on resolution failure |
| MEDIUM | Premature `_connected.set()` | Wait for server VersionInfo |
| LOW | Missing `identity_hash` validation | Add format validation |
| LOW | Silent packet send failures | Add logging/checking |
| LOW | `_pending_packets` memory | Clear on Link close |
| LOW | Wrong hash type in resize/signal | Resolve to identity hash |
| LOW | Missing `link_destination` validation | Add hex format check |

## Files Affected

- `src/styrened/terminal/client.py`
- `src/styrened/terminal/service.py`
