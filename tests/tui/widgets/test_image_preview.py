"""Tests for ImagePreview widget and inline image rendering in MessageBubble.

Covers:
- Module-level capability flags (_HAS_IMAGE_WIDGET, _HAS_PILLOW)
- ImagePreview widget initial state and reactive properties
- MessageBubble compose() yields correct children for text, image, and audio
"""
from __future__ import annotations

import pytest
from textual.widgets import Static

from styrened.tui.widgets.image_preview import (
    _HAS_IMAGE_WIDGET,
    _HAS_PILLOW,
    ImagePreview,
    _human_size,
)
from styrened.tui.widgets.message_bubble import MessageBubble

# ---------------------------------------------------------------------------
# Availability flags
# ---------------------------------------------------------------------------


class TestImagePreviewAvailability:
    """Test module-level capability detection flags."""

    def test_has_image_widget_is_bool(self):
        """_HAS_IMAGE_WIDGET should be a boolean."""
        assert isinstance(_HAS_IMAGE_WIDGET, bool)

    def test_has_pillow_is_bool(self):
        """_HAS_PILLOW should be a boolean."""
        assert isinstance(_HAS_PILLOW, bool)

    def test_has_image_support_property(self):
        """has_image_support property matches _HAS_IMAGE_WIDGET."""
        widget = ImagePreview()
        assert widget.has_image_support == _HAS_IMAGE_WIDGET


# ---------------------------------------------------------------------------
# ImagePreview widget state
# ---------------------------------------------------------------------------


class TestImagePreviewWidget:
    """Test ImagePreview reactive state and initialization."""

    def test_initial_loading_false(self):
        """Widget starts with loading=False."""
        widget = ImagePreview()
        assert widget.loading is False

    def test_initial_error_empty(self):
        """Widget starts with empty error string."""
        widget = ImagePreview()
        assert widget.error == ""

    def test_initial_image_data_empty(self):
        """Widget starts with empty image data."""
        widget = ImagePreview()
        assert widget.image_data == b""

    def test_initial_filename_empty(self):
        """Widget starts with empty filename."""
        widget = ImagePreview()
        assert widget.filename == ""

    def test_set_loading(self):
        """Can set loading reactive property."""
        widget = ImagePreview()
        widget.loading = True
        assert widget.loading is True

    def test_set_error(self):
        """Can set error reactive property."""
        widget = ImagePreview()
        widget.error = "something broke"
        assert widget.error == "something broke"

    def test_set_filename(self):
        """Can set filename reactive property."""
        widget = ImagePreview()
        widget.filename = "photo.jpg"
        assert widget.filename == "photo.jpg"


# ---------------------------------------------------------------------------
# human_size helper
# ---------------------------------------------------------------------------


class TestHumanSize:
    """Test the _human_size helper function."""

    def test_bytes(self):
        assert _human_size(500) == "500 B"

    def test_kilobytes(self):
        assert _human_size(2048) == "2.0 KB"

    def test_megabytes(self):
        assert _human_size(5 * 1024 * 1024) == "5.0 MB"

    def test_gigabytes(self):
        assert _human_size(2 * 1024 * 1024 * 1024) == "2.0 GB"


# ---------------------------------------------------------------------------
# MessageBubble composition
# ---------------------------------------------------------------------------


class TestDecompressionBombProtection:
    """Tests for PIL decompression bomb limit (W21)."""

    def test_max_image_pixels_class_attribute(self):
        """ImagePreview should have a _MAX_IMAGE_PIXELS class attribute."""
        assert hasattr(ImagePreview, "_MAX_IMAGE_PIXELS")
        assert ImagePreview._MAX_IMAGE_PIXELS == 4_000_000

    def test_render_image_limits_max_pixels(self):
        """_render_image should temporarily set MAX_IMAGE_PIXELS to the limit."""
        if not _HAS_PILLOW:
            pytest.skip("Pillow not installed")

        from unittest.mock import patch as _patch

        from PIL import Image as PILImageModule

        original = PILImageModule.MAX_IMAGE_PIXELS
        observed_limits: list[int | None] = []

        real_open = PILImageModule.open

        def spy_open(*args, **kwargs):
            observed_limits.append(PILImageModule.MAX_IMAGE_PIXELS)
            return real_open(*args, **kwargs)

        # Create a tiny valid PNG
        import io

        img = PILImageModule.new("RGB", (2, 2), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()

        widget = ImagePreview()

        with _patch.object(PILImageModule, "open", side_effect=spy_open):
            # Call will fail on mount (widget not mounted) but PIL.open will
            # have been called first, so we can observe the limit.
            try:
                widget._render_image(data)
            except Exception:
                pass

        # PIL.open was called with the restricted limit
        assert len(observed_limits) > 0
        assert observed_limits[0] == ImagePreview._MAX_IMAGE_PIXELS

        # MAX_IMAGE_PIXELS should be restored to original
        assert PILImageModule.MAX_IMAGE_PIXELS == original

    def test_render_image_resets_on_exception(self):
        """_render_image should restore MAX_IMAGE_PIXELS even on PIL failure."""
        if not _HAS_PILLOW:
            pytest.skip("Pillow not installed")

        from PIL import Image as PILImageModule

        original = PILImageModule.MAX_IMAGE_PIXELS

        widget = ImagePreview()
        # Pass invalid data — PIL.open will fail, but limit must be restored
        try:
            widget._render_image(b"not-a-valid-image")
        except Exception:
            pass

        # MAX_IMAGE_PIXELS should be restored
        assert PILImageModule.MAX_IMAGE_PIXELS == original


class TestBubbleComposition:
    """Test MessageBubble.compose() yields correct children."""

    def test_bubble_composes_static_for_text_message(self):
        """Text-only message (no attachment) yields only a Static child."""
        bubble = MessageBubble(
            "Hello world",
            message_id=1,
            is_outgoing=True,
        )
        children = list(bubble.compose())
        assert len(children) == 1
        assert isinstance(children[0], Static)

    def test_bubble_composes_image_preview_for_image(self):
        """Image attachment yields Static + ImagePreview."""
        bubble = MessageBubble(
            "Check this photo",
            message_id=2,
            has_attachment=True,
            attachment_type="image",
            attachment_name="photo.jpg",
        )
        children = list(bubble.compose())
        assert len(children) == 2
        assert isinstance(children[0], Static)
        assert isinstance(children[1], ImagePreview)

    def test_bubble_composes_text_indicator_for_audio(self):
        """Audio attachment yields only Static (no ImagePreview)."""
        bubble = MessageBubble(
            "Voice note\n\U0001f50a recording.ogg",
            message_id=3,
            has_attachment=True,
            attachment_type="audio",
            attachment_name="recording.ogg",
        )
        children = list(bubble.compose())
        assert len(children) == 1
        assert isinstance(children[0], Static)

    def test_bubble_composes_text_indicator_for_file(self):
        """File attachment yields only Static (no ImagePreview)."""
        bubble = MessageBubble(
            "Document\n\U0001f4ce report.pdf",
            message_id=4,
            has_attachment=True,
            attachment_type="file",
            attachment_name="report.pdf",
        )
        children = list(bubble.compose())
        assert len(children) == 1
        assert isinstance(children[0], Static)

    def test_bubble_image_preview_has_correct_id(self):
        """ImagePreview child has id based on message_id."""
        bubble = MessageBubble(
            "Photo",
            message_id=99,
            has_attachment=True,
            attachment_type="image/jpeg",
            attachment_name="sunset.jpg",
        )
        children = list(bubble.compose())
        preview = children[1]
        assert preview.id == "bubble-img-99"

    def test_bubble_static_has_bubble_text_class(self):
        """Static child has the bubble-text CSS class."""
        bubble = MessageBubble("Test", message_id=1)
        children = list(bubble.compose())
        static = children[0]
        assert "bubble-text" in static.classes

    def test_bubble_update_text(self):
        """update_text stores new text value."""
        bubble = MessageBubble("Original", message_id=1)
        bubble.update_text("Updated")
        assert bubble._text == "Updated"

    def test_bubble_is_image_attachment_false_for_no_attachment(self):
        """_is_image_attachment is False when no attachment."""
        bubble = MessageBubble("Hello", message_id=1)
        assert bubble._is_image_attachment is False

    def test_bubble_is_image_attachment_true_for_image(self):
        """_is_image_attachment is True for image type."""
        bubble = MessageBubble(
            "Photo",
            message_id=1,
            has_attachment=True,
            attachment_type="image/png",
        )
        assert bubble._is_image_attachment is True

    def test_bubble_is_image_attachment_false_for_audio(self):
        """_is_image_attachment is False for audio type."""
        bubble = MessageBubble(
            "Audio",
            message_id=1,
            has_attachment=True,
            attachment_type="audio/ogg",
        )
        assert bubble._is_image_attachment is False

    def test_collapse_to_text_indicator_appends_fallback(self):
        """_collapse_to_text_indicator appends attachment line to bubble text."""
        bubble = MessageBubble(
            "Check this photo",
            message_id=10,
            has_attachment=True,
            attachment_type="image/png",
            attachment_name="photo.png",
            attachment_size=1700,
        )
        bubble._collapse_to_text_indicator()
        assert "photo.png" in bubble._text
        assert "1.7 KB" in bubble._text
        assert "Check this photo" in bubble._text

    def test_collapse_to_text_indicator_no_size(self):
        """_collapse_to_text_indicator works when attachment_size is None."""
        bubble = MessageBubble(
            "Image",
            message_id=11,
            has_attachment=True,
            attachment_type="image",
            attachment_name="pic.jpg",
        )
        bubble._collapse_to_text_indicator()
        assert "pic.jpg" in bubble._text
        assert "()" not in bubble._text
