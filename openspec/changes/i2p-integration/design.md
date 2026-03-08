# I2P Integration — Design

## Architecture Decisions

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

## Research Context

### I2P fundamentals and how it differs from Yggdrasil



### Integration dimension 1: I2P eepsite browsing in the NomadNet page browser



### Integration dimension 2: public hub as I2P hidden service



### Integration dimension 3: RNS over I2P SAM — assessment and verdict



### The I2PService design: detect-only vs managed process


