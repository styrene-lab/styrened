# Unified TUI Device Cache

## Intent

All TUI screens currently call bridge.get_devices() independently, maintain per-screen caches, and have divergent fallback paths to discover_devices(). mesh_device_detail.py even reaches into exploration.py's _live_nodes_cache via getattr. This creates stale/inconsistent views across screens and silent empty-list failures. A single app-level DeviceCache eliminates all shadow paths.

See [Unified TUI Device Cache design doc](../../../docs/tui-device-cache.md) for full context.
