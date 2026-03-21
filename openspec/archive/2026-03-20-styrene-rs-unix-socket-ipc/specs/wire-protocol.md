# wire-protocol — Delta Spec

## ADDED Requirements

### Requirement: Frame encode produces Python-compatible bytes

#### Scenario: Encode a PING frame

Given a MessageType::Ping (0x01), a 16-byte request_id, and an empty dict payload
When encode_frame is called
Then the output is [4-byte BE length = 18][0x01][request_id][msgpack {}]

#### Scenario: Encode a RESULT frame with payload

Given a MessageType::Result (0x81), a request_id, and payload {"uptime": 42}
When encode_frame is called
Then the 4-byte length prefix equals 1 + 16 + len(msgpack({"uptime": 42}))
And the payload bytes round-trip through rmp_serde and Python msgpack identically

### Requirement: Frame decode handles valid and malformed input

#### Scenario: Decode a valid QUERY_STATUS frame

Given raw bytes encoding a QUERY_STATUS (0x12) frame with empty payload
When decode_frame is called
Then it returns MessageType::QueryStatus, the correct request_id, and an empty HashMap

#### Scenario: Decode truncated frame returns error

Given raw bytes with length prefix claiming 100 bytes but only 20 bytes present
When decode_frame is called
Then it returns Err(WireError::Incomplete)

#### Scenario: Unknown message type returns error

Given a frame with type byte 0xFF (not in enum)
When decode_frame is called
Then it returns Err(WireError::UnknownType(0xFF))

#### Scenario: Payload exceeding MAX_PAYLOAD_SIZE is rejected

Given a frame with length prefix exceeding 4MB + 17
When decode_frame is called
Then it returns Err(WireError::PayloadTooLarge)

### Requirement: MessageType enum values match Python IPCMessageType

#### Scenario: Core message type byte values

Given the MessageType enum
Then Ping == 0x01, Pong == 0x80, QueryDevices == 0x10, QueryIdentity == 0x11
And QueryStatus == 0x12, Result == 0x81, Error == 0x82
And SubDevices == 0x30, SubMessages == 0x31, SubActivity == 0x32, Unsub == 0x3F
And EventDevice == 0xC0, EventMessage == 0xC1, EventActivity == 0xC6
