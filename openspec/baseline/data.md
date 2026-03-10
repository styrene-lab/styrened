# data — Block Store Schema Spec

### Requirement: contacts PK is identity_hash (0.16.0 breaking migration)

The `contacts` table PK changes from `peer_hash VARCHAR(32)` (LXMF dest hash)
to `identity_hash TEXT PRIMARY KEY` (RNS identity hash, 32 hex chars).
`lxmf_dest_hash` column added to retain the transport address for sending.
Migration runs once on startup: existing rows are backfilled via NodeStore lookup.
Rows for peers not in NodeStore use the old `peer_hash` value as a best-effort
identity_hash; they are corrected when the peer next announces.

#### Scenario: clean DB — first run

Given the messages database has no contacts table
When `init_db()` runs
Then a contacts table exists with `identity_hash TEXT PRIMARY KEY`
And the table has columns: `identity_hash`, `lxmf_dest_hash`, `alias`, `notes`, `blocked`, `blocked_at`, `created_at`, `updated_at`

#### Scenario: existing DB — migration from peer_hash PK

Given the messages database has a contacts table with `peer_hash VARCHAR(32) PRIMARY KEY`
And the table has a row `peer_hash="abc123", alias="Alice", blocked=0`
When `init_db()` runs the schema migration
Then a contacts table exists with `identity_hash TEXT PRIMARY KEY`
And the row is preserved: `identity_hash="abc123"`, `alias="Alice"`, `blocked=0`
And a `lxmf_dest_hash` column exists (nullable)

#### Scenario: migration backfills identity_hash from NodeStore

Given a contacts row with `peer_hash="lxmf000abc"` (an LXMF dest hash)
And NodeStore maps `lxmf_dest_hash="lxmf000abc"` → `identity_hash="id000abc"`
When the startup backfill runs
Then the contacts row is updated to `identity_hash="id000abc"`, `lxmf_dest_hash="lxmf000abc"`

#### Scenario: migration falls back to peer_hash when NodeStore has no mapping

Given a contacts row with `peer_hash="unknown000"` not in NodeStore
When the startup backfill runs
Then the contacts row retains `identity_hash="unknown000"` (best-effort)
And a log warning is emitted indicating the row needs resolution

---

## ADDED: peer_blocks table

### Requirement: peer_blocks is the authoritative runtime block store

`peer_blocks` stores runtime blocks keyed on `identity_hash`.
Survives daemon restarts. Loaded into RBAC on every startup.
`contacts.blocked` is a derived hint, not authoritative.

#### Scenario: peer_blocks table created on first run

Given the messages database has no peer_blocks table
When `init_db()` runs
Then a peer_blocks table exists with columns:
  `identity_hash TEXT PRIMARY KEY`, `lxmf_dest_hash TEXT`, `alias TEXT`,
  `blocked_at REAL NOT NULL`, `blocked_by TEXT NOT NULL DEFAULT 'operator'`, `notes TEXT`
And an index exists on `peer_blocks(lxmf_dest_hash)`

#### Scenario: peer_blocks survives daemon restart

Given `block_peer("id_abc123")` was called and the row exists in peer_blocks
When the daemon process restarts and `_seed_blocks_to_rbac()` runs
Then `resolve_role("id_abc123")` returns `Role.BLOCKED`

#### Scenario: unblocking removes from peer_blocks

Given a row exists in peer_blocks for `identity_hash="id_abc123"`
When `unblock_peer("id_abc123")` is called
Then the row is deleted from peer_blocks
And `resolve_role("id_abc123")` no longer returns `Role.BLOCKED`
