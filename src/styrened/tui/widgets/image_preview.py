"""Image preview widget with progressive terminal rendering.

Wraps textual-image for in-terminal image display with graceful fallback
when the library is not installed. Supports Kitty TGP, Sixel, and
Unicode halfblock rendering depending on terminal capabilities.
"""

import io
import logging

from textual.app import ComposeResult
from textual.reactive import reactive
from textual.widget import Widget
from textual.widgets import Static

logger = logging.getLogger(__name__)

# Independent capability flags
try:
    from textual_image.widget import Image as TextualImage

    _HAS_IMAGE_WIDGET = True
except ImportError:
    TextualImage = None  # type: ignore[assignment,misc]
    _HAS_IMAGE_WIDGET = False

try:
    from PIL import Image as PILImage

    _HAS_PILLOW = True
except ImportError:
    PILImage = None  # type: ignore[assignment,misc]
    _HAS_PILLOW = False


def _human_size(size: int) -> str:
    """Format byte count as human-readable string."""
    if size < 1024:
        return f"{size} B"
    elif size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    elif size < 1024 * 1024 * 1024:
        return f"{size / (1024 * 1024):.1f} MB"
    return f"{size / (1024 * 1024 * 1024):.1f} GB"


class ImagePreview(Widget):
    """Image preview with reactive loading/error/data states.

    When textual-image is available, renders the image in the terminal
    using the best available protocol (Kitty TGP > Sixel > halfblock).
    Falls back to metadata display when unavailable.

    Attributes:
        loading: Whether image data is being fetched.
        error: Error message if fetch/decode failed, empty string if OK.
        image_data: Raw image bytes (set externally to trigger render).
        filename: Display filename for the image.
    """

    loading: reactive[bool] = reactive(False)
    error: reactive[str] = reactive("")
    image_data: reactive[bytes] = reactive(b"")
    filename: reactive[str] = reactive("")

    DEFAULT_CSS = """
    ImagePreview {
        height: auto;
        width: 1fr;
    }

    ImagePreview #image-status {
        height: auto;
        color: $panel;
        padding: 0 1;
    }

    ImagePreview #image-fallback {
        height: auto;
        width: 1fr;
        padding: 0 1;
    }
    """

    @property
    def has_image_support(self) -> bool:
        """Whether in-terminal image rendering is available."""
        return _HAS_IMAGE_WIDGET

    def compose(self) -> ComposeResult:
        yield Static("", id="image-status")

    def watch_loading(self, loading: bool) -> None:
        """React to loading state changes."""
        try:
            status = self.query_one("#image-status", Static)
            if loading:
                status.update("[dim]Loading image...[/]")
            elif not self.error:
                status.update("")
        except Exception:
            pass

    def watch_error(self, error: str) -> None:
        """React to error state changes."""
        if not error:
            return
        try:
            status = self.query_one("#image-status", Static)
            status.update(f"[red]{error}[/]")
        except Exception:
            pass

    def watch_image_data(self, data: bytes) -> None:
        """React to image data changes — render or show fallback."""
        if not data:
            return
        self.loading = False
        self.error = ""
        self._render_image(data)

    def _clear_image_content(self) -> None:
        """Remove any previously rendered image or fallback content."""
        for child_id in ("#image-render", "#image-fallback"):
            try:
                self.query_one(child_id).remove()
            except Exception:
                pass

    # Maximum pixel count for untrusted images (2000x2000)
    _MAX_IMAGE_PIXELS = 4_000_000

    def _render_image(self, data: bytes) -> None:
        """Decode and display image data."""
        self._clear_image_content()

        status_widget = None
        try:
            status_widget = self.query_one("#image-status", Static)
        except Exception:
            pass

        if _HAS_IMAGE_WIDGET and _HAS_PILLOW:
            try:
                saved_max = PILImage.MAX_IMAGE_PIXELS
                PILImage.MAX_IMAGE_PIXELS = self._MAX_IMAGE_PIXELS
                try:
                    pil_img = PILImage.open(io.BytesIO(data))
                finally:
                    PILImage.MAX_IMAGE_PIXELS = saved_max
                img_widget = TextualImage(pil_img)
                img_widget.id = "image-render"

                # Mount directly as child of ImagePreview (before the
                # status line) so Textual's layout engine calls the
                # widget's get_content_height() without an intermediate
                # container swallowing the sizing request.
                if status_widget is not None:
                    self.mount(img_widget, before=status_widget)
                else:
                    self.mount(img_widget)

                # Show metadata in status
                w, h = pil_img.size
                size_str = _human_size(len(data))
                status_text = f"[dim]{self.filename}  {w}x{h}  {size_str}[/]"
                if status_widget is not None:
                    status_widget.update(status_text)
                return
            except Exception as e:
                logger.warning(f"Failed to render image: {e}")
                self.error = f"Render failed: {e}"

        # Fallback: show metadata text
        self._show_fallback(data)

    def _show_fallback(self, data: bytes) -> None:
        """Show text fallback when image rendering is unavailable."""
        self._clear_image_content()

        lines: list[str] = []
        if self.filename:
            lines.append(f"[bold]{self.filename}[/]")

        size_str = _human_size(len(data))
        lines.append(f"Size: {size_str}")

        if _HAS_PILLOW:
            try:
                saved_max = PILImage.MAX_IMAGE_PIXELS
                PILImage.MAX_IMAGE_PIXELS = self._MAX_IMAGE_PIXELS
                try:
                    pil_img = PILImage.open(io.BytesIO(data))
                finally:
                    PILImage.MAX_IMAGE_PIXELS = saved_max
                w, h = pil_img.size
                lines.append(f"Dimensions: {w}x{h}")
                lines.append(f"Format: {pil_img.format or 'unknown'}")
            except Exception:
                pass

        if not _HAS_IMAGE_WIDGET:
            lines.append("")
            lines.append("[dim]Install textual-image for in-terminal preview[/]")

        fallback = Static("\n".join(lines), id="image-fallback")
        try:
            status_widget = self.query_one("#image-status", Static)
            self.mount(fallback, before=status_widget)
        except Exception:
            self.mount(fallback)
