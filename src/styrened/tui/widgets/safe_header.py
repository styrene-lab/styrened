"""Safe Header wrapper — catches NoMatches during Textual 8.x title updates.

Textual 8.1.x Header._on_mount() sets up watchers that call
query_one(HeaderTitle), which can raise NoMatches when the Header's
children haven't fully composed or the screen is mid-transition.
The upstream code only catches NoScreen.

Drop-in replacement: ``from styrened.tui.widgets.safe_header import Header``
"""

from __future__ import annotations

import logging

from textual.css.query import NoMatches
from textual.dom import NoScreen
from textual.events import Mount
from textual.widgets import Header as _TextualHeader
from textual.widgets._header import HeaderTitle

log = logging.getLogger(__name__)


class Header(_TextualHeader):
    """Header subclass that tolerates missing HeaderTitle during mount."""

    def _on_mount(self, event: Mount) -> None:
        """Override to catch NoMatches alongside NoScreen."""

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
