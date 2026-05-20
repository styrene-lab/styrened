# Python Daemon Maintenance Policy

`styrened` began as Styrene's first Python implementation on Reticulum/LXMF. It is now legacy software. The Python daemon is maintenance-only and must not be used as the place to add new transport, bridge, or public-network behavior.

## Why this policy exists

The Python daemon carried experimental bridge and discovery ideas too far. In particular, Meshtastic/MQTT bridge behavior was left in a dangerous state and produced harmful traffic on public Reticulum transports. That is not acceptable behavior for this project or for software participating in a shared mesh network.

The cleanup commits that established the maintenance boundary are:

- `2224970` — rate-limit legacy Python announces to a one-hour public cadence.
- `c7b18f9` — suppress TCP interface churn from triggering legacy re-announce storms.
- `c81ce92` — bound LXMF path-request fanout from arbitrary destination input.
- `1f4c4fb` — poison legacy Meshtastic/MQTT bridge config at startup/config load.
- `5eec9b1` — align tests with the safety defaults and validate locally.

## Status

Python `styrened` is retained only for maintenance, migration, and safety releases.

New work belongs in [`styrene-rs`](https://github.com/styrene-lab/styrene-rs), especially:

- transport adapters,
- radio bridges,
- Meshtastic or other LoRa integration,
- hub/peer behavior,
- public Reticulum announce behavior,
- path discovery strategy.

## Non-negotiable rules for the Python daemon

The Python daemon must not:

1. Create Reticulum identities or destinations for Meshtastic, MQTT, or other non-Reticulum nodes.
2. Bridge MQTT-observed Meshtastic nodes onto Reticulum.
3. Auto-forward LXMF messages into Meshtastic or Meshtastic messages into LXMF.
4. Emit public Reticulum announces more frequently than once per hour.
5. Treat TCP interface churn as a reason to re-register destinations or re-announce.
6. Fan out unbounded Reticulum path requests from arbitrary discovery, bridge, or UI input.
7. Reintroduce operator-facing controls that allow unsafe public announce cadence.

These rules apply even if a feature appears useful for local labs. Local testing must use isolated fixtures or `styrene-rs` harnesses, not public-network Python behavior.

## Poison pill behavior

`load_core_config()` refuses top-level legacy bridge sections:

```yaml
meshtastic:
  enabled: true
```

```yaml
mqtt:
  enabled: true
```

This is intentional. It is a local startup/config-load safety interlock, not remote disablement. Operators with old configs must remove those sections before running Python `styrened`.

## Acceptable Python changes

Acceptable changes are limited to:

- safety fixes,
- dependency/security fixes,
- migration warnings,
- tests for the safety boundary,
- documentation and release notes,
- compatibility shims that reduce risk without expanding network behavior.

## Release guidance

For a final safety release:

1. Keep the poison pill enabled.
2. Keep one-hour announce validation enabled.
3. Keep bounded path-request fanout enabled.
4. Publish release notes warning old Meshtastic/MQTT bridge operators to upgrade or stop running Python `styrened` on public Reticulum transports.
5. Yank known-bad releases after the safe release exists, so users have an upgrade path.

Do not remove the package before publishing a safe upgrade. Existing `pipx` installs will continue running until the operator upgrades or uninstalls them.
