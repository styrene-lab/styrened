"""Tests for attachment store service."""
from __future__ import annotations


import os
from pathlib import Path

import pytest

from styrened.services.attachment_store import (
    PEER_DIR_PREFIX_LEN,
    AttachmentStore,
    _sanitize_filename,
)


@pytest.fixture
def store(tmp_path: Path) -> AttachmentStore:
    """Create an AttachmentStore with a temporary directory."""
    return AttachmentStore(
        base_dir=tmp_path / "attachments",
        max_file_size=1024,  # 1KB for testing
        storage_budget=4096,  # 4KB budget
    )


class TestSanitizeFilename:
    """Tests for filename sanitization."""

    def test_sanitize_basic_filename(self):
        assert _sanitize_filename("photo.jpg") == "photo.jpg"

    def test_sanitize_strips_directory_components(self):
        assert _sanitize_filename("/etc/passwd") == "passwd"
        assert _sanitize_filename("../../secret.txt") == "secret.txt"
        # Backslashes are sanitized as unsafe chars on Unix
        result = _sanitize_filename("C:\\Users\\file.txt")
        assert "file.txt" in result

    def test_sanitize_replaces_unsafe_chars(self):
        result = _sanitize_filename('file<name>:with|bad"chars?.jpg')
        assert "/" not in result
        assert "\\" not in result
        assert ":" not in result
        assert "<" not in result
        assert ">" not in result
        assert '"' not in result
        assert "?" not in result
        assert "*" not in result
        assert result.endswith(".jpg")

    def test_sanitize_limits_length(self):
        long_name = "a" * 300 + ".jpg"
        result = _sanitize_filename(long_name)
        assert len(result) <= 200

    def test_sanitize_preserves_extension_on_truncate(self):
        long_name = "a" * 300 + ".jpg"
        result = _sanitize_filename(long_name)
        assert result.endswith(".jpg")

    def test_sanitize_empty_name_fallback(self):
        assert _sanitize_filename("") == "attachment"
        assert _sanitize_filename("///") == "attachment"

    def test_sanitize_collapses_underscores(self):
        result = _sanitize_filename("file:::name.txt")
        assert "___" not in result


class TestAttachmentStoreSaveLoad:
    """Tests for save/load operations."""

    def test_save_load_roundtrip(self, store: AttachmentStore):
        data = b"hello attachment world"
        path = store.save("aabbccdd1122334455667788", 42, "test.txt", data)

        assert path.exists()
        assert path.name == "42_test.txt"
        assert path.parent.name == "aabbccdd11223344"

        loaded = store.load(path)
        assert loaded == data

    def test_save_with_zero_message_id(self, store: AttachmentStore):
        data = b"placeholder"
        path = store.save("aabbccdd1122334455667788", 0, "photo.jpg", data)
        assert path.name == "0_photo.jpg"

    def test_save_sanitizes_filename(self, store: AttachmentStore):
        data = b"test"
        path = store.save("aabbccdd1122334455667788", 1, "../../etc/passwd", data)
        assert "etc" not in path.name
        assert ".." not in str(path.name)
        assert path.name == "1_passwd"

    def test_save_rejects_oversize(self, store: AttachmentStore):
        data = b"x" * 2048  # Exceeds 1KB limit
        with pytest.raises(ValueError, match="exceeds maximum"):
            store.save("aabbccdd1122334455667788", 1, "big.bin", data)

    def test_save_creates_peer_directory(self, store: AttachmentStore):
        data = b"test"
        path = store.save("deadbeef123456780000aaaa", 1, "file.txt", data)
        assert path.parent.name == "deadbeef12345678"
        assert path.parent.exists()

    def test_load_nonexistent_raises(self, store: AttachmentStore):
        """Loading a nonexistent file within the store raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            store.load(store.base_dir / "nonexistent" / "file.txt")


class TestAttachmentStoreRename:
    """Tests for rename_for_message."""

    def test_rename_updates_message_id(self, store: AttachmentStore):
        data = b"test"
        old_path = store.save("aabbccdd1122334455667788", 0, "photo.jpg", data)
        assert old_path.name == "0_photo.jpg"

        new_path = store.rename_for_message(old_path, 99)
        assert new_path.name == "99_photo.jpg"
        assert new_path.exists()
        assert not old_path.exists()
        assert store.load(new_path) == data

    def test_rename_nonexistent_returns_original(self, store: AttachmentStore):
        """TOCTOU-safe: rename of nonexistent returns original path."""
        path = store.base_dir / "somepeer" / "0_file.txt"
        result = store.rename_for_message(path, 42)
        assert result == path

    def test_rename_non_zero_prefix_unchanged(self, store: AttachmentStore):
        data = b"test"
        path = store.save("aabbccdd1122334455667788", 5, "photo.jpg", data)
        result = store.rename_for_message(path, 99)
        # Already has non-zero message_id prefix, should not change
        assert result == path


class TestAttachmentStoreDelete:
    """Tests for delete operations."""

    def test_delete_existing_file(self, store: AttachmentStore):
        data = b"test"
        path = store.save("aabbccdd1122334455667788", 1, "file.txt", data)
        assert path.exists()

        result = store.delete(path)
        assert result is True
        assert not path.exists()

    def test_delete_nonexistent_returns_false(self, store: AttachmentStore):
        """Deleting a nonexistent file within the store returns False."""
        fake = store.base_dir / "somepeer" / "file.txt"
        result = store.delete(fake)
        assert result is False

    def test_delete_for_peer(self, store: AttachmentStore):
        store.save("aabbccdd1122334455667788", 1, "a.txt", b"data1")
        store.save("aabbccdd1122334455667788", 2, "b.txt", b"data2")
        store.save("11111111ffffffff00002222", 3, "c.txt", b"data3")

        count = store.delete_for_peer("aabbccdd1122334455667788")
        assert count == 2

        # Other peer's files untouched
        peer_dir = store.base_dir / "11111111ffffffff"
        assert peer_dir.exists()
        assert len(list(peer_dir.iterdir())) == 1

    def test_delete_for_peer_nonexistent(self, store: AttachmentStore):
        count = store.delete_for_peer("nonexistent12345678901234")
        assert count == 0


class TestAttachmentStoreBudget:
    """Tests for budget enforcement."""

    def test_get_usage(self, store: AttachmentStore):
        store.save("aabbccdd1122334455667788", 1, "a.txt", b"x" * 100)
        store.save("aabbccdd1122334455667788", 2, "b.txt", b"y" * 200)

        used, budget = store.get_usage()
        assert used == 300
        assert budget == 4096

    def test_enforce_budget_evicts_oldest(self, tmp_path: Path):
        # Very small budget to trigger eviction
        store = AttachmentStore(
            base_dir=tmp_path / "attachments",
            max_file_size=1024,
            storage_budget=500,
        )

        peer = "aabbccdd1122334455667788"

        # Save files that exceed budget
        store.save(peer, 1, "old.txt", b"x" * 200)
        p1 = store.base_dir / peer[:PEER_DIR_PREFIX_LEN] / "1_old.txt"
        os.utime(p1, (1000, 1000))

        store.save(peer, 2, "mid.txt", b"y" * 200)
        p2 = store.base_dir / peer[:PEER_DIR_PREFIX_LEN] / "2_mid.txt"
        os.utime(p2, (2000, 2000))

        store.save(peer, 3, "new.txt", b"z" * 200)

        # Manually enforce budget (no longer called from save())
        store.enforce_budget()

        # Oldest file should have been evicted
        assert not p1.exists()
        # Newest should still exist
        p3 = store.base_dir / peer[:PEER_DIR_PREFIX_LEN] / "3_new.txt"
        assert p3.exists()

    def test_enforce_budget_noop_under_budget(self, store: AttachmentStore):
        store.save("aabbccdd1122334455667788", 1, "small.txt", b"tiny")
        freed = store.enforce_budget()
        assert freed == 0

    def test_save_does_not_call_enforce_budget(self, store: AttachmentStore):
        """Saving should NOT trigger budget enforcement (perf fix)."""
        store.save("aabbccdd1122334455667788", 1, "a.txt", b"x" * 100)
        store.save("aabbccdd1122334455667788", 2, "b.txt", b"y" * 100)
        # Both files exist — no eviction happened
        peer_dir = store.base_dir / "aabbccdd11223344"
        assert len(list(peer_dir.iterdir())) == 2


class TestAttachmentStoreEdgeCases:
    """Edge case tests."""

    def test_save_with_mime_type(self, store: AttachmentStore):
        """MIME type is accepted but only used for logging."""
        path = store.save(
            "aabbccdd1122334455667788", 1, "photo.jpg", b"data", mime="image/jpeg"
        )
        assert path.exists()

    def test_save_empty_data(self, store: AttachmentStore):
        path = store.save("aabbccdd1122334455667788", 1, "empty.txt", b"")
        assert path.exists()
        assert store.load(path) == b""

    def test_multiple_saves_same_name(self, store: AttachmentStore):
        """Second save with same message_id/filename overwrites."""
        store.save("aabbccdd1122334455667788", 1, "file.txt", b"first")
        path = store.save("aabbccdd1122334455667788", 1, "file.txt", b"second")
        assert store.load(path) == b"second"


class TestPathContainment:
    """Tests for path traversal prevention (Batch 1a)."""

    def test_load_absolute_path_outside_rejected(self, store: AttachmentStore):
        """Loading an absolute path outside the store raises ValueError."""
        with pytest.raises(ValueError, match="Path escapes attachment store"):
            store.load("/etc/passwd")

    def test_load_relative_traversal_rejected(self, store: AttachmentStore):
        """Loading a relative path that escapes the store raises ValueError."""
        with pytest.raises(ValueError, match="Path escapes attachment store"):
            store.load("../../etc/passwd")

    def test_load_symlink_escape_rejected(self, store: AttachmentStore, tmp_path: Path):
        """A symlink inside base_dir pointing outside raises ValueError."""
        # Create a file outside the store
        outside = tmp_path / "outside_secret.txt"
        outside.write_text("secret data")

        # Create symlink inside the store pointing to it
        link = store.base_dir / "escape_link"
        link.symlink_to(outside)

        with pytest.raises(ValueError, match="Path escapes attachment store"):
            store.load(link)

    def test_delete_traversal_rejected(self, store: AttachmentStore):
        """Deleting a path that escapes the store raises ValueError."""
        with pytest.raises(ValueError, match="Path escapes attachment store"):
            store.delete("../../etc/important")

    def test_delete_absolute_outside_rejected(self, store: AttachmentStore):
        """Deleting an absolute path outside the store raises ValueError."""
        with pytest.raises(ValueError, match="Path escapes attachment store"):
            store.delete("/tmp/some_other_file")

    def test_load_valid_path_still_works(self, store: AttachmentStore):
        """Regression: normal load within base_dir succeeds."""
        data = b"valid data"
        path = store.save("aabbccdd1122334455667788", 1, "normal.txt", data)
        loaded = store.load(path)
        assert loaded == data

    def test_load_relative_within_store_works(self, store: AttachmentStore):
        """Relative paths within the store resolve correctly."""
        data = b"relative ok"
        store.save("aabbccdd1122334455667788", 1, "rel.txt", data)
        loaded = store.load("aabbccdd11223344/1_rel.txt")
        assert loaded == data


class TestSavePathContainment:
    """Tests for save() path containment (C1)."""

    def test_save_normal_filename_succeeds(self, store: AttachmentStore):
        """Normal save() calls succeed with containment check."""
        path = store.save("aabbccdd1122334455667788", 1, "normal.txt", b"data")
        assert path.exists()

    def test_save_traversal_filename_is_sanitized(self, store: AttachmentStore):
        """Filenames with path traversal are sanitized before containment check."""
        # The sanitizer strips directory components, so ../../etc/passwd becomes passwd
        path = store.save("aabbccdd1122334455667788", 1, "../../etc/passwd", b"data")
        assert path.exists()
        assert ".." not in str(path)


class TestDeleteForPeerContainment:
    """Tests for delete_for_peer() containment (W10)."""

    def test_delete_for_peer_normal_succeeds(self, store: AttachmentStore):
        """Normal delete_for_peer() works with containment check."""
        store.save("aabbccdd1122334455667788", 1, "file.txt", b"data")
        count = store.delete_for_peer("aabbccdd1122334455667788")
        assert count == 1

    def test_delete_for_peer_nonexistent_returns_zero(self, store: AttachmentStore):
        """delete_for_peer() for nonexistent peer returns 0 (exits before containment check)."""
        count = store.delete_for_peer("ffffffff0000000011111111")
        assert count == 0


class TestPeerDirPrefix:
    """Tests for 16-char peer directory prefix (Batch 3c)."""

    def test_peer_dir_uses_16_chars(self, store: AttachmentStore):
        """Peer directory should use first 16 chars of the hash."""
        peer = "aabbccdd11223344eeff5566"
        path = store.save(peer, 1, "file.txt", b"data")
        assert path.parent.name == "aabbccdd11223344"

    def test_peer_dir_migrates_8_to_16(self, store: AttachmentStore):
        """If legacy 8-char dir exists, it should be renamed to 16-char."""
        peer = "aabbccdd1122334455667788"
        # Manually create old-style 8-char directory with a file
        old_dir = store.base_dir / peer[:8]
        old_dir.mkdir(parents=True)
        (old_dir / "1_old.txt").write_bytes(b"old data")

        # Save triggers _peer_dir which should migrate
        path = store.save(peer, 2, "new.txt", b"new data")

        # Old dir should be gone, new dir should exist
        new_dir = store.base_dir / peer[:PEER_DIR_PREFIX_LEN]
        assert new_dir.exists()
        assert not old_dir.exists()
        # Old file should have been migrated
        assert (new_dir / "1_old.txt").exists()
        assert (new_dir / "1_old.txt").read_bytes() == b"old data"
        # New file should be in new dir
        assert path.parent == new_dir

    def test_different_peers_same_8_prefix_separate_dirs(self, store: AttachmentStore):
        """Peers sharing same 8-char prefix get separate 16-char dirs."""
        peer_a = "aabbccdd11111111aaaaaaaa"
        peer_b = "aabbccdd22222222bbbbbbbb"

        store.save(peer_a, 1, "a.txt", b"data_a")
        store.save(peer_b, 1, "b.txt", b"data_b")

        dir_a = store.base_dir / peer_a[:PEER_DIR_PREFIX_LEN]
        dir_b = store.base_dir / peer_b[:PEER_DIR_PREFIX_LEN]

        assert dir_a.exists()
        assert dir_b.exists()
        assert dir_a != dir_b
        assert len(list(dir_a.iterdir())) == 1
        assert len(list(dir_b.iterdir())) == 1
