"""Unified TUI device cache.

A single app-level service that owns the authoritative list of known
MeshDevices.  All TUI screens and widgets read from here instead of
each making independent IPC / discover_devices() calls.

Usage::

    # In any screen/widget:
    cache = self.app.services.device_cache
    all_devices    = cache.get()          # list[MeshDevice], last known good
    styrene_only   = cache.get_styrene()  # filtered subset

    # React to updates without polling — post to the app:
    # Textual routes DeviceCache.DevicesUpdated to every mounted widget.
    def on_device_cache_devices_updated(self, msg):
        self._populate_table(msg.devices)

Lifecycle::

    cache = DeviceCache(bridge=..., interval=15.0)
    cache.start(app)   # registers delayed initial refresh + periodic updates
    cache.stop()       # cancels timers
    await cache.refresh()  # on-demand immediate refresh
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from textual.message import Message

from styrened.models.mesh_device import DeviceType, MeshDevice

if TYPE_CHECKING:
    from textual.app import App

log = logging.getLogger(__name__)

_DEFAULT_INTERVAL = 15.0   # seconds between background refreshes
_DEFAULT_PRIME_DELAY = 0.25  # seconds after first paint before cache priming starts


class DeviceCache:
    """App-level device cache with background refresh.

    Attributes:
        devices:  Full list of known MeshDevices (last successful fetch).
    """

    # -------------------------------------------------------------------------
    # Textual message emitted when cache content changes
    # -------------------------------------------------------------------------

    class DevicesUpdated(Message):
        """Posted to the app when the device list has been refreshed.

        Screens / widgets react by declaring::

            def on_device_cache_devices_updated(self, msg: DeviceCache.DevicesUpdated):
                ...
        """

        def __init__(self, devices: list[MeshDevice]) -> None:
            super().__init__()
            self.devices = devices

    # -------------------------------------------------------------------------
    # Init
    # -------------------------------------------------------------------------

    def __init__(
        self,
        bridge: Any | None = None,
        interval: float = _DEFAULT_INTERVAL,
        prime_delay: float = _DEFAULT_PRIME_DELAY,
    ) -> None:
        self._bridge = bridge
        self._interval = interval
        self._prime_delay = prime_delay
        self._devices: list[MeshDevice] = []
        self._app: App | None = None
        self._timer: Any = None
        self._prime_timer: Any = None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    def start(self, app: "App") -> None:
        """Attach to *app* and schedule delayed priming after first paint.

        Idempotent — safe to call again on IPC reconnect; cancels any existing
        timers before starting new ones.
        """
        self.stop()
        self._app = app
        app.call_after_refresh(self._schedule_initial_load)

    def stop(self) -> None:
        """Cancel the refresh timers."""
        if self._prime_timer is not None:
            self._prime_timer.stop()
            self._prime_timer = None
        if self._timer is not None:
            self._timer.stop()
            self._timer = None

    def update_bridge(self, bridge: Any | None) -> None:
        """Replace the IPC bridge reference (called when IPC reconnects)."""
        self._bridge = bridge

    # -------------------------------------------------------------------------
    # Public read API — always synchronous, never raises
    # -------------------------------------------------------------------------

    def get(self) -> list[MeshDevice]:
        """Return the full cached device list (last known good)."""
        return list(self._devices)

    def get_styrene(self) -> list[MeshDevice]:
        """Return only Styrene-protocol nodes."""
        return [d for d in self._devices if d.device_type == DeviceType.STYRENE_NODE]

    def get_by_hash(self, destination_hash: str) -> MeshDevice | None:
        """Look up a device by destination hash.  Returns None if not found."""
        for d in self._devices:
            if d.destination_hash == destination_hash:
                return d
        return None

    # -------------------------------------------------------------------------
    # Refresh
    # -------------------------------------------------------------------------

    async def refresh(self) -> None:
        """On-demand refresh — fetches immediately and posts DevicesUpdated."""
        await self._do_refresh()

    def _schedule_initial_load(self) -> None:
        """Schedule the first bulk refresh after the app has painted once."""
        app = self._app
        if app is None:
            return
        self._prime_timer = app.set_timer(self._prime_delay, self._run_initial_refresh)

    def _run_initial_refresh(self) -> None:
        """Kick off delayed bulk hydration in a background worker."""
        self._prime_timer = None
        app = self._app
        if app is None:
            return
        app.run_worker(self._initial_load(), exclusive=False, group="device-cache")

    async def _initial_load(self) -> None:
        """Initial fetch; schedule the periodic timer afterwards."""
        await self._do_refresh()
        if self._app is not None and self._timer is None:
            self._timer = self._app.set_interval(self._interval, self._on_timer)

    def _on_timer(self) -> None:
        """Periodic timer callback — kicks off a background refresh worker."""
        if self._app is not None:
            self._app.run_worker(
                self._do_refresh(),
                exclusive=False,
                group="device-cache",
            )

    async def _do_refresh(self) -> None:
        """Fetch devices from bridge or fallback, update cache, notify app."""
        try:
            devices = await self._fetch()
        except Exception:
            log.debug("DeviceCache._do_refresh failed", exc_info=True)
            return   # keep stale cache; don't wipe it on transient error

        # Deduplicate by destination_hash (last-write-wins)
        seen: dict[str, MeshDevice] = {}
        for d in devices:
            seen[d.destination_hash] = d
        new_list = list(seen.values())

        # Only notify if the list actually changed (avoids unnecessary re-renders)
        if self._list_changed(new_list):
            self._devices = new_list
            self._post_update(new_list)

    @staticmethod
    def _device_fingerprint(d: MeshDevice) -> tuple:
        """Stable tuple covering every field a UI might display.

        Cheap to compute, hashable, and catches all mutations that matter:
        name changes, hop count updates, new version strings, capability
        additions, metadata fetched via /meta (ygg/i2p/web), etc.
        """
        return (
            d.destination_hash,
            d.name,
            d.device_type,
            d.last_announce,
            d.announce_count,
            d.hops,
            d.version,
            tuple(sorted(d.capabilities)) if d.capabilities else None,
            d.lxmf_destination_hash,
            d.short_name,
            d.system_fingerprint,
            d.nomadnet_destination_hash,
            d.discovered_via,
            d.ygg_address,
            d.b32_address,
            d.web_url,
        )

    def _list_changed(self, new: list[MeshDevice]) -> bool:
        """Return True if the new list differs from the cached list in any way.

        Compares both membership (add/remove) and field-level mutations so
        that metadata updates (hops, name, version, /meta addresses) trigger
        DevicesUpdated rather than being silently swallowed.
        """
        if len(new) != len(self._devices):
            return True
        old_fps = {self._device_fingerprint(d) for d in self._devices}
        new_fps = {self._device_fingerprint(d) for d in new}
        return old_fps != new_fps

    async def _fetch(self) -> list[MeshDevice]:
        """Fetch raw device list: bridge → discover_devices() fallback."""
        if self._bridge is not None:
            from styrened.tui.utils import device_info_to_mesh

            device_infos = await self._bridge.get_devices(styrene_only=False)
            return [device_info_to_mesh(d) for d in device_infos]

        # No bridge (legacy / offline): fall back to local discovery
        from styrened.tui.services.reticulum import discover_devices

        return discover_devices()

    def _post_update(self, devices: list[MeshDevice]) -> None:
        """Post DevicesUpdated to the app (non-blocking)."""
        if self._app is not None:
            try:
                self._app.post_message(DeviceCache.DevicesUpdated(devices))
            except Exception:
                log.debug("DeviceCache._post_update failed", exc_info=True)
