"""Unit tests for shared frontend-agnostic ui_state builders."""

from dataclasses import dataclass

from styrened.ipc.messages import DaemonStatus, DeviceInfo, IdentityInfo
from styrened.ui_state import (
    CapabilityState,
    CommsMode,
    CommsWorkspaceInputs,
    ConversationScopeKind,
    CommsWorkspaceState,
    ConfigDraftInputs,
    ConfigSaveState,
    DeliveryPathClass,
    GroupThreadFeatureTier,
    KnowledgeState,
    MailIndexInputs,
    MediaFrictionLevel,
    PageBrowserSessionInputs,
    PageTransport,
    PeerWorkspaceFocus,
    PresenceState,
    WorkspaceId,
    build_comms_workspace_state,
    build_config_draft_state,
    build_local_daemon_state,
    build_mail_index,
    build_node_catalog,
    build_page_browser_session_state,
    build_peer_workspace_context,
)
from styrened.ui_state.daemon import LocalDaemonInputs
from styrened.ui_state.nodes import NodeCatalogInputs


@dataclass
class FakeDevice:
    destination_hash: str
    identity_hash: str
    name: str
    device_type: str
    last_announce: float
    announce_count: int = 0
    capabilities: list[str] | None = None
    lxmf_destination_hash: str | None = None
    discovered_via: str | None = None
    hops: int | None = None
    ygg_address: str | None = None
    b32_address: str | None = None


class TestNodeCatalogState:
    def test_build_node_catalog_merges_devices_by_identity(self):
        inputs = NodeCatalogInputs(
            devices=(
                FakeDevice(
                    destination_hash="dest-styrene",
                    identity_hash="peer1",
                    name="Peer One",
                    device_type="styrene",
                    last_announce=1000.0,
                    capabilities=["yggdrasil"],
                    ygg_address="200:1111::1",
                ),
                FakeDevice(
                    destination_hash="dest-nomad",
                    identity_hash="peer1",
                    name="Peer One Docs",
                    device_type="nomadnet_node",
                    last_announce=995.0,
                ),
            ),
            now=1100.0,
        )

        state = build_node_catalog(inputs)

        assert len(state.nodes) == 1
        node = state.by_identity["peer1"]
        assert node.primary_destination_hash == "dest-styrene"
        assert {route.destination_hash for route in node.routes} == {"dest-styrene", "dest-nomad"}
        assert node.ygg.capability_state == CapabilityState.AVAILABLE
        assert node.ygg.knowledge == KnowledgeState.KNOWN
        assert node.i2p.capability_state == CapabilityState.UNSUPPORTED

    def test_build_node_catalog_applies_relationship_overlays(self):
        inputs = NodeCatalogInputs(
            devices=(
                FakeDevice(
                    destination_hash="dest-1",
                    identity_hash="peer1",
                    name="Peer One",
                    device_type="styrene",
                    last_announce=1000.0,
                ),
            ),
            unread_counts={"peer1": 3},
            aliases={"peer1": "Alias One"},
            blocked_identities=frozenset({"peer1"}),
            local_identity_hash="peer1",
            now=1010.0,
        )

        state = build_node_catalog(inputs)
        node = state.by_identity["peer1"]

        assert node.display_name == "Alias One"
        assert node.relationship.unread_count == 3
        assert node.relationship.blocked is True
        assert node.relationship.in_my_mesh is True

    def test_build_node_catalog_marks_overlay_unknown_when_capability_present_without_address(self):
        inputs = NodeCatalogInputs(
            devices=(
                FakeDevice(
                    destination_hash="dest-1",
                    identity_hash="peer1",
                    name="Peer One",
                    device_type="styrene",
                    last_announce=1000.0,
                    capabilities=["i2p"],
                ),
            ),
            now=1005.0,
        )

        state = build_node_catalog(inputs)
        node = state.by_identity["peer1"]

        assert node.i2p.capability_state == CapabilityState.UNAVAILABLE
        assert node.i2p.knowledge == KnowledgeState.UNKNOWN
        assert node.i2p.address is None

    def test_classify_presence_uses_snapshot_time(self):
        inputs = NodeCatalogInputs(
            devices=(
                FakeDevice(
                    destination_hash="dest-1",
                    identity_hash="peer1",
                    name="Peer One",
                    device_type="styrene",
                    last_announce=0.0,
                ),
            ),
            now=2000.0,
        )

        state = build_node_catalog(inputs)
        assert state.by_identity["peer1"].presence == PresenceState.UNKNOWN

        live_state = build_node_catalog(
            NodeCatalogInputs(
                devices=(
                    FakeDevice(
                        destination_hash="dest-2",
                        identity_hash="peer2",
                        name="Peer Two",
                        device_type="styrene",
                        last_announce=1990.0,
                    ),
                ),
                now=2000.0,
            )
        )
        assert live_state.by_identity["peer2"].presence == PresenceState.LIVE


class TestPeerWorkspaceContext:
    def test_build_peer_workspace_context_coerces_workspace_and_tab_focus(self):
        context = build_peer_workspace_context(
            "peer1",
            "nodes",
            focus="chat",
        )

        assert context.peer_identity_hash == "peer1"
        assert context.origin_workspace == WorkspaceId.NODES
        assert context.focus == PeerWorkspaceFocus.COMMS

    def test_build_peer_workspace_context_defaults_unknown_values_safely(self):
        context = build_peer_workspace_context(
            "peer2",
            "not-a-workspace",
            focus="not-a-tab",
        )

        assert context.origin_workspace == WorkspaceId.HOME
        assert context.focus == PeerWorkspaceFocus.STATUS


class TestCommsWorkspaceState:
    def test_build_comms_workspace_state_exposes_transport_aware_modes(self):
        state = build_comms_workspace_state(
            CommsWorkspaceInputs(
                active_mode="bridges",
                direct_available=True,
                active_session_count=2,
                bridge_status={
                    "meshtastic": {"enabled": True, "available": False, "warning": "gateway offline"},
                    "yggdrasil": {"enabled": True, "available": True},
                    "i2p": {"enabled": False, "available": False},
                },
                now=1234.0,
            )
        )

        assert state.active_mode == CommsMode.BRIDGES
        assert state.available_modes == (
            CommsMode.DIRECT,
            CommsMode.ACTIVE,
            CommsMode.BRIDGES,
            CommsMode.PRESENCE,
        )
        assert state.direct_available is True
        assert state.active_session_count == 2
        assert {cap.key for cap in state.bridge_capabilities} == {"meshtastic", "yggdrasil", "i2p"}
        by_key = {cap.key: cap for cap in state.bridge_capabilities}
        assert by_key["yggdrasil"].capability_state == CapabilityState.AVAILABLE
        assert by_key["meshtastic"].capability_state == CapabilityState.UNAVAILABLE
        assert by_key["i2p"].capability_state == CapabilityState.UNSUPPORTED

    def test_build_comms_workspace_state_defaults_safely(self):
        state = build_comms_workspace_state(CommsWorkspaceInputs())

        assert state.active_mode == CommsMode.DIRECT
        assert state.direct_available is False
        assert state.active_session_count == 0
        assert state.bridge_capabilities == ()


class TestMailIndexState:
    def test_build_mail_index_keeps_direct_threads_identity_centric(self):
        state = build_mail_index(
            MailIndexInputs(
                threads=(
                    {
                        "thread_id": "peer1",
                        "scope_kind": "direct",
                        "peer_identity": "peer1",
                        "display_name": "Peer One",
                        "unread_count": 2,
                        "last_message_preview": "hello",
                        "last_message_time": 1000.0,
                        "transport": "lxmf",
                    },
                ),
                now=1010.0,
            )
        )

        thread = state.by_thread_id["peer1"]
        assert thread.scope_kind == ConversationScopeKind.DIRECT
        assert thread.participant_identity == "peer1"
        assert thread.group is None
        assert thread.forum is None
        assert thread.transports[0].transport == "lxmf"

    def test_build_mail_index_preserves_room_metadata_for_group_threads(self):
        state = build_mail_index(
            MailIndexInputs(
                threads=(
                    {
                        "thread_id": "room-alpha",
                        "scope_kind": "group",
                        "room_id": "room-alpha",
                        "room_name": "Alpha Room",
                        "epoch_id": "epoch-7",
                        "member_count": 4,
                        "display_name": "Alpha Room",
                        "last_message_preview": "group msg",
                        "last_message_time": 2000.0,
                        "transport": "lxmf",
                        "participants": [
                            {
                                "identity": "peer-a",
                                "display_name": "Peer A",
                                "highest_available_interface": "tcp",
                                "fallback_interfaces": ["lxmf"],
                                "delivery_path_class": "high",
                            },
                            {
                                "identity": "peer-b",
                                "display_name": "Peer B",
                                "highest_available_interface": "lora",
                                "delivery_path_class": "constrained",
                                "requires_media_confirmation": True,
                            },
                        ],
                        "group_policy": {
                            "feature_tier": "minimal",
                            "bounded_retention": True,
                            "auto_media_fetch": False,
                            "metadata_first_sync": True,
                            "background_catchup": False,
                        },
                    },
                ),
                now=2010.0,
            )
        )

        thread = state.by_thread_id["room-alpha"]
        assert thread.scope_kind == ConversationScopeKind.GROUP
        assert thread.participant_identity is None
        assert thread.group is not None
        assert thread.group.room_id == "room-alpha"
        assert thread.group.epoch_id == "epoch-7"
        assert thread.group.member_count == 4
        assert len(thread.group.participants) == 2
        assert thread.group.participants[0].delivery_path_class == DeliveryPathClass.HIGH
        assert thread.group.participants[1].media_friction == MediaFrictionLevel.CONFIRM
        assert thread.group.policy.feature_tier == GroupThreadFeatureTier.MINIMAL
        assert thread.group.policy.auto_media_fetch is False

    def test_build_mail_index_preserves_topic_metadata_for_forum_threads(self):
        state = build_mail_index(
            MailIndexInputs(
                threads=(
                    {
                        "thread_id": "topic-1",
                        "scope_kind": "forum",
                        "topic_id": "topic-1",
                        "topic_title": "Mesh Planning",
                        "page_ref": "nomad://board/topic-1",
                        "display_name": "Mesh Planning",
                        "last_message_preview": "topic msg",
                        "last_message_time": 3000.0,
                        "transport": "nomadnet",
                    },
                ),
                now=3010.0,
            )
        )

        thread = state.by_thread_id["topic-1"]
        assert thread.scope_kind == ConversationScopeKind.FORUM
        assert thread.forum is not None
        assert thread.forum.topic_id == "topic-1"
        assert thread.forum.page_ref == "nomad://board/topic-1"
        assert thread.group is None

    def test_build_mail_index_keeps_unified_index_across_scope_kinds(self):
        state = build_mail_index(
            MailIndexInputs(
                threads=(
                    {
                        "thread_id": "peer1",
                        "scope_kind": "direct",
                        "peer_identity": "peer1",
                        "last_message_time": 1000.0,
                    },
                    {
                        "thread_id": "room-alpha",
                        "scope_kind": "group",
                        "room_id": "room-alpha",
                        "last_message_time": 2000.0,
                    },
                    {
                        "thread_id": "topic-1",
                        "scope_kind": "forum",
                        "topic_id": "topic-1",
                        "last_message_time": 1500.0,
                    },
                ),
                now=2010.0,
            )
        )

        assert [thread.thread_id for thread in state.threads] == ["room-alpha", "topic-1", "peer1"]
        assert {thread.scope_kind for thread in state.threads} == {
            ConversationScopeKind.DIRECT,
            ConversationScopeKind.GROUP,
            ConversationScopeKind.FORUM,
        }

    def test_build_mail_index_safely_normalizes_malformed_snapshot_values(self):
        state = build_mail_index(
            MailIndexInputs(
                threads=(
                    {
                        "thread_id": "room-alpha",
                        "scope_kind": "group",
                        "room_id": "room-alpha",
                        "epoch_id": object(),
                        "member_count": -5,
                        "unread_count": "not-a-number",
                        "last_message_time": "not-a-float",
                        "transport": "lxmf",
                        "bridge_kind": object(),
                    },
                ),
                now=2010.0,
            )
        )

        thread = state.by_thread_id["room-alpha"]
        assert thread.unread_count == 0
        assert thread.latest_message is not None
        assert thread.latest_message.timestamp is None
        assert thread.transports[0].bridge_kind is not None
        assert thread.group is not None
        assert thread.group.member_count == 0
        assert thread.group.epoch_id is not None


class TestLocalDaemonState:
    def test_build_local_daemon_state_leaves_optional_capabilities_unsupported_when_disabled(self):
        daemon_status = DaemonStatus(
            uptime=10.0,
            daemon_version="0.1.0",
            rns_initialized=True,
            lxmf_initialized=True,
            device_count=1,
            styrene_node_count=1,
            pending_rpc_count=0,
        )
        identity = IdentityInfo(
            identity_hash="local-id",
            destination_hash="local-dest",
            lxmf_destination_hash="local-lxmf",
        )

        state = build_local_daemon_state(
            LocalDaemonInputs(
                daemon_status=daemon_status,
                identity_info=identity,
                core_config={"yggdrasil": {"mode": "disabled"}, "i2p": {"mode": "disabled"}},
                now=1234.0,
            )
        )

        assert state.daemon_running is True
        assert state.local_identity_hash == "local-id"
        assert state.ygg.capability_state == CapabilityState.UNSUPPORTED
        assert state.i2p.capability_state == CapabilityState.UNSUPPORTED
        assert state.group_thread_feature_tier == GroupThreadFeatureTier.BALANCED

    def test_build_local_daemon_state_populates_enabled_capabilities_from_authoritative_runtime_inputs(self):
        daemon_status = DaemonStatus(
            uptime=10.0,
            daemon_version="0.1.0",
            rns_initialized=True,
            lxmf_initialized=False,
            device_count=1,
            styrene_node_count=1,
            pending_rpc_count=0,
            hub_address="hub.example",
        )

        state = build_local_daemon_state(
            LocalDaemonInputs(
                daemon_status=daemon_status,
                hub_status={"is_connected": True, "hub_destination": "abcd", "hub_address": "hub.example"},
                core_config={
                    "yggdrasil": {"mode": "adopt"},
                    "i2p": {"mode": "managed"},
                    "group_threads": {
                        "enabled": True,
                        "feature_tier": "minimal",
                        "bounded_retention": True,
                        "auto_media_fetch": False,
                        "metadata_first_sync": True,
                    },
                },
                ygg_runtime={"running": True, "address": "200:1111::1", "peer_count": 5},
                i2p_runtime={"running": False, "b32_address": None, "warning": "warming up"},
                now=1234.0,
            )
        )

        assert state.hub_connected is True
        assert state.hub_destination == "abcd"
        assert state.ygg.capability_state == CapabilityState.AVAILABLE
        assert state.ygg.address == "200:1111::1"
        assert state.ygg.peer_count == 5
        assert state.i2p.capability_state == CapabilityState.UNAVAILABLE
        assert state.i2p.warning == "warming up"
        assert state.group_thread_feature_tier == GroupThreadFeatureTier.MINIMAL
        assert state.group_thread_bounded_retention is True
        assert state.group_thread_auto_media_fetch is False
        assert state.group_thread_metadata_first_sync is True
        assert "LXMF not initialized" in state.warnings


class TestConfigDraftState:
    def test_build_config_draft_state_keeps_persisted_and_editable_distinct(self):
        state = build_config_draft_state(
            ConfigDraftInputs(
                persisted={"identity": {"display_name": "Old"}, "rpc": {"enabled": True}},
                editable={"identity": {"display_name": "New"}, "rpc": {"enabled": True}},
                validation_errors={"identity.display_name": "too long"},
                now=1234.0,
            )
        )

        assert state.persisted["identity"]["display_name"] == "Old"
        assert state.editable["identity"]["display_name"] == "New"
        assert state.is_dirty is True
        assert state.dirty_fields == ("identity.display_name",)
        assert state.validation_issues[0].field_path == "identity.display_name"
        assert state.validation_issues[0].message == "too long"

    def test_build_config_draft_state_tracks_save_lifecycle(self):
        saving = build_config_draft_state(ConfigDraftInputs(saving=True, now=1.0))
        saved = build_config_draft_state(ConfigDraftInputs(save_succeeded=True, now=2.0))
        errored = build_config_draft_state(
            ConfigDraftInputs(save_error="disk full", now=3.0)
        )

        assert saving.save_state == ConfigSaveState.SAVING
        assert saved.save_state == ConfigSaveState.SAVED
        assert errored.save_state == ConfigSaveState.ERROR
        assert errored.save_error == "disk full"


class TestPageBrowserSessionState:
    def test_build_page_browser_session_state_separates_transport_from_actions(self):
        state = build_page_browser_session_state(
            PageBrowserSessionInputs(
                destination_hash="abcd1234",
                current_path="/page/index.mu",
                history=("/page/welcome.mu",),
                cache_fallback_used=True,
                cache_available=True,
                can_submit_forms=True,
                status="ok",
                now=1234.0,
            )
        )

        assert state.transport == PageTransport.NOMADNET
        assert state.cache_fallback_used is True
        assert state.cache_capability == CapabilityState.AVAILABLE
        assert state.action_capabilities.can_go_back is True
        assert state.action_capabilities.can_save_site is True
        assert state.action_capabilities.can_crawl_site is True
        assert state.action_capabilities.can_submit_forms is True

    def test_build_page_browser_session_state_detects_external_i2p_mode(self):
        state = build_page_browser_session_state(
            PageBrowserSessionInputs(
                external_url="http://docs.example.i2p/index.html",
                status="error",
                error_message="proxy unavailable",
                now=1234.0,
            )
        )

        assert state.transport == PageTransport.I2P
        assert state.external_url == "http://docs.example.i2p/index.html"
        assert state.action_capabilities.can_save_site is False
        assert state.action_capabilities.can_crawl_site is False
        assert state.error_message == "proxy unavailable"
        assert state.refresh.error_message == "proxy unavailable"
        assert state.refresh.load_state.value == "error"


class TestDeviceInfoCompatibility:
    def test_build_node_catalog_accepts_deviceinfo_snapshots(self):
        device = DeviceInfo(
            destination_hash="dest-1",
            identity_hash="peer1",
            name="Peer One",
            device_type="styrene",
            status="active",
            is_styrene_node=True,
            lxmf_destination_hash=None,
            last_announce=1000.0,
            announce_count=2,
        )

        state = build_node_catalog(NodeCatalogInputs(devices=(device,), now=1005.0))
        assert state.by_identity["peer1"].display_name == "Peer One"
