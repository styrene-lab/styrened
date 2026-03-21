# styrene-rs-unix-socket-ipc — Tasks

## 1. IPC server accepts connections on Unix socket

- [x] 1.1 Server starts and listens
- [x] 1.2 Multiple concurrent clients
- [x] 1.3 Client sends QUERY_STATUS
- [x] 1.4 Client sends unknown message type
- [x] 1.5 Write tests for IPC server accepts connections on Unix socket

## 2. Server graceful shutdown

- [x] 2.1 Stop removes socket file
- [x] 2.2 Write tests for Server graceful shutdown

## 3. Subscription event push

- [x] 3.1 Client subscribes to devices then receives events
- [x] 3.2 Client unsubscribes stops receiving events
- [x] 3.3 Write tests for Subscription event push

## 4. Frame encode produces Python-compatible bytes

- [x] 4.1 Encode a PING frame
- [x] 4.2 Encode a RESULT frame with payload
- [x] 4.3 Write tests for Frame encode produces Python-compatible bytes

## 5. Frame decode handles valid and malformed input

- [x] 5.1 Decode a valid QUERY_STATUS frame
- [x] 5.2 Decode truncated frame returns error
- [x] 5.3 Unknown message type returns error
- [x] 5.4 Payload exceeding MAX_PAYLOAD_SIZE is rejected
- [x] 5.5 Write tests for Frame decode handles valid and malformed input

## 6. MessageType enum values match Python IPCMessageType

- [x] 6.1 Core message type byte values
- [x] 6.2 Write tests for MessageType enum values match Python IPCMessageType
