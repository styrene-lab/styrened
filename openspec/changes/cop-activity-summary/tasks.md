# COP Activity Summary Widget — Tasks

## Group 1: CopActivitySummary widget

- [ ] 1.1 Create `src/styrened/tui/widgets/cop_activity_summary.py`
  - SituationCategory enum: UNREAD, NODE_ANOMALY, NODE_DISCOVERY, HUB_STATUS, FILE_ACTIVITY, SECURITY
  - SituationLine dataclass: category, message, timestamp, transport_tag, priority, resolved
  - _TRANSPORT_LABELS dict (TCP, Auto, RNode, I2P, Ygg, UDP, SER, KISS, Pipe, Mesh, fallback —)
  - `transport_label(discovered_via: str | None) -> str` parser
  - CopActivitySummary(Static) widget
    - `_situations: dict[str, SituationLine]` keyed by situation ID
    - `ingest_event(event_type, payload)` — coalescing router
    - `_coalesce_unread(payload)` — group by peer, count, list names
    - `_coalesce_node_discovery(payload)` — count per transport tag
    - `_coalesce_node_anomaly(payload)` — per-node, persists until recovered
    - `_handle_hub_status(payload)`
    - `_handle_file_activity(payload)`
    - `_handle_security(payload)`
    - `_render_situations() -> str` — priority-sorted Rich markup
    - `_age_situations()` — dim resolved, drop after TTL (30m default)
    - `render()` calls `_render_situations()`
  - `_EVENT_ROUTING` dict mapping event_type strings to handler methods
  - Ignored events: delivery_status, announce_sent, rpc_received, contact_*, conversation_*, auto_reply_changed, identity_changed
- [ ] 1.2 Register in `src/styrened/tui/widgets/__init__.py`
- [ ] 1.3 Add `#activity-panel CopActivitySummary` styles to `styrene.tcss`

## Group 2: Daemon event payload fix

- [ ] 2.1 Add `discovered_via` to device_discovered activity event metadata in `src/styrened/daemon.py` `_on_device_discovered()`

## Group 3: Dashboard integration

- [ ] 3.1 Replace `ActivityFeedWidget` with `CopActivitySummary` in `dashboard.py` Home compose
- [ ] 3.2 Update `_subscribe_activity()` to call `cop_summary.ingest_event()` instead of `activity_widget.add_event()`
- [ ] 3.3 Add periodic `_age_situations()` call (timer or on-event check)

## Group 4: Tests

- [ ] 4.1 Unit tests for `transport_label()` parser — all 11 interface types + fallback
- [ ] 4.2 Unit tests for situation coalescing — UNREAD grouping, NODE_DISCOVERY per-transport counting
- [ ] 4.3 Unit tests for aging — dim after resolve, drop after TTL
- [ ] 4.4 Unit tests for priority ordering — anomalies first, then actionable, then informational
- [ ] 4.5 Unit tests for ignored event types — verify they don't create situation lines
- [ ] 4.6 Update dashboard test to expect CopActivitySummary instead of ActivityFeedWidget
