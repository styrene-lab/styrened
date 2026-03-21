# Dev Config Profiles — Design Spec (extracted)

> Auto-extracted from docs/dev-config-profiles.md at decide-time.

## Decisions

### Overlay YAML files under dev/profiles/ (decided)

dev/profiles/_base.yaml contains the shared identity and minimal shared config. Per-profile overlays (full.yaml, standard.yaml, minimal.yaml, hub.yaml, etc.) contain only the differing keys. Justfile merges base + profile overlay into STYRENE_HOME dir before launch. Mirrors kustomize pattern — DRY, diffable, committable.

### STYRENE_HOME for dev isolation — no new code needed (decided)

paths.py already supports STYRENE_HOME env var which redirects both config_dir() and data_dir() under a single base. dev-daemon recipe exports STYRENE_HOME=~/.styrene-dev so identity, message DB, LXMF storage, and IPC socket are all isolated from the production install. No daemon code changes required.

### Persistent QA identity in dev home, optional ephemeral identity flag (decided)

~/.styrene-dev/config/ holds a long-lived QA identity (stable hash, persistent message DB, real mesh state accumulation). This surfaces temporal/environmental edge cases invisible in fresh-identity runs. Ephemeral identity supported via --ephemeral flag on dev-daemon recipe: generates a temp STYRENE_HOME, runs, discards on exit. Not baked per-profile.

## Research Summary

### Config dimensions available for profiling

From CoreConfig model:
- reticulum.mode: standalone | hub | peer
- reticulum.enable_transport: bool (None=auto from mode)
- reticulum.interfaces.auto: AutoInterface (local UDP discovery)
- reticulum.interfaces.server: TCPServerInterface (listen_ip, port)
- reticulum.interfaces.peers: list[PeerConfig] (well-known hubs, all disabled by default except Styrene hub)
- lxmf.autopeer / propagation_node
- api.enabled / public_mode
- vpn (MeshVPNConfig): enabled
- i2p (I2PConfig): enabled
- yggdrasil (Yg…

### Existing config isolation mechanisms

Already implemented in src/styrened/paths.py:
- STYRENE_CONFIG_DIR env var → overrides config_dir() entirely
- STYRENE_DATA_DIR env var → overrides data_dir() (message DB, LXMF storage)
- STYRENE_HOME env var → base dir, config and data become $STYRENE_HOME/config and $STYRENE_HOME/data
- XDG_CONFIG_HOME / XDG_DATA_HOME also respected

This means full dev isolation already works: STYRENE_HOME=~/.styrene-dev just dev-daemon will use a completely separate config and data tree with no code changes …
