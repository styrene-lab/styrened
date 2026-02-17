"""Periodic snapshot of Reticulum path table to SQLite.

Takes a snapshot of the RNS path table every 30 seconds and persists
path entries (destination, next_hop, hops, interface info) to the
`paths` table in nodes.db. This data is consumed by specularium's
styrene adapter to generate mesh topology edges.

Threading Model:
    Runs as a daemon thread. Uses NodeStore's thread-safe write methods.
    The RNS path table API is read-only and thread-safe.
"""

import logging
import threading
import time

logger = logging.getLogger(__name__)

# Default snapshot interval in seconds
DEFAULT_SNAPSHOT_INTERVAL: int = 30


class PathSnapshotService:
    """Periodically snapshots the Reticulum path table to SQLite.

    Reads RNS.Transport path table entries and persists them via NodeStore
    for consumption by external tools (e.g., specularium topology edges).

    Args:
        node_store: NodeStore instance for persistence.
        interval: Snapshot interval in seconds (default: 30).
    """

    def __init__(self, node_store, interval: int = DEFAULT_SNAPSHOT_INTERVAL) -> None:
        self._node_store = node_store
        self._interval = interval
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the snapshot background thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.debug("Path snapshot service already running")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._snapshot_loop,
            name="path-snapshot",
            daemon=True,
        )
        self._thread.start()
        logger.info(f"Path snapshot service started (interval={self._interval}s)")

    def stop(self) -> None:
        """Stop the snapshot background thread."""
        if self._thread is None:
            return

        self._stop_event.set()
        self._thread.join(timeout=5.0)
        self._thread = None
        logger.info("Path snapshot service stopped")

    @property
    def is_running(self) -> bool:
        """Check if the service is running."""
        return self._thread is not None and self._thread.is_alive()

    def _snapshot_loop(self) -> None:
        """Background loop that periodically snapshots the path table."""
        while not self._stop_event.is_set():
            try:
                self._take_snapshot()
            except Exception as e:
                logger.error(f"Path snapshot error: {e}")

            self._stop_event.wait(timeout=self._interval)

    def _take_snapshot(self) -> None:
        """Take a single snapshot of the path table."""
        try:
            import RNS
        except ImportError:
            logger.debug("RNS not available, skipping path snapshot")
            return

        reticulum = RNS.Reticulum.get_instance()
        if reticulum is None:
            logger.debug("Reticulum not initialized, skipping path snapshot")
            return

        path_table = reticulum.get_path_table()
        if not path_table:
            logger.debug("Path table empty, skipping snapshot")
            return

        saved = 0
        errors = 0

        for entry in path_table:
            try:
                dest_hash_bytes = entry.get("hash")
                if dest_hash_bytes is None:
                    continue

                dest_hash = dest_hash_bytes.hex() if isinstance(dest_hash_bytes, bytes) else str(dest_hash_bytes)

                # Get next hop and interface info
                hops = entry.get("hops", 0)
                expires = entry.get("expires")

                # Query transport for next hop details
                next_hop = None
                interface_type = None
                interface_name = None
                bitrate = None

                try:
                    next_hop_bytes = RNS.Transport.next_hop(dest_hash_bytes)
                    if next_hop_bytes:
                        next_hop = next_hop_bytes.hex() if isinstance(next_hop_bytes, bytes) else str(next_hop_bytes)

                    next_hop_iface = RNS.Transport.next_hop_interface(dest_hash_bytes)
                    if next_hop_iface:
                        interface_type = type(next_hop_iface).__name__
                        interface_name = getattr(next_hop_iface, "name", None)
                        bitrate = getattr(next_hop_iface, "bitrate", None)
                except Exception as e:
                    logger.debug(f"Could not get next hop details for {dest_hash[:16]}...: {e}")

                self._node_store.save_path(
                    destination_hash=dest_hash,
                    next_hop=next_hop,
                    hops=hops,
                    interface_type=interface_type,
                    interface_name=interface_name,
                    bitrate=bitrate,
                    expires=expires,
                )
                saved += 1

            except Exception as e:
                errors += 1
                logger.debug(f"Error processing path entry: {e}")

        # Prune expired paths after snapshot
        pruned = self._node_store.prune_expired_paths()

        logger.debug(f"Path snapshot: {saved} saved, {errors} errors, {pruned} pruned")
