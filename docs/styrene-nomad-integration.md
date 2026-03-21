---
id: styrene-nomad-integration
title: Styrene × N.O.M.A.D. Integration — Mesh-Distributed Offline Knowledge via Hub
status: exploring
dependencies: [styrene-rs-daemon-port-execution-plan]
tags: [strategic, hub, nomad, omegon, edge, offline-knowledge]
open_questions:
  - "How does omegon's Qdrant-backed RAG differ from N.O.M.A.D.'s — is it the same vector DB serving both, or separate instances with different retrieval strategies?"
  - What is the licensing play — N.O.M.A.D. is Apache 2.0, Styrene is proprietary. Is this a fork, a complement, or a replacement distribution?
  - Should content announce capabilities use a bitfield in app_data, or a manifest hash with full inventory fetchable via RPC?
issue_type: epic
priority: 2
---

# Styrene × N.O.M.A.D. Integration — Mesh-Distributed Offline Knowledge via Hub

## Overview

Strategic integration of Crosstalk Solutions' Project N.O.M.A.D. (Node for Offline Media, Archives, and Data) into the Styrene ecosystem. N.O.M.A.D. provides a curated stack of offline services — Kiwix (Wikipedia/knowledge), Kolibri (education), ProtoMaps (offline maps), CyberChef (data tools), Ollama+Qdrant (local AI) — wrapped in a mediocre web UI. The play: gut the wrapper, keep the valuable services, replace the 'Command Center' with Styrene Hub for fleet-wide management, replace their crude Ollama chat with omegon's multi-tier model harness, and expose everything over the Styrene mesh so knowledge is distributed rather than siloed on a single node. This transforms N.O.M.A.D. from a standalone offline server into a mesh-networked knowledge fleet managed through Styrene.

## Research

### N.O.M.A.D. architecture assessment — what to keep, what to gut

**Project N.O.M.A.D.** (Crosstalk-Solutions/project-nomad, Apache 2.0) is a Docker-orchestrated offline knowledge server. 286 files, ~1.1MB. Install script drops a docker-compose stack on Debian-based systems.

**Service stack (KEEP — these are the valuable parts):**
- **Kiwix** — offline Wikipedia, WikiHow, Project Gutenberg, medical references via ZIM format. Mature, well-maintained upstream. Terabytes of curated human knowledge.
- **Kolibri** — offline Khan Academy with progress tracking. Legitimate education platform from Learning Equality.
- **ProtoMaps** — offline regional map tiles. Real operational value for field/off-grid.
- **CyberChef** — GCHQ's encoding/encryption/analysis toolkit. Useful for data ops.
- **Ollama** — local LLM inference. We already run this better via omegon.
- **Qdrant** — vector DB for RAG. Useful for document search.

**The "Command Center" (GUT — this is the weak part):**
- AdonisJS TypeScript web app (~286 files)
- Controllers: chats, docs, downloads, maps, ollama, rag, settings, system, zim
- Jobs: download_model, embed_file, run_benchmark, check_updates
- Basic chat UI with RAG document upload
- Content collection management (download/update offline content packs)
- Disk/storage management
- No mesh networking, no fleet management, no peer-to-peer anything
- Community already asking for P2P capabilities (GitHub Discussion: "Moving from Offline Server to Sovereign P2P Node")

**What N.O.M.A.D. gets wrong:**
- Single-node. One box, one operator. No mesh, no fleet, no distribution.
- Web-only UI with no terminal/TUI option.
- Ollama chat is basic — no model tiers, no thinking levels, no context management, no tool use.
- No encryption between nodes (there are no nodes to connect to).
- No provisioning story beyond "run this bash script."

**What Styrene already does better:**
- Encrypted mesh networking (Reticulum/LXMF)
- Fleet management and device discovery
- Edge device provisioning (styrene-edge, NixOS flakes)
- Sophisticated TUI with COP, inbox, settings, fleet overview
- IPC bridge with ~60 methods
- Content distribution system (styrene-content crate)

**What omegon already does better:**
- Multi-tier model routing (local/retribution/victory/gloriana)
- Context-aware model switching with safety rails
- Ollama lifecycle management (start/stop/pull/status)
- Thinking level control (off → minimal → low → medium → high)
- Tool use, file operations, web search, memory systems
- RAG via project memory (semantic search, knowledge graph)

### Target architecture — three layers

The integration has three distinct layers:

**Layer 1: Omegon over Styrene mesh**
Pi/omegon gains a Styrene transport — the agent can operate over mesh connections, not just local terminal or cloud API. This means an operator at one node can run an omegon session that reaches services on other mesh nodes. The agent's tool calls (read, bash, web_search) work locally, but it can also invoke Styrene RPC to query/manage remote nodes. This is the "agentic mesh" capability.

**Layer 2: Styrene Hub as N.O.M.A.D. management plane**
The Styrene Hub (public-hub) becomes the fleet-wide management layer for N.O.M.A.D. services. Instead of each node running its own "Command Center" web UI, the Hub:
- Provisions edge nodes with N.O.M.A.D. service stacks via styrene-edge
- Monitors service health across the fleet (Kiwix up? Ollama loaded? Maps current?)
- Manages content collection distribution (push Wikipedia updates to fleet)
- Provides centralized content search across distributed Kiwix instances
- Exposes N.O.M.A.D. services to mesh peers via NomadNet page protocol or Styrene RPC

**Layer 3: Omegon replaces N.O.M.A.D. AI**
N.O.M.A.D.'s basic Ollama chat + Qdrant RAG gets replaced by omegon's full harness:
- Model routing with context classes (Squad/Maniple/Clan/Legion)
- Thinking levels (Servitor through Omnissiah)
- Project memory (persistent knowledge graph, not just vector similarity)
- Tool use (the AI can actually DO things, not just chat)
- Local model management is already superior (start/stop/pull/status lifecycle)
- Document RAG can be backed by the same Qdrant but with smarter retrieval

**Deployment topology:**

```
Hub node (public-hub / home server)
├── styrened (daemon — transport, propagation, fleet management)
├── kiwix-serve (primary knowledge library — full content sets)
├── kolibri (education platform)
├── protomaps tileserver (full map coverage)
├── ollama (larger models — 30B+)
├── qdrant (vector DB — fleet-wide document index)
└── omegon harness (replaces N.O.M.A.D. Command Center AI)

Edge node (styrene-edge provisioned Pi/SBC)
├── styrened (daemon — mesh, RPC, discovery)
├── kiwix-serve (subset — medical refs, survival guides)
├── protomaps tileserver (local region only)
├── ollama (smaller models — 4B-8B, resource-constrained)
└── content sync via styrene-content distribution

Operator workstation
├── omegon/pi (full agent)
├── styrened (local mesh node)
└── Reaches any node's services over encrypted mesh
```

**Content distribution path:**
Hub downloads full content packs → styrene-content distributes chunks to edge nodes → edge nodes serve locally → mesh peers can query any node's Kiwix/maps via Styrene RPC or NomadNet pages.

### Existing public-hub audit — what the Rust Hub must replace

**Current hub architecture** (public-hub repo):
Single container running two Python processes:
1. **styrened** (daemon) — owns RNS transport, LXMF propagation, fleet management, IPC, HTTP API on :8000
2. **NomadNet** (daemon mode) — BBS page server, connects to styrened's shared RNS instance

The hub currently has almost no custom code (3 LOC Python package, the rest is config/deploy/pages). The custom value is:
- `pages/demo/*.mu` — Micron markup pages, some executable (Python scripts that generate pages dynamically)
- `styrened.pages.hub_bridge` — helper for NomadNet executable pages to call back into styrened
- `styrened.services.page_server` (472 LOC) — serves NomadNet-compatible pages over RNS using `("nomadnetwork", "node")` aspect. Smart about hub coexistence: on hub nodes where NomadNet owns the destination, falls back to executable page bridge; on edge nodes, creates the destination directly.
- Config for RNS transport (TCP backbone on :4242, shared instance), LXMF propagation, NomadNet
- Deploy manifests: K8s (base + overlays), docker-compose, systemd, ansible

**What a Rust Hub must do (minimum parity):**
1. Run the full Rust daemon (styrened-rs) — RNS transport, LXMF propagation, identity, fleet management
2. Serve NomadNet-compatible pages (static .mu + dynamic handlers) — needs Micron support (styrene-micron crate already exists)
3. Accept TCP backbone connections on :4242 from mesh peers
4. LXMF store-and-forward propagation node
5. HTTP API (:8000) for external integrations
6. IPC socket for local management tools

**What the Rust Hub adds beyond parity:**
- N.O.M.A.D. service orchestration (Kiwix, Kolibri, ProtoMaps)
- Omegon harness as the AI layer
- Content distribution management via styrene-content
- Fleet-wide N.O.M.A.D. service health monitoring
- Knowledge search across distributed Kiwix instances

**Container architecture shift:**
Current: single container (styrened Python + NomadNet Python)
Target: styrene-hub Rust binary + sidecar containers (Kiwix, Kolibri, ProtoMaps, Ollama, Qdrant)
Or: styrene-hub manages sidecars via Docker socket / containerd API

### styrene-hub architecture — the Rust Hub as daemon + hub services layer

**Crate structure:**

```
styrene-hub/                         (new repo — or rename public-hub)
├── Cargo.toml                       (workspace or single crate)
├── src/
│   ├── main.rs                      (binary entry point)
│   ├── hub.rs                       (Hub orchestrator — extends daemon with hub responsibilities)
│   ├── services/
│   │   ├── propagation.rs           (LXMF store-and-forward propagation node)
│   │   ├── page_server.rs           (NomadNet-compatible page serving in Rust)
│   │   ├── knowledge.rs             (Kiwix/ZIM integration — serve offline content to mesh)
│   │   ├── maps.rs                  (ProtoMaps tile serving integration)
│   │   ├── education.rs             (Kolibri integration)
│   │   ├── sidecar_manager.rs       (Docker/containerd sidecar lifecycle management)
│   │   └── content_distribution.rs  (styrene-content fleet distribution orchestration)
│   ├── pages/
│   │   ├── static_server.rs         (serve .mu files from disk)
│   │   ├── dynamic_handlers.rs      (programmatic page generation — fleet, status, knowledge search)
│   │   └── kiwix_bridge.rs          (Kiwix article → Micron page conversion)
│   └── api/
│       ├── http.rs                   (HTTP API — status, fleet, content management)
│       └── omegon.rs                 (omegon mesh integration endpoint)
└── deploy/
    ├── compose.yaml                  (Hub + sidecars)
    ├── kubernetes/                   (K8s manifests)
    └── nix/                          (NixOS module for hub deployment)
```

**Dependency on styrene-rs crates:**
```toml
[dependencies]
styrene-rns = { workspace = true, features = ["transport"] }
styrene-lxmf = { workspace = true, features = ["sdk"] }
styrene-mesh = { workspace = true }
styrene-ipc = { workspace = true }
styrene-micron = { workspace = true }
styrene-content = { workspace = true, features = ["tokio"] }
```

**Key architectural decisions:**
- styrene-hub IS a full daemon — it embeds all of styrened-rs functionality plus hub-specific services
- It does NOT shell out to a separate styrened-rs binary — it uses the same crates directly
- Sidecars (Kiwix, Kolibri, ProtoMaps, Ollama, Qdrant) are managed containers, not embedded
- The hub binary manages sidecar lifecycle (health checks, restart, config)
- NomadNet is replaced entirely — styrene-hub serves pages natively using styrene-micron
- Content distribution uses styrene-content for chunk-based mesh distribution of ZIM files/map tiles

**The three faces of the Hub:**
1. **Mesh face** — RNS transport backbone, LXMF propagation, device discovery, fleet management
2. **Content face** — Kiwix knowledge serving, offline maps, education platform, content distribution
3. **AI face** — omegon harness endpoint, local inference via Ollama, RAG via Qdrant, mesh-accessible agent

### Omegon architecture — pure Rust agent runtime with Feature trait and WebSocket interface

**Omegon** is a standalone Rust coding agent at ~/workspace/ai/omegon. v0.14.0, MIT license. Workspace: 5 crates (omegon, omegon-git, omegon-memory, omegon-secrets, omegon-traits).

**Key architecture:**
- **Feature trait** (omegon-traits) — unified interface for integrated subsystems: tools, context injection, event handling, slash commands. Features implement this trait and register with the runtime.
- **Bus events** — typed event bus (BusEvent/BusRequest) for agent loop ↔ feature communication.
- **LLM providers** — native Rust HTTP streaming to Anthropic/OpenAI APIs. No Node.js dependency.
- **Local inference** — Ollama integration via OpenAI-compatible API at localhost:11434. Tools: ask_local_model, list_local_models, manage_ollama.
- **Web interface** — embedded Axum HTTP server + WebSocket. The WS protocol is "the full agent interface — any web UI can connect and drive the agent as a black box." Auth token gated.
- **Core tools** — bash, read, write, edit, view, web_search, chronos, whoami, local_inference, speculate, validate, change, render.
- **Ratatui TUI** — conversation widget, dashboard, spinner, theme, effects.
- **Memory** — SQLite-backed with vector search (omegon-memory crate), decay model, semantic recall.

**Integration surface for Styrene mesh:**
The Feature trait is the natural extension point. A `StyreneMeshFeature` would:
1. Register mesh tools (query_node, send_rpc, fetch_page, search_knowledge)
2. Provide mesh context injection (fleet status, nearby nodes)
3. React to mesh events (new device discovered, message received)
4. Register slash commands (/mesh, /fleet, /knowledge)

The WebSocket interface means omegon sessions can already be driven remotely — the question is whether the transport between the remote operator and the omegon instance is HTTP/WS (current) or Styrene mesh (new).

## Decisions

### Decision: Hub is a new Rust codebase from the ground up, not a patched public-hub

**Status:** decided
**Rationale:** The existing public-hub is a thin config wrapper (3 LOC Python) around styrened + NomadNet. The Rust Hub will be a purpose-built binary that embeds the full Rust daemon (using styrene-rs crates directly) plus Hub-specific service orchestration. The existing repo can be renamed to styrene-hub or a new repo created — repo logistics are not architecturally significant.

### Decision: Hub replaces NomadNet entirely — serves pages natively via styrene-micron

**Status:** decided
**Rationale:** NomadNet is currently a separate Python process that connects to styrened's shared RNS instance. The Rust Hub will serve NomadNet-compatible pages natively using the styrene-micron crate (1,692 LOC, already exists). Dynamic page handlers become Rust functions, not Python subprocess scripts. This eliminates the two-process supervisor, the NomadNet dependency, and the hub_bridge shim. The page server service (currently 472 LOC Python) gets a Rust equivalent that directly participates in the daemon's service graph.

### Decision: N.O.M.A.D. services run as managed sidecar containers, not embedded in the Hub binary

**Status:** decided
**Rationale:** Kiwix, Kolibri, ProtoMaps, Ollama, and Qdrant are third-party services with their own container images, update cycles, and resource profiles. Embedding them in the Hub binary would be impractical and fragile. Instead, the Hub manages them as sidecar containers via Docker/containerd API — health checks, restart, config injection, log collection. The Hub binary itself stays lean: Rust daemon + hub orchestration logic. Sidecar compose is shipped alongside the Hub image.

## Open Questions

- How does omegon's Qdrant-backed RAG differ from N.O.M.A.D.'s — is it the same vector DB serving both, or separate instances with different retrieval strategies?
- What is the licensing play — N.O.M.A.D. is Apache 2.0, Styrene is proprietary. Is this a fork, a complement, or a replacement distribution?
- Should content announce capabilities use a bitfield in app_data, or a manifest hash with full inventory fetchable via RPC?
