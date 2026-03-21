# server — Delta Spec

## ADDED Requirements

### Requirement: IPC server accepts connections on Unix socket

#### Scenario: Server starts and listens

Given an IpcServer configured with a temp socket path and an Arc<dyn Daemon>
When start() is called
Then the socket file exists at the configured path
And the server accepts TCP-style connections

#### Scenario: Multiple concurrent clients

Given a running IpcServer
When two clients connect simultaneously and send PING
Then both receive PONG responses without blocking each other

#### Scenario: Client sends QUERY_STATUS

Given a running IpcServer with a DaemonFacade that returns uptime=42
When a client sends a QUERY_STATUS frame
Then the client receives a RESULT frame with payload containing uptime=42

#### Scenario: Client sends unknown message type

Given a running IpcServer
When a client sends a frame with type byte 0xFF
Then the client receives an ERROR frame with a descriptive message

### Requirement: Server graceful shutdown

#### Scenario: Stop removes socket file

Given a running IpcServer
When stop() is called
Then all client connections are closed
And the socket file is removed from the filesystem

### Requirement: Subscription event push

#### Scenario: Client subscribes to devices then receives events

Given a running IpcServer and a connected client
When the client sends SUB_DEVICES and the daemon emits a Device event
Then the client receives an EVENT_DEVICE frame with the device info

#### Scenario: Client unsubscribes stops receiving events

Given a client subscribed to SUB_DEVICES
When the client sends UNSUB for devices
Then subsequent Device events are not pushed to that client
"
