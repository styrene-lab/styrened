# Styrene Mobile — Push Identity, APNs Distribution, and YubiKey Integration — Design Spec (extracted)

> Auto-extracted from docs/styrene-mobile-push-identity.md at decide-time.

## Decisions

### YubiKey on mobile is a session-unlock token, not a per-packet signer (decided)

NFC tap per signing operation is disruptive for routine mesh operations (periodic announces, message signing). YubiKey use on mobile: tap to unlock a session key held in memory, session key signs all mesh traffic until app kill or configurable timeout. This matches how YubiKey+SSH agent works. The YubiKey signs exactly once per session (the unlock assertion); symmetric/derived keys handle per-packet operations. This makes Tier A viable on mobile without requiring the user to tap their YubiKey on every message send.

### Android Keystore Ed25519 (Tier B) is the recommended mobile default on StrongBox devices (decided)

Android Keystore natively supports Ed25519 (API 33+) with StrongBox hardware backing on recent Pixel and Samsung devices. This is the cleanest Tier B path — native algorithm, no P-256 workaround needed unlike iOS Secure Enclave. For de-Googled Android (GrapheneOS) on supported hardware (Pixels), StrongBox is available. This aligns with the first-class de-Googled Android target: GrapheneOS users on Pixel hardware get hardware-backed identity without Google services.

### Push delivery path is determined by identity tier — no single universal push path (decided)

Tier B users (Apple Passwords / Android Credential Manager) are already in platform ecosystems; App Store + Styrene Lab APNs relay is coherent with their threat model and acceptable metadata exposure. Tier C/A users (Bitwarden, YubiKey) chose out of platform ecosystems; they use UnifiedPush (self-hosted ntfy/Gotify) or WorkManager/timer polling — no APNs, no Styrene Lab relay. Sideloading and custom builds are not required for any deployment. Self-hosted hubs serving privacy-first users are completely Google-and-Apple-free. The App Store + APNs path is an opt-in for mainstream usability.

## Research Summary

### The APNs credential binding problem

APNs push notifications are cryptographically bound to a specific app bundle ID and a specific Apple Developer team. A .p8 signing key is issued per team, scoped to specific bundle IDs. This creates a fundamental tension for self-hosted Styrene deployments:

**Option A — Centralized (App Store model)**
Styrene Lab holds the APNs .p8 key. The hub push gateway sends to Styrene Lab's APNs endpoint. Styrene Lab's servers relay to Apple.
- Problem: Styrene Lab becomes a mandatory intermediary even fo…

### iOS YubiKey support status (2025)

- **YubiKey 5 NFC**: Works on iPhone via NFC tap. Yubico Mobile iOS SDK. Supports FIDO2/WebAuthn, PIV (smart card), OTP, OpenPGP card.
- **YubiKey 5Ci** (Lightning): Works on older iPhones without NFC support. Lightning port.
- **USB-C YubiKeys**: Work on iPhone 15+ (USB-C port) and iPad Pro. Direct connection.
- **MFi requirement**: Lightning accessories require MFi certification. USB-C is open. NFC works without MFi.
- **Yubico Mobile iOS SDK**: Open source, handles NFC session management, FID…

### IdentitySigner on mobile — which tiers are available per platform

The four-tier IdentitySigner model (resolved in styrene-identity) maps to mobile platforms as follows:

**iOS:**
- Tier A (Hardware HSM): YubiKey via NFC tap (YubiKey 5 NFC) or USB-C (YubiKey 5C, iPhone 15+). Yubico Mobile iOS SDK. PIV signing requires NFC session per operation — acceptable for login/identity assertion, disruptive for routine mesh announces. Practical model: use YubiKey to unlock a session key held in Tier B, not for per-packet signing.
- Tier B (Device HSM): iOS Secure Enclave.…

### Identity tier availability per mobile platform — revised

With the corrected four-tier model:

**iOS / iPadOS:**
- Tier A: YubiKey 5 NFC (tap) or YubiKey 5C (USB-C, iPhone 15+). Session-unlock model.
- Tier B: iCloud Keychain / Apple Passwords app. FaceID/TouchID unlock. Secure Enclave-backed on-device. Syncs across Apple devices via end-to-end encrypted iCloud. Natural fit for App Store users.
- Tier C: Bitwarden iOS (credential provider extension), 1Password. FOSS preference, cross-platform.
- Tier D: Encrypted file in app sandbox. Default for new in…

### APNs distribution model — resolved by tier alignment

The three open APNs questions collapse into a cleaner picture once identity tiers are aligned with push delivery tiers:

**Tier B users (Apple Passwords / iCloud Keychain) — App Store + Styrene Lab APNs relay**
These users are already in Apple's ecosystem. They chose Apple's credential manager, they use the App Store, and iCloud is acceptable to their threat model. For them:
- App Store distribution with Styrene Lab's bundle ID and APNs .p8 key is the natural path
- Styrene Lab operates the APNs…
