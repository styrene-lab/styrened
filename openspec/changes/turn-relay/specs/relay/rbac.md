# relay/rbac — Delta Spec

## ADDED Requirements

### Requirement: Relay capabilities added to RBAC model

10 new relay.* capabilities registered in the Capability class and assigned to role tiers.

#### Scenario: PEER tier relay capabilities
Given the RBAC capability registry
When PEER tier capabilities are listed
Then they include relay.request, relay.list, relay.teardown, relay.accept, relay.reject

#### Scenario: OPERATOR tier relay capabilities
Given the RBAC capability registry
When OPERATOR tier capabilities are listed
Then they include relay.request_permanent, relay.accept_permanent, relay.prioritize, relay.bridge

#### Scenario: ADMIN tier relay capabilities
Given the RBAC capability registry
When ADMIN tier capabilities are listed
Then they include relay.admin

#### Scenario: All relay capabilities in ALL registry
Given the Capability.ALL frozenset
When checked for relay capabilities
Then all 10 relay.* strings are present

### Requirement: Relay request RBAC gating

Hub checks requester has relay.request before creating a session.

#### Scenario: Authorized relay request
Given peer A has PEER role on the hub
When peer A requests a relay to peer B
Then the request is accepted (pending target consent)

#### Scenario: Unauthorized relay request
Given peer A has NONE role on the hub (no relay.request)
When peer A requests a relay
Then RelayUnauthorized is raised

#### Scenario: Permanent relay request requires OPERATOR
Given peer A has PEER role (not OPERATOR)
When peer A requests a permanent relay
Then RelayPermanentDenied is raised

### Requirement: Target peer RBAC gating

Target peer's RBAC policy gates incoming relayed connections.

#### Scenario: Target accepts relay
Given peer B has relay.accept in their RBAC policy for peer A
When hub forwards the relay request to peer B
Then the relay is established

#### Scenario: Target rejects relay
Given peer B has relay.reject for peer A's identity
When hub forwards the relay request
Then RelayTargetRejected is raised

#### Scenario: Permanent relay target consent
Given peer B lacks relay.accept_permanent for peer A
When a permanent relay is requested
Then RelayPermanentConsentDenied is raised
