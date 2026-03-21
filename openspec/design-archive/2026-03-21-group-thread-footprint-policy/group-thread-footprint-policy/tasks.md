# Group Thread Footprint Policy — Tasks

## 1. src/styrened/ui_state/mail.py (modified)

- [x] 1.1 Group-thread state now includes feature tiers, participant reachability records, fallback interfaces, delivery-path class, and media-friction metadata so constrained-path decisions are modeled canonically rather than inferred ad hoc.

## 2. src/styrened/tui/screens/mail_group_thread.py (modified)

- [x] 2.1 Group-thread placeholder now surfaces local degradation policy, participant highest-available interfaces, fallback routes, and constrained-path media warnings, preserving one room across varying transport quality.

## 3. src/styrened/models/config.py (modified)

- [x] 3.1 CoreConfig now carries an explicit group_threads policy section with feature tier and degradation flags so footprint behavior is operator-visible and serializable.

## 4. src/styrened/services/config.py (modified)

- [x] 4.1 Config load/save now round-trips group_threads policy fields, keeping footprint behavior in declarative config rather than placeholder-only UI state.

## 5. src/styrened/services/group_threads.py (new)

- [x] 5.1 HardwareFootprintInputs and choose_group_thread_feature_tier() provide a conservative first-run heuristic for selecting minimal/balanced/full group-thread feature tiers from coarse hardware signals.

## 6. src/styrened/ui_state/daemon.py (modified)

- [x] 6.1 Local daemon state now surfaces group-thread feature tier and degradation flags so frontends can show current local footprint policy without custom config parsing.

## 7. src/styrened/tui/screens/settings.py (modified)

- [x] 7.1 Settings screen now exposes the group_threads policy section so operators can explicitly control feature tier, bounded retention, metadata-first sync, media auto-fetch, background catch-up, and first-run auto-tier behavior.

## 8. tests/tui/screens/test_settings_tui.py (modified)

- [x] 8.1 TUI tests now verify group-thread footprint controls render current config values and persist operator-edited policy settings on save.

## 9. src/styrened/tui/services/config.py (modified)

- [x] 9.1 Default TUI config creation now automatically applies the group-thread hardware heuristic and derives bounded-retention / metadata-first / media-fetch / background-catchup defaults from the chosen tier, while respecting first_run_auto_tier overrides.

## 10. tests/tui/services/test_config.py (modified)

- [x] 10.1 Config-service tests now verify first-run group-thread defaults are chosen from hardware inputs, that balanced/full policy bundles are derived correctly, and that disabling first_run_auto_tier preserves operator overrides.

## 11. src/styrened/tui/screens/mail_group_thread.py (modified)

- [x] 11.1 Group Mail room UI now explains the effective local tier in plain language, enumerates the resulting history/sync/media/catch-up behavior, and shows a policy-driven media warning even when no constrained participant snapshot is present.

## 12. tests/tui/screens/test_group_forum_placeholders.py (modified)

- [x] 12.1 Placeholder-room tests now verify the UI surfaces tier explanations and on-demand media warnings tied to the local footprint policy.

## 13. Cross-cutting constraints

- [x] 13.1 Current participant reachability data is modeled and rendered, but still supplied through snapshot inputs rather than authoritative live daemon wiring.
- [x] 13.2 Hardware-informed first-run defaults now apply during default-config creation, but current heuristics still rely on coarse local hardware detection and optional `STYRENE_DEVICE_PROFILE` rather than richer daemon-provided device classification.
- [x] 13.3 The room screen now explains the local policy clearly, but the actual invite/send/media action flows do not yet consume the footprint policy directly.
