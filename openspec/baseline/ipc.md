# ipc — IPC Interface Breaking Changes Spec

### Requirement: CmdBlockPeerRequest uses identity_hash, no peer_hash field

#### Scenario: block request serialization

Given a block request for `identity_hash="id_abc"`, `lxmf_dest_hash="lxmf_abc"`, `alias="Alice"`
When `CmdBlockPeerRequest(identity_hash="id_abc", lxmf_dest_hash="lxmf_abc", alias="Alice").to_payload()` is called
Then the payload is `{"identity_hash": "id_abc", "lxmf_dest_hash": "lxmf_abc", "alias": "Alice"}`
And the payload does NOT contain a `peer_hash` key

#### Scenario: block request deserialization

Given a payload `{"identity_hash": "id_abc", "lxmf_dest_hash": "lxmf_abc"}`
When `CmdBlockPeerRequest.from_payload(payload)` is called
Then `req.identity_hash == "id_abc"` and `req.lxmf_dest_hash == "lxmf_abc"`

#### Scenario: handler rejects request with empty identity_hash

Given a `CmdBlockPeerRequest` with `identity_hash=""`
When `handle_cmd_block_peer` processes it
Then an `ErrorResponse` is returned with message containing "identity_hash required"
And `block_peer` is NOT called

---

## CHANGED: CmdUnblockPeerRequest

### Requirement: CmdUnblockPeerRequest uses identity_hash, no peer_hash field

#### Scenario: unblock request serialization

Given `CmdUnblockPeerRequest(identity_hash="id_abc").to_payload()`
Then payload is `{"identity_hash": "id_abc"}` with no `peer_hash` key

---

## CHANGED: QueryBlockedPeersRequest response

### Requirement: blocked peers response uses identity_hash

#### Scenario: get blocked peers response shape

Given peer_blocks has `{identity_hash="id_abc", lxmf_dest_hash="lxmf_abc", alias="Alice"}`
When `QueryBlockedPeersRequest` is processed
Then the result data contains `[{"identity_hash": "id_abc", "lxmf_dest_hash": "lxmf_abc", "alias": "Alice"}]`
And no item in the list has a `peer_hash` key

---

## CHANGED: IPCBridge and IPCClient

### Requirement: bridge and client block_peer/unblock_peer take identity_hash

#### Scenario: bridge forwards identity_hash to IPC

Given `bridge.block_peer(identity_hash="id_abc", lxmf_dest_hash="lxmf_abc")`
When the request is serialized and dispatched
Then `CmdBlockPeerRequest.identity_hash == "id_abc"` reaches the handler

---

## REMOVED: MeshDevice.identity property

### Requirement: MeshDevice.identity property is removed entirely

#### Scenario: accessing .identity raises AttributeError

Given a `MeshDevice` instance
When code accesses `device.identity`
Then `AttributeError` is raised (property no longer exists)
And all former callers have been updated to use `device.identity_hash` or `device.destination_hash` explicitly

#### Scenario: TUI block actions use device.identity_hash

Given a ConversationScreen opened for a peer with `identity_hash="id_abc"`
When the operator presses B twice to confirm block
Then `bridge.block_peer(identity_hash="id_abc")` is called
And NOT `bridge.block_peer(identity_hash=device.destination_hash)`
