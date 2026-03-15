---
id: hub-status-semantics
title: Hub Status Semantics — DISABLED vs WAITING for Default Hub
status: implemented
parent: tui-home-cop
tags: [hub, cop, ux, onboarding, hub-connection, first-run]
open_questions: []
---

# Hub Status Semantics — DISABLED vs WAITING for Default Hub

## Overview

HubStatus.DISABLED currently means 'no hub address configured' — but the Styrene Community Hub is seeded into every fresh install via WELL_KNOWN_HUBS. A new user who has never received a hub announce will see 'hub: dark/disabled' which incorrectly implies they haven't configured a hub at all. The semantic distinction is: DISABLED should mean the operator has explicitly opted out of hub connectivity, not 'we haven't heard an announce yet.' A user with the Community Hub in their peers list has A hub — they're just waiting for the first announce.

## Research

### Current behavior and the bug

HubConnection._hub_address is None until connect() is called. connect() is only called when a hub announce arrives over RNS. HubStatus.get_status() returns DISABLED when _hub_address is None. So a brand new user with WELL_KNOWN_HUBS seeded in their peers list sees HUB: disabled (dark) until they receive their first announce from the Community Hub — which can take minutes on first boot as RNS builds paths.

This is wrong in two ways:
1. **Semantic wrong**: DISABLED implies the operator chose not to use a hub. But they didn't choose anything — the hub is configured by default. The user is just waiting.
2. **Trust wrong**: The Community Hub IS their hub for announce propagation purposes. They are not hub-less. They are hub-unreached.

The actual state machine should be:
- DISABLED = operator has explicitly set hub.mode = none / removed all hub peers
- WAITING = hub is configured (known address exists), awaiting first announce
- CONNECTED = announce received within window
- DISCONNECTED = had a connection, announce window expired

The current code collapses DISABLED and WAITING into the same bucket (None address).

### Fix surface

The WELL_KNOWN_HUBS constant in models/config.py contains PeerConfig entries including the Community Hub (enabled=True). The hub's RNS destination hash is either:
a) Known statically (hardcoded in WELL_KNOWN_HUBS or a companion constant), or
b) Only discoverable after the first announce.

Option (a) would let HubConnection seed _hub_address at daemon startup → immediately shows WAITING. Option (b) means we need a different signal: "hub is configured in peers, but address not yet resolved."

The cleanest fix is a new WAITING_FOR_ANNOUNCE status that the daemon sets at startup when hub peers are present in config but no announce has arrived. This requires no static address — just a flag that says "I know a hub exists and I'm listening for it."

Alternatively: store the Community Hub's known RNS destination hash as a constant alongside WELL_KNOWN_HUBS. The daemon pre-populates _hub_address with it at startup. Status immediately goes to WAITING (is_within_announce_window() will be False initially, but CONNECTED requires is_connected which requires path validation). This is simpler and correct — the Community Hub's address doesn't change.

### Transport vs identity — two distinct concepts

The TCP peer at rns.styrene.io:4242 in WELL_KNOWN_HUBS is the **transport** — it gives RNS a path to reach the hub's network segment. The hub's RNS destination hash is the **identity** — it's only learned when the hub sends an announce over that transport path.

These are separate things and must not be conflated:
- Transport (TCP peer config) → enables RNS to build a path
- Identity (dest hash from announce) → tells HubConnection who the hub actually is

`set_configured()` should fire when the TCP peer is in config — i.e., when the transport is present. This is the correct signal for "a hub exists in my world." The identity arrives later via announce and populates _hub_address via connect().

This also clarifies why hardcoding the hash (Branch A) is wrong even if the hash were stable: it would bypass the announce-based identity discovery that the RNS transport is specifically designed to provide. The TCP peer at rns.styrene.io:4242 is the right and only thing to reference at config time.

## Decisions

### Decision: Branch B — hub configured flag, not hardcoded hash

**Status:** decided
**Rationale:** The Community Hub's identity is Vault-secret-backed and therefore semi-stable — it can change on rotation, DR, or migration. Hardcoding the RNS destination hash in the client would silently break every existing install on any such event. Instead: HubConnection gains a _hub_configured: bool flag, set True at daemon startup when any enabled hub peers exist in config (WELL_KNOWN_HUBS or operator-added). get_status() returns WAITING when _hub_configured and not _hub_address, rather than DISABLED. DISABLED is reserved for the explicit no-hub case.

### Decision: DISABLED reserved for explicit operator opt-out only

**Status:** decided
**Rationale:** DISABLED must only appear when the operator has deliberately removed all hub peers from config or set an explicit hub.mode = none. A fresh install with WELL_KNOWN_HUBS seeded has A hub by definition — the user is waiting for the first announce, not opted out. Showing dark/disabled to a new user who hasn't touched hub config is both semantically wrong and a bad first impression. The state machine is: DISABLED (no peers) → WAITING (peers configured, no announce yet) → CONNECTED (announce received) → DISCONNECTED (announce window expired).

## Open Questions

*No open questions.*

## Implementation Notes

### File Scope

- `src/styrened/services/hub_connection.py` (modified) — Add _hub_configured: bool flag. set_configured(bool) called by daemon at startup. get_status() returns WAITING when _hub_configured and not _hub_address.
- `src/styrened/daemon.py` (modified) — After loading config, call hub_connection.set_configured(any enabled hub peers in config).
- `src/styrened/services/reticulum.py` (modified) — Or wherever announces are handled — ensure set_configured() is called before first announce could arrive.
- `tests/unit/test_hub_connection.py` (modified) — Add tests: configured+no address=WAITING, no peers=DISABLED, configured+address+connected=CONNECTED, configured+address+window expired=DISCONNECTED.

### Constraints

- DISABLED must never appear when WELL_KNOWN_HUBS has any enabled entry
- set_configured() must be called before the RNS announce handler can fire
- No hub hash hardcoded anywhere in client code — all hash knowledge comes from announces
