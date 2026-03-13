# Styrene Distrust Model — Negative Signals, Propagation Boundaries, and Sybil Resistance — Tasks

## 1. src/styrened/models/messages.py (modified)

- [x] 1.1 Add peer_blocks table to init_db(). Add identity_hash column + index migration to contacts table. One-time migration: backfill contacts.identity_hash from NodeStore on startup.

## 2. src/styrened/services/lxmf_service.py (modified)

- [x] 2.1 Redesign block_peer(identity_hash, lxmf_dest_hash=None). Redesign unblock_peer(identity_hash). Add _seed_blocks_to_rbac() reading from peer_blocks. Fix _handle_lxmf_message: NodeStore lookup before RBAC check. Add _load_peer_blocks() from new table. Remove _load_blocklist() dead code.

## 3. src/styrened/ipc/messages.py (modified)

- [x] 3.1 CmdBlockPeerRequest: add identity_hash field, deprecate peer_hash (compat shim). CmdUnblockPeerRequest: same. QueryBlockedPeers response: return identity_hash + optional lxmf_dest_hash.

## 4. src/styrened/ipc/handlers.py (modified)

- [x] 4.1 handle_cmd_block_peer: read identity_hash first, fall back to resolving peer_hash via NodeStore shim. Same for handle_cmd_unblock_peer.

## 5. src/styrened/ipc/client.py (modified)

- [x] 5.1 block_peer(identity_hash) and unblock_peer(identity_hash) — parameter rename.

## 6. src/styrened/ipc/bridge.py (modified)

- [x] 6.1 block_peer(identity_hash), unblock_peer(identity_hash) — parameter rename.

## 7. src/styrened/models/mesh_device.py (modified)

- [x] 7.1 Remove MeshDevice.identity property (legacy alias returning destination_hash). All callers must use .identity_hash or .destination_hash explicitly.

## 8. src/styrened/tui/screens/conversation.py (modified)

- [x] 8.1 Block action: use device.identity_hash not device.identity.

## 9. src/styrened/tui/widgets/chat_widget.py (modified)

- [x] 9.1 Block action: use peer's identity_hash.

## 10. Cross-cutting constraints

- [x] 10.1 Canonical block key is rns_identity_hash everywhere. LXMF dest hash is a transport address, not a peer identifier.
- [x] 10.2 Runtime block_peer() writes ONLY to peer_blocks SQLite table + in-memory RBAC. Never writes to YAML config. YAML rbac.blocked is for static pre-configured operator blocks only.
- [x] 10.3 contacts.blocked is a denormalized UI hint kept in sync with peer_blocks. peer_blocks is the authoritative block store.
- [x] 10.4 contacts.peer_hash PK remains as LXMF dest hash in 0.16.0-rc1. Full contacts PK migration to identity_hash deferred to 0.17.0.
- [x] 10.5 IPC compat shim: CmdBlockPeerRequest accepts both identity_hash (preferred) and peer_hash (deprecated). Handler checks identity_hash first; if empty, resolves peer_hash via NodeStore. Shim removed at 0.17.0.
- [x] 10.6 Backfill gap: if a peer is in contacts.blocked=1 but not in NodeStore, write peer_blocks with dest hash as best-effort identity key. Block still works at LXMF layer. Entry self-heals on next announce.
- [x] 10.7 _seed_blocks_to_rbac() reinstated at LXMF init time. Reads peer_blocks table. Merges with static YAML blocks already in RBACPolicy.blocked.
- [x] 10.8 _handle_lxmf_message: NodeStore.get_identity_for_lxmf_destination(source_lxmf_hash) before RBAC check. Falls back to source_lxmf_hash if NodeStore lookup returns None.
- [x] 10.9 MeshDevice.identity property removed (not deprecated) — it silently returned destination_hash masquerading as identity_hash, which caused 8 TUI bugs. All callers must use .identity_hash or .destination_hash explicitly.
- [x] 10.10 Version target: 0.16.0rc1 (PEP 440 pre-release). Tag: v0.16.0rc1. Promote to v0.16.0 after validation.
