# block-ops — Block / Unblock Operation Spec

### Requirement: block_peer takes identity_hash as canonical key

Signature: `block_peer(identity_hash: str, lxmf_dest_hash: str | None = None, alias: str | None = None) -> bool`
No `peer_hash` parameter. No compat shim.

#### Scenario: block a known peer

Given a peer with `identity_hash="id_abc"` and `lxmf_dest_hash="lxmf_abc"`
When `block_peer("id_abc", lxmf_dest_hash="lxmf_abc", alias="Alice")` is called
Then a row is inserted into peer_blocks: `identity_hash="id_abc"`, `lxmf_dest_hash="lxmf_abc"`, `alias="Alice"`, `blocked_by="operator"`
And `resolve_role("id_abc")` returns `Role.BLOCKED` immediately
And the contacts row for `identity_hash="id_abc"` has `blocked=1`
And `True` is returned

#### Scenario: block with identity_hash only (no lxmf_dest_hash)

Given no lxmf_dest_hash is available
When `block_peer("id_abc")` is called
Then a row is inserted into peer_blocks with `identity_hash="id_abc"`, `lxmf_dest_hash=NULL`
And `resolve_role("id_abc")` returns `Role.BLOCKED`

#### Scenario: block is idempotent

Given `block_peer("id_abc")` has already been called
When `block_peer("id_abc")` is called again
Then the peer_blocks row is updated (upsert), not duplicated
And `True` is returned

#### Scenario: block_peer fails gracefully on DB error

Given the SQLite database is unavailable
When `block_peer("id_abc")` is called
Then `False` is returned
And in-memory RBAC is NOT modified (no partial state)
And an error is logged

---

## CHANGED: unblock_peer

### Requirement: unblock_peer takes identity_hash

Signature: `unblock_peer(identity_hash: str) -> bool`

#### Scenario: unblock a blocked peer

Given `identity_hash="id_abc"` is in peer_blocks and in RBAC.blocked
When `unblock_peer("id_abc")` is called
Then the peer_blocks row is deleted
And `identity_hash` is removed from `RBACPolicy.blocked`
And contacts row has `blocked=0`
And `True` is returned

#### Scenario: unblock a peer that was not blocked

Given `identity_hash="id_xyz"` is NOT in peer_blocks
When `unblock_peer("id_xyz")` is called
Then `False` is returned

---

## ADDED: _seed_blocks_to_rbac

### Requirement: runtime blocks are loaded into RBAC on every startup

#### Scenario: blocks seeded from peer_blocks on initialization

Given peer_blocks table has rows for `["id_aaa", "id_bbb"]`
And the YAML rbac.blocked list has `["ca3e9813"]` (static prefix)
When `_seed_blocks_to_rbac()` runs during `LXMFService.initialize()`
Then `resolve_role("id_aaa")` returns `Role.BLOCKED`
And `resolve_role("id_bbb")` returns `Role.BLOCKED`
And `resolve_role("ca3e9813abcdef12")` returns `Role.BLOCKED` (static YAML prefix still works)

#### Scenario: empty peer_blocks produces no RBAC changes

Given peer_blocks table is empty
When `_seed_blocks_to_rbac()` runs
Then no entries are added to RBAC.blocked beyond those from YAML config

---

## CHANGED: get_blocked_peers

### Requirement: get_blocked_peers returns identity_hash-keyed records

#### Scenario: returns identity_hash and optional lxmf_dest_hash

Given peer_blocks has `{identity_hash="id_abc", lxmf_dest_hash="lxmf_abc", alias="Alice"}`
When `get_blocked_peers()` is called
Then the result contains `{"identity_hash": "id_abc", "lxmf_dest_hash": "lxmf_abc", "alias": "Alice"}`
And no result has a `peer_hash` key
