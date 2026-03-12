"""macOS clipboard integration for attachment staging.

Reads image data and file references from the system clipboard using
PyObjC (AppKit). Falls back to pbpaste for text content.

Clipboard content priority:
1. Image data (PNG/TIFF) — screenshot utilities, copy image
2. File URL references — Finder copy, file manager
3. Text that looks like a file path — terminal copy of path
4. Plain text — not an attachment, let it paste normally
"""
from __future__ import annotations


import base64
import logging
import mimetypes
import platform
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class ClipboardAttachment:
    """Attachment data extracted from the clipboard."""

    data_b64: str
    filename: str
    mime: str
    size: int
    source: str  # "screenshot", "image_copy", "file", "path"


def read_clipboard_attachment() -> ClipboardAttachment | None:
    """Read attachment data from the macOS clipboard.

    Returns ClipboardAttachment if the clipboard contains image data
    or a file reference, None if it's just text.
    """
    if platform.system() != "Darwin":
        return None

    try:
        return _read_clipboard_darwin()
    except Exception as e:
        logger.debug(f"Clipboard read failed: {e}")
        return None


def _read_clipboard_darwin() -> ClipboardAttachment | None:
    """Read clipboard on macOS via PyObjC."""
    try:
        from AppKit import (
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeTIFF,
        )
    except ImportError:
        logger.debug("AppKit not available, falling back to text-only")
        return _read_clipboard_text_fallback()

    pb = NSPasteboard.generalPasteboard()
    types = pb.types() or []

    # Priority 1: PNG image data (screenshots produce this)
    if NSPasteboardTypePNG in types:
        data = pb.dataForType_(NSPasteboardTypePNG)
        if data and len(data) > 0:
            raw = bytes(data)
            return ClipboardAttachment(
                data_b64=base64.b64encode(raw).decode("ascii"),
                filename=_generate_screenshot_name("png"),
                mime="image/png",
                size=len(raw),
                source="screenshot",
            )

    # Priority 2: TIFF image data (some apps copy as TIFF)
    if NSPasteboardTypeTIFF in types:
        data = pb.dataForType_(NSPasteboardTypeTIFF)
        if data and len(data) > 0:
            raw = bytes(data)
            # Convert TIFF to PNG for smaller size and wider compat
            png_data = _tiff_to_png(raw)
            if png_data:
                return ClipboardAttachment(
                    data_b64=base64.b64encode(png_data).decode("ascii"),
                    filename=_generate_screenshot_name("png"),
                    mime="image/png",
                    size=len(png_data),
                    source="image_copy",
                )

    # Priority 3: File URL references (Finder copy)
    file_url_type = "public.file-url"
    if file_url_type in types:
        url_str = pb.stringForType_(file_url_type)
        if url_str and url_str.startswith("file://"):
            from urllib.parse import unquote, urlparse

            parsed = urlparse(url_str)
            file_path = Path(unquote(parsed.path))
            return _attachment_from_path(file_path, source="file")

    # Priority 4: Text content that looks like a file path
    text_types = ["public.utf8-plain-text", "NSStringPboardType"]
    for tt in text_types:
        if tt in types:
            text = pb.stringForType_(tt)
            if text:
                stripped = text.strip()
                if _looks_like_path(stripped):
                    path = Path(stripped).expanduser()
                    if path.is_file():
                        return _attachment_from_path(path, source="path")
            break  # only check first available text type

    return None


def has_clipboard_image() -> bool:
    """Quick check if clipboard has image data without reading it."""
    if platform.system() != "Darwin":
        return False
    try:
        from AppKit import (
            NSPasteboard,
            NSPasteboardTypePNG,
            NSPasteboardTypeTIFF,
        )

        pb = NSPasteboard.generalPasteboard()
        types = pb.types() or []
        return NSPasteboardTypePNG in types or NSPasteboardTypeTIFF in types
    except ImportError:
        return False


def _looks_like_path(text: str) -> bool:
    """Heuristic: does this text look like a file path?"""
    if not text:
        return False
    if "\n" in text:
        return False
    if len(text) > 500:
        return False
    return text.startswith(("/", "~", ".")) or (len(text) > 2 and text[1] == ":")


def _attachment_from_path(path: Path, source: str) -> ClipboardAttachment | None:
    """Build a ClipboardAttachment from a file path."""
    from styrened.services.attachment_store import DEFAULT_MAX_FILE_SIZE

    if not path.is_file():
        return None

    try:
        size = path.stat().st_size
    except OSError:
        return None

    if size > DEFAULT_MAX_FILE_SIZE:
        logger.debug(f"File too large for attachment: {size}")
        return None

    try:
        data = path.read_bytes()
    except OSError:
        return None

    mime_type, _ = mimetypes.guess_type(str(path))
    if not mime_type:
        mime_type = "application/octet-stream"

    return ClipboardAttachment(
        data_b64=base64.b64encode(data).decode("ascii"),
        filename=path.name,
        mime=mime_type,
        size=len(data),
        source=source,
    )


def _generate_screenshot_name(ext: str) -> str:
    """Generate a timestamped screenshot filename."""
    import datetime

    ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"screenshot_{ts}.{ext}"


def _tiff_to_png(tiff_data: bytes) -> bytes | None:
    """Convert TIFF bytes to PNG bytes via Pillow."""
    try:
        import io

        from PIL import Image

        img = Image.open(io.BytesIO(tiff_data))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception as e:
        logger.debug(f"TIFF→PNG conversion failed: {e}")
        return None


def _read_clipboard_text_fallback() -> ClipboardAttachment | None:
    """Fallback: read clipboard text via pbpaste and check if it's a path."""
    import subprocess

    try:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            text=True,
            timeout=2,
        )
        text = result.stdout.strip()
        if text and _looks_like_path(text):
            path = Path(text).expanduser()
            if path.is_file():
                return _attachment_from_path(path, source="path")
    except Exception:
        pass

    return None
