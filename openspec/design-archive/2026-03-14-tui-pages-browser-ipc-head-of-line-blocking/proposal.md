# Pages browser IPC head-of-line blocking

## Intent

The Exploration Pages tab still feels laggy on large meshes because page fetches run over the same shared IPC bridge used for summary/status work. A slow or timing-out NomadNet page request can monopolize the client connection and the daemon's per-client request loop, delaying unrelated UI requests and making the whole TUI feel stuck while a single page load is in flight.

See [Pages browser IPC head-of-line blocking design doc](../../../docs/tui-pages-browser-ipc-head-of-line-blocking.md) for full context.
