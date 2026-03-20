# Styrene Mobile — Background Execution Architecture — Design Spec (extracted)

> Auto-extracted from docs/styrene-mobile-background-arch.md at decide-time.

## Decisions

### Three-tier background participation model: Rich Client → BLE Node → Full Node (decided)

No single background mode satisfies all user personas and platforms. Tier 1 (hub + APNs/FCM push gateway) covers mainstream users, requires no special entitlements, and ships first. Tier 2 (BLE/RNode) adds hardware-backed background for radio operators using existing Meshtastic-pattern entitlements. Tier 3 (Network Extension / foreground service) is opt-in for power users who want a full always-on mesh node. Starting with Tier 1 avoids App Store entitlement risk on the MVP and delivers value immediately. Tiers 2 and 3 can be added as progressive enhancements once Tier 1 is proven.

### Push payload carries no message content — wakeup signal only (decided)

Privacy: message content must not transit APNs/FCM infrastructure. iOS payload size limit (4KB) and Android limits also make content embedding fragile for LXMF attachments. The push is a wakeup nudge; the app fetches actual content from the hub over its own encrypted channel on wake. This matches how Signal and Matrix handle this.

### De-Googled Android (no FCM) falls back to WorkManager polling (decided)

Styrene's likely user base skews privacy-conscious; GrapheneOS/CalyxOS are realistic targets. FCM requires Google Play Services which these users deliberately exclude. WorkManager polling at a configurable interval (default 15min, aggressive 5min) is battery-friendly, requires no Google infrastructure, and works on all Android variants. Real-time delivery is degraded but functional. UnifiedPush (a de-Googled FCM alternative) is worth investigating as a future enhancement.

### Mobile deployment model: hub-connected client (Tier 1) as default, embedded library for Tiers 2/3 (decided)

The three-tier model resolves the embedded-vs-remote question differently per tier. Tier 1 (MVP): Dioxus app is a hub-connected LXMF propagation client — no embedded daemon, no special entitlements, hub holds messages during suspension and sends push wakeup. Tier 2 (BLE/RNode): styrened-rs RNS transport compiled into the app as a library, BLE interface only, Core Bluetooth background mode. Tier 3 (Full Node): iOS uses PacketTunnelProvider extension binary (styrened-rs as embedded library in a separate process); Android uses a foreground service (styrened-rs embedded in main process). The progression from client → embedded library is an intentional capability ladder, not a binary choice.

### De-Googled Android is a first-class target — UnifiedPush preferred over FCM, not a fallback (decided)

Styrene's user base skews privacy-conscious. GrapheneOS/CalyxOS are realistic primary targets, not edge cases. If forced to choose, de-Googled Android is preferred over stock Android. Therefore: UnifiedPush is the primary push mechanism for Android, not a fallback. FCM is the optional compatibility shim for stock Android users. UnifiedPush (ntfy, Gotify, etc.) is self-hostable, Google-free, and already used by Element, Tusky, and other privacy-first apps — maturity is sufficient for v1. The hub push gateway implements UnifiedPush distributor protocol natively; FCM bridging is a secondary concern. WorkManager polling remains for devices with neither UnifiedPush nor FCM (fully offline/airgapped).

## Research Summary

### iOS background execution constraints

iOS has several distinct background execution modes, each with different capabilities and review scrutiny:

**Suspension (default)**
App is suspended shortly after leaving foreground. No code runs. Any open TCP sockets will eventually time out. The OS gives ~5-30s of grace via `beginBackgroundTask` to finish in-flight work cleanly.

**BGAppRefreshTask**
~30s budget, system-scheduled (app cannot trigger it). Used for content refresh. Frequency determined by iOS based on usage patterns. Completely…

### Android background execution constraints

Android is substantially more permissive than iOS, but has tightened significantly since Android 6 (Doze) and Android 9 (App Standby Buckets).

**Doze mode** (Android 6+)
When device is stationary and screen off: network access suspended, wakelocks ignored, job scheduler deferred. Apps get periodic "maintenance windows." Wake locks released even if held. WiFi lock ignored in Doze unless battery optimization is disabled for the app.

**App Standby Buckets** (Android 9+)
Apps categorized: Active →…

### Prior art — how decentralized/privacy-first apps solve this

**Signal**
Hub-and-spoke push model despite being "decentralized" messaging. Signal operates push servers that bridge to APNs/FCM. On iOS: app is a client only in background — Signal servers hold messages and send APNs wakeup, app fetches on wake. This works because Signal has central infrastructure. Not directly applicable to Styrene (no mandatory hub), but the hub-as-push-gateway pattern is extractable.

**Matrix / Element**
Sygnal is a self-hostable push gateway. Homeserver → Sygnal → APNs/FC…

### Proposed three-tier architecture for Styrene mobile

Three tiers of background participation, matching user personas. The app ships with Tier 1 and allows opt-in to Tiers 2/3.

---

**Tier 1 — "Rich Client" (default, all platforms)**
- App is an LXMF propagation client registered with a hub.
- When backgrounded: app suspends, no active transport.
- Delivery path: hub holds messages → hub push gateway sends APNs/FCM wakeup → app wakes, connects to hub, fetches messages.
- iOS: requires hub to run a push gateway service (Sygnal-inspired, purpose-bui…

### Architectural constraints this imposes on styrened-rs and the hub

Implications that need to be designed in from the start, before any mobile code is written:

**1. styrened-rs must support LXMF propagation client mode**
The RNS transport layer needs a "thin client" mode where the device registers as an LXMF propagation node but does not route traffic or maintain announce tables for others. This is different from a full RNS node. Python styrened already supports this partially — Rust needs to model it explicitly as a first-class `NodeRole::PropagationClient`.

…
