"""Group-thread placeholder screen for Mail workspace migration."""

from __future__ import annotations

from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import Binding, BindingType
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Footer, Static

from styrened.tui.widgets.safe_header import Header
from styrened.ui_state import (
    DeliveryPathClass,
    GroupThreadFeatureTier,
    GroupThreadMeta,
    GroupThreadPolicy,
    MediaFrictionLevel,
)


class MailGroupThreadScreen(Screen[None]):
    """Placeholder destination for room-centric Mail group threads."""

    BINDINGS: ClassVar[list[BindingType]] = [
        Binding("escape", "app.pop_screen", "Back"),
    ]

    def __init__(
        self,
        thread_id: str,
        display_name: str,
        group: GroupThreadMeta | None = None,
    ) -> None:
        super().__init__()
        self.thread_id = thread_id
        self.display_name = display_name
        self.group = group

    def _policy_summary(self, policy: GroupThreadPolicy) -> str:
        flags: list[str] = [f"tier={policy.feature_tier.value}"]
        if policy.bounded_retention:
            flags.append("bounded-retention")
        if policy.metadata_first_sync:
            flags.append("metadata-first")
        if not policy.auto_media_fetch:
            flags.append("auto-media=off")
        if not policy.background_catchup:
            flags.append("background-catchup=off")
        return ", ".join(flags)

    def _tier_headline(self, policy: GroupThreadPolicy) -> str:
        if policy.feature_tier is GroupThreadFeatureTier.MINIMAL:
            return "Minimal tier active — room continuity is preserved, but this device stays lean on storage and bandwidth."
        if policy.feature_tier is GroupThreadFeatureTier.FULL:
            return "Full tier active — this device keeps richer room history and background behavior enabled."
        return "Balanced tier active — this device keeps the room usable while avoiding the heaviest automatic behavior."

    def _tier_details(self, policy: GroupThreadPolicy) -> str:
        details: list[str] = []
        details.append(
            "History: bounded retention" if policy.bounded_retention else "History: full local retention"
        )
        details.append(
            "Sync: metadata-first" if policy.metadata_first_sync else "Sync: full thread metadata when available"
        )
        details.append(
            "Media: auto-fetch enabled" if policy.auto_media_fetch else "Media: confirm/fetch on demand"
        )
        details.append(
            "Catch-up: background enabled" if policy.background_catchup else "Catch-up: manual/on-open only"
        )
        return "\n".join(f"- {detail}" for detail in details)

    def _participant_summary(self) -> str:
        if not self.group or not self.group.participants:
            return "No participant reachability snapshot available yet."

        lines: list[str] = []
        for participant in self.group.participants:
            route = participant.highest_available_interface or "unknown"
            path_label = participant.delivery_path_class.value
            line = f"- {participant.display_name or participant.identity_hash}: {route} ({path_label})"
            if participant.media_friction != MediaFrictionLevel.NONE:
                line += f" · media={participant.media_friction.value}"
            if participant.fallback_interfaces:
                line += f" · fallback={', '.join(participant.fallback_interfaces)}"
            lines.append(line)
        return "\n".join(lines)

    def compose(self) -> ComposeResult:
        room_name = self.group.room_name if self.group and self.group.room_name else self.display_name
        room_id = self.group.room_id if self.group else self.thread_id
        epoch_id = self.group.epoch_id if self.group else None
        member_count = self.group.member_count if self.group else None
        policy = self.group.policy if self.group else GroupThreadPolicy()
        constrained = any(
            participant.delivery_path_class in {DeliveryPathClass.CONSTRAINED, DeliveryPathClass.STORE_AND_FORWARD}
            or participant.requires_media_confirmation
            for participant in (self.group.participants if self.group else ())
        )

        yield Header()
        with Container(id="mail-group-thread-container"):
            yield Static(f"[bold]{room_name}[/]", id="mail-group-thread-title")
            yield Static(f"Room ID: {room_id}", id="mail-group-thread-room-id")
            if epoch_id:
                yield Static(f"Epoch: {epoch_id}", id="mail-group-thread-epoch")
            if member_count is not None:
                yield Static(f"Members: {member_count}", id="mail-group-thread-members")
            yield Static(self._tier_headline(policy), id="mail-group-thread-tier-headline")
            yield Static(f"Local policy: {self._policy_summary(policy)}", id="mail-group-thread-policy")
            yield Static(self._tier_details(policy), id="mail-group-thread-policy-details")
            yield Static(self._participant_summary(), id="mail-group-thread-participants")
            if constrained:
                yield Static(
                    "Some members are currently on constrained or store-and-forward paths. Confirm expensive media actions before sending.",
                    id="mail-group-thread-media-warning",
                )
            elif not policy.auto_media_fetch:
                yield Static(
                    "Auto-media fetch is disabled for this device tier. Rich media should be treated as on-demand unless you explicitly confirm it.",
                    id="mail-group-thread-media-warning",
                )
            yield Static(
                "This is the dedicated placeholder for room-centric group Mail threads. "
                "Message composition and room timeline rendering are not wired yet.",
                id="mail-group-thread-placeholder",
            )
        yield Footer()
