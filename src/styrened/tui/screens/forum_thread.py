"""Forum-thread placeholder screen for Pages-adjacent Mail/forum routing."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Static

from styrened.tui.widgets.safe_header import Header
from styrened.ui_state import ForumThreadMeta


class ForumThreadScreen(Screen[None]):
    """Placeholder destination for topic-centric forum discussions."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(
        self,
        thread_id: str,
        display_name: str,
        forum: ForumThreadMeta | None = None,
    ) -> None:
        super().__init__()
        self.thread_id = thread_id
        self.display_name = display_name
        self.forum = forum

    def compose(self) -> ComposeResult:
        topic_title = self.forum.topic_title if self.forum and self.forum.topic_title else self.display_name
        topic_id = self.forum.topic_id if self.forum else self.thread_id
        page_ref = self.forum.page_ref if self.forum else None

        yield Header()
        with Container(id="forum-thread-container"):
            yield Static(f"[bold]{topic_title}[/]", id="forum-thread-title")
            yield Static(f"Topic ID: {topic_id}", id="forum-thread-topic-id")
            if page_ref:
                yield Static(f"Page Ref: {page_ref}", id="forum-thread-page-ref")
            yield Static(
                "This placeholder marks the future Pages-adjacent destination for forum/topic discussion. "
                "It is intentionally separate from direct peer Mail threads.",
                id="forum-thread-placeholder",
            )
        yield Footer()
