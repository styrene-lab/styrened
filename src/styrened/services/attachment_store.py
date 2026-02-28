"""Filesystem attachment storage with budget enforcement.

Stores attachment binary data on the filesystem, organized by peer hash.
Avoids SQLite bloat on resource-constrained devices (Pi, etc.).

Layout: data_dir() / "attachments" / <peer_hash[:16]> / <msg_id>_<filename>
"""

import logging
import os
import re
from pathlib import Path

from styrened.paths import data_dir

logger = logging.getLogger(__name__)

# Defaults
DEFAULT_MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB
DEFAULT_STORAGE_BUDGET = 500 * 1024 * 1024  # 500 MB

# Peer directory prefix length (64-bit, birthday-safe for millions of peers)
PEER_DIR_PREFIX_LEN = 16

# Filename sanitization
_UNSAFE_CHARS = re.compile(r'[/\\:\x00-\x1f<>"|?*]')
_MAX_FILENAME_LEN = 200


def _sanitize_filename(name: str) -> str:
    """Sanitize a filename for safe filesystem storage.

    Strips path separators, control characters, and limits length.
    """
    # Take only the basename (strip directory components)
    name = os.path.basename(name)
    # Remove unsafe characters
    name = _UNSAFE_CHARS.sub("_", name)
    # Collapse consecutive underscores
    name = re.sub(r"_+", "_", name).strip("_")
    # Limit length while preserving extension
    if len(name) > _MAX_FILENAME_LEN:
        stem, _, ext = name.rpartition(".")
        if ext and len(ext) < 20:
            max_stem = _MAX_FILENAME_LEN - len(ext) - 1
            name = stem[:max_stem] + "." + ext
        else:
            name = name[:_MAX_FILENAME_LEN]
    # Fallback for empty names
    if not name:
        name = "attachment"
    return name


class AttachmentStore:
    """Filesystem attachment storage with budget enforcement.

    Layout: base_dir / <peer_hash[:16]> / <msg_id>_<filename>

    Thread-safe: individual save/load/delete operations are atomic
    at the filesystem level via atomic rename (write to temp, rename).
    """

    def __init__(
        self,
        base_dir: Path | None = None,
        max_file_size: int = DEFAULT_MAX_FILE_SIZE,
        storage_budget: int = DEFAULT_STORAGE_BUDGET,
    ) -> None:
        self._base_dir = base_dir or (data_dir() / "attachments")
        self._max_file_size = max_file_size
        self._storage_budget = storage_budget
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _require_contained(self, p: Path) -> Path:
        """Verify that a path resolves within the attachment store base directory.

        Resolves symlinks and relative components, then checks containment.

        Args:
            p: Path to validate.

        Returns:
            Resolved path guaranteed to be inside base_dir.

        Raises:
            ValueError: If the resolved path escapes the base directory.
        """
        resolved = p.resolve()
        base = self._base_dir.resolve()
        if resolved != base and not str(resolved).startswith(str(base) + os.sep):
            raise ValueError(f"Path escapes attachment store: {p}")
        return resolved

    @property
    def base_dir(self) -> Path:
        return self._base_dir

    def _peer_dir(self, peer_hash: str) -> Path:
        """Get or create the peer subdirectory, migrating 8→16 prefix if needed.

        Args:
            peer_hash: Full hex hash of the peer.

        Returns:
            Path to the peer directory.
        """
        new_dir = self._base_dir / peer_hash[:PEER_DIR_PREFIX_LEN]
        if not new_dir.exists():
            old_dir = self._base_dir / peer_hash[:8]
            if old_dir.exists():
                try:
                    old_dir.rename(new_dir)
                    logger.debug(
                        f"Migrated peer dir {peer_hash[:8]} -> {peer_hash[:PEER_DIR_PREFIX_LEN]}"
                    )
                except OSError:
                    pass  # Race or permission issue; fall through to mkdir
        new_dir.mkdir(parents=True, exist_ok=True)
        return new_dir

    def save(
        self,
        peer_hash: str,
        message_id: int,
        filename: str,
        data: bytes,
        mime: str | None = None,
    ) -> Path:
        """Save attachment data to filesystem.

        Args:
            peer_hash: Hex hash of the peer (uses first 16 chars for directory).
            message_id: Database message ID (0 if not yet known).
            filename: Original filename from sender.
            data: Raw attachment bytes.
            mime: Optional MIME type (unused for storage, logged).

        Returns:
            Path to the saved file.

        Raises:
            ValueError: If data exceeds max_file_size.
        """
        if len(data) > self._max_file_size:
            raise ValueError(
                f"Attachment size {len(data)} exceeds maximum {self._max_file_size}"
            )

        safe_name = _sanitize_filename(filename)
        peer_dir = self._peer_dir(peer_hash)

        target = peer_dir / f"{message_id}_{safe_name}"
        self._require_contained(target)

        # Atomic write: write to temp, then rename
        tmp = target.with_suffix(target.suffix + ".tmp")
        try:
            tmp.write_bytes(data)
            tmp.rename(target)
        except Exception:
            # Clean up temp file on failure
            tmp.unlink(missing_ok=True)
            raise

        logger.debug(
            f"Saved attachment: {target.name} ({len(data)} bytes, mime={mime})"
        )

        return target

    def rename_for_message(self, old_path: Path, message_id: int) -> Path:
        """Rename an attachment file to include the real message ID.

        Called after DB commit when the actual message_id is known.
        Uses try/except on rename instead of exists() check to avoid TOCTOU.

        Args:
            old_path: Current path (may have message_id=0).
            message_id: Actual database message ID.

        Returns:
            New path after rename, or old_path if rename not applicable/failed.
        """
        name = old_path.name
        # Replace leading "0_" with "<msg_id>_"
        if not name.startswith("0_"):
            return old_path

        new_name = f"{message_id}_{name[2:]}"
        new_path = old_path.parent / new_name
        try:
            old_path.rename(new_path)
            return new_path
        except FileNotFoundError:
            return old_path

    def load(self, path: str | Path) -> bytes:
        """Load attachment data from filesystem.

        Args:
            path: Path to the attachment file.

        Returns:
            Raw attachment bytes.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If path escapes the attachment store.
        """
        p = Path(path)
        if not p.is_absolute():
            p = self._base_dir / p
        p = self._require_contained(p)
        return p.read_bytes()

    def delete(self, path: str | Path) -> bool:
        """Delete an attachment file.

        Args:
            path: Path to the attachment file.

        Returns:
            True if file was deleted, False if it didn't exist.

        Raises:
            ValueError: If path escapes the attachment store.
        """
        p = Path(path)
        if not p.is_absolute():
            p = self._base_dir / p
        p = self._require_contained(p)
        try:
            p.unlink()
            logger.debug(f"Deleted attachment: {p}")
            return True
        except FileNotFoundError:
            return False

    def delete_for_peer(self, peer_hash: str) -> int:
        """Delete all attachments for a peer.

        Checks both 16-char and legacy 8-char directories.

        Args:
            peer_hash: Hex hash of the peer.

        Returns:
            Number of files deleted.

        Raises:
            ValueError: If the constructed peer directory escapes the store.
        """
        peer_dir = self._base_dir / peer_hash[:PEER_DIR_PREFIX_LEN]
        if not peer_dir.exists():
            # Check legacy 8-char directory
            peer_dir = self._base_dir / peer_hash[:8]
        if not peer_dir.exists():
            return 0

        self._require_contained(peer_dir)

        count = 0
        for f in peer_dir.iterdir():
            if f.is_file():
                f.unlink()
                count += 1

        # Remove the now-empty directory
        try:
            peer_dir.rmdir()
        except OSError:
            pass  # Directory not empty (race) or already gone

        logger.info(f"Deleted {count} attachments for peer {peer_hash[:8]}")
        return count

    def get_usage(self) -> tuple[int, int]:
        """Get current storage usage and budget.

        Returns:
            Tuple of (used_bytes, budget_bytes).
        """
        used = 0
        for f in self._base_dir.rglob("*"):
            if f.is_file():
                try:
                    used += f.stat().st_size
                except OSError:
                    pass
        return used, self._storage_budget

    def enforce_budget(self) -> int:
        """Evict oldest files until storage is within budget.

        Returns:
            Number of bytes freed.
        """
        used, budget = self.get_usage()
        if used <= budget:
            return 0

        # Collect all files with mtime for LRU eviction
        files: list[tuple[float, int, Path]] = []
        for f in self._base_dir.rglob("*"):
            if f.is_file() and not f.name.endswith(".tmp"):
                try:
                    stat = f.stat()
                    files.append((stat.st_mtime, stat.st_size, f))
                except OSError:
                    pass

        # Sort by mtime ascending (oldest first)
        files.sort(key=lambda x: x[0])

        freed = 0
        for _mtime, size, path in files:
            if used - freed <= budget:
                break
            try:
                path.unlink()
                freed += size
                logger.debug(f"Budget eviction: {path.name} ({size} bytes)")
            except OSError:
                pass

        if freed > 0:
            logger.info(f"Budget enforcement freed {freed} bytes")

        # Clean up empty peer directories
        for d in self._base_dir.iterdir():
            if d.is_dir():
                try:
                    d.rmdir()  # Only succeeds if empty
                except OSError:
                    pass

        return freed


# ---------------------------------------------------------------------------
# Singleton access
# ---------------------------------------------------------------------------

_attachment_store: AttachmentStore | None = None


def get_attachment_store() -> AttachmentStore:
    """Get the global AttachmentStore instance."""
    global _attachment_store
    if _attachment_store is None:
        _attachment_store = AttachmentStore()
    return _attachment_store


def set_attachment_store(store: AttachmentStore) -> None:
    """Set the global AttachmentStore instance (for testing/custom config)."""
    global _attachment_store
    _attachment_store = store
