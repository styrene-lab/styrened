# Hub Status Semantics — DISABLED vs WAITING for Default Hub

## Intent

HubStatus.DISABLED currently means 'no hub address configured' — but the Styrene Community Hub is seeded into every fresh install via WELL_KNOWN_HUBS. A new user who has never received a hub announce will see 'hub: dark/disabled' which incorrectly implies they haven't configured a hub at all. The semantic distinction is: DISABLED should mean the operator has explicitly opted out of hub connectivity, not 'we haven't heard an announce yet.' A user with the Community Hub in their peers list has A hub — they're just waiting for the first announce.

See [Hub Status Semantics — DISABLED vs WAITING for Default Hub design doc](../../../docs/hub-status-semantics.md) for full context.
