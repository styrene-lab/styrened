"""Unit tests for the Global COP screen, fleet table, and alert list."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from styrened.models.mesh_device import DeviceType, MeshDevice, NodeStatus
from styrened.tui.widgets.alert_list import AlertListWidget, AlertSeverity
from styrened.tui.widgets.global_cop_fleet_table import GlobalCopFleetTable


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATUS_LAST_ANNOUNCE = {
    NodeStatus.ACTIVE: int(time.time()) - 60,        # 1 min ago → ACTIVE (<5 min)
    NodeStatus.STALE: int(time.time()) - 7 * 60,     # 7 min ago → STALE (5-15 min)
    NodeStatus.LOST: int(time.time()) - 20 * 60,     # 20 min ago → LOST (>15 min)
}


def _make_device(
    name: str,
    status: NodeStatus = NodeStatus.ACTIVE,
    hops: int | None = 1,
    device_type: DeviceType = DeviceType.STYRENE_NODE,
    identity_hash: str | None = None,
    destination_hash: str | None = None,
) -> MeshDevice:
    ih = identity_hash or f"id-{name.lower()}"
    dh = destination_hash or f"dest-{name.lower()}"
    last_announce = _STATUS_LAST_ANNOUNCE[status]
    return MeshDevice(
        destination_hash=dh,
        identity_hash=ih,
        name=name,
        device_type=device_type,
        last_announce=last_announce,
        hops=hops,
    )


# ---------------------------------------------------------------------------
# GlobalCopFleetTable — health sort order
# ---------------------------------------------------------------------------

class TestGlobalCopFleetTableSort:
    """Fleet table health sort key respects LOST → STALE → ACTIVE ordering."""

    def test_health_key_lost_first(self) -> None:
        table = GlobalCopFleetTable()
        lost = _make_device("Lost", NodeStatus.LOST, hops=0)
        active = _make_device("Active", NodeStatus.ACTIVE, hops=0)
        stale = _make_device("Stale", NodeStatus.STALE, hops=0)

        keys = [table._health_key(d) for d in [lost, active, stale]]
        assert keys[0] < keys[2] < keys[1], "LOST < STALE < ACTIVE"

    def test_health_key_ties_broken_by_hops(self) -> None:
        table = GlobalCopFleetTable()
        near = _make_device("A", NodeStatus.ACTIVE, hops=1)
        far = _make_device("B", NodeStatus.ACTIVE, hops=5)

        assert table._health_key(near) < table._health_key(far)

    def test_health_key_none_hops_sorts_last(self) -> None:
        table = GlobalCopFleetTable()
        with_hops = _make_device("A", NodeStatus.ACTIVE, hops=2)
        no_hops = _make_device("B", NodeStatus.ACTIVE, hops=None)

        assert table._health_key(with_hops) < table._health_key(no_hops)


# ---------------------------------------------------------------------------
# GlobalCopFleetTable — scope toggle
# ---------------------------------------------------------------------------

class TestGlobalCopFleetTableScope:
    """Styrene-primary scope filter and toggle."""

    def test_styrene_only_default(self) -> None:
        table = GlobalCopFleetTable()
        assert table.styrene_only is True

    def test_toggle_scope_flips(self) -> None:
        table = GlobalCopFleetTable()
        # Stub _rebuild_table to avoid unmounted DataTable column errors
        table._rebuild_table = MagicMock()  # type: ignore[method-assign]
        result = table.toggle_scope()
        assert result is False
        assert table.styrene_only is False

    def test_toggle_scope_double_flips_back(self) -> None:
        table = GlobalCopFleetTable()
        table._rebuild_table = MagicMock()  # type: ignore[method-assign]
        table.toggle_scope()
        table.toggle_scope()
        assert table.styrene_only is True

    def test_load_devices_updates_count(self) -> None:
        table = GlobalCopFleetTable()
        table._rebuild_table = MagicMock()  # type: ignore[method-assign]
        devices = [_make_device("A"), _make_device("B")]
        table.load_devices(devices)
        assert table.device_count == 2


# ---------------------------------------------------------------------------
# AlertListWidget — derive_from_devices
# ---------------------------------------------------------------------------

class TestAlertListDeriveFromDevices:
    """Alert list derives LOST-node alerts and auto-resolves them."""

    def _make_alert_list(self) -> AlertListWidget:
        w = AlertListWidget()
        # Stub _redraw so we don't need a full Textual app
        w._redraw = MagicMock()  # type: ignore[method-assign]
        return w

    def test_lost_node_produces_alert(self) -> None:
        w = self._make_alert_list()
        devices = [_make_device("Node1", NodeStatus.LOST)]
        w.derive_from_devices(devices)
        assert any("lost:" in aid for aid in w._alerts)

    def test_active_node_no_alert(self) -> None:
        w = self._make_alert_list()
        devices = [_make_device("Node1", NodeStatus.ACTIVE)]
        w.derive_from_devices(devices)
        assert len(w._alerts) == 0

    def test_lost_alert_auto_resolves_when_node_recovers(self) -> None:
        w = self._make_alert_list()
        # First call — node is LOST
        lost = _make_device("Node1", NodeStatus.LOST)
        w.derive_from_devices([lost])
        assert len(w._alerts) == 1

        # Second call — node is now ACTIVE
        recovered = _make_device("Node1", NodeStatus.ACTIVE, identity_hash=lost.identity_hash)
        w.derive_from_devices([recovered])
        assert len(w._alerts) == 0

    def test_no_duplicate_alerts_for_same_node(self) -> None:
        w = self._make_alert_list()
        devices = [_make_device("Node1", NodeStatus.LOST)]
        w.derive_from_devices(devices)
        w.derive_from_devices(devices)
        # Should still be exactly one alert
        assert len(w._alerts) == 1

    def test_multiple_lost_nodes(self) -> None:
        w = self._make_alert_list()
        devices = [
            _make_device("A", NodeStatus.LOST),
            _make_device("B", NodeStatus.LOST),
            _make_device("C", NodeStatus.ACTIVE),
        ]
        w.derive_from_devices(devices)
        assert len(w._alerts) == 2


# ---------------------------------------------------------------------------
# AlertListWidget — manual add/resolve
# ---------------------------------------------------------------------------

class TestAlertListManual:
    """Manual alert add and resolve."""

    def _make_alert_list(self) -> AlertListWidget:
        w = AlertListWidget()
        w._redraw = MagicMock()  # type: ignore[method-assign]
        return w

    def test_add_alert(self) -> None:
        w = self._make_alert_list()
        w.add_alert("test-1", AlertSeverity.WARNING, "something wrong")
        assert "test-1" in w._alerts
        assert w._alerts["test-1"].severity == AlertSeverity.WARNING

    def test_resolve_alert_removes_it(self) -> None:
        w = self._make_alert_list()
        w.add_alert("test-1", AlertSeverity.INFO, "note")
        w.resolve_alert("test-1")
        assert "test-1" not in w._alerts

    def test_resolve_missing_alert_is_noop(self) -> None:
        w = self._make_alert_list()
        # Should not raise
        w.resolve_alert("nonexistent")


# ---------------------------------------------------------------------------
# GlobalCopScreen — registration in app
# ---------------------------------------------------------------------------

class TestGlobalCopScreenRegistration:
    """GlobalCopScreen is registered in the app and keybinding exists."""

    def test_screen_registered(self) -> None:
        from styrened.tui.app import StyreneApp
        from styrened.tui.screens.global_cop import GlobalCopScreen

        assert "global_cop" in StyreneApp.SCREENS
        assert StyreneApp.SCREENS["global_cop"] is GlobalCopScreen

    def test_keybinding_g_registered(self) -> None:
        from styrened.tui.app import StyreneApp

        keys = {b.key for b in StyreneApp.BINDINGS}
        assert "g" in keys

    def test_action_open_global_cop_not_stub(self) -> None:
        """action_open_global_cop must not be the old 'coming soon' notify stub."""
        import inspect
        from styrened.tui.app import StyreneApp

        src = inspect.getsource(StyreneApp.action_open_global_cop)
        assert "coming soon" not in src
        assert "_toggle_screen" in src
