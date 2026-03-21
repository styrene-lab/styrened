# Group Thread Footprint Policy — Design Spec (extracted)

> Auto-extracted from docs/group-thread-footprint-policy.md at decide-time.

## Decisions

### Group-thread participation should degrade by feature tier, not by transport-specific room fragmentation (decided)

Even the smallest nodes should be able to participate in the same room when they can support basic async text and membership control. Resource pressure should disable or reduce heavyweight conveniences such as large media handling, deep history retention, and aggressive background sync before it changes room identity or splits participation by transport.

### Group-thread persistence and richer features should be governed by an explicit operator setting with hardware-informed first-run defaults (decided)

A first-run heuristic can choose a safe starting tier for low-resource devices, but long-term behavior must remain transparent and operator-controlled. This setting can default differently on tiny LoRa nodes versus larger machines while still allowing later adjustment as needs change.

### Constrained tiers should prefer bounded retention, metadata-first sync, and confirmation before expensive media actions (decided)

The best graceful-degradation path is to keep room identity, membership, and recent text usable while reducing storage and bandwidth pressure. Bounded retained history, on-demand fetch, disabled auto-media download, and explicit confirmation for costly transfers preserve room usability without overcommitting scarce resources.

## Research Summary

### Group-thread capability should be feature-tiered, not all-or-nothing

Constrained devices should not be forced to either fully support every group-room convenience feature or opt out of room participation entirely. The room identity, membership, and basic async text participation model should remain available at the lowest tier, while heavier capabilities such as rich media caching, full local room history retention, background catch-up, and aggressive attachment fetching can be selectively disabled. This preserves interoperability and room continuity while reduci…

### First-run defaults can be hardware-informed but must remain operator-overridable

It is reasonable to choose an initial group-thread feature tier based on authoritative local hardware signals such as memory class, storage class, and device profile, but this should only set a default. Operators need an explicit setting to raise or lower the tier later. This avoids silent capability cliffs while still protecting small edge devices from expensive defaults.

### Graceful degradation should prefer fetch-on-demand and bounded retention over room fragmentation

If resources are constrained, the system should degrade by bounding cached room metadata, limiting retained local history, disabling automatic media fetch, reducing background synchronization, or keeping only membership/epoch state plus recent text summaries. It should not degrade by creating separate room variants per transport or by hiding a room entirely from constrained peers that can still participate asynchronously.

### Implementation status checkpoint

The footprint policy is now materially wired through config, defaulting, and placeholder UI. `group_threads` is persisted in core config, Settings exposes explicit operator overrides, default TUI config creation applies the hardware-informed tier heuristic automatically, and the dedicated group-room screen explains the effective local tier and its consequences for history/sync/media/catch-up behavior. Remaining gaps are primarily action-path wiring and authoritative live participant/path inputs …
