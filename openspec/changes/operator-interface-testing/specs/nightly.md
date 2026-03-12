# Operator Interface Testing — Nightly CI Spec

## Scenario: Operator path tests run in nightly workflow

Given the nightly Argo workflow runs with test-tier "smoke or integration"
When the smoke tier succeeds
Then the operator-paths step executes `pytest tests/tui/operator/ -m operator_path`
And JUnit XML results are written to `/workspace/results/operator-paths-results.xml`
And the step uses a container with styrened[tui] installed

## Scenario: Daemon subprocess works in CI container

Given the CI container is python:3.11-slim based
When the DaemonHarness starts a styrened subprocess
Then RNS initializes in standalone mode (no shared instance conflict)
And TCP server binds successfully on a dynamic port
And the daemon shuts down cleanly on SIGTERM
