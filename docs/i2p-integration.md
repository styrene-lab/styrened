---
id: i2p-integration
title: I2P Integration
status: implementing
parent: overlay-network-integration
dependencies: [optional-daemon-adoption-model, styrene-identity]
tags: [i2p, i2pd, eepsite, anonymity, page-browser, hidden-service]
open_questions: []
branches: ["feature/i2p-integration"]
openspec_change: i2p-integration
---

# I2P Integration

## Overview

Explore I2P integration dimensions for styrened: eepsite browsing in the NomadNet page browser, hub exposure as an I2P hidden service, and whether RNS-over-I2P-SAM has any merit. I2P is a garlic-routing anonymizing overlay — fundamentally different from Yggdrasil in goals and characteristics.

## Research

### I2P fundamentals and how it differs from Yggdrasil



### Integration dimension 1: I2P eepsite browsing in the NomadNet page browser



### Integration dimension 2: public hub as I2P hidden service



### Integration dimension 3: RNS over I2P SAM — assessment and verdict



### The I2PService design: detect-only vs managed process



### Design tree hygiene note

The design tree still contains an older detect-only decision title and an extra section arguing against management. Treat those as superseded historical context, not active guidance. Active implementation and docs follow the explicit DISABLED | ADOPT | MANAGED model plus explicit transport selection for page browsing.

## Decisions

### Decision: RNS over I2P SAM deferred indefinitely

**Status:** rejected
**Rationale:** Latency (3–10s tunnel build) makes RNS interactive features unusable. I2P adds transport-layer IP anonymity but RNS identity is still visible at the application layer — minimal anonymity gain for significant complexity. The use case (hiding your IP while running RNS) is a narrow, deliberate operator choice that doesn't belong in the core daemon. If ever implemented, it would be a separate RNSsam interface plugin outside styrened.

### Decision: styrened detects i2pd but never manages it — follows BATMAN-ADV model not WireGuard model

**Status:** decided
**Rationale:** i2pd needs 5–10 minutes to integrate into the I2P network on first start — running it ephemerally defeats the purpose. Users who want I2P are already running i2pd persistently as a system service. Tunnel configs and bandwidth limits are deliberate operator decisions, not generated dynamically. NixOS handles i2pd via services.i2pd. styrened's I2PDetector probes localhost:4444 and uses it if available.

### Decision: I2P eepsite browsing via HTTP proxy — PageCacheService becomes transport-agnostic

**Status:** decided
**Rationale:** localhost:4444 HTTP proxy is the only integration point needed. httpx already supports HTTP proxies. PageCacheService dispatches on URL scheme: nomadnet:// → RNS fetcher, *.i2p → I2P proxy fetcher, http(s):// → direct HTTP. I2P cache entries use shorter default TTL (1hr) since eepsites can change like any website. HTML rendering via html2text (pure Python) with optional w3m/lynx escape hatch.

### Decision: CAPABILITY_I2P bit in announces — .b32.i2p address fetched via DirectLink /meta

**Status:** decided
**Rationale:** Consistent with CAPABILITY_YGGDRASIL decision. Same pattern: single capability bit in announce, actual address in /meta response. Allows mesh peers to discover a node's I2P presence and use it as an alternative access path. The b32_address in /meta is only populated if the operator has configured it (i2p.b32_address in CoreConfig) or if I2PDetector can auto-detect it from i2pd API.

### Decision: i2pd follows DaemonMode: DISABLED | ADOPT | MANAGED — not detect-only

**Status:** decided
**Rationale:** Supersedes earlier "detect-only / BATMAN-ADV model" decision. MANAGED mode IS available for i2pd — styrened provisions a Nix-built i2pd binary, generates minimal config in ~/.styrene/i2pd/, uses port 4445 (HTTP proxy) and 7651 (I2PControl) to avoid conflicting with a system i2pd. Cold-start warm-up (5–10 min) is surfaced explicitly in TUI and doctor, not silently swallowed. ADOPT mode retains the original "detect and use, never touch" contract.

### Decision: b32 address detection: I2PControl API (autodetect) with fallback to operator config

**Status:** decided
**Rationale:** Graceful degradation always. In MANAGED mode: styrened enabled I2PControl (port 7651) in its generated config, so auto-detection is reliable and requires no operator action. In ADOPT mode: probe I2PControl on port 7650 (system default) — succeeds if operator has enabled httpserver in their i2pd.conf, falls back to i2p.b32_address in CoreConfig if not. Never fail hard on detection failure — just omit the field from /meta and don't set CAPABILITY_I2P until an address is known.

### Decision: Page browser I2P fetch requires explicit i2p.mode != disabled — never opportunistic

**Status:** decided
**Rationale:** Do not route traffic through someone's personal i2pd without their consent. i2p.mode: adopt or managed IS the consent, set deliberately by the operator. If mode is DISABLED and the user tries to open a .i2p URL, return a clear error: 'I2P not enabled — set i2p.mode: adopt or managed in config.' I2P users are privacy-aware by definition and expect conscious control over which applications use their I2P router.

### Decision: Graceful degradation for published docs uses explicit parallel endpoints, not implicit transport fallback

**Status:** decided
**Rationale:** Styrene Docs may exist simultaneously on NomadNet, HTTPS, and I2P. The browser should handle each transport explicitly and return clear errors when one path is unavailable, letting the caller or operator choose another endpoint deliberately rather than silently downgrading privacy-sensitive traffic.

### Decision: Earlier detect-only i2pd discussion is superseded by the explicit DISABLED | ADOPT | MANAGED model

**Status:** decided
**Rationale:** The old BATMAN-ADV-style detect-only reasoning remains useful historical context, but it is no longer the active design. The source of truth is the three-mode model: DISABLED for no I2P use, ADOPT for operator-managed routers, and MANAGED for styrened-managed routers on non-conflicting ports with visible warm-up behavior.

## Open Questions

*No open questions.*

## Should styrened manage i2pd like it manages WireGuard / Yggdrasil?

**Against managing i2pd**:
- i2pd has a 5–10 minute tunnel build time on first start — it needs to integrate into the I2P network before it's useful. Starting it on-demand with styrened would mean it's useless for the first several minutes of every daemon run.
- The anonymity/privacy goals of I2P mean users who want it are likely already running i2pd as a persistent system service. They've made a deliberate choice.
- i2pd's peer and tunnel databases take time to populate — running it ephemerally defeats the purpose. This is fundamentally different from WireGuard (instant) and Yggdrasil (connects in seconds).
- The operator configuration for i2pd (tunnel definitions, bandwidth limits, proxy settings) is intentional and persistent — not something to generate dynamically.

**For managing i2pd**:
- Consistency with YggdrasilService pattern (detect system instance, optionally manage own process)

**Verdict**: I2P follows the BATMAN-ADV model, not the WireGuard model. styrened **detects** a running i2pd and uses it — it does not own or manage the i2pd lifecycle. The `I2PService` (or simply I2P detection in a config service) is purely:

```python
class I2PDetector:
    """Detect and probe a locally running i2pd/I2P instance."""
    
    async def probe_http_proxy(self, host="127.0.0.1", port=4444) -> bool: ...
    async def probe_sam(self, host="127.0.0.1", port=7656) -> bool: ...
    async def get_b32_address(self) -> str | None:
        """Fetch our own .b32.i2p address via I2PControl or config parsing."""
    
    @property
    def is_available(self) -> bool:
        """True if HTTP proxy is reachable."""
```

No process management. No config generation. Just detection and the HTTP proxy reference for PageCacheService.

## I2P config in CoreConfig

```python
@dataclass
class I2PConfig:
    enabled: bool = False
    http_proxy_host: str = "127.0.0.1"
    http_proxy_port: int = 4444
    sam_host: str = "127.0.0.1"        # for future use
    sam_port: int = 7656
    cache_ttl: int = 3600               # seconds, shorter than NomadNet default
    fetch_timeout: float = 45.0         # I2P tunnels can be slow to build
    # Our I2P address (if we're exposing a service) — operator fills this in
    # or it can be auto-detected from i2pd API
    b32_address: str = ""               # published in /meta if set
```

No `manage_process` field — that's the key difference from YggdrasilConfig.

## NixOS integration (styrene-edge / public-hub)

```nix
# styrene-edge or public-hub NixOS config
services.i2pd = {
  enable = true;
  bandwidth = "P2P";  # router class — L/M/N/O/P/X
  
  tunnels.styrened-api = {
    type = "http";
    host = "127.0.0.1";
    port = 8080;
    keys = "styrened-api.dat";  # persistent keypair = stable .b32 address
  };
};
```

This is purely in styrene-edge / vanderlyn, not in the styrened daemon repo. styrened just binds to 8080 and i2pd proxies in.

## The idea

Use I2P's SAM (Simple Application Messaging) API to create I2P streaming sessions that carry RNS traffic — effectively running Reticulum inside I2P tunnels. This would give RNS traffic I2P's anonymity properties.

## What SAM provides

SAM v3.1 is a text protocol on localhost:7656. You open a session, create a stream connection to a destination, and get a socket-like bidirectional channel:

```
SESSION CREATE STYLE=STREAM ID=mysession DESTINATION=TRANSIENT ...
STREAM CONNECT ID=mysession DESTINATION=<b32-address> ...
→ raw bidirectional byte stream
```

RNS in principle could run over any bidirectional byte stream — it does this for TCP and serial. A SAM-based interface would look like a TCP interface but with SAM session management underneath.

## Why this is unattractive

**Latency**: I2P tunnels take 3–10 seconds to build initially, ~1–3s once warmed up. RNS's announce/response design assumes reasonably prompt responses. Many RNS timeouts are in the 5–30s range — an I2P hop burns most of that budget just establishing the tunnel. Interactive features (speedtest, exec, RPC) would be effectively unusable.

**Anonymity vs identity tension**: Reticulum is built around persistent cryptographic identity — your destination hash *is* your identity, and it's intentionally stable and discoverable. I2P is built around the opposite: ephemeral, unlinkable sessions. Running RNS over I2P buys you transport-layer obfuscation at the cost of defeating RNS's own identity model. You still have your RNS identity hash visible at the application layer — I2P only hides the TCP connection, not the RNS protocol contents.

**What you actually get**: You hide which IP address your RNS traffic originates from, at significant latency cost. Reticulum already encrypts its traffic end-to-end — I2P adds a redundant encryption layer for the connection without adding meaningful anonymity at the RNS layer.

**Deployment complexity**: Every node wanting RNS-over-I2P needs i2pd running, a SAM session, and a custom RNS interface implementation. This is a significant new surface area for a feature whose benefit is marginal given that RNS already runs over Yggdrasil (which provides NAT traversal and encryption without the latency penalty).

## Verdict: defer indefinitely

RNS over I2P SAM solves a problem (transport-layer IP anonymity for RNS) that the existing stack doesn't have, at a cost (latency, complexity, identity model confusion) that is hard to justify. The specific use case where you want to hide your IP while running RNS is a narrow edge case that would require a very deliberate operator decision.

If this ever becomes valuable, the right implementation is a `RNSsam` interface class registered with Reticulum's interface framework — not something styrened manages. It would live in a separate plugin, not in the core daemon. Record the verdict and close this dimension.

## What this means

The public hub runs styrened's HTTP API (FastAPI/uvicorn). Exposing it as an I2P hidden service means the API is reachable at a .b32.i2p address from within the I2P network — without a clearnet IP, without a domain name, censorship-resistant.

## How I2P hidden services work (server side)

i2pd config creates a "server tunnel" — a listener inside I2P that forwards to a local port:

```ini
# /etc/i2pd/tunnels.conf
[styrened-api]
type = http
host = 127.0.0.1
port = 8080         # styrened's local HTTP API port
keys = styrened-api.dat   # keypair file — determines your .b32.i2p address
```

The .b32.i2p address is derived from the keypair — stable as long as `styrened-api.dat` exists. This is analogous to Yggdrasil's address being derived from its keypair: stable cryptographic identity.

## Who manages the tunnel config?

Two options:
1. **i2pd config file** (NixOS module / static config) — operator sets it up once, stable address
2. **SAM API** (programmatic) — styrened creates an I2P session via SAM and exposes a service

Option 1 is far simpler and more robust for a production hub. The address is predictable and can be published. Option 2 gives programmatic control but adds significant complexity and changes the address on restart if keys aren't persisted (back to the persistence/security discussion).

**Recommendation**: NixOS module manages the i2pd server tunnel for `public-hub`. styrened's role is zero — i2pd proxies to localhost:8080 independently. styrened just needs to be listening on 8080.

## What styrened does know: its own I2P address

The hub operator can get their .b32.i2p address from the i2pd web console or `i2pd` API. This should be surfaced in:
- `styrened status` output (if I2P is detected and configured)
- The `/meta` DirectLink response (so mesh peers know the hub has an I2P presence)
- The NomadNet auto-generated index.mu page (planned feature — show hub endpoints)

## A new capability: CAPABILITY_I2P

Similar to CAPABILITY_YGGDRASIL: a bit that says "I am reachable via I2P." The actual .b32.i2p address is fetched via DirectLink `/meta`:

```json
{
  "styrene_version": "...",
  "capabilities": ["yggdrasil", "i2p", ...],
  "ygg_address": "200:...",
  "i2p_address": "abc...def.b32.i2p",
  "i2p_port": 8080
}
```

This lets mesh peers discover that a node has I2P connectivity — useful for routing decisions and for the page browser (know that a hub's API is accessible via I2P as a fallback when clearnet is down).

## Value proposition

For the public hub specifically: I2P access provides a censorship-resistant endpoint for nodes that:
- Are in network environments that block clearnet connections to the hub
- Prefer anonymized connectivity to the mesh
- Are behind firewalls that allow I2P traffic specifically

The clearnet API remains primary. I2P is a parallel access path, not a replacement. No changes to the API itself — i2pd handles the proxying transparently.

## Context: the existing page browser

styrened already has a NomadNet page caching system (PageCacheService) that:
- Fetches NomadNet Micron pages via RNS
- Caches them in SQLite (page_cache + saved_sites tables)
- Supports BFS crawling and background refresh
- IPC commands for save/remove/list/crawl/get-cached operations

The page browser currently knows about one content type: NomadNet Micron pages (NomadNet protocol over RNS). HTTP URLs were always a potential second type.

## What I2P eepsite browsing would add

I2P has its own web of "eepsites" — HTTP servers running as I2P hidden services, accessible only through the I2P network. They use .i2p hostnames or base32 addresses (e.g., `dg7fhh23g...b32.i2p`).

To fetch an eepsite, you make an HTTP request to the I2P HTTP proxy at `localhost:4444`, using the .i2p hostname as the Host header — identical to any HTTP proxy:

```python
import httpx

async def fetch_eepsite(url: str) -> str:
    """Fetch an I2P eepsite via local HTTP proxy."""
    # url: "http://somename.i2p/path"
    async with httpx.AsyncClient(
        proxies={"all://": "http://localhost:4444"},
        timeout=30.0,  # I2P tunnels can take time to build
    ) as client:
        response = await client.get(url)
        return response.text
```

That is the entire integration at the fetch level. httpx already supports HTTP proxies. No SAM needed, no I2P-specific library.

## Where it fits in PageCacheService

The cleanest model: PageCacheService becomes transport-agnostic. It currently has a `fetch_page(url)` dispatcher that routes NomadNet URLs to the RNS fetcher. Add I2P as another branch:

```python
async def fetch_page(self, url: str) -> PageResult:
    if url.startswith("nomadnet://") or url.startswith("rns://"):
        return await self._fetch_nomadnet(url)
    elif url.endswith(".i2p") or ".i2p/" in url:
        return await self._fetch_i2p(url)
    elif url.startswith("http://") or url.startswith("https://"):
        return await self._fetch_http(url)
    else:
        raise ValueError(f"Unknown URL scheme: {url}")
```

`_fetch_i2p()` checks `config.i2p.enabled` and `config.i2p.http_proxy` first. If I2P isn't configured, return a graceful error the TUI can surface ("I2P not configured — enable in settings").

## Caching: same model as NomadNet pages

The SQLite `page_cache` table stores URL + content + fetched_at + content_type. I2P pages are just HTTP content (HTML, or Micron markup if the eepsite serves that). Same cache model, different content_type tag (`"i2p_html"` vs `"nomadnet_micron"`).

The TTL question is different: NomadNet pages change rarely (mesh nodes don't update frequently). I2P eepsites can change like any website. A shorter default TTL for I2P cache entries makes sense — configurable via `i2p.cache_ttl` (default: 1 hour vs NomadNet's longer default).

## Rendering I2P HTML in the TUI

This is the hardest part. NomadNet Micron markup renders cleanly in a terminal (it's designed for that). HTML is not. Options:

1. **Strip tags, show plain text** — trivial, lossy but functional. `BeautifulSoup` for parsing, extract text. Good enough for reading I2P forum posts, news sites.
2. **Render as Markdown** — some converters (html2text, markdownify) produce readable terminal output from HTML. Medium complexity.
3. **Delegate to an external terminal browser** — `w3m`, `lynx`, `elinks`. Shell out, capture output. Avoids parsing complexity but requires external dependency.

**Recommendation**: html2text (pure Python, already lightweight) as default rendering. Optional: detect w3m/lynx and offer "open in terminal browser" action in TUI. This keeps the implementation self-contained while giving power users an escape hatch.

## Detection: is i2pd running?

Same pattern as YggdrasilService: check the HTTP proxy port (connect to localhost:4444, see if it responds), and/or check the I2PControl API port (7650). No admin socket — I2P uses HTTP APIs.

```python
async def _detect_i2p_proxy(host: str, port: int) -> bool:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=2.0
        )
        writer.close()
        return True
    except (ConnectionRefusedError, asyncio.TimeoutError, OSError):
        return False
```

## What I2P actually is

I2P (Invisible Internet Project) is a garlic-routing anonymizing overlay. Where Yggdrasil is a mesh that gives you a stable routable IPv6 address — a better internet — I2P is a darknet that deliberately obscures routing and identity. They solve opposite problems.

**Key I2P properties**:
- Addresses are cryptographic hashes of destination keys (.b32.i2p base32 addresses, or human-readable .i2p hostnames via addressbook)
- Traffic is bundled into "garlic" (multi-layered encrypted) messages, routed through volunteer relay nodes
- No persistent identity between sessions by design — the anonymity property
- High latency: 2–10 seconds typical for a new tunnel, ~1–3s once established
- Limited throughput: not designed for bulk transfer, better for messaging and small pages
- Runs as a local daemon (Java I2P or i2pd in C++/Rust) that manages tunnel pools

**Programmatic access to I2P**:
- **HTTP proxy** at `localhost:4444` — point a browser (or HTTP client) at this for .i2p URL access. No special API needed.
- **SAM (Simple Application Messaging) v3.1** at `localhost:7656` — socket API for creating I2P sessions. Used by applications wanting deeper integration (streaming sessions, datagrams).
- **BOB (Basic Open Bridge)** — older, simpler tunnel bridge. Less commonly used now.
- **I2PControl** — JSON-RPC API for controlling the I2P router itself (status, bandwidth, etc.).

**i2pd vs Java I2P**:
- Java I2P: original, fully featured, heavy (JVM, 200–400MB RAM), robust
- i2pd: C++ rewrite, much lighter (~30MB RAM), actively maintained, ships as a single binary
- For styrened integration: i2pd is the target. Single binary, Nix-packaged, systemd-friendly, no JVM dependency.

## The critical difference from Yggdrasil for integration

Yggdrasil is **additive** to the existing stack: it's just another transport IP, WireGuard endpoints work over it unchanged.

I2P is **protocol-level** integration: there's no "IP address you can route to." You interact with I2P through the local daemon's proxy/SAM interface. This means:
- No kernel TUN interface to detect
- No transparent IP routing — must explicitly proxy through localhost:4444
- The anonymity model means you don't know (or want to know) the remote's real IP — that's the point

This shapes every integration decision: I2P integration is always about proxying through a local gateway, never about adding I2P as a route in a routing table.
