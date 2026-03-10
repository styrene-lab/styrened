---
id: group-thread-footprint-policy
title: Group Thread Footprint Policy
status: decided
parent: lxmf-group-discussion-model
tags: [tui, mail, group-threads, performance, storage]
open_questions: []
---

# Group Thread Footprint Policy

## Overview

Define how private group-thread state, storage, and richer capabilities should degrade gracefully on constrained hardware without fragmenting room identity or transport-unified participation.

## Research

### Group-thread capability should be feature-tiered, not all-or-nothing

Constrained devices should not be forced to either fully support every group-room convenience feature or opt out of room participation entirely. The room identity, membership, and basic async text participation model should remain available at the lowest tier, while heavier capabilities such as rich media caching, full local room history retention, background catch-up, and aggressive attachment fetching can be selectively disabled. This preserves interoperability and room continuity while reducing storage, CPU, RAM, and link pressure.

### First-run defaults can be hardware-informed but must remain operator-overridable

It is reasonable to choose an initial group-thread feature tier based on authoritative local hardware signals such as memory class, storage class, and device profile, but this should only set a default. Operators need an explicit setting to raise or lower the tier later. This avoids silent capability cliffs while still protecting small edge devices from expensive defaults.

### Graceful degradation should prefer fetch-on-demand and bounded retention over room fragmentation

If resources are constrained, the system should degrade by bounding cached room metadata, limiting retained local history, disabling automatic media fetch, reducing background synchronization, or keeping only membership/epoch state plus recent text summaries. It should not degrade by creating separate room variants per transport or by hiding a room entirely from constrained peers that can still participate asynchronously.

### Implementation status checkpoint

The footprint policy is now materially wired through config, defaulting, and placeholder UI. `group_threads` is persisted in core config, Settings exposes explicit operator overrides, default TUI config creation applies the hardware-informed tier heuristic automatically, and the dedicated group-room screen explains the effective local tier and its consequences for history/sync/media/catch-up behavior. Remaining gaps are primarily action-path wiring and authoritative live participant/path inputs rather than policy modeling or persistence.

## Decisions

### Decision: Group-thread participation should degrade by feature tier, not by transport-specific room fragmentation

**Status:** decided
**Rationale:** Even the smallest nodes should be able to participate in the same room when they can support basic async text and membership control. Resource pressure should disable or reduce heavyweight conveniences such as large media handling, deep history retention, and aggressive background sync before it changes room identity or splits participation by transport.

### Decision: Group-thread persistence and richer features should be governed by an explicit operator setting with hardware-informed first-run defaults

**Status:** decided
**Rationale:** A first-run heuristic can choose a safe starting tier for low-resource devices, but long-term behavior must remain transparent and operator-controlled. This setting can default differently on tiny LoRa nodes versus larger machines while still allowing later adjustment as needs change.

### Decision: Constrained tiers should prefer bounded retention, metadata-first sync, and confirmation before expensive media actions

**Status:** decided
**Rationale:** The best graceful-degradation path is to keep room identity, membership, and recent text usable while reducing storage and bandwidth pressure. Bounded retained history, on-demand fetch, disabled auto-media download, and explicit confirmation for costly transfers preserve room usability without overcommitting scarce resources.

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/ui_state/mail.py` (modified) — Group-thread state now includes feature tiers, participant reachability records, fallback interfaces, delivery-path class, and media-friction metadata so constrained-path decisions are modeled canonically rather than inferred ad hoc.
- `src/styrened/tui/screens/mail_group_thread.py` (modified) — Group-thread placeholder now surfaces local degradation policy, participant highest-available interfaces, fallback routes, and constrained-path media warnings, preserving one room across varying transport quality.
- `src/styrened/models/config.py` (modified) — CoreConfig now carries an explicit group_threads policy section with feature tier and degradation flags so footprint behavior is operator-visible and serializable.
- `src/styrened/services/config.py` (modified) — Config load/save now round-trips group_threads policy fields, keeping footprint behavior in declarative config rather than placeholder-only UI state.
- `src/styrened/services/group_threads.py` (new) — HardwareFootprintInputs and choose_group_thread_feature_tier() provide a conservative first-run heuristic for selecting minimal/balanced/full group-thread feature tiers from coarse hardware signals.
- `src/styrened/ui_state/daemon.py` (modified) — Local daemon state now surfaces group-thread feature tier and degradation flags so frontends can show current local footprint policy without custom config parsing.
- `src/styrened/tui/screens/settings.py` (modified) — Settings screen now exposes the group_threads policy section so operators can explicitly control feature tier, bounded retention, metadata-first sync, media auto-fetch, background catch-up, and first-run auto-tier behavior.
- `tests/tui/screens/test_settings_tui.py` (modified) — TUI tests now verify group-thread footprint controls render current config values and persist operator-edited policy settings on save.
- `src/styrened/tui/services/config.py` (modified) — Default TUI config creation now automatically applies the group-thread hardware heuristic and derives bounded-retention / metadata-first / media-fetch / background-catchup defaults from the chosen tier, while respecting first_run_auto_tier overrides.
- `tests/tui/services/test_config.py` (modified) — Config-service tests now verify first-run group-thread defaults are chosen from hardware inputs, that balanced/full policy bundles are derived correctly, and that disabling first_run_auto_tier preserves operator overrides.
- `src/styrened/tui/screens/mail_group_thread.py` (modified) — Group Mail room UI now explains the effective local tier in plain language, enumerates the resulting history/sync/media/catch-up behavior, and shows a policy-driven media warning even when no constrained participant snapshot is present.
- `tests/tui/screens/test_group_forum_placeholders.py` (modified) — Placeholder-room tests now verify the UI surfaces tier explanations and on-demand media warnings tied to the local footprint policy.

### Constraints

- Current participant reachability data is modeled and rendered, but still supplied through snapshot inputs rather than authoritative live daemon wiring.
- Hardware-informed first-run defaults now apply during default-config creation, but current heuristics still rely on coarse local hardware detection and optional `STYRENE_DEVICE_PROFILE` rather than richer daemon-provided device classification.
- The room screen now explains the local policy clearly, but the actual invite/send/media action flows do not yet consume the footprint policy directly.
