## Result

**Status:** SUCCESS

**Summary:** Added 10 relay.* capabilities to the RBAC model across 3 tiers (PEER: 5, OPERATOR: 4, ADMIN: 1). All capabilities registered in Capability.ALL and cumulative ROLE_CAPABILITIES sets. TDD: 66 tests written first, all pass. Existing 66 RBAC tests unaffected.

**Artifacts:**
- `src/styrened/models/rbac.py` — 10 new Capability constants + added to _PEER_CAPS, _OPERATOR_CAPS, _ADMIN_CAPS frozensets
- `tests/unit/test_relay_rbac.py` — 66 tests covering existence, tier assignment, ALL registry, has_capability gating, cumulative hierarchy, roster grants

**Decisions Made:**
- Relay capabilities follow the same cumulative hierarchy pattern as existing capabilities (PEER ⊂ OPERATOR ⊂ ADMIN)
- relay.admin is in the ADMIN tier (not orthogonal like vpn.handshake) since admin relay control is a natural privilege escalation

**Assumptions:**
- No orthogonal relay grants needed (all relay caps fit the standard tier hierarchy)

**Interfaces Published:**
- `Capability.RELAY_REQUEST` = "relay.request"
- `Capability.RELAY_LIST` = "relay.list"
- `Capability.RELAY_TEARDOWN` = "relay.teardown"
- `Capability.RELAY_ACCEPT` = "relay.accept"
- `Capability.RELAY_REJECT` = "relay.reject"
- `Capability.RELAY_REQUEST_PERMANENT` = "relay.request_permanent"
- `Capability.RELAY_ACCEPT_PERMANENT` = "relay.accept_permanent"
- `Capability.RELAY_PRIORITIZE` = "relay.prioritize"
- `Capability.RELAY_BRIDGE` = "relay.bridge"
- `Capability.RELAY_ADMIN` = "relay.admin"

**Verification:**
- Command: `.venv/bin/python -m pytest tests/unit/test_relay_rbac.py tests/unit/test_rbac.py -v`
- Output: 132 passed (66 new + 66 existing)
- Edge cases: roster grant override tested, NONE/BLOCKED exclusion tested, cumulative inheritance verified
