# Operator Interface Testing Paths — Tasks

Phase 1: Single-peer TCP localhost. Full daemon subprocess + TUI pilot.

## Group 1: Fixture Identity Keys

- [x] 1.1 Generate 3 RNS identity key files (host, alpha, bravo) and commit to `tests/fixtures/test_peers/{host,alpha,bravo}/identity`
- [x] 1.2 Create README.md in each fixture dir documenting identity_hash and lxmf_destination_hash
- [x] 1.3 Create base `core-config.yaml` for alpha: display_name "🤖 Test Peer Alpha", auto_reply enabled, cooldown 1s, announce_interval 1, RPC enabled + exec enabled, TCP server on port 0 (dynamic)
- [x] 1.4 Create base `core-config.yaml` for host: TCP client connecting to alpha's server (RBAC grants deferred to Phase 2)
- [x] 1.5 Create base `core-config.yaml` for bravo: display_name "🤖 Test Peer Bravo", similar to alpha but different identity

## Group 2: In-Process Daemon Harness

- [x] 2.1 Create `tests/harness/daemon.py` — DaemonHarness class that starts `styrened daemon` subprocess with temp config dir, copies fixture identity + merges transport overlay into core-config.yaml
- [x] 2.2 Dynamic port allocation: bind to port 0, read assigned port, write into config before daemon start
- [x] 2.3 Startup wait: poll TCP port until accepting connections (poll-with-timeout, 15s max)
- [x] 2.4 Graceful shutdown: SIGTERM → wait 5s → SIGKILL. Cleanup temp dir.
- [x] 2.5 Create `tests/fixtures/transports/tcp_localhost.yaml` — transport overlay with dynamic port placeholder
- [x] 2.6 RNS config generation: _generate_rns_config() builds INI from merged config dict, config_path_override forces daemon to use it
- [x] 2.7 Isolation: .paths-migrated marker prevents legacy data copy, all env vars (CONFIG/DATA/STATE/RNS/SOCKET) point to temp dir

## Group 3: Pytest Fixtures (conftest)

- [x] 3.1 Create `tests/tui/operator/conftest.py` — session-scoped `alpha_daemon` fixture using DaemonHarness
- [x] 3.2 Host daemon as function-scoped fixture with extra_config for TCP peer connection
- [x] 3.3 `_host_env` fixture — sets STYRENED_SOCKET + STYRENE_*_DIR env vars for StyreneApp
- [x] 3.4 Add `await_condition(predicate, timeout)` helper for poll-with-timeout assertions
- [x] 3.5 Register pytest marker: `@pytest.mark.operator_path`

## Group 4: TUI Pilot Tests — Peer Discovery Path

- [x] 4.1 `test_peer_discovery.py::TestDaemonHarnessBasics` — 4 tests: daemon alive, port listening, identity hash, LXMF hash
- [x] 4.2 `test_peer_discovery.py::TestHostDaemonConnectivity` — 2 tests: host starts, host reaches alpha port
- [x] 4.3 `test_peer_discovery.py::TestTUIPeerDiscovery::test_tui_connects_to_host_daemon` — IPC bridge connects
- [x] 4.4 `test_peer_discovery.py::TestTUIPeerDiscovery::test_tui_discovers_alpha_peer` — alpha found via bridge.get_devices() after polling
- [x] 4.5 `test_peer_discovery.py::TestTUIPeerDiscovery::test_tui_alpha_display_name_correct` — name matches fixture
- [ ] 4.6 `test_peer_discovery.py::test_navigate_to_device_detail` — select alpha in device list, MeshDeviceDetailScreen opens with correct identity
- [ ] 4.7 `test_peer_discovery.py::test_status_tab_loads` — Status tab fires RPC, receives system info
- [ ] 4.8 `test_peer_discovery.py::test_chat_send_and_auto_reply` — send message, auto-reply received, both visible
- [ ] 4.9 `test_peer_discovery.py::test_fleet_ops_exec` — execute `echo hello` via RPC, response displayed

## Group 5: Nightly Workflow Integration

- [x] 5.1 Add `operator-paths` task to nightly DAG in `.argo/workflows/nightly-tests.yaml`
- [x] 5.2 Install styrened[tui] + test deps in the workflow step
- [ ] 5.3 Verify daemon subprocess starts inside CI container (standalone mode, no shared instance)
- [x] 5.4 JUnit XML output to `/workspace/results/operator-paths-results.xml`
- [ ] 5.5 Update cron-nightly.yaml comment to document the new tier
