"""Tests for peer_blocks table and contacts PK migration (v0.16.0).

Covers:
- Clean DB gets new schema (identity_hash PK, peer_blocks table)
- Old DB (peer_hash PK) migrates correctly to identity_hash PK
- Backfill updates identity_hash when NodeStore has mapping
- Backfill falls through gracefully when NodeStore has no mapping
"""

from __future__ import annotations

import os
import tempfile
import time
from unittest.mock import MagicMock

from sqlalchemy import create_engine, text


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh_db_path() -> str:
    td = tempfile.mkdtemp()
    return os.path.join(td, "test.db")


def _init(db_path: str):
    """Run init_db() and return the engine it produces."""
    from styrened.models.messages import init_db

    return init_db(db_path)


def _engine(db_path: str):
    return create_engine(f"sqlite:///{db_path}")


def _build_old_schema(db_path: str) -> None:
    """Create pre-v0.16 contacts table (peer_hash PK) without running init_db."""
    eng = _engine(db_path)
    with eng.connect() as conn:
        conn.execute(
            text(
                "CREATE TABLE contacts ("
                "peer_hash VARCHAR(32) PRIMARY KEY, "
                "alias VARCHAR(100) NOT NULL, "
                "notes VARCHAR(500), "
                "created_at REAL NOT NULL, "
                "updated_at REAL NOT NULL"
                ")"
            )
        )
        conn.commit()
    eng.dispose()


# ---------------------------------------------------------------------------
# Clean DB schema
# ---------------------------------------------------------------------------


def test_clean_db_contacts_has_identity_hash_pk():
    """A fresh DB should have contacts.identity_hash as the primary key."""
    p = _fresh_db_path()
    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(contacts)"))
        cols = {row[1]: row for row in result}
    assert "identity_hash" in cols, "identity_hash column missing"
    assert cols["identity_hash"][5] == 1, "identity_hash should be the PK (pk=1)"


def test_clean_db_contacts_no_peer_hash_column():
    """A fresh DB must NOT have the old peer_hash column."""
    p = _fresh_db_path()
    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(contacts)"))
        cols = {row[1] for row in result}
    assert "peer_hash" not in cols


def test_clean_db_peer_blocks_table_exists():
    """peer_blocks table should be created on a fresh DB."""
    p = _fresh_db_path()
    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(peer_blocks)"))
        cols = {row[1] for row in result}
    assert "identity_hash" in cols
    assert "blocked_at" in cols
    assert "reason" in cols


def test_clean_db_peer_blocks_identity_hash_pk():
    """peer_blocks.identity_hash should be the primary key."""
    p = _fresh_db_path()
    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(peer_blocks)"))
        cols = {row[1]: row for row in result}
    assert cols["identity_hash"][5] == 1


def test_clean_db_peer_blocks_insert_and_query():
    """Basic insert/query round-trip on peer_blocks."""
    p = _fresh_db_path()
    eng = _init(p)
    ih = "a" * 64
    now = time.time()
    with eng.connect() as conn:
        conn.execute(
            text("INSERT INTO peer_blocks (identity_hash, blocked_at) VALUES (:ih, :ts)"),
            {"ih": ih, "ts": now},
        )
        conn.commit()
        row = conn.execute(
            text("SELECT * FROM peer_blocks WHERE identity_hash = :ih"), {"ih": ih}
        ).fetchone()
    assert row is not None
    assert row[0] == ih


# ---------------------------------------------------------------------------
# Migration: old schema → new schema
# ---------------------------------------------------------------------------


def test_migration_renames_pk_column():
    """init_db on old schema should produce identity_hash PK."""
    p = _fresh_db_path()
    _build_old_schema(p)
    eng_old = _engine(p)
    with eng_old.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO contacts (peer_hash, alias, created_at, updated_at) "
                "VALUES ('deadbeef12345678', 'Alice', 1.0, 1.0)"
            )
        )
        conn.commit()
    eng_old.dispose()

    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(contacts)"))
        cols = {row[1]: row for row in result}
    assert "identity_hash" in cols
    assert cols["identity_hash"][5] == 1
    assert "peer_hash" not in cols


def test_migration_preserves_row_data():
    """Existing rows survive the migration with data intact."""
    p = _fresh_db_path()
    _build_old_schema(p)
    eng_old = _engine(p)
    with eng_old.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO contacts (peer_hash, alias, created_at, updated_at) "
                "VALUES ('deadbeef12345678', 'Bob', 100.0, 200.0)"
            )
        )
        conn.commit()
    eng_old.dispose()

    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM contacts WHERE identity_hash = 'deadbeef12345678'")
        ).fetchone()
    assert row is not None
    assert row[1] == "Bob"  # alias


def test_migration_preserves_multiple_rows():
    """All rows are preserved after migration."""
    p = _fresh_db_path()
    _build_old_schema(p)
    eng_old = _engine(p)
    rows = [("hash1111", "Alice"), ("hash2222", "Bob"), ("hash3333", "Carol")]
    with eng_old.connect() as conn:
        for ph, alias in rows:
            conn.execute(
                text(
                    "INSERT INTO contacts (peer_hash, alias, created_at, updated_at) "
                    "VALUES (:ph, :alias, 1.0, 1.0)"
                ),
                {"ph": ph, "alias": alias},
            )
        conn.commit()
    eng_old.dispose()

    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM contacts")).scalar()
    assert count == 3


def test_migration_idempotent():
    """Running init_db twice on a migrated DB is safe."""
    p = _fresh_db_path()
    _build_old_schema(p)
    _init(p)
    _init(p)  # second call should not raise
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(contacts)"))
        cols = {row[1] for row in result}
    assert "identity_hash" in cols
    assert "peer_hash" not in cols


def test_migration_adds_blocked_columns():
    """Old schema without blocked column gains it after migration."""
    p = _fresh_db_path()
    _build_old_schema(p)
    _init(p)
    eng = _engine(p)
    with eng.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(contacts)"))
        cols = {row[1] for row in result}
    assert "blocked" in cols
    assert "blocked_at" in cols


# ---------------------------------------------------------------------------
# NodeStore backfill
# ---------------------------------------------------------------------------


def _make_node_store_mock(mapping: dict[str, str]) -> MagicMock:
    ns = MagicMock()

    def _resolve(dest_hash: str) -> str | None:
        return mapping.get(dest_hash)

    ns.get_identity_hash_for_destination.side_effect = _resolve
    return ns


def _backfill(eng, node_store) -> int:
    """Inline backfill: resolve 32-char dest-hashes to full identity hashes."""
    updated = 0
    with eng.connect() as conn:
        rows = conn.execute(
            text("SELECT identity_hash FROM contacts WHERE LENGTH(identity_hash) = 32")
        ).fetchall()
        for (ih,) in rows:
            resolved = node_store.get_identity_hash_for_destination(ih)
            if resolved and resolved != ih:
                existing = conn.execute(
                    text("SELECT 1 FROM contacts WHERE identity_hash = :ih"),
                    {"ih": resolved},
                ).fetchone()
                if not existing:
                    conn.execute(
                        text(
                            "UPDATE contacts SET identity_hash = :new WHERE identity_hash = :old"
                        ),
                        {"new": resolved, "old": ih},
                    )
                    updated += 1
        conn.commit()
    return updated


def test_backfill_updates_identity_hash_when_nodestore_has_mapping():
    """Backfill resolves 32-char dest hashes to full identity hashes."""
    p = _fresh_db_path()
    _build_old_schema(p)
    eng_old = _engine(p)
    dest = "d" * 32
    with eng_old.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO contacts (peer_hash, alias, created_at, updated_at) "
                "VALUES (:ph, 'Alice', 1.0, 1.0)"
            ),
            {"ph": dest},
        )
        conn.commit()
    eng_old.dispose()

    eng = _init(p)
    full_identity = "f" * 64
    ns = _make_node_store_mock({dest: full_identity})
    updated = _backfill(eng, ns)

    assert updated == 1
    with eng.connect() as conn:
        row = conn.execute(
            text("SELECT * FROM contacts WHERE identity_hash = :ih"), {"ih": full_identity}
        ).fetchone()
    assert row is not None


def test_backfill_falls_through_gracefully_when_no_mapping():
    """Backfill leaves rows untouched when NodeStore has no mapping."""
    p = _fresh_db_path()
    _build_old_schema(p)
    eng_old = _engine(p)
    dest = "d" * 32
    with eng_old.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO contacts (peer_hash, alias, created_at, updated_at) "
                "VALUES (:ph, 'Bob', 1.0, 1.0)"
            ),
            {"ph": dest},
        )
        conn.commit()
    eng_old.dispose()

    eng = _init(p)
    ns = _make_node_store_mock({})
    updated = _backfill(eng, ns)

    assert updated == 0
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM contacts")).scalar()
    assert count == 1


def test_backfill_skips_conflict_rows():
    """Backfill does not overwrite a row that already exists with the resolved identity."""
    p = _fresh_db_path()
    eng = _init(p)

    dest_hash = "d" * 32
    full_identity = "e" * 64
    with eng.connect() as conn:
        conn.execute(
            text(
                "INSERT INTO contacts (identity_hash, alias, blocked, created_at, updated_at) "
                "VALUES (:ih, 'Old', 0, 1.0, 1.0)"
            ),
            {"ih": dest_hash},
        )
        conn.execute(
            text(
                "INSERT INTO contacts (identity_hash, alias, blocked, created_at, updated_at) "
                "VALUES (:ih, 'Existing', 0, 1.0, 1.0)"
            ),
            {"ih": full_identity},
        )
        conn.commit()

    ns = _make_node_store_mock({dest_hash: full_identity})
    updated = _backfill(eng, ns)

    assert updated == 0
    with eng.connect() as conn:
        count = conn.execute(text("SELECT COUNT(*) FROM contacts")).scalar()
    assert count == 2
