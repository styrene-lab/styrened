# Operator Interface Testing — Harness Spec

## Scenario: Daemon harness starts and stops cleanly

Given a DaemonHarness configured with alpha fixture identity and tcp_localhost transport
When the harness starts
Then a `styrened` subprocess is running in standalone mode
And the TCP server port is accepting connections within 10 seconds
And the daemon's identity hash matches the alpha fixture README

When the harness stops
Then the subprocess exits within 5 seconds
And the temp config directory is removed
And no orphaned processes remain

## Scenario: Fixture identity keys are deterministic

Given the identity files in `tests/fixtures/test_peers/{host,alpha,bravo}/identity`
When each identity is loaded via `RNS.Identity.from_file()`
Then the identity_hash matches the value documented in the corresponding README.md
And loading the same file twice produces the same hash

## Scenario: Host discovers alpha peer via announce

Given a running alpha daemon harness with announce_interval=1
And a StyreneApp configured with host identity and TCP client to alpha's port
When the TUI starts and waits up to 15 seconds
Then \"🤖 Test Peer Alpha\" appears in the device list
And the device's identity hash matches alpha's fixture hash

## Scenario: Chat round-trip with auto-reply

Given the host TUI has discovered alpha and navigated to the Chat tab
When the operator sends \"test message\"
Then the message appears in the conversation view
And alpha's auto-reply arrives within 5 seconds
And the auto-reply text is visible in the conversation view

## Scenario: RPC exec round-trip

Given the host TUI has discovered alpha and navigated to the Fleet Ops tab
When the operator executes \"echo hello\" via the RPC exec widget
Then the response \"hello\" appears in the output within 10 seconds
