# relay/models — Delta Spec

## ADDED Requirements

### Requirement: RelayConfig data model

RelayConfig holds hub-side relay configuration with sensible defaults.

#### Scenario: Default RelayConfig
Given a RelayConfig is instantiated with no arguments
When its fields are inspected
Then enabled is False
And max_sessions is 16
And max_per_identity is 2
And max_bytes_per_session is 52428800
And idle_timeout is 900
And allow_permanent is False
And allowed_identities is an empty list

### Requirement: RelaySession data model

RelaySession tracks an active relay between two peers through the hub.

#### Scenario: Session creation
Given peer A hash "aaa" and peer B hash "bbb"
When a RelaySession is created for them
Then requester_hash is "aaa"
And target_hash is "bbb"
And bytes_forwarded is 0
And is_permanent is False
And created_at is set
And last_activity is set

#### Scenario: Session byte tracking
Given an active RelaySession with 0 bytes forwarded
When 1024 bytes are recorded via record_bytes(1024)
Then bytes_forwarded is 1024
And last_activity is updated

### Requirement: 12 distinct RelayError types

Each error condition has its own exception class for precise error handling and testing.

#### Scenario: All error types are distinct
Given the relay error hierarchy
When all RelayError subclasses are collected
Then there are exactly 12 distinct error types
And each has a unique error_code string
And all inherit from RelayError base

#### Scenario: Error types enumerated
Given the relay error hierarchy
When the error classes are listed
Then they include RelayDisabled, RelayMaxSessions, RelayMaxPerIdentity, RelayByteLimitExceeded, RelayIdleTimeout, RelayUnauthorized, RelayPermanentDenied, RelayTargetRejected, RelayTargetOffline, RelayPermanentConsentDenied, RelayEvicted, RelayBridgeDenied
