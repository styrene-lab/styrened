# message-receive — LXMF Receive RBAC Fix Spec

### Requirement: RBAC check uses identity_hash resolved from source LXMF hash

#### Scenario: blocked peer message is dropped — identity hash known

Given `block_peer("id_abc")` has been called
And NodeStore maps `lxmf_dest_hash="lxmf_abc"` → `identity_hash="id_abc"`
When an LXMF message arrives with `source_hash="lxmf_abc"`
Then `resolve_role("id_abc")` is called (not `resolve_role("lxmf_abc")`)
And the message is dropped with a log entry
And no protocol callbacks are invoked

#### Scenario: blocked peer message is dropped — identity hash unknown (fallback)

Given `block_peer("lxmf_abc")` was called with dest hash as best-effort key
And NodeStore has NO mapping for `lxmf_dest_hash="lxmf_abc"`
When an LXMF message arrives with `source_hash="lxmf_abc"`
Then `resolve_role("lxmf_abc")` is checked as fallback
And the message is dropped (block still effective at LXMF layer)

#### Scenario: allowed peer message passes through

Given `identity_hash="id_xyz"` is NOT in RBAC blocked list
And NodeStore maps `lxmf_dest_hash="lxmf_xyz"` → `identity_hash="id_xyz"`
When an LXMF message arrives with `source_hash="lxmf_xyz"`
Then the message is NOT dropped
And protocol callbacks are invoked normally

#### Scenario: NodeStore lookup failure does not drop message

Given NodeStore raises an exception during lookup
When an LXMF message arrives from an unblocked peer
Then the exception is caught
And the fallback is the raw LXMF source hash for RBAC check
And the message is processed normally (not silently dropped)

#### Scenario: YAML static block prefix matches via identity hash

Given YAML rbac.blocked contains prefix `"ca3e9813"`
And NodeStore maps `lxmf_dest_hash="lxmf_ca3"` → `identity_hash="ca3e9813abcdef12"`
When an LXMF message arrives from `source_hash="lxmf_ca3"`
Then `resolve_role("ca3e9813abcdef12")` returns `Role.BLOCKED` (prefix match)
And the message is dropped
