"""CommsSummaryWidget — rich communications summary panel for the dashboard.

Shows:
  - Mail: unread count + per-conversation previews (sender, snippet, age)
  - Conversations: recent threads even when no unread
  - Direct: active direct-link session count
  - Contacts: contact count
  - Auto-reply: on/off
"""

from __future__ import annotations

import time
from typing import Any

from textual.app import ComposeResult
from textual.widgets import Static

_POLL_INTERVAL = 10.0


def _age(ts: float | int | None) -> str:
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


def _trunc(text: str, n: int) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


class CommsSummaryWidget(Static):
    """Rich comms summary: mail previews, direct sessions, contacts."""

    DEFAULT_CSS = """
    CommsSummaryWidget {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._conversations: list[dict[str, Any]] = []
        self._contact_count: int = 0
        self._active_links: int = 0
        self._auto_reply: bool = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_mount(self) -> None:
        self._refresh()
        self.set_interval(_POLL_INTERVAL, self._refresh)

    def _refresh(self) -> None:
        self.run_worker(self._fetch_and_render(), exclusive=True)

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    async def _fetch_and_render(self) -> None:
        bridge = self._bridge
        if bridge is not None:
            try:
                self._conversations = await bridge.get_conversations() or []
            except Exception:
                self._conversations = []
            try:
                status = await bridge.get_status()
                self._active_links = getattr(status, "active_links", 0) or 0
                self._auto_reply = getattr(status, "auto_reply_enabled", False)
            except Exception:
                pass
            try:
                cfg = await bridge.get_core_config()
                if isinstance(cfg, dict):
                    contacts = cfg.get("contacts") or []
                    self._contact_count = len(contacts)
            except Exception:
                pass

        self.update(self._build_markup())

    def _unread_from_db(self) -> int:
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
        dim = "dim"
        hi = "#5f9ea0"
        bright = "#a8d8d8"
        warn = "#ffaf5f"

        unread_total = self._unread_from_db()

        # ── MAIL ──────────────────────────────────────────────────────
        lines.append(f"[bold {hi}]MAIL[/]")
        if unread_total:
            lines.append(f"  [{warn} bold]✉ {unread_total} unread[/]")
        else:
            lines.append(f"  [{dim}]no unread[/]")

        # Sort convos: unread first, then by recency
        sorted_convos = sorted(
            self._conversations,
            key=lambda c: (
                -(c.get("unread_count") or 0),
                -(c.get("latest_timestamp") or c.get("timestamp") or 0),
            ),
        )

        shown = 0
        for conv in sorted_convos[:8]:
            name = (
                conv.get("display_name")
                or conv.get("sender_name")
                or (conv.get("peer_hash") or "")[:10]
                or "unknown"
            )
            snippet = conv.get("latest_snippet") or conv.get("preview") or ""
            ts = conv.get("latest_timestamp") or conv.get("timestamp")
            unread = conv.get("unread_count") or 0
            age = _age(ts)

            unread_badge = f"[{warn} bold]({unread})[/] " if unread else "  "
            lines.append(
                f"  {unread_badge}[{bright}]{_trunc(name, 20)}[/]"
                f"  [{dim}]{_trunc(snippet, 36)}[/]"
                f"  [{hi}]{age}[/]"
            )
            shown += 1

        if not shown:
            lines.append(f"  [{dim}]no conversations yet[/]")

        lines.append("")

        # ── DIRECT ────────────────────────────────────────────────────
        lines.append(f"[bold {hi}]DIRECT[/]")
        if self._active_links:
            lines.append(f"  [{bright}]{self._active_links} active session(s)[/]")
        else:
            lines.append(f"  [{dim}]no active sessions[/]")

        lines.append("")

        # ── CONTACTS ──────────────────────────────────────────────────
        lines.append(f"[bold {hi}]CONTACTS[/]")
        if self._contact_count:
            lines.append(f"  [{bright}]{self._contact_count} contact(s)[/]")
        else:
            lines.append(f"  [{dim}]none[/]")

        if self._auto_reply:
            lines.append(f"  [bold {hi}]auto-reply:[/] [{bright}]on[/]")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Textual overrides
    # ------------------------------------------------------------------

    def compose(self) -> ComposeResult:
        yield Static(self._build_markup(), id="comms-summary-inner")

    def update(self, markup: str) -> None:  # type: ignore[override]
        try:
            self.query_one("#comms-summary-inner", Static).update(markup)
        except Exception:
            pass
