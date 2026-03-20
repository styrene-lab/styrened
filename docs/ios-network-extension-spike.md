---
id: ios-network-extension-spike
title: iOS Network Extension — Entitlement, IPC, and Process Model Spike
status: resolved
parent: styrene-mobile-background-arch
open_questions: []
issue_type: task
---

# iOS Network Extension — Entitlement, IPC, and Process Model Spike

## Overview

> Parent: [Styrene Mobile — Background Execution Architecture](styrene-mobile-background-arch.md)
> Spawned from: "For iOS Network Extension (Tier 3): how does the Dioxus main app UI communicate with the PacketTunnelProvider extension process? NETunnelProviderSession IPC has strict message size limits. Does styrened-rs need a dedicated IPC protocol for this, or can it reuse the Unix socket / broadcast channel architecture?"

*To be explored.*

## Research

### What we know going in

**Network Extension framework** allows apps to extend iOS/macOS networking at the OS level. The relevant capability for Styrene is `PacketTunnelProvider` — a NEPacketTunnelProvider subclass that runs in a separate OS-managed process and can handle arbitrary IP traffic / custom tunnel protocols.

**Approved use cases (from Apple docs + App Store precedent):**
- Personal VPN (IKEv2, IPSec, custom protocols — WireGuard, Tailscale, ProtonVPN)
- Content filtering (parental controls, corporate MDM)
- DNS proxy
- App proxy (per-app VPN)

**Why this fits Styrene:** RNS is a custom packet routing protocol over TCP/UDP. The PacketTunnelProvider would intercept/generate packets for the mesh tunnel — functionally equivalent to WireGuard's use case. The differentiation from "VPN abuse" needs to be clear in the App Store review justification.

**What we don't know:**
- Exact entitlement string(s) required and whether they require a paid Apple Developer account with explicit approval, or if they're available to all paid devs
- Whether Apple requires a formal entitlement request (like some enterprise entitlements) or whether it's self-declared in capabilities
- NETunnelProviderSession message size limits (reported as 64KB per message in some sources)
- Whether a Unix socket between the extension process and main app is possible (shared app group container is the standard IPC path)
- What Tailscale's open-source iOS implementation reveals about the process model

**Spike goals:**
1. Determine entitlement acquisition path and cost
2. Understand the process model: what can the extension access vs. the main app
3. Determine IPC mechanism (app group shared container? NETunnelProviderSession messages? XPC?)
4. Assess whether the tokio broadcast/mpsc architecture survives process isolation or needs a different IPC layer
5. Check Tailscale iOS source (open source, MIT) as primary reference implementation

### Q1: Entitlement acquisition — self-declared, no Apple approval required for iOS App Store

**Entitlement string:** `com.apple.developer.networking.networkextension`

**Acquisition path:**
1. Enroll in Apple Developer Program ($99/yr) — standard membership, no special tier
2. Create an App ID for the main app and a separate App ID for the extension target in the Developer Portal
3. Enable the "Network Extension" capability on both App IDs → check "Packet Tunnel Provider" and "Personal VPN"
4. In Xcode: target → Signing & Capabilities → add Network Extensions capability

**No special Apple approval required for iOS App Store distribution.** This changed in November 2016. The entitlement is self-declared via Capabilities in Xcode + App ID configuration in the Developer Portal. Apple Developer Forums explicitly confirm: "There are no extra entitlements required for provider/app messaging; if you get to the point where your provider is loading, you have the entitlements correct."

**Important caveat — macOS Developer ID (outside App Store) IS different:** Distributing a Network Extension outside the Mac App Store (Developer ID signing) DOES require a formal entitlement request submitted to Apple. This is not relevant for the iOS App Store path or the Mac App Store path.

**App Store review scrutiny (separate from entitlement):** Apple's TN3120 technote defines expected use cases for PacketTunnelProvider. Review team will check the use case is legitimate. See Q4 for framing.

### Q2 + Q3: IPC mechanism — app group shared container + Unix socket. tokio architecture fully preserved.

**The IPC model, from WireGuard-apple source (primary reference):**

The extension and main app share an **App Group container** — a sandboxed filesystem directory both processes can read/write, identified by a group ID like `group.com.wireguard.ios`. The container URL is:
```swift
FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupId)
```

WireGuard uses three channels over this shared container:
1. **Files**: `tunnel-log.bin` (ring logger, written by extension, tailed by app), `last-error.txt` (extension writes error state, app reads on status change). Persistent state survives both processes dying.
2. **`sendProviderMessage` / `handleAppMessage`**: `NETunnelProviderSession.sendProviderMessage(_:responseHandler:)` → `NEPacketTunnelProvider.handleAppMessage(_:completionHandler:)`. Used for lightweight live queries. WireGuard uses it to fetch the current UAPI tunnel config with a single-byte request. **Message size limit: 64KB per message** (confirmed in Apple headers). Not suitable for streaming; good for one-shot queries.
3. **`NEVPNStatusDidChange` notification**: Standard `NotificationCenter` notification for connection/disconnection events. Main app observes this to update UI.

**The clean path for Styrene — Unix socket in the shared container:**

A Unix domain socket placed inside the app group container directory is accessible to both processes. This is exactly the pattern WireGuard-go uses for its UAPI socket on sandboxed macOS (the socket path is relocated from `/var/run/wireguard/` into the app group container). Tailscale's Go daemon similarly exposes a local API socket.

For styrened-rs: the RNS transport + tokio event loop runs entirely inside the PacketTunnelProvider process. It opens a Unix socket at `{appGroupContainer}/styrened.sock`. The Dioxus main app connects to this socket — **identical to how it connects to the daemon on desktop**. The existing IPC protocol (broadcast events, mpsc commands) is completely reused across the process boundary.

```
PacketTunnelProvider process                Main Dioxus app process
┌──────────────────────────────┐            ┌──────────────────────────────┐
│  styrened-rs                 │            │  Dioxus UI                   │
│    tokio runtime             │            │    IPC client                │
│    RNS transport             │◄──Unix────►│    (same as desktop)         │
│    broadcast/mpsc bus        │   socket   │                              │
│    Unix socket server        │            │                              │
│      @ appGroup/styrened.sock│            │                              │
└──────────────────────────────┘            └──────────────────────────────┘
         App Group Container (shared filesystem)
              appGroup/styrened.sock   ← the socket itself
              appGroup/tunnel-log.bin  ← ring log (optional)
              appGroup/config.cbor     ← persisted config
```

**sendProviderMessage** is used for exactly one thing: the "are you alive?" keepalive that NEVPNStatus already doesn't cover. The Dioxus app uses the Unix socket for all real IPC; sendProviderMessage is an optional backup for extension health checks.

**tokio broadcast/mpsc architecture survives completely.** The process boundary is transparent — it's just a Unix socket connection, the same abstraction used on all other platforms. No special bridging, no message adaptation, no new IPC protocol.

### Q4: App Store review framing — "mesh communications node", not "VPN"

**Apple's TN3120** (updated July 2025) defines expected use cases for PacketTunnelProvider. Supported use cases include: VPN clients implementing custom tunneling protocols, zero-trust network access, split tunneling. Unsupported: using NE purely as a background execution bypass with no real tunnel work, ad/content blocking (separate Content Filter extension exists for that), passive traffic observation.

**Styrene's framing:**
The App Store review description should say: "Styrene is a decentralized mesh communications network. This extension allows the user's device to function as a mesh node, maintaining encrypted peer-to-peer connections to other nodes in the user's mesh using the Reticulum Network Stack (RNS) protocol. The tunnel is used to route mesh traffic — not internet traffic — between mesh participants."

**Key distinctions from VPN abuse (what Apple looks for):**
- ✅ Actual custom tunnel protocol (RNS over TCP/UDP) — not a wrapper around existing internet traffic
- ✅ User-visible purpose: mesh network participation, not "make my internet private"
- ✅ Precedent: Tailscale (mesh VPN, App Store approved), WireGuard (custom protocol, App Store approved)
- ✅ The tunnel carries mesh protocol traffic specifically, not arbitrary internet traffic
- ❌ Must NOT claim the extension is needed to "protect privacy online" — that framing triggers VPN abuse scrutiny

**The Tailscale parallel is exact:** Tailscale IS a mesh network using a custom WireGuard-based protocol, App Store approved, uses PacketTunnelProvider. Styrene is a mesh network using a custom RNS-based protocol. The use case is identical in structure.

**App Store Connect metadata:** The "App Review Information" notes field should briefly describe the NE use case. Something like: "This app implements a decentralized mesh networking protocol (Reticulum Network Stack). The Network Extension target maintains peer-to-peer mesh connections between nodes. To test: enable 'Full Node' mode in Settings."

**Entitlement request on developer portal:** Under the App ID's Network Extension capability, the "Packet Tunnel" checkbox is sufficient. No additional justification field at entitlement configuration time — the justification is provided during App Review.

## Decisions

### Decision: Entitlement is self-declared — standard $99/yr Apple Developer Program, no special approval

**Status:** decided
**Rationale:** com.apple.developer.networking.networkextension with Packet Tunnel Provider capability has been self-declared via Xcode Capabilities since November 2016. No formal Apple entitlement request is required for iOS App Store or Mac App Store distribution. The only gating is the standard App Review process. macOS Developer ID (outside App Store) is a different case and DOES require formal Apple approval — not relevant for Styrene's distribution model.

### Decision: IPC: Unix socket in app group shared container — tokio architecture fully preserved across process boundary

**Status:** decided
**Rationale:** The PacketTunnelProvider process and the main Dioxus app share an app group container filesystem. A Unix domain socket placed in this container is accessible to both processes. styrened-rs runs its tokio runtime, RNS transport, and broadcast/mpsc event bus entirely inside the extension process, exposing a Unix socket at {appGroupContainer}/styrened.sock. The Dioxus app connects to this socket identically to how it connects on desktop — the process boundary is transparent. No new IPC protocol, no message adaptation, no architectural change. sendProviderMessage (64KB limit) is reserved for extension health checks only. This is the same pattern used by WireGuard-go's UAPI socket on sandboxed macOS and Tailscale's local API socket.

### Decision: App Store framing: "mesh communications node" — not "VPN". Tailscale is the direct precedent.

**Status:** decided
**Rationale:** TN3120 supports PacketTunnelProvider for custom tunnel protocols. Styrene's use case — a decentralized mesh network using RNS protocol, routing mesh traffic between nodes — is structurally identical to Tailscale (mesh network, custom WireGuard protocol, App Store approved). App Review notes describe the NE as maintaining peer-to-peer mesh connections, not "protecting internet privacy." The actual tunnel carries RNS mesh protocol traffic, not arbitrary internet traffic, which is the key distinction Apple cares about.

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- This is a spike — output is research findings and a decision, not production code
- Primary reference: Tailscale iOS open-source repo (MIT license)
- Secondary reference: WireGuard iOS open-source repo
- Spike must answer the entitlement acquisition question before any Tier 3 implementation begins
- styrened-rs RNS transport must remain a no-UI library regardless of how IPC is resolved
