"""Safe Header patch — prevents NoMatches crash in Textual 8.x Header.

Textual 8.1.x Header._on_mount() sets up watchers that call
query_one(HeaderTitle), which can raise NoMatches when the Header's
children haven't fully composed or the screen is mid-transition.
The upstream code only catches NoScreen.

Textual's handler dispatch walks the MRO and calls each class's _on_mount
independently, so subclass overrides don't prevent the parent handler
from firing. We monkey-patch the stock Header class directly.

Usage: ``import styrened.tui.widgets.safe_header``  (side-effect import)
Then use ``from textual.widgets import Header`` normally.
"""

from __future__ import annotations

from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.widgets._header import Header, HeaderTitle


def _safe_on_mount(self: Header, _: object) -> None:
    """Replacement _on_mount that catches NoMatches alongside NoScreen."""

    async def set_title() -> None:
        try:
            self.query_one(HeaderTitle).update(self.format_title())
        except (NoMatches, NoScreen):
            pass

    self.watch(self.app, "title", set_title)
    self.watch(self.app, "sub_title", set_title)
    try:
        self.watch(self.screen, "title", set_title)
        self.watch(self.screen, "sub_title", set_title)
    except NoScreen:
        pass


# Monkey-patch the stock Header class
Header._on_mount = _safe_on_mount  # type: ignore[assignment]
