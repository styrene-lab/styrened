---
id: styrene-mobile-background-arch
title: Styrene Mobile — Background Execution Architecture
status: decided
parent: styrene-dioxus-ui
open_questions: []
---

# Styrene Mobile — Background Execution Architecture

## Overview

> Parent: [Styrene Dioxus UI — Web Dashboard + Mobile App](styrene-dioxus-ui.md)
> Spawned from: "For mobile: does the Dioxus app run styrened-rs as an embedded library (no separate daemon process) or connect to a remote hub? On-device daemon has significant implications for battery, background execution, and App Store review."

*To be explored.*

## Research

### iOS background execution constraints

iOS has several distinct background execution modes, each with different capabilities and review scrutiny:

**Suspension (default)**
App is suspended shortly after leaving foreground. No code runs. Any open TCP sockets will eventually time out. The OS gives ~5-30s of grace via `beginBackgroundTask` to finish in-flight work cleanly.

**BGAppRefreshTask**
~30s budget, system-scheduled (app cannot trigger it). Used for content refresh. Frequency determined by iOS based on usage patterns. Completely unreliable for mesh participation — might run once an hour or not at all.

**BGProcessingTask**
For longer deferred operations (minutes). Requires device plugged in and idle. System-scheduled. Same problem — not suitable for networking.

**BGContinuedProcessingTask** (iOS 26 / WWDC 2025 — NEW)
User-initiated long-running tasks. Better than BGProcessingTask but still not persistent networking — it's for compute-heavy user-triggered work (exports, ML). Does not solve the "maintain a TCP connection in background" problem.

**PushKit / VoIP entitlement**
Historically allowed persistent socket + reliable background wakeup. As of iOS 13, Apple requires PushKit users to report incoming pushes as VoIP calls via CallKit. Using PushKit for non-call purposes is grounds for App Store rejection. The `unrestricted-voip` PTT entitlement was also deprecated in favor of the Push-to-Talk framework (which is call-semantics only). This path is closed for Styrene.

**Network Extension — PacketTunnelProvider**
Runs as a **separate OS process** that persists even when the main app is killed. Can maintain persistent network connections (TCP, UDP, custom protocols). Used by: WireGuard, ProtonVPN, Mullvad, Tailscale. Requires explicit entitlement (`com.apple.developer.networking.networkextension`), developer justification, and Apple review. This is the **only legitimate iOS mechanism for persistent background networking**. The RNS transport layer would run inside the extension process.

**Core Bluetooth background mode**
If primary connectivity is via RNode (BLE LoRa interface), there's a `bluetooth-central` background mode that allows BLE scanning and connection maintenance. App gets woken on BLE events. Limited to BLE-connected interfaces only.

**APNs silent push (content-available)**
Can wake a suspended app for ~30s. Reliability is intentionally limited by Apple — iOS may defer or drop silent pushes for battery reasons. Not suitable as the primary delivery mechanism but useful as a "nudge to fetch" signal.

### Android background execution constraints

Android is substantially more permissive than iOS, but has tightened significantly since Android 6 (Doze) and Android 9 (App Standby Buckets).

**Doze mode** (Android 6+)
When device is stationary and screen off: network access suspended, wakelocks ignored, job scheduler deferred. Apps get periodic "maintenance windows." Wake locks released even if held. WiFi lock ignored in Doze unless battery optimization is disabled for the app.

**App Standby Buckets** (Android 9+)
Apps categorized: Active → Working Set → Frequent → Rare → Restricted. Network access frequency decreases as apps move toward Rare/Restricted. An app the user hasn't opened in days may have very infrequent network windows.

**Foreground Service**
A service with a persistent user-visible notification. Can keep running indefinitely, including network access, regardless of Doze (with battery optimization exemption) or standby buckets. **This is the Android equivalent of the iOS Network Extension.** Users can grant "unrestricted battery usage" from Settings. Android 14+ requires explicit permission declaration (`FOREGROUND_SERVICE_CONNECTED_DEVICE` for BLE/mesh use cases).

**FCM high-priority messages**
Firebase Cloud Messaging can wake an app in Doze via high-priority push. However FCM requires Google Play Services — not available on GrapheneOS, CalyxOS, or de-Googled devices, which are a significant portion of Styrene's likely user base (mesh networking, privacy-focused).

**Battery optimization exemption**
User can exempt an app from Doze restrictions via Settings → Battery → App. This allows foreground services and wakelocks to function normally. Cannot be requested programmatically after Android 11 without a specific use-case whitelist (calling, alarm clock, etc.).

**WorkManager**
For deferrable background work. Not suitable for persistent networking.

**Android is tractable**: A foreground service with appropriate permissions can maintain an RNS transport socket indefinitely. The UX cost is a persistent notification, which is acceptable for a mesh node application. The bigger concern is de-Googled devices where FCM is unavailable.

### Prior art — how decentralized/privacy-first apps solve this

**Signal**
Hub-and-spoke push model despite being "decentralized" messaging. Signal operates push servers that bridge to APNs/FCM. On iOS: app is a client only in background — Signal servers hold messages and send APNs wakeup, app fetches on wake. This works because Signal has central infrastructure. Not directly applicable to Styrene (no mandatory hub), but the hub-as-push-gateway pattern is extractable.

**Matrix / Element**
Sygnal is a self-hostable push gateway. Homeserver → Sygnal → APNs/FCM. Critically: the push payload is a wakeup signal only (no message content) — app connects to homeserver on wake to fetch actual messages. Self-hosted deployments run their own Sygnal instance with their own APNs certificate. This is the closest analogue to Styrene's architecture. The styrene hub can run a Sygnal-equivalent push gateway.

**WireGuard / Tailscale / ProtonVPN (iOS)**
All use Network Extension (PacketTunnelProvider). The VPN tunnel persists in a separate OS process. The main app is just configuration UI. This is the legitimacy path for Styrene's "full node on iOS" power-user mode — and the App Store precedent is clear and approved.

**Briar (Android)**
Decentralized, no central server. Uses foreground service for persistent Tor/direct connectivity on Android. iOS app has severely limited background functionality — they explicitly acknowledge this as a platform limitation and trade it for decentralization. Relevant as a "what happens if you don't solve this" example.

**Meshtastic**
BLE-primary mesh. Uses Core Bluetooth background mode on iOS to maintain BLE connection to the radio in background. Works because the transport is BLE to a hardware device, not TCP. Styrene with an RNode interface could take this path for the BLE interface specifically.

**Key insight from all prior art**: Nobody has solved persistent arbitrary TCP in iOS background without either (a) a central push server, (b) Network Extension, or (c) accepting that background delivery is unreliable. Styrene needs to pick a lane for each user persona.

### Proposed three-tier architecture for Styrene mobile

Three tiers of background participation, matching user personas. The app ships with Tier 1 and allows opt-in to Tiers 2/3.

---

**Tier 1 — "Rich Client" (default, all platforms)**
- App is an LXMF propagation client registered with a hub.
- When backgrounded: app suspends, no active transport.
- Delivery path: hub holds messages → hub push gateway sends APNs/FCM wakeup → app wakes, connects to hub, fetches messages.
- iOS: requires hub to run a push gateway service (Sygnal-inspired, purpose-built for LXMF). User registers their APNs token with their hub.
- Android: same path, using FCM or a polling WorkManager task for de-Googled devices.
- App Store review: clean. No special entitlements. Standard push notification usage.
- Trade-off: requires a hub. Not a full peer. Message delivery latency is hub-polling interval + APNs latency.
- **This is the MVP path and covers 90% of users.**

---

**Tier 2 — "BLE Node" (iOS + Android, for RNode users)**
- App maintains a Core Bluetooth connection to an RNode in background.
- iOS: `bluetooth-central` background mode entitlement. App woken on BLE events (incoming packet from RNode).
- Android: BLE background is more permissive; foreground service optional.
- styrened-rs RNS transport: BLE interface only in this mode (not TCP).
- App Store review: standard BLE accessory entitlement, well-precedented (Meshtastic pattern).
- Trade-off: requires an RNode hardware device. Only the BLE/LoRa transport is live in background.
- **Second tier — add after Tier 1 is stable.**

---

**Tier 3 — "Full Node" (iOS Network Extension, Android foreground service)**
- iOS: PacketTunnelProvider extension process. RNS transport (TCP/UDP) lives in the extension. Main app is just the UI connecting to the extension's local IPC.
- Android: Foreground service with persistent notification ("Styrene mesh — connected"). RNS transport runs in service.
- App Store review (iOS): Requires `com.apple.developer.networking.networkextension` entitlement. Must justify to Apple as a "mesh networking" use case. Precedent: WireGuard, Tailscale are approved. The key is that the extension is doing real network tunnel work, not abusing the entitlement.
- Battery: meaningful impact. Must be user opt-in with clear explanation. "Always-on mesh node" is a power-user feature.
- Trade-off: complex process model on iOS (main app ↔ extension IPC). On Android, user sees persistent notification.
- **Power-user tier — defer until Tier 1 is proven and there's demand.**

---

**Push gateway service (required for Tier 1 iOS/Android-with-FCM)**
The styrene hub gains a push gateway service: when an LXMF message arrives for a registered mobile device, it sends an APNs/FCM push to wake the device. Push payload is a wakeup signal only (no message content — privacy and iOS payload size limits). App fetches full message on wake. Similar to Matrix's Sygnal gateway, but purpose-built for LXMF propagation events.

De-Googled Android: fall back to periodic WorkManager polling (configurable interval, default 15min). Not real-time but functional without Google infrastructure.

### Architectural constraints this imposes on styrened-rs and the hub

Implications that need to be designed in from the start, before any mobile code is written:

**1. styrened-rs must support LXMF propagation client mode**
The RNS transport layer needs a "thin client" mode where the device registers as an LXMF propagation node but does not route traffic or maintain announce tables for others. This is different from a full RNS node. Python styrened already supports this partially — Rust needs to model it explicitly as a first-class `NodeRole::PropagationClient`.

**2. Hub push gateway service (new service in styrened/public-hub)**
The hub needs:
- A device registration endpoint: `POST /push/register` accepting `{lxmf_destination, platform: "apns"|"fcm"|"polling", push_token}`
- APNs/FCM send capability (HTTP/2 to APNs, FCM v1 API)
- Trigger: when LXMF router delivers a message to a propagation node that has a registered push token, fire the wakeup push
- Privacy: push payload is `{"type": "lxmf_delivery"}` only — no message content, no sender
- Self-hostable: operators bring their own APNs certificate (.p8 key, team ID, bundle ID) and FCM service account JSON

**3. App must re-connect and sync on wake**
On APNs/FCM wakeup, the app gets ~30s on iOS. It must:
- Establish connection to hub (TCP, via stored hub address)
- Request pending messages from LXMF propagation store
- Acknowledge/fetch, update local state
- Terminate cleanly
This means the Dioxus app needs a fast-path sync codepath that works entirely in background without UI.

**4. iOS Network Extension (Tier 3) requires process isolation**
The `PacketTunnelProvider` is a separate binary target in the same app bundle. It cannot directly call into the main Dioxus app. Communication is via `NETunnelProviderSession` IPC. The styrened-rs RNS transport must be compilable as a standalone library with no UI dependencies, callable from both the extension process and the main app. This is already the right architecture (daemon/library separation) — but it must be an explicit constraint in the crate design.

**5. Android foreground service (Tier 3) needs notification management**
The foreground service notification must be informative ("Styrene — 3 mesh peers connected") not generic. This is UX work but needs to be wired into the daemon's event broadcast so the notification updates reactively.

**6. LXMF propagation store TTL and quota**
If the hub is holding messages for suspended mobile clients, it needs message TTL and per-device storage quotas. Unbounded accumulation is a denial-of-service vector against hub operators. This is a hub policy concern but the mobile architecture requires it be defined.

## Decisions

### Decision: Three-tier background participation model: Rich Client → BLE Node → Full Node

**Status:** decided
**Rationale:** No single background mode satisfies all user personas and platforms. Tier 1 (hub + APNs/FCM push gateway) covers mainstream users, requires no special entitlements, and ships first. Tier 2 (BLE/RNode) adds hardware-backed background for radio operators using existing Meshtastic-pattern entitlements. Tier 3 (Network Extension / foreground service) is opt-in for power users who want a full always-on mesh node. Starting with Tier 1 avoids App Store entitlement risk on the MVP and delivers value immediately. Tiers 2 and 3 can be added as progressive enhancements once Tier 1 is proven.

### Decision: Push payload carries no message content — wakeup signal only

**Status:** decided
**Rationale:** Privacy: message content must not transit APNs/FCM infrastructure. iOS payload size limit (4KB) and Android limits also make content embedding fragile for LXMF attachments. The push is a wakeup nudge; the app fetches actual content from the hub over its own encrypted channel on wake. This matches how Signal and Matrix handle this.

### Decision: De-Googled Android (no FCM) falls back to WorkManager polling

**Status:** decided
**Rationale:** Styrene's likely user base skews privacy-conscious; GrapheneOS/CalyxOS are realistic targets. FCM requires Google Play Services which these users deliberately exclude. WorkManager polling at a configurable interval (default 15min, aggressive 5min) is battery-friendly, requires no Google infrastructure, and works on all Android variants. Real-time delivery is degraded but functional. UnifiedPush (a de-Googled FCM alternative) is worth investigating as a future enhancement.

### Decision: Mobile deployment model: hub-connected client (Tier 1) as default, embedded library for Tiers 2/3

**Status:** decided
**Rationale:** The three-tier model resolves the embedded-vs-remote question differently per tier. Tier 1 (MVP): Dioxus app is a hub-connected LXMF propagation client — no embedded daemon, no special entitlements, hub holds messages during suspension and sends push wakeup. Tier 2 (BLE/RNode): styrened-rs RNS transport compiled into the app as a library, BLE interface only, Core Bluetooth background mode. Tier 3 (Full Node): iOS uses PacketTunnelProvider extension binary (styrened-rs as embedded library in a separate process); Android uses a foreground service (styrened-rs embedded in main process). The progression from client → embedded library is an intentional capability ladder, not a binary choice.

### Decision: De-Googled Android is a first-class target — UnifiedPush preferred over FCM, not a fallback

**Status:** decided
**Rationale:** Styrene's user base skews privacy-conscious. GrapheneOS/CalyxOS are realistic primary targets, not edge cases. If forced to choose, de-Googled Android is preferred over stock Android. Therefore: UnifiedPush is the primary push mechanism for Android, not a fallback. FCM is the optional compatibility shim for stock Android users. UnifiedPush (ntfy, Gotify, etc.) is self-hostable, Google-free, and already used by Element, Tusky, and other privacy-first apps — maturity is sufficient for v1. The hub push gateway implements UnifiedPush distributor protocol natively; FCM bridging is a secondary concern. WorkManager polling remains for devices with neither UnifiedPush nor FCM (fully offline/airgapped).

## Open Questions

*No open questions.*

## Implementation Notes

### Constraints

- styrened-rs RNS transport must compile as a no-UI library usable from both iOS Network Extension process and main app process
- Push payload must never contain message content — wakeup signal only
- Hub push gateway must be self-hostable; operators provide their own APNs credentials
- LXMF propagation store on hub must enforce per-device TTL and storage quotas before mobile clients are added
- iOS Tier 3 (Network Extension) is a separate binary target — cannot share process with Dioxus app
- Android Tier 3 foreground service notification must update reactively from daemon event broadcast (not static text)
- FCM must be optional — app must function without Google Play Services
