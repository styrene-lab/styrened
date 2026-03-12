# Internal Event System

## Intent

Styrened lacks a unified internal event bus. When something happens in the daemon (node announce received, message delivered, hub status change, link established, adapter state change), there is no canonical way to propagate that fact to all interested consumers. This leads to:

1. **Polling everywhere** — Dashboard polls IPC every N seconds, exploration screen polls separately, COP summary re-derives state each tick. All doing redundant work, all with latency gaps.

2. **Shadow state proliferation** — `_live_nodes_cache`, `_stored_nodes_cache`, ephemeral event lists, dedup sets. Each consumer builds its own view of truth because there's no shared event stream.

3. **Missed events** — COP originally couldn't see nodes discovered before TUI connected. Exploration screen counters show "0 active" while table has data. Status bar lags behind reality.

4. **Fragile wiring** — One-off callbacks (`_on_device_discovered`), activity subscription over IPC that's separate from device queries, `ingest_event` vs `update_from_state` confusion.

5. **IPC as the only event path** — TUI gets events only through IPC subscription, which is a serialized socket protocol with its own failure modes. Internal daemon services have no event mechanism at all — they call each other directly or not at all.

The fix is a proper publish-subscribe event bus internal to the daemon process, with IPC as one subscriber that bridges events to external consumers (TUI, CLI, web API). Daemon services publish typed events; the TUI subscribes to event streams rather than polling for state snapshots.
