---
id: dev-config-profiles
title: Dev Config Profiles
status: decided
tags: [dev-workflow, testing, config]
open_questions: []
---

# Dev Config Profiles

## Overview

Named YAML configuration profiles under dev/profiles/ that capture common styrene deployment archetypes. Each profile is a complete core-config.yaml snapshot that can be activated via justfile recipe (e.g. `just dev-daemon profile=full`). Goals: (1) give developers quick access to realistic deployment configs without manual YAML editing, (2) serve as stable fixtures for TUI visual QA sessions, (3) eventually feed into the k8s test suite as parameterized test scenarios against known config shapes.

## Research

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
- yggdrasil (YggdrasilConfig): enabled
- rpc.enabled / allow_execute
- discovery: announce_interval, respond_to_info
- logging.boundary_sink (new)

Well-known hubs defined: rns.styrene.io (enabled), + 4 community hubs (disabled by default).

### Existing config isolation mechanisms

Already implemented in src/styrened/paths.py:
- STYRENE_CONFIG_DIR env var → overrides config_dir() entirely
- STYRENE_DATA_DIR env var → overrides data_dir() (message DB, LXMF storage)
- STYRENE_HOME env var → base dir, config and data become $STYRENE_HOME/config and $STYRENE_HOME/data
- XDG_CONFIG_HOME / XDG_DATA_HOME also respected

This means full dev isolation already works: STYRENE_HOME=~/.styrene-dev just dev-daemon will use a completely separate config and data tree with no code changes needed. The justfile recipe just needs to export this env var.

daemon subcommand has NO --config flag currently (only setup subcommand does). load_core_config() in cmd_daemon takes no path arg — it calls load_core_config() with no args, reading from paths.config_dir(). So env var is the correct lever, not a CLI flag.

## Decisions

### Decision: Overlay YAML files under dev/profiles/

**Status:** decided
**Rationale:** dev/profiles/_base.yaml contains the shared identity and minimal shared config. Per-profile overlays (full.yaml, standard.yaml, minimal.yaml, hub.yaml, etc.) contain only the differing keys. Justfile merges base + profile overlay into STYRENE_HOME dir before launch. Mirrors kustomize pattern — DRY, diffable, committable.

### Decision: STYRENE_HOME for dev isolation — no new code needed

**Status:** decided
**Rationale:** paths.py already supports STYRENE_HOME env var which redirects both config_dir() and data_dir() under a single base. dev-daemon recipe exports STYRENE_HOME=~/.styrene-dev so identity, message DB, LXMF storage, and IPC socket are all isolated from the production install. No daemon code changes required.

### Decision: Persistent QA identity in dev home, optional ephemeral identity flag

**Status:** decided
**Rationale:** ~/.styrene-dev/config/ holds a long-lived QA identity (stable hash, persistent message DB, real mesh state accumulation). This surfaces temporal/environmental edge cases invisible in fresh-identity runs. Ephemeral identity supported via --ephemeral flag on dev-daemon recipe: generates a temp STYRENE_HOME, runs, discards on exit. Not baked per-profile.

## Open Questions

*No open questions.*
