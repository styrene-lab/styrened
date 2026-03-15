"""Parent-owned lifecycle helpers for embedded screen content panes."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class ScreenContentHooks:
    """Lifecycle callbacks for one embedded content slot."""

    activate: Callable[[bool], None] | None = None
    resume: Callable[[], None] | None = None
    deactivate: Callable[[], None] | None = None
    suspend: Callable[[], None] | None = None
    cleanup: Callable[[], None] | None = None

    @classmethod
    def from_content(cls, content: Any) -> ScreenContentHooks:
        """Build hooks from a pane-like object with explicit lifecycle methods."""
        return cls(
            activate=getattr(content, "activate_content", None),
            resume=getattr(content, "resume_content", None),
            deactivate=getattr(content, "deactivate_content", None),
            suspend=getattr(content, "suspend_content", None),
            cleanup=getattr(content, "cleanup_content", None),
        )


class ScreenContentHost:
    """Translate parent screen lifecycle events into embedded pane hooks."""

    def __init__(self, owner: Any, *, owner_logger: logging.Logger | None = None) -> None:
        self._owner = owner
        self._logger = owner_logger or logger
        self._slots: dict[str, ScreenContentHooks] = {}
        self._active_slot_id: str | None = None
        self._activated_slots: set[str] = set()

    @property
    def active_slot_id(self) -> str | None:
        """Currently active content slot, if any."""
        return self._active_slot_id

    def register(
        self,
        slot_id: str,
        content: Any | None = None,
        *,
        hooks: ScreenContentHooks | None = None,
    ) -> None:
        """Register one content slot by object or explicit hooks."""
        if hooks is None:
            hooks = ScreenContentHooks.from_content(content)
        self._slots[slot_id] = hooks

    def activate(self, slot_id: str) -> None:
        """Activate the requested slot, deactivating the previous one first."""
        hooks = self._slots.get(slot_id)
        if hooks is None:
            return

        previous_slot_id = self._active_slot_id
        if previous_slot_id == slot_id:
            return

        if previous_slot_id is not None:
            previous_hooks = self._slots.get(previous_slot_id)
            self._call(previous_hooks.deactivate if previous_hooks is not None else None)

        self._active_slot_id = slot_id
        if slot_id in self._activated_slots:
            resumed = self._call(hooks.resume)
            if not resumed:
                self._call_activate(hooks, initial=False)
            return

        self._activated_slots.add(slot_id)
        self._call_activate(hooks, initial=True)

    def resume_active(self) -> None:
        """Resume the active slot after the parent screen resumes."""
        if self._active_slot_id is None:
            return
        hooks = self._slots.get(self._active_slot_id)
        if hooks is None:
            return
        was_activated = self._active_slot_id in self._activated_slots
        if was_activated:
            resumed = self._call(hooks.resume)
            if resumed:
                return
        else:
            self._activated_slots.add(self._active_slot_id)
        self._call_activate(hooks, initial=not was_activated)

    def suspend_active(self) -> None:
        """Suspend only the currently active slot."""
        if self._active_slot_id is None:
            return
        hooks = self._slots.get(self._active_slot_id)
        if hooks is None:
            return
        suspended = self._call(hooks.suspend)
        if not suspended:
            self._call(hooks.deactivate)

    def cleanup_all(self) -> None:
        """Fan out final cleanup to all registered slots."""
        self.suspend_active()
        for hooks in self._slots.values():
            self._call(hooks.cleanup)
        self._active_slot_id = None
        self._activated_slots.clear()

    def _call_activate(self, hooks: ScreenContentHooks, *, initial: bool) -> None:
        callback = hooks.activate
        if callback is None:
            hooks.resume and self._call(hooks.resume)
            return
        try:
            callback(initial)
        except Exception:
            self._logger.debug("Embedded screen content activate failed", exc_info=True)

    def _call(self, callback: Callable[[], None] | None) -> bool:
        if callback is None:
            return False
        try:
            callback()
            return True
        except Exception:
            self._logger.debug("Embedded screen content lifecycle callback failed", exc_info=True)
            return True
