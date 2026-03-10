# block-store-canonicalization — Tasks

## Group 1: Database schema (no external deps)

**Label:** `schema`
**Files:** `src/styrened/models/messages.py`
**Tests:** `tests/unit/test_block_store_schema.py` (new)

### Tasks

- [ ] 1.1 Add `peer_blocks` table to `init_db()`:
  - columns: `identity_hash TEXT PRIMARY KEY`, `lxmf_dest_hash TEXT`, `alias TEXT`,
    `blocked_at REAL NOT NULL`, `blocked_by TEXT NOT NULL DEFAULT 'operator'`, `notes TEXT`
  - index: `CREATE INDEX IF NOT EXISTS idx_peer_blocks_lxmf ON peer_blocks(lxmf_dest_hash)`
  - idempotent (IF NOT EXISTS)

- [ ] 1.2 Migrate `contacts` table PK from `peer_hash` to `identity_hash`:
  - Create `contacts_new` with `identity_hash TEXT PRIMARY KEY`, `lxmf_dest_hash TEXT` (replaces `peer_hash`),
    plus all existing columns (`alias`, `notes`, `blocked`, `blocked_at`, `created_at`, `updated_at`)
  - `INSERT INTO contacts_new SELECT peer_hash AS identity_hash, NULL AS lxmf_dest_hash, ...`
  - `DROP TABLE contacts` → `ALTER TABLE contacts_new RENAME TO contacts`
  - Run as schema migration in `init_db()` when old schema detected (presence of `peer_hash` column)

- [ ] 1.3 Add startup backfill: for each contacts row, attempt
  `NodeStore.get_identity_for_lxmf_destination(identity_hash)` — if resolved and different,
  update contacts row `identity_hash` and set `lxmf_dest_hash` to old value.
  Log warning for rows that couldn't be resolved.

- [ ] 1.4 Write unit tests:
  - clean DB gets `peer_blocks` and new contacts schema
  - existing contacts DB with `peer_hash` PK is migrated correctly
  - NodeStore backfill updates identity_hash when mapping found
  - backfill falls through gracefully when NodeStore has no mapping

---

## Group 2: LXMFService block operations (depends on Group 1)

**Label:** `block-ops`
**Files:** `src/styrened/services/lxmf_service.py`
**Tests:** `tests/unit/test_block_store.py` (new, replaces/extends `test_blocklist.py`)

### Tasks

- [ ] 2.1 Redesign `block_peer(identity_hash, lxmf_dest_hash=None, alias=None) -> bool`:
  - Write order: (1) peer_blocks upsert, (2) `_rbac_policy.block(identity_hash)`, (3) contacts.blocked=1 best-effort
  - If step 1 raises, return False and do NOT update RBAC (no partial state)
  - Remove old `peer_hash` parameter entirely

- [ ] 2.2 Redesign `unblock_peer(identity_hash) -> bool`:
  - Delete from peer_blocks, remove from RBAC.blocked, set contacts.blocked=0
  - Return False if identity_hash not in peer_blocks (was never blocked)

- [ ] 2.3 Add `_load_peer_blocks() -> list[str]`:
  - Reads `peer_blocks` table, returns list of identity_hash strings
  - Used by _seed_blocks_to_rbac and get_blocked_peers

- [ ] 2.4 Reinstate `_seed_blocks_to_rbac()`:
  - Reads peer_blocks via `_load_peer_blocks()`
  - Merges into `self._rbac_policy.blocked` (does not duplicate YAML entries)
  - Calls `invalidate_cache()` once after all entries added
  - Called from `initialize()` after RBAC policy is set

- [ ] 2.5 Update `get_blocked_peers() -> list[dict]`:
  - Reads from peer_blocks table (not contacts)
  - Returns `[{"identity_hash": ..., "lxmf_dest_hash": ..., "alias": ..., "blocked_at": ...}]`
  - No `peer_hash` key in any result dict

- [ ] 2.6 Remove `_load_blocklist()` (dead code, was never wired)

- [ ] 2.7 Write unit tests (TDD — tests first):
  - block_peer writes to peer_blocks and RBAC
  - block_peer is idempotent (upsert, not duplicate)
  - block_peer returns False and does NOT update RBAC on DB error
  - unblock_peer removes from both stores
  - unblock_peer returns False if not blocked
  - _seed_blocks_to_rbac loads peer_blocks into RBAC
  - _seed_blocks_to_rbac merges with existing YAML static entries
  - get_blocked_peers returns identity_hash-keyed records

---

## Group 3: _handle_lxmf_message RBAC fix (depends on Group 2)

**Label:** `receive-fix`
**Files:** `src/styrened/services/lxmf_service.py`
**Tests:** `tests/unit/test_lxmf_rbac.py` (extend existing)

### Tasks

- [ ] 3.1 Add NodeStore lookup in `_handle_lxmf_message` before RBAC check:
  ```python
  source_lxmf_hash = message.source_hash.hex()
  identity_hash = None
  try:
      identity_hash = get_node_store().get_identity_for_lxmf_destination(source_lxmf_hash)
  except Exception:
      pass
  check_hash = identity_hash or source_lxmf_hash
  if self._rbac_policy.resolve_role(check_hash) == Role.BLOCKED:
      ...drop...
  ```

- [ ] 3.2 Write unit tests:
  - blocked peer with known identity hash: message dropped, resolve_role called with identity_hash
  - blocked peer with unknown identity hash (fallback): message dropped using dest hash
  - allowed peer: message passes through
  - NodeStore raises exception: message still processed (no silent drop)
  - YAML prefix block matches via resolved identity_hash

---

## Group 4: IPC + TUI breaking changes (depends on Group 2)

**Label:** `ipc-tui`
**Files:**
  - `src/styrened/ipc/messages.py`
  - `src/styrened/ipc/handlers.py`
  - `src/styrened/ipc/client.py`
  - `src/styrened/ipc/bridge.py`
  - `src/styrened/models/mesh_device.py`
  - `src/styrened/tui/screens/conversation.py`
  - `src/styrened/tui/widgets/chat_widget.py`
**Tests:** `tests/unit/test_ipc_block.py` (new), update existing TUI tests

### Tasks

- [ ] 4.1 `CmdBlockPeerRequest`: remove `peer_hash` field, add `identity_hash: str = ""`,
  add `lxmf_dest_hash: str = ""`, add `alias: str = ""`.
  Update `to_payload()` and `from_payload()`.

- [ ] 4.2 `CmdUnblockPeerRequest`: remove `peer_hash` field, add `identity_hash: str = ""`.

- [ ] 4.3 `QueryBlockedPeersRequest` response: ensure handler returns `identity_hash`-keyed dicts.

- [ ] 4.4 IPC handler `handle_cmd_block_peer`: validate `identity_hash` not empty,
  call `svc.block_peer(identity_hash, lxmf_dest_hash, alias)`.
  NO peer_hash fallback resolution.

- [ ] 4.5 IPC handler `handle_cmd_unblock_peer`: validate `identity_hash` not empty,
  call `svc.unblock_peer(identity_hash)`.

- [ ] 4.6 `IPCClient.block_peer(identity_hash, lxmf_dest_hash="", alias="")` — rename param.
  `IPCClient.unblock_peer(identity_hash)` — rename param.

- [ ] 4.7 `IPCBridge.block_peer(identity_hash, lxmf_dest_hash="", alias="")` — rename param.
  `IPCBridge.unblock_peer(identity_hash)` — rename param.

- [ ] 4.8 `MeshDevice.identity` property: **delete entirely** (no deprecation warning).
  Grep all callers and replace with explicit `.identity_hash` or `.destination_hash`.
  Known callers: `tui/screens/conversation.py`, `tui/widgets/chat_widget.py`,
  any test mocks using `.identity`.

- [ ] 4.9 TUI `ConversationScreen.action_block_peer`: pass `device.identity_hash` to
  `bridge.block_peer(identity_hash=..., lxmf_dest_hash=device.lxmf_destination_hash)`.

- [ ] 4.10 TUI `ChatWidget._block_peer_async`: same — use `identity_hash` not `peer_hash`
  (verify `self.peer_hash` in ChatWidget is already identity hash or fix the assignment).

- [ ] 4.11 Write unit tests:
  - CmdBlockPeerRequest serializes/deserializes with identity_hash (no peer_hash key)
  - Handler rejects empty identity_hash
  - Handler calls block_peer(identity_hash=...) not block_peer(peer_hash=...)
  - MeshDevice has no .identity attribute (AttributeError expected in removed-property test)

---

## Completion criteria

- [ ] All 4 groups merged and green on main
- [ ] `just test-unit` passes (target: no regression from current count)
- [ ] `block_peer("id_abc")` survives a daemon restart — blocks still enforced after restart
- [ ] `message.source_hash` from a blocked peer is dropped using identity_hash RBAC check
- [ ] No `peer_hash` key appears in any IPC block/unblock message payload
- [ ] `MeshDevice().identity` raises AttributeError
- [ ] Version bumped to `0.16.0`, tagged `v0.16.0`, pushed
