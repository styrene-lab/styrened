# Python Daemon Sunset — TUI-only styrened + Rust daemon backend

## Intent

Transition styrened from daemon+TUI monolith to TUI-only package that connects to styrened-rs over IPC. The Python daemon, services, RPC, and protocol layers become dead code once the Rust daemon handles all active IPC message types. The TUI, IPC bridge, models, and CLI stay Python.

See [design doc](../../../docs/python-daemon-sunset.md).
