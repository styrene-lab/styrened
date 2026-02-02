"""SQLite storage for discovered mesh nodes.

Persists discovered nodes to ~/.styrene/nodes.db so that identity hashes
are remembered across restarts. This allows sending messages to nodes
that were discovered in previous sessions.

The key insight: RNS.Identity.recall(identity_hash) only works if we've
seen an announce from that identity in the current session OR if we have
the identity cached. This store provides that cache.

Threading Model:
-----------------
This store is accessed from multiple threads:
- Main application thread (queries, UI updates)
- RNS announce handler threads (save_node calls)
- Background cleanup threads (prune operations)

To prevent file descriptor leaks and ensure thread safety:
1. Each operation creates a NEW connection (no shared connection state)
2. Connections use context managers to guarantee cleanup
3. Write operations use a global lock for serialization
4. Read operations are lock-free (SQLite allows concurrent reads)
5. Connection creation is logged at DEBUG level for monitoring

This design trades connection reuse for guaranteed resource cleanup and
thread safety. SQLite connection overhead is negligible (<1ms) and eliminates
the complexity of connection pooling for this use case.
"""

import logging
import re
import sqlite3
import threading
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

import platformdirs

from styrened.models.mesh_device import DeviceType, MeshDevice

logger = logging.getLogger(__name__)

# Validation pattern for 32-character hex hashes (RNS identity/destination hashes)
_HEX_HASH_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")

# Validation pattern for truncated hex hashes (used in prefix matching)
_HEX_PREFIX_PATTERN = re.compile(r"^[a-fA-F0-9]+$")

# Minimum prefix length for hash lookups to avoid ambiguous matches
# 8 hex chars = 32 bits = 4 billion possible values, reasonable collision resistance
MIN_PREFIX_LENGTH = 8


def _is_valid_hash(h: str | None) -> bool:
    """Validate a 32-character hex hash.

    RNS identity and destination hashes are 16 bytes (128 bits),
    represented as 32 hexadecimal characters.

    Args:
        h: Hash string to validate.

    Returns:
        True if valid 32-char hex string, False otherwise.
    """
    return h is not None and bool(_HEX_HASH_PATTERN.match(h))


def _is_valid_hash_prefix(h: str | None) -> bool:
    """Validate a hex hash prefix for prefix matching.

    Ensures the prefix is valid hex and meets minimum length requirements.

    Args:
        h: Hash prefix string to validate.

    Returns:
        True if valid hex prefix of sufficient length, False otherwise.
    """
    if h is None:
        return False
    if len(h) < MIN_PREFIX_LENGTH:
        return False
    return bool(_HEX_PREFIX_PATTERN.match(h))


# Global lock for thread-safe database operations
# RNS announce handlers run in separate threads
_db_lock = threading.Lock()


def get_db_path() -> Path:
    """Get path to the nodes database.

    Returns:
        Path to ~/.styrene/nodes.db
    """
    config_dir = Path(platformdirs.user_config_dir("styrene"))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / "nodes.db"


def init_db(db_path: Path | None = None) -> sqlite3.Connection:
    """Initialize the nodes database and return a new connection.

    This function creates the schema if needed and returns a fresh connection.
    Callers MUST close the connection when done (use context manager).

    Args:
        db_path: Optional path override (for testing).

    Returns:
        SQLite connection (caller must close).

    Note:
        Uses check_same_thread=False because the connection may be created
        in one thread and used immediately. However, connections should NOT
        be shared across threads - create a new connection per operation.
    """
    if db_path is None:
        db_path = get_db_path()

    # Log connection creation for leak detection
    logger.debug(f"Creating new database connection to {db_path}")

    # check_same_thread=False allows immediate use after creation,
    # but connection should not be shared across threads
    conn = sqlite3.Connection(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row

    # Create tables
    conn.execute("""
        CREATE TABLE IF NOT EXISTS nodes (
            destination_hash TEXT PRIMARY KEY,
            identity_hash TEXT NOT NULL,
            name TEXT,
            device_type TEXT,
            last_announce INTEGER,
            announce_count INTEGER DEFAULT 1,
            capabilities TEXT,
            version TEXT,
            lxmf_destination_hash TEXT,
            created_at INTEGER DEFAULT (strftime('%s', 'now')),
            updated_at INTEGER DEFAULT (strftime('%s', 'now'))
        )
    """)

    # Schema migration: Add lxmf_destination_hash column if it doesn't exist
    # This handles existing databases created before this column was added
    try:
        conn.execute("ALTER TABLE nodes ADD COLUMN lxmf_destination_hash TEXT")
        logger.debug("Added lxmf_destination_hash column to nodes table")
    except sqlite3.OperationalError:
        # Column already exists, this is expected
        pass

    # Index on identity_hash for lookups
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_identity_hash ON nodes(identity_hash)
    """)

    # Index on lxmf_destination_hash for message sending lookups
    # This enables efficient identity_hash lookup when sending to LXMF destinations
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_lxmf_destination_hash ON nodes(lxmf_destination_hash)
    """)

    conn.commit()
    logger.debug(f"Initialized node store at {db_path}")
    return conn


class NodeStore:
    """Persistent storage for discovered mesh nodes.

    Thread Safety:
        - All methods are thread-safe
        - Each operation creates a fresh connection (no shared state)
        - Write operations use a global lock for serialization
        - Read operations allow concurrent access

    Resource Management:
        - Connections are created per-operation and closed immediately
        - No persistent connections that could leak file descriptors
        - Connection creation is logged for leak detection
    """

    def __init__(self, db_path: Path | None = None) -> None:
        """Initialize the node store.

        Args:
            db_path: Optional path override (for testing).
        """
        self._db_path = db_path or get_db_path()
        # Ensure database schema exists
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Ensure database schema exists (called once during init)."""
        conn = init_db(self._db_path)
        try:
            # Schema creation is idempotent (CREATE TABLE IF NOT EXISTS)
            pass
        finally:
            conn.close()
            logger.debug("Closed schema initialization connection")

    def _get_conn(self) -> sqlite3.Connection:
        """Create a new database connection.

        Returns:
            A new SQLite connection. Caller MUST close it.

        Note:
            This method is deprecated. Use _connection() context manager instead.
        """
        logger.debug("Creating connection via deprecated _get_conn()")
        return init_db(self._db_path)

    @contextmanager
    def _connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Context manager for database connections.

        Yields:
            sqlite3.Connection that is automatically closed on exit.

        Example:
            with self._connection() as conn:
                result = conn.execute("SELECT * FROM nodes").fetchall()
            # Connection is closed here
        """
        conn = init_db(self._db_path)
        try:
            yield conn
        finally:
            conn.close()
            logger.debug("Closed database connection")

    def save_node(self, device: MeshDevice) -> None:
        """Save or update a node in the store.

        Thread-safe: uses lock for concurrent access from RNS threads.

        Args:
            device: MeshDevice to persist.

        Note:
            Invalid hashes are rejected with a warning log. This protects
            against malformed data from untrusted mesh peers.
        """
        # Validate hashes from potentially untrusted mesh peers
        if not _is_valid_hash(device.destination_hash):
            logger.warning(f"Invalid destination_hash rejected: {device.destination_hash!r}")
            return
        if not _is_valid_hash(device.identity_hash):
            logger.warning(f"Invalid identity_hash rejected: {device.identity_hash!r}")
            return

        with _db_lock:
            with self._connection() as conn:
                # Serialize capabilities
                caps = ",".join(device.capabilities) if device.capabilities else None

                conn.execute(
                    """
                    INSERT INTO nodes (
                        destination_hash, identity_hash, name, device_type,
                        last_announce, announce_count, capabilities, version,
                        lxmf_destination_hash, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, strftime('%s', 'now'))
                    ON CONFLICT(destination_hash) DO UPDATE SET
                        identity_hash = excluded.identity_hash,
                        name = excluded.name,
                        device_type = excluded.device_type,
                        last_announce = excluded.last_announce,
                        announce_count = nodes.announce_count + 1,
                        capabilities = excluded.capabilities,
                        version = excluded.version,
                        lxmf_destination_hash = excluded.lxmf_destination_hash,
                        updated_at = strftime('%s', 'now')
                    """,
                    (
                        device.destination_hash,
                        device.identity_hash,
                        device.name,
                        device.device_type.value,
                        device.last_announce,
                        device.announce_count,
                        caps,
                        device.version,
                        device.lxmf_destination_hash,
                    ),
                )
                conn.commit()
                logger.debug(f"Saved node {device.name} ({device.identity_short})")

    def get_node_by_destination(self, destination_hash: str) -> MeshDevice | None:
        """Get a node by its destination hash.

        Thread-safe: read operations allow concurrent access.

        Args:
            destination_hash: Hex-encoded destination hash.

        Returns:
            MeshDevice if found, None otherwise.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE destination_hash = ?",
                (destination_hash,),
            ).fetchone()

            if row:
                return self._row_to_device(row)
            return None

    def get_node_by_identity(self, identity_hash: str) -> MeshDevice | None:
        """Get a node by its identity hash.

        Thread-safe: read operations allow concurrent access.

        Args:
            identity_hash: Hex-encoded identity hash.

        Returns:
            MeshDevice if found, None otherwise.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE identity_hash = ?",
                (identity_hash,),
            ).fetchone()

            if row:
                return self._row_to_device(row)
            return None

    def get_identity_for_destination(self, destination_hash: str) -> str | None:
        """Get identity hash for an operator destination hash.

        This lookup is used when we have the operator destination hash
        (from `styrene_node:operator` announces). For LXMF destinations,
        use get_identity_for_lxmf_destination() instead.

        Supports both exact match and prefix match for truncated hashes
        (common when users copy partial hashes from CLI output).
        Prefix matching requires minimum 8 characters to avoid ambiguity.

        Thread-safe: read operations allow concurrent access.

        Args:
            destination_hash: Hex-encoded operator destination hash (full or truncated).

        Returns:
            Identity hash if found, None otherwise.
            Returns None if prefix is ambiguous (matches multiple nodes).
        """
        with self._connection() as conn:
            # First try exact match
            row = conn.execute(
                "SELECT identity_hash FROM nodes WHERE destination_hash = ?",
                (destination_hash,),
            ).fetchone()

            # If not found, try prefix match for truncated hashes
            if not row and len(destination_hash) < 32:
                # Validate prefix before using in query
                if not _is_valid_hash_prefix(destination_hash):
                    logger.debug(
                        f"[HASH] NodeStore lookup: operator_dest={destination_hash[:16]}... "
                        f"-> INVALID (too short or not hex)"
                    )
                    return None

                # Check for ambiguous matches
                rows = conn.execute(
                    "SELECT identity_hash FROM nodes WHERE destination_hash LIKE ?",
                    (destination_hash + "%",),
                ).fetchall()

                if len(rows) > 1:
                    logger.warning(
                        f"[HASH] NodeStore lookup: operator_dest={destination_hash[:16]}... "
                        f"-> AMBIGUOUS ({len(rows)} matches, need longer prefix)"
                    )
                    return None
                elif len(rows) == 1:
                    row = rows[0]

            if row:
                identity_hash: str = row["identity_hash"]
                logger.debug(
                    f"[HASH] NodeStore lookup: operator_dest={destination_hash[:16]}... "
                    f"-> identity_hash={identity_hash[:16]}..."
                )
                return identity_hash
            else:
                logger.debug(
                    f"[HASH] NodeStore lookup: operator_dest={destination_hash[:16]}... "
                    f"-> NOT FOUND"
                )
                return None

    def get_node_by_lxmf_destination(self, lxmf_destination_hash: str) -> MeshDevice | None:
        """Get a node by its LXMF destination hash.

        Thread-safe: read operations allow concurrent access.

        Args:
            lxmf_destination_hash: Hex-encoded LXMF delivery destination hash.

        Returns:
            MeshDevice if found, None otherwise.
        """
        with self._connection() as conn:
            row = conn.execute(
                "SELECT * FROM nodes WHERE lxmf_destination_hash = ?",
                (lxmf_destination_hash,),
            ).fetchone()

            if row:
                return self._row_to_device(row)
            return None

    def get_identity_for_lxmf_destination(self, lxmf_destination_hash: str) -> str | None:
        """Get identity hash for an LXMF destination hash.

        This is the KEY lookup for sending LXMF messages:
        - We have the target's LXMF destination_hash (what we want to send to)
        - We need the identity_hash to call RNS.Identity.recall()
        - The LXMF destination is different from the operator destination,
          but both share the same identity_hash

        Supports both exact match and prefix match for truncated hashes.
        Prefix matching requires minimum 8 characters to avoid ambiguity.

        Thread-safe: read operations allow concurrent access.

        Args:
            lxmf_destination_hash: Hex-encoded LXMF delivery destination hash (full or truncated).

        Returns:
            Identity hash if found, None otherwise.
            Returns None if prefix is ambiguous (matches multiple nodes).
        """
        with self._connection() as conn:
            # First try exact match
            row = conn.execute(
                "SELECT identity_hash FROM nodes WHERE lxmf_destination_hash = ?",
                (lxmf_destination_hash,),
            ).fetchone()

            # If not found, try prefix match for truncated hashes
            if not row and len(lxmf_destination_hash) < 32:
                # Validate prefix before using in query
                if not _is_valid_hash_prefix(lxmf_destination_hash):
                    logger.debug(
                        f"[HASH] NodeStore lookup: lxmf_dest={lxmf_destination_hash[:16]}... "
                        f"-> INVALID (too short or not hex)"
                    )
                    return None

                # Check for ambiguous matches
                rows = conn.execute(
                    "SELECT identity_hash FROM nodes WHERE lxmf_destination_hash LIKE ?",
                    (lxmf_destination_hash + "%",),
                ).fetchall()

                if len(rows) > 1:
                    logger.warning(
                        f"[HASH] NodeStore lookup: lxmf_dest={lxmf_destination_hash[:16]}... "
                        f"-> AMBIGUOUS ({len(rows)} matches, need longer prefix)"
                    )
                    return None
                elif len(rows) == 1:
                    row = rows[0]

            if row:
                identity_hash: str = row["identity_hash"]
                logger.debug(
                    f"[HASH] NodeStore lookup: lxmf_dest={lxmf_destination_hash[:16]}... "
                    f"-> identity_hash={identity_hash[:16]}..."
                )
                return identity_hash
            else:
                logger.debug(
                    f"[HASH] NodeStore lookup: lxmf_dest={lxmf_destination_hash[:16]}... "
                    f"-> NOT FOUND (node may not have announced with LXMF dest in app_data)"
                )
                return None

    def get_all_nodes(self) -> list[MeshDevice]:
        """Get all stored nodes.

        Thread-safe: read operations allow concurrent access.

        Returns:
            List of MeshDevice objects.
        """
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM nodes ORDER BY last_announce DESC").fetchall()

            return [self._row_to_device(row) for row in rows]

    def get_styrene_nodes(self) -> list[MeshDevice]:
        """Get all Styrene nodes.

        Thread-safe: read operations allow concurrent access.

        Returns:
            List of MeshDevice objects that are Styrene nodes.
        """
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM nodes WHERE device_type = ? ORDER BY last_announce DESC",
                (DeviceType.STYRENE_NODE.value,),
            ).fetchall()

            return [self._row_to_device(row) for row in rows]

    def delete_node(self, destination_hash: str) -> bool:
        """Delete a node from the store.

        Thread-safe: uses lock for concurrent access.

        Args:
            destination_hash: Hex-encoded destination hash.

        Returns:
            True if deleted, False if not found.
        """
        with _db_lock:
            with self._connection() as conn:
                cursor = conn.execute(
                    "DELETE FROM nodes WHERE destination_hash = ?",
                    (destination_hash,),
                )
                conn.commit()
                return bool(cursor.rowcount > 0)

    def prune_old_nodes(self, max_age_seconds: int = 86400 * 30) -> int:
        """Delete nodes not seen in a while.

        Thread-safe: uses lock for concurrent access.

        Args:
            max_age_seconds: Max age in seconds (default 30 days).

        Returns:
            Number of nodes deleted.
        """
        import time

        with _db_lock:
            with self._connection() as conn:
                cutoff = int(time.time()) - max_age_seconds
                cursor = conn.execute(
                    "DELETE FROM nodes WHERE last_announce < ?",
                    (cutoff,),
                )
                conn.commit()
                return int(cursor.rowcount)

    def clear_all_nodes(self) -> int:
        """Clear all nodes from the store.

        Thread-safe: uses lock for concurrent access.

        Returns:
            Number of nodes deleted.
        """
        with _db_lock:
            with self._connection() as conn:
                cursor = conn.execute("DELETE FROM nodes")
                conn.commit()
                return int(cursor.rowcount)

    def _row_to_device(self, row: sqlite3.Row) -> MeshDevice:
        """Convert a database row to MeshDevice.

        Args:
            row: SQLite row.

        Returns:
            MeshDevice instance.
        """
        caps = row["capabilities"].split(",") if row["capabilities"] else None

        # Handle optional lxmf_destination_hash column (may not exist in older DBs)
        lxmf_dest = None
        try:
            lxmf_dest = row["lxmf_destination_hash"]
        except (KeyError, IndexError):
            pass

        return MeshDevice(
            destination_hash=row["destination_hash"],
            identity_hash=row["identity_hash"],
            name=row["name"] or f"device-{row['destination_hash'][:8]}",
            device_type=DeviceType(row["device_type"])
            if row["device_type"]
            else DeviceType.UNKNOWN,
            last_announce=row["last_announce"] or 0,
            announce_count=row["announce_count"] or 1,
            capabilities=caps,
            version=row["version"],
            lxmf_destination_hash=lxmf_dest,
        )

    def get_connection_count(self) -> int:
        """Get the number of open file descriptors for the database.

        This is a diagnostic method to detect file descriptor leaks.
        In normal operation, this should return 0 (no persistent connections).

        Returns:
            Number of open file descriptors for this database file.

        Raises:
            RuntimeError: If lsof command fails (Unix-like systems only).

        Note:
            This method is Unix-specific and will log a warning on other platforms.
        """
        import subprocess
        import sys

        if sys.platform == "win32":
            logger.warning("Connection count check not supported on Windows")
            return -1

        try:
            # Use lsof to count file descriptors for this database file
            result = subprocess.run(
                ["lsof", "-t", str(self._db_path)],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0:
                # Count unique PIDs (each line is a PID)
                pids = result.stdout.strip().split("\n")
                return len([p for p in pids if p])
            else:
                # lsof returns 1 if no files found (which is good)
                return 0
        except subprocess.TimeoutExpired:
            logger.warning("Connection count check timed out")
            return -1
        except FileNotFoundError:
            logger.warning("lsof not found - cannot check connection count")
            return -1
        except Exception as e:
            logger.warning(f"Failed to check connection count: {e}")
            return -1

    def close(self) -> None:
        """Close the database connection.

        Note:
            This method is a no-op in the current implementation because
            connections are created per-operation and closed automatically.
            Kept for backwards compatibility with code that calls close().
        """
        # No-op: connections are managed per-operation via context managers
        logger.debug("NodeStore.close() called (no-op with per-operation connections)")


# Global singleton
_node_store: NodeStore | None = None


def get_node_store() -> NodeStore:
    """Get the global NodeStore instance.

    Returns:
        Singleton NodeStore.
    """
    global _node_store
    if _node_store is None:
        _node_store = NodeStore()
    return _node_store


def check_connection_health() -> dict[str, int | bool | str]:
    """Check NodeStore connection health (diagnostic/monitoring).

    This function provides metrics for detecting file descriptor leaks.
    It should be called periodically (e.g., every 60 seconds) in production
    to detect and alert on connection leaks early.

    Returns:
        Dictionary with health metrics:
        - connection_count: Number of open file descriptors (-1 if unavailable)
        - healthy: True if connection_count is acceptable (<= 2)
        - warning: Human-readable warning message if unhealthy

    Example:
        >>> health = check_connection_health()
        >>> if not health["healthy"]:
        ...     logger.error(health["warning"])
    """
    store = get_node_store()
    count = store.get_connection_count()

    # Acceptable thresholds:
    # 0 = ideal (no persistent connections)
    # 1-2 = acceptable (one operation in progress per process)
    # 3+ = potential leak or concurrent operations (warning)
    # 10+ = definite leak (error)

    healthy = count <= 2 or count == -1  # -1 means unavailable (treat as healthy)
    warning = ""

    if count >= 10:
        warning = (
            f"CRITICAL: NodeStore has {count} open connections. "
            "File descriptor leak detected. Check for unclosed connections."
        )
        logger.error(warning)
    elif count >= 3:
        warning = (
            f"WARNING: NodeStore has {count} open connections. "
            "This may indicate a leak or heavy concurrent usage."
        )
        logger.warning(warning)
    elif count == -1:
        logger.debug("Connection health check unavailable on this platform")
    else:
        logger.debug(f"NodeStore connection health OK ({count} connections)")

    return {
        "connection_count": count,
        "healthy": healthy,
        "warning": warning,
    }
