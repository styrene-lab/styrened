# Hub Status Semantics — Design Spec

## Scenarios

### Scenario 1: Fresh install shows WAITING, not DISABLED

Given a fresh install with WELL_KNOWN_HUBS seeded (Community Hub enabled)
When the daemon starts and no hub announce has arrived yet
Then HubStatus is WAITING — not DISABLED

### Scenario 2: DISABLED only when no hub peers exist

Given the operator has removed all hub peers from config (or set hub.mode = none)
When the daemon starts
Then HubStatus is DISABLED

### Scenario 3: CONNECTED after announce arrives

Given HubStatus is WAITING
When a hub announce is received over RNS
Then HubStatus transitions to CONNECTED

### Scenario 4: DISCONNECTED after announce window expires

Given HubStatus is CONNECTED
When the announce window expires without a new announce
Then HubStatus transitions to DISCONNECTED (not DISABLED)

### Scenario 5: No hub hash hardcoded

Given the Community Hub rotates its Vault-backed RNS identity
When the new announce arrives
Then connect() updates _hub_address from the announce — no stale hardcoded hash causes breakage

## Falsifiability

- If a fresh install with default config ever shows HubStatus.DISABLED, this design fails
- If any hub destination hash appears hardcoded in client source, this design fails
- If set_configured() can be called after the first announce handler fires, there is a race condition

## Constraints

- set_configured() must be called at daemon startup, before RNS announce processing begins
- WELL_KNOWN_HUBS with any enabled entry must produce _hub_configured = True
- No hash knowledge in client — all hub address resolution comes from announces
