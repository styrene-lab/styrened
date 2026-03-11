"""CommsSummaryWidget — scannable communications summary panel.

Polls IPC for conversation data and renders an at-a-glance summary of:
  1. Unread message count + up to 3 preview lines (sender, snippet, age)
  2. Active direct sessions count (from get_conversations)
  3. Bookmarked pages count (stubbed at 0 — no bookmark IPC exists yet)
"""

from __future__ import annotations

import datetime
import time
from typing import Any

from textual.app import ComposeResult
from textual.widgets import Static

_POLL_INTERVAL = 10.0  # seconds


def _age(ts: float | int | None) -> str:
    """Convert a Unix timestamp to a short human-readable age string."""
    if ts is None:
        return "?"
    delta = time.time() - float(ts)
    if delta < 60:
        return f"{int(delta)}s"
    if delta < 3600:
        return f"{int(delta // 60)}m"
    if delta < 86400:
        return f"{int(delta // 3600)}h"
    return f"{int(delta // 86400)}d"


def _truncate(text: str, max_len: int = 40) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


class CommsSummaryWidget(Static):
    """Compact comms summary: unread messages, active sessions, bookmarks."""

    DEFAULT_CSS = """
    CommsSummaryWidget {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._conversations: list[dict[str, Any]] = []
        self._unread_count: int = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(_POLL_INTERVAL, self._refresh)

    # ------------------------------------------------------------------
    # Data fetching
    # ------------------------------------------------------------------

    def _refresh(self) -> None:
        """Schedule async data fetch then re-render."""
        self.run_worker(self._fetch_and_render(), exclusive=True)

    async def _fetch_and_render(self) -> None:
        bridge = self._bridge
        if bridge is not None:
            try:
                self._conversations = await bridge.get_conversations()  # type: ignore[union-attr]
            except Exception:
                self._conversations = []

        # Unread count from DB (same pattern as DashboardScreen.get_unread_count)
        self._unread_count = self._count_unread_from_db()
        self.update(self._build_markup())

    def _count_unread_from_db(self) -> int:
        """Count unread messages using app.db_engine + app.local_identity_hash."""
        try:
            db_engine = getattr(self.app, "db_engine", None)
            identity_hash = getattr(self.app, "local_identity_hash", None)
            if db_engine is None or not identity_hash:
                return 0
            from sqlalchemy.orm import Session

            from styrened.models.messages import Message

            with Session(db_engine) as session:
                return (
                    session.query(Message)
                    .filter(
                        Message.protocol_id == "chat",
                        Message.status == "pending",
                        Message.destination_hash == identity_hash,
                    )
                    .count()
                )
        except Exception:
            return 0

    @property
    def _bridge(self) -> Any:
        try:
            return self.app.services.bridge  # type: ignore[attr-defined]
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Rendering
    # ------------------------------------------------------------------

    def _build_markup(self) -> str:
        lines: list[str] = []

        # Section header
        lines.append("[bold #5f9ea0]◈ COMMS SUMMARY[/]")

        # --- Unread messages ---
        unread = self._unread_count
        if unread:
            badge = f"[bold #ffaf5f]{unread}[/]"
            lines.append(f"  [#5f9ea0]Unread[/] {badge}")
        else:
            lines.append("  [#5f9ea0]Unread[/] [dim]0[/]")

        # Up to 3 preview lines from most-recent conversations with pending messages
        previews = self._build_previews(3)
        for sender, snippet, ts in previews:
            age = _age(ts)
            lines.append(
                f"    [bold #d7d7af]{_truncate(sender, 18)}[/]"
                f"  [dim]{_truncate(snippet, 32)}[/]"
                f"  [#5f9ea0]{age}[/]"
            )

        # --- Active direct sessions ---
        sessions = len(self._conversations)
        lines.append(f"  [#5f9ea0]Sessions[/] {sessions if sessions else '[dim]0[/]'}")

        # --- Bookmarks (stub) ---
        lines.append("  [#5f9ea0]Bookmarks[/] [dim]0[/]")

        return "\n".join(lines)

    def _build_previews(self, limit: int) -> list[tuple[str, str, float | None]]:
        """Extract sender/snippet/timestamp tuples from unread conversations."""
        previews: list[tuple[str, str, float | None]] = []
        # Sort by latest message timestamp descending
        candidates = sorted(
            self._conversations,
            key=lambda c: c.get("latest_timestamp") or c.get("timestamp") or 0,
            reverse=True,
        )
        for conv in candidates:
            if len(previews) >= limit:
                break
            unread = conv.get("unread_count", 0)
            if not unread:
                continue
            sender = (
                conv.get("display_name")
                or conv.get("sender_name")
                or conv.get("peer_hash", "unknown")[:12]
            )
            snippet = conv.get("latest_snippet") or conv.get("preview") or ""
            ts = conv.get("latest_timestamp") or conv.get("timestamp")
            previews.append((str(sender), str(snippet), float(ts) if ts is not None else None))
        return previews

    def compose(self) -> ComposeResult:
        # Initial placeholder — updated by _fetch_and_render
        yield Static(self._build_markup(), id="comms-summary-inner")

    def update(self, markup: str) -> None:  # type: ignore[override]
        """Push fresh markup into the inner Static."""
        try:
            inner = self.query_one("#comms-summary-inner", Static)
            inner.update(markup)
        except Exception:
            pass
