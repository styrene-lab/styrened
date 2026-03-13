# relay/service

### Requirement: RelayService session lifecycle

RelayService manages active relay sessions on the hub, enforcing all resource limits.

#### Scenario: Create relay session within limits
Given relay is enabled with default limits
And peer A has relay.request capability
And no existing sessions for peer A
When peer A requests relay to peer B
Then a RelaySession is created
And active_sessions count is 1

#### Scenario: Global session cap enforced
Given relay.max_sessions is 2
And 2 relay sessions are active
When a new relay is requested
Then RelayMaxSessions is raised
And no new session is created

#### Scenario: Per-identity session cap enforced
Given relay.max_per_identity is 2
And peer A already has 2 active relay sessions
When peer A requests another relay
Then RelayMaxPerIdentity is raised

#### Scenario: Byte limit enforcement
Given a session with max_bytes_per_session of 1000
And 900 bytes have been forwarded
When 200 more bytes are forwarded
Then RelayByteLimitExceeded is raised
And the session is torn down

#### Scenario: Idle timeout teardown
Given a session with idle_timeout of 5 seconds
And no data has flowed for 6 seconds
When the idle check runs
Then the session is torn down
And RelayIdleTimeout is recorded

#### Scenario: Permanent session skips idle timeout and byte cap
Given a permanent relay session
And no data has flowed for 30 minutes
When the idle check runs
Then the session remains active

#### Scenario: Disconnect propagation (default)
Given a non-permanent relay session between A and B
When peer A disconnects
Then the session for peer B is also torn down

#### Scenario: Disconnect handling (permanent)
Given a permanent relay session between A and B
When peer A disconnects
Then peer B's half remains alive
And hub attempts reconnect to peer A for the grace period

### Requirement: LRU eviction with priority

When the hub hits max_sessions, non-priority sessions are evicted first.

#### Scenario: LRU eviction of oldest non-priority session
Given max_sessions is 2 with sessions S1 (old, non-priority) and S2 (new, priority)
When a new priority relay is requested
Then S1 is evicted (RelayEvicted)
And the new session is created

#### Scenario: All priority sessions prevents new session
Given max_sessions is 2 with both sessions marked priority
When a new non-priority relay is requested
Then RelayMaxSessions is raised (no evictable sessions)

### Requirement: Relay disabled check

Hub must reject all relay requests when relay.enabled is false.

#### Scenario: Relay disabled
Given relay.enabled is false in hub config
When any relay request arrives
Then RelayDisabled is raised

### Requirement: Target offline detection

Hub must detect when the target peer has no active link.

#### Scenario: Target not connected
Given peer B has no active DirectLink to the hub
When peer A requests a relay to peer B
Then RelayTargetOffline is raised
