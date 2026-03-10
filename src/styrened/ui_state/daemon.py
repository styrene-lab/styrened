"""Canonical local daemon state built from authoritative runtime snapshots."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from styrened.models.hardware import NetworkInterface, SystemInfo
from styrened.services.hub_connection import HubStatus

from styrened.ui_state.base import CapabilityState, LoadState, RefreshMeta
from styrened.ui_state.mail import GroupThreadFeatureTier


@dataclass(frozen=True)
class OverlayRuntimeState:
    """Capability-aware runtime summary for an overlay daemon."""

    capability_state: CapabilityState = CapabilityState.UNSUPPORTED
    mode: str | None = None
    running: bool = False
    address: str | None = None
    peer_count: int | None = None
    warning: str | None = None


@dataclass(frozen=True)
class LocalDaemonState:
    """Canonical local daemon/operator-facing state."""

    daemon_running: bool
    local_identity_hash: str | None = None
    hub_connected: bool = False
    hub_address: str | None = None
    hub_destination: str | None = None
    ygg: OverlayRuntimeState = field(default_factory=OverlayRuntimeState)
    i2p: OverlayRuntimeState = field(default_factory=OverlayRuntimeState)
    group_thread_feature_tier: GroupThreadFeatureTier = GroupThreadFeatureTier.BALANCED
    group_threads_enabled: bool = True
    group_thread_bounded_retention: bool = False
    group_thread_auto_media_fetch: bool = True
    group_thread_metadata_first_sync: bool = False
    warnings: tuple[str, ...] = ()
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class LocalDaemonInputs:
    """Explicit authoritative inputs for local daemon state construction."""

    daemon_status: object | None = None
    identity_info: object | None = None
    hub_status: dict[str, Any] | None = None
    core_config: dict[str, Any] | None = None
    ygg_runtime: dict[str, Any] | None = None
    i2p_runtime: dict[str, Any] | None = None
    now: float | None = None


@dataclass(frozen=True)
class HomeNodeLocalState:
    """Panel-scoped snapshot for local Home hardware/config presentation."""

    system_info: SystemInfo | None = None
    primary_interface: NetworkInterface | None = None
    removable_count: int = 0
    hardware_error: str | None = None
    mode: str = "standalone"
    identity_display_name: str = ""
    identity_icon: str = ""
    identity_short_name: str | None = None
    security_tier: str = ""
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class HomeNodeInfoState:
    """Panel-scoped snapshot for the Home/NodeInfoPanel daemon-backed surface."""

    daemon_connected: bool = False
    daemon_version: str = ""
    daemon_uptime: float = 0.0
    local_identity_hash: str | None = None
    hub_status: HubStatus = HubStatus.DISABLED
    styrene_mesh_count: int = 0
    rns_online: bool = False
    interface_count: int = 0
    propagation_enabled: bool = False
    transport_enabled: bool = False
    active_links: int = 0
    unread_count: int = 0
    conversation_count: int = 0
    contact_count: int = 0
    messages_sent: int = 0
    messages_received: int = 0
    pending_deliveries: int = 0
    auto_reply_enabled: bool = False
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


def _overlay_state(
    *,
    config_section: dict[str, Any] | None,
    runtime: dict[str, Any] | None,
    address_key: str,
) -> OverlayRuntimeState:
    mode = str((config_section or {}).get("mode", "") or "") or None
    if not mode or mode == "disabled":
        return OverlayRuntimeState()

    runtime = runtime or {}
    running = bool(runtime.get("running", False))
    capability_state = CapabilityState.AVAILABLE if running else CapabilityState.UNAVAILABLE
    return OverlayRuntimeState(
        capability_state=capability_state,
        mode=mode,
        running=running,
        address=runtime.get(address_key),
        peer_count=runtime.get("peer_count"),
        warning=runtime.get("warning"),
    )


def build_local_daemon_state(inputs: LocalDaemonInputs) -> LocalDaemonState:
    """Build canonical local daemon state from authoritative snapshots."""
    now = inputs.now if inputs.now is not None else time.time()
    daemon_status = inputs.daemon_status
    identity_info = inputs.identity_info
    hub_status = inputs.hub_status or {}
    core_config = inputs.core_config or {}

    daemon_running = daemon_status is not None and bool(getattr(daemon_status, "rns_initialized", False))
    local_identity_hash = getattr(identity_info, "identity_hash", None) if identity_info else None
    hub_connected = bool(hub_status.get("is_connected", False))

    warnings: list[str] = []
    if daemon_status is not None and not bool(getattr(daemon_status, "lxmf_initialized", False)):
        warnings.append("LXMF not initialized")

    group_threads = core_config.get("group_threads") if isinstance(core_config, dict) else {}
    tier_raw = str((group_threads or {}).get("feature_tier", GroupThreadFeatureTier.BALANCED.value)).lower()
    try:
        feature_tier = GroupThreadFeatureTier(tier_raw)
    except ValueError:
        feature_tier = GroupThreadFeatureTier.BALANCED

    return LocalDaemonState(
        daemon_running=daemon_running,
        local_identity_hash=local_identity_hash,
        hub_connected=hub_connected,
        hub_address=hub_status.get("hub_address") or getattr(daemon_status, "hub_address", None),
        hub_destination=hub_status.get("hub_destination"),
        ygg=_overlay_state(
            config_section=core_config.get("yggdrasil") if isinstance(core_config, dict) else None,
            runtime=inputs.ygg_runtime,
            address_key="address",
        ),
        i2p=_overlay_state(
            config_section=core_config.get("i2p") if isinstance(core_config, dict) else None,
            runtime=inputs.i2p_runtime,
            address_key="b32_address",
        ),
        group_thread_feature_tier=feature_tier,
        group_threads_enabled=bool((group_threads or {}).get("enabled", True)),
        group_thread_bounded_retention=bool((group_threads or {}).get("bounded_retention", False)),
        group_thread_auto_media_fetch=bool((group_threads or {}).get("auto_media_fetch", True)),
        group_thread_metadata_first_sync=bool((group_threads or {}).get("metadata_first_sync", False)),
        warnings=tuple(warnings),
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=now),
    )


def build_home_node_local_state(
    *,
    system_info: SystemInfo | None = None,
    primary_interface: NetworkInterface | None = None,
    removable_count: int = 0,
    hardware_error: str | None = None,
    mode: str = "standalone",
    identity_display_name: str = "",
    identity_icon: str = "",
    identity_short_name: str | None = None,
    identity_provider: str = "file",
    refreshed_at: float | None = None,
) -> HomeNodeLocalState:
    """Build the panel-scoped local Home snapshot consumed by NodeInfoPanel."""
    return HomeNodeLocalState(
        system_info=system_info,
        primary_interface=primary_interface,
        removable_count=removable_count,
        hardware_error=hardware_error,
        mode=mode,
        identity_display_name=identity_display_name,
        identity_icon=identity_icon,
        identity_short_name=identity_short_name,
        security_tier="YubiKey/FIDO2" if identity_provider == "yubikey" else "X25519",
        refresh=RefreshMeta(load_state=LoadState.READY, refreshed_at=refreshed_at or time.time(), source="local"),
    )


def build_home_node_info_state(
    *,
    daemon_state: LocalDaemonState,
    daemon_status: object | None = None,
    mesh_node_count: int = 0,
    conversations: list[dict[str, Any]] | None = None,
    contacts: list[dict[str, Any]] | None = None,
    auto_reply: dict[str, Any] | None = None,
) -> HomeNodeInfoState:
    """Build the panel-scoped Home snapshot consumed by NodeInfoPanel."""
    refresh = daemon_state.refresh
    if daemon_status is not None and daemon_state.refresh.refreshed_at is None:
        refresh = RefreshMeta(load_state=LoadState.READY, refreshed_at=time.time())

    conversations = conversations or []
    contacts = contacts or []
    auto_reply = auto_reply or {}
    unread_count = sum(int(conv.get("unread_count", 0) or 0) for conv in conversations)
    message_count = sum(int(conv.get("message_count", 0) or 0) for conv in conversations)

    return HomeNodeInfoState(
        daemon_connected=daemon_state.daemon_running,
        daemon_version=str(getattr(daemon_status, "daemon_version", "") or ""),
        daemon_uptime=float(getattr(daemon_status, "uptime", 0.0) or 0.0),
        local_identity_hash=daemon_state.local_identity_hash,
        hub_status=HubStatus.CONNECTED if daemon_state.hub_connected else HubStatus.DISCONNECTED,
        styrene_mesh_count=mesh_node_count,
        rns_online=bool(getattr(daemon_status, "rns_initialized", False)),
        interface_count=int(getattr(daemon_status, "interface_count", 0) or 0),
        propagation_enabled=bool(getattr(daemon_status, "propagation_enabled", False)),
        transport_enabled=bool(getattr(daemon_status, "transport_enabled", False)),
        active_links=int(getattr(daemon_status, "active_links", 0) or 0),
        unread_count=unread_count,
        conversation_count=len(conversations),
        contact_count=len(contacts),
        messages_sent=0,
        messages_received=message_count,
        pending_deliveries=0,
        auto_reply_enabled=bool(auto_reply.get("enabled", False)),
        refresh=refresh,
    )
