"""Tests for macOS clipboard integration."""
from __future__ import annotations


import base64
from unittest.mock import patch

from styrened.tui.menubar.clipboard import (
    ClipboardAttachment,
    _attachment_from_path,
    _generate_screenshot_name,
    _looks_like_path,
    _tiff_to_png,
)


class TestLooksLikePath:
    def test_absolute_path(self):
        assert _looks_like_path("/Users/test/file.png") is True

    def test_home_relative(self):
        assert _looks_like_path("~/Downloads/file.jpg") is True

    def test_dot_relative(self):
        assert _looks_like_path("./image.png") is True

    def test_plain_text(self):
        assert _looks_like_path("hello world") is False

    def test_empty(self):
        assert _looks_like_path("") is False

    def test_multiline(self):
        assert _looks_like_path("/path/to\nfile") is False

    def test_very_long(self):
        assert _looks_like_path("/" + "a" * 600) is False

    def test_windows_path(self):
        assert _looks_like_path("C:\\Users\\test") is True


class TestGenerateScreenshotName:
    def test_png_extension(self):
        name = _generate_screenshot_name("png")
        assert name.startswith("screenshot_")
        assert name.endswith(".png")

    def test_jpg_extension(self):
        name = _generate_screenshot_name("jpg")
        assert name.endswith(".jpg")

    def test_timestamp_format(self):
        name = _generate_screenshot_name("png")
        # screenshot_YYYYMMDD_HHMMSS.png
        parts = name.replace("screenshot_", "").replace(".png", "")
        assert len(parts) == 15  # YYYYMMDD_HHMMSS


class TestAttachmentFromPath:
    def test_valid_image(self, tmp_path):
        img = tmp_path / "test.png"
        img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 100)

        with patch("styrened.services.attachment_store.DEFAULT_MAX_FILE_SIZE", 1024 * 1024):
            result = _attachment_from_path(img, source="file")

        assert result is not None
        assert result.filename == "test.png"
        assert result.mime == "image/png"
        assert result.source == "file"
        assert result.size == 108

    def test_nonexistent_file(self, tmp_path):
        result = _attachment_from_path(tmp_path / "nope.png", source="file")
        assert result is None

    def test_file_too_large(self, tmp_path):
        big = tmp_path / "huge.png"
        big.write_bytes(b"\x00" * 100)

        with patch("styrened.services.attachment_store.DEFAULT_MAX_FILE_SIZE", 50):
            result = _attachment_from_path(big, source="file")

        assert result is None

    def test_unknown_mime(self, tmp_path):
        f = tmp_path / "data.xyz123"
        f.write_bytes(b"some data")

        with patch("styrened.services.attachment_store.DEFAULT_MAX_FILE_SIZE", 1024 * 1024):
            result = _attachment_from_path(f, source="path")

        assert result is not None
        assert result.mime == "application/octet-stream"


class TestTiffToPng:
    def test_valid_tiff(self):
        """Convert a minimal valid image via Pillow."""
        from io import BytesIO

        from PIL import Image

        img = Image.new("RGB", (2, 2), color="red")
        buf = BytesIO()
        img.save(buf, format="TIFF")
        tiff_bytes = buf.getvalue()

        result = _tiff_to_png(tiff_bytes)
        assert result is not None
        assert result[:4] == b"\x89PNG"

    def test_invalid_data(self):
        result = _tiff_to_png(b"not a tiff")
        assert result is None


class TestClipboardAttachment:
    def test_dataclass_fields(self):
        att = ClipboardAttachment(
            data_b64="dGVzdA==",
            filename="test.png",
            mime="image/png",
            size=4,
            source="screenshot",
        )
        assert att.filename == "test.png"
        assert base64.b64decode(att.data_b64) == b"test"
