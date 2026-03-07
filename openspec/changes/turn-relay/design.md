# turn-relay — Design

## Spec-Derived Architecture

### relay/config

- **RelayConfig in CoreConfig** (added) — 3 scenarios
- **DirectLink tracks link type** (modified) — 2 scenarios

### relay/models

- **RelayConfig data model** (added) — 1 scenarios
- **RelaySession data model** (added) — 2 scenarios
- **12 distinct RelayError types** (added) — 2 scenarios

### relay/rbac

- **Relay capabilities added to RBAC model** (added) — 4 scenarios
- **Relay request RBAC gating** (added) — 3 scenarios
- **Target peer RBAC gating** (added) — 3 scenarios

### relay/service

- **RelayService session lifecycle** (added) — 8 scenarios
- **LRU eviction with priority** (added) — 2 scenarios
- **Relay disabled check** (added) — 1 scenarios
- **Target offline detection** (added) — 1 scenarios

## File Changes

| File | Action | Scope |
|------|--------|-------|
| `src/styrened/models/relay.py` | new | RelayConfig, RelaySession, LinkType, 12 RelayError subclasses |
| `src/styrened/models/rbac.py` | modified | 10 relay.* capabilities across PEER/OPERATOR/ADMIN tiers |
| `src/styrened/models/config.py` | modified | Add RelayConfig field to CoreConfig |
| `src/styrened/services/relay.py` | new | RelayService — session lifecycle, limits, eviction, idle check |
| `src/styrened/services/config.py` | modified | Parse relay: YAML section |
| `src/styrened/services/direct_link.py` | modified | /relay endpoint, LinkType tracking, request forwarding |
| `src/styrened/daemon.py` | modified | Wire RelayService lifecycle, config loading |
| `tests/unit/test_relay_errors.py` | new | Error hierarchy + model tests |
| `tests/unit/test_relay_rbac.py` | new | Capability tier + gating tests |
| `tests/unit/test_relay.py` | new | Service lifecycle, limits, eviction, config tests |

## Constraints

- RNS.Channel is single-packet (~383B) — use for signaling only, not bulk forwarding
- Relay must not bypass target peer RBAC — relayed links carry source identity hash
- Permanent links require triple consent: requester cap + hub config + target cap
- 12 distinct error types, each with dedicated test
- Hub relay is opt-in (relay.enabled defaults to false)

## Task Dependencies

Groups 1 and 2 are independent (models only). Group 3 depends on 1+2. Group 4 depends on 3.
