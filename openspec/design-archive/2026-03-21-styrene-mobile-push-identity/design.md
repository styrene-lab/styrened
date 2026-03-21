# Styrene Mobile — Push Identity, APNs Distribution, and YubiKey Integration — Design

## Architecture Decisions

### Decision: YubiKey on mobile is a session-unlock token, not a per-packet signer

**Status:** decided
**Rationale:** NFC tap per signing operation is disruptive for routine mesh operations (periodic announces, message signing). YubiKey use on mobile: tap to unlock a session key held in memory, session key signs all mesh traffic until app kill or configurable timeout. This matches how YubiKey+SSH agent works. The YubiKey signs exactly once per session (the unlock assertion); symmetric/derived keys handle per-packet operations. This makes Tier A viable on mobile without requiring the user to tap their YubiKey on every message send.

### Decision: Android Keystore Ed25519 (Tier B) is the recommended mobile default on StrongBox devices

**Status:** decided
**Rationale:** Android Keystore natively supports Ed25519 (API 33+) with StrongBox hardware backing on recent Pixel and Samsung devices. This is the cleanest Tier B path — native algorithm, no P-256 workaround needed unlike iOS Secure Enclave. For de-Googled Android (GrapheneOS) on supported hardware (Pixels), StrongBox is available. This aligns with the first-class de-Googled Android target: GrapheneOS users on Pixel hardware get hardware-backed identity without Google services.

### Decision: Push delivery path is determined by identity tier — no single universal push path

**Status:** decided
**Rationale:** Tier B users (Apple Passwords / Android Credential Manager) are already in platform ecosystems; App Store + Styrene Lab APNs relay is coherent with their threat model and acceptable metadata exposure. Tier C/A users (Bitwarden, YubiKey) chose out of platform ecosystems; they use UnifiedPush (self-hosted ntfy/Gotify) or WorkManager/timer polling — no APNs, no Styrene Lab relay. Sideloading and custom builds are not required for any deployment. Self-hosted hubs serving privacy-first users are completely Google-and-Apple-free. The App Store + APNs path is an opt-in for mainstream usability.

## Research Context

### The APNs credential binding problem

APNs push notifications are cryptographically bound to a specific app bundle ID and a specific Apple Developer team. A .p8 signing key is issued per team, scoped to specific bundle IDs. This creates a fundamental tension for self-hosted Styrene deployments:

**Option A — Centralized (App Store model)**
Styrene Lab holds the APNs .p8 key. The hub push gateway sends to Styrene Lab's APNs endpoint. Styrene Lab's servers relay to Apple.
- Problem: Styrene Lab becomes a mandatory intermediary even for fully self-hosted deployments. Contradicts the decentralized ethos. Styrene Lab can observe push metadata (device tokens, timing, hub addresses).
- Benefit: Zero operator configuration, works out of the box for App Store users.

**Option B — Operator-owned credentials (self-hostable, requires custom build)**
Each operator who wants push gets an Apple Developer account ($99/yr), creates their own bundle ID, builds their own IPA. Hub gateway uses their own .p8 key.
- Problem: Users must install an IPA that's not in the App Store (TestFlight, AltStore, sideload, MDM). iOS sideloading is restricted (EU only without special entitlements on stock iOS). Technical barrier is high.
- Benefit: Fully self-sovereign, no third-party in the push path.

**Option C — Hybrid (App Store app + operator push relay)**
App Store app with Styrene Lab's bundle ID. Operators register their device's APNs token with Styrene Lab's push relay service (not their hub). Hub sends to Styrene Lab relay, relay sends to Apple.
- Problem: Still requires Styrene Lab relay, now as a cloud service. Operational burden. Worse than Option A.

**Option D — Notification-free operation as a first-class mode**
Don't require APNs at all. Tier 1 works via UnifiedPush (self-hostable, Android/desktop) and WorkManager polling for iOS. iOS users get polling-based delivery — not real-time but functional. Avoids the APNs credential problem entirely on iOS for privacy-first users.
- This is actually coherent: iOS users who want push either accept Styrene Lab APNs relay (Option A for mass market) or use polling (for self-sovereign deployments).

**The YubiKey angle**
iOS YubiKey support (via NFC and Lightning/USB-C) has matured significantly. The YubiKey 5 NFC works with iOS via the Yubico Mobile iOS SDK and MFi. If Styrene identity is YubiKey-backed (as the styrene-identity design explores), then the mobile app authenticating with a YubiKey changes the threat model for push credentials: even if a push token is observed, it can't be used to impersonate the user without the physical YubiKey. This doesn't solve the APNs metadata problem but significantly raises the bar for the identity concern.

### iOS YubiKey support status (2025)

- **YubiKey 5 NFC**: Works on iPhone via NFC tap. Yubico Mobile iOS SDK. Supports FIDO2/WebAuthn, PIV (smart card), OTP, OpenPGP card.
- **YubiKey 5Ci** (Lightning): Works on older iPhones without NFC support. Lightning port.
- **USB-C YubiKeys**: Work on iPhone 15+ (USB-C port) and iPad Pro. Direct connection.
- **MFi requirement**: Lightning accessories require MFi certification. USB-C is open. NFC works without MFi.
- **Yubico Mobile iOS SDK**: Open source, handles NFC session management, FIDO2 assertions, PIV operations. Integrates with iOS AuthenticationServices for WebAuthn.
- **PIV on mobile**: The PIV applet allows RSA/ECC key operations where the private key never leaves the YubiKey. Signing operations require physical touch (or NFC tap for NFC models).
- **FIDO2/Passkeys**: iOS 16+ has native passkey support. YubiKey can serve as a roaming FIDO2 authenticator for passkey flows.

**Relevance to Styrene identity:**
If the Styrene identity system uses Ed25519 keys derived from or attested by a YubiKey (as explored in the styrene-identity node), then mobile authentication could work as: NFC tap → YubiKey signs challenge → RNS identity assertion verified. The private key never enters the phone's keychain — it lives on the YubiKey. This is a strong security property for mobile: phone compromise doesn't expose the mesh identity.

**Interaction with push credentials:**
APNs device token is separate from Styrene identity. The token is iPhone-bound, not user-bound. A YubiKey-backed identity means the APNs token tells the hub "wake this device" but the subsequent authentication (connecting to hub and fetching messages) requires the YubiKey-signed challenge. No YubiKey → no message content, even if the push is observed or replayed.

### IdentitySigner on mobile — which tiers are available per platform

The four-tier IdentitySigner model (resolved in styrene-identity) maps to mobile platforms as follows:

**iOS:**
- Tier A (Hardware HSM): YubiKey via NFC tap (YubiKey 5 NFC) or USB-C (YubiKey 5C, iPhone 15+). Yubico Mobile iOS SDK. PIV signing requires NFC session per operation — acceptable for login/identity assertion, disruptive for routine mesh announces. Practical model: use YubiKey to unlock a session key held in Tier B, not for per-packet signing.
- Tier B (Device HSM): iOS Secure Enclave. Keys are device-bound and non-exportable. Available via CryptoKit (`SecureEnclave.P256.Signing.PrivateKey`). Limitation: P-256 only, not Ed25519. Styrene uses Ed25519. Workaround: use Secure Enclave P-256 key to encrypt/decrypt an Ed25519 key held in the iOS Keychain (so Ed25519 key is extractable IF Secure Enclave key is unlocked — practical Tier B+). OR: derive session credentials from Secure Enclave key without exposing the Ed25519 root.
- Tier C (Credential Manager): Bitwarden iOS app exposes stored SSH keys via iOS credential provider extension. Styrene could retrieve the root secret from Bitwarden at app launch. Cross-device — same identity works on iPhone and MacBook. Requires Bitwarden app installed.
- Tier D (Encrypted file): Stored in iOS app sandbox (~/.styrene equivalent in app documents). Password-protected. Accessible only within the app. Default for new installs without other setup.

**Android:**
- Tier A: YubiKey via NFC or USB-C (via OTG). Yubico Android SDK. Same NFC-per-operation constraint as iOS.
- Tier B: Android Keystore with StrongBox (hardware-backed on devices with dedicated security chip — Pixel 3+, Samsung Galaxy S20+). Ed25519 IS supported in Android Keystore (API 23+, algorithm `ED25519` added in API 33+). This is the cleanest Tier B path for Android — native Ed25519, hardware-backed, no workaround needed.
- Tier C: Bitwarden Android (SSH agent extension), 1Password Android. Same pattern as iOS.
- Tier D: Encrypted file in app-private storage.

**Key insight for mobile identity UX:**
The NFC-per-signing constraint on YubiKey means it's not viable for routine mesh operations (announcements fire periodically, message signing happens on every send). Practical mobile use of YubiKey is as an **unlock token** — tap YubiKey → derive session key → session key signs mesh traffic until app is killed or a timeout. The YubiKey never signs individual mesh packets; it only unlocks the session.

This is the same model as how YubiKey works with SSH agent forwarding — key never signs individual SSH session packets; it signs the SSH handshake once, the session symmetric key does the rest.

**Recommended mobile defaults by platform:**
- iOS with YubiKey: Tier A unlock → Tier D session key in memory
- iOS without YubiKey, with Bitwarden: Tier C (Bitwarden retrieves root at launch)
- iOS without Bitwarden: Tier B+ (Secure Enclave P-256 wraps Ed25519 in Keychain)
- Android with StrongBox device: Tier B (native Ed25519 in Android Keystore)
- Android without StrongBox: Tier C (Bitwarden) or Tier D (encrypted file)

**`styrened identity` / setup wizard implications:**
The Dioxus mobile app's onboarding flow should detect available tiers and recommend:
1. "You have Bitwarden installed — use your existing Styrene identity?" (Tier C)
2. "Set up hardware-backed identity on this device" (Tier B — Secure Enclave / Keystore)
3. "Link a YubiKey for high-security operations" (Tier A upgrade)
4. "Create a new identity secured by passphrase" (Tier D fallback)

### Identity tier availability per mobile platform — revised

With the corrected four-tier model:

**iOS / iPadOS:**
- Tier A: YubiKey 5 NFC (tap) or YubiKey 5C (USB-C, iPhone 15+). Session-unlock model.
- Tier B: iCloud Keychain / Apple Passwords app. FaceID/TouchID unlock. Secure Enclave-backed on-device. Syncs across Apple devices via end-to-end encrypted iCloud. Natural fit for App Store users.
- Tier C: Bitwarden iOS (credential provider extension), 1Password. FOSS preference, cross-platform.
- Tier D: Encrypted file in app sandbox. Default for new installs with no other setup.

**Stock Android (Google Play Services present):**
- Tier A: YubiKey via NFC or USB-C OTG.
- Tier B: Android Credential Manager / Google Password Manager. Biometric unlock. StrongBox-backed on Pixel/Galaxy. Syncs to Google account.
- Tier C: Bitwarden Android. FOSS preference.
- Tier D: Encrypted file in app-private storage.

**De-Googled Android (GrapheneOS, CalyxOS):**
- Tier A: YubiKey (NFC works fine on GrapheneOS).
- Tier B: NOT AVAILABLE — no Google Password Manager, no Android Credential Manager backend. OEM alternatives (Samsung Pass) not present on clean AOSP. This tier simply does not exist on de-Googled Android without Google services.
- Tier C: Bitwarden. THIS IS THE DEFAULT for de-Googled Android. Vaultwarden for self-hosted deployments. Preferred and first-class.
- Tier D: Encrypted file fallback.

**Consequence for de-Googled Android:**
Tier C (Bitwarden/Vaultwarden) becomes the primary non-YubiKey identity tier on de-Googled Android. The onboarding wizard should skip Tier B entirely on AOSP without Google services and present Tier C as the first recommendation after Tier A. This aligns with the explicit first-class de-Googled Android decision.

**Interaction with push notifications on de-Googled Android:**
A user on GrapheneOS using Bitwarden (Tier C identity) will also lack FCM for push. They get UnifiedPush (ntfy/Gotify) or WorkManager polling. The entire stack is Google-free from identity storage through message delivery. This is coherent and complete — no Google dependency anywhere.

### APNs distribution model — resolved by tier alignment

The three open APNs questions collapse into a cleaner picture once identity tiers are aligned with push delivery tiers:

**Tier B users (Apple Passwords / iCloud Keychain) — App Store + Styrene Lab APNs relay**
These users are already in Apple's ecosystem. They chose Apple's credential manager, they use the App Store, and iCloud is acceptable to their threat model. For them:
- App Store distribution with Styrene Lab's bundle ID and APNs .p8 key is the natural path
- Styrene Lab operates the APNs relay (forwards wakeup push from hub → Apple → device)
- Metadata exposure: device token, timestamp, hub address observable by Styrene Lab. Acceptable for this user's stated threat model (they already trust Apple with their identity).

**Tier C users (Bitwarden) — polling or UnifiedPush**
These users chose a FOSS credential manager specifically to avoid platform lock-in. For them:
- APNs relay through Styrene Lab is inconsistent with their threat model — they don't want Styrene Lab in the push path
- Option D (WorkManager polling / NSTimer polling): functional, configurable interval, zero third-party involvement. Not real-time but coherent with the privacy posture.
- UnifiedPush (ntfy, Gotify): self-hostable push, no Apple/Google/Styrene Lab in the path. iOS support is emerging (ntfy has an iOS app that implements UnifiedPush distributor).
- For Tier C on iOS specifically: polling is the cleanest story for now. UnifiedPush on iOS is a watch item.

**Tier A users (YubiKey) — same as Tier C posture**
YubiKey users are security-conscious. Same reasoning as Tier C — polling or self-hosted UnifiedPush. Unlikely to want Styrene Lab APNs relay metadata.

**De-Googled Android (Tier C) — UnifiedPush primary, polling fallback**
Already decided: UnifiedPush is the first-class push mechanism. ntfy/Gotify run on the user's own infrastructure or a trusted server.

---

**The split is therefore:**
```
App Store + Styrene Lab APNs  →  Tier B users (opted into Apple ecosystem)
UnifiedPush (self-hosted)     →  Tier C/A users who self-host a hub
WorkManager / timer polling   →  Universal fallback, configurable interval
```

This is not "Option A vs. Option D" — it's three valid paths that the app selects based on identity tier + push capability detection. No single path is the default for all users.

---

**Sideloading / custom build is not required**
The previous concern was: self-hosted operators need their own APNs .p8 key → own bundle ID → can't use App Store app.

This dissolves because:
- The hub push gateway only uses APNs for Tier B users who accept the Styrene Lab relay
- Tier C/A users don't go through APNs at all — they use UnifiedPush or polling
- Operators who run their own hub and serve only Tier C/A users need zero APNs integration
- Operators who want to serve Tier B users (App Store users wanting APNs push) need to either: use Styrene Lab relay (simplest), or stand up their own APNs relay with their own developer account and a custom build (advanced, not required for basic deployment)

Self-hosted deployments that serve privacy-first users are completely Google-and-Apple-free by design. The App Store + APNs path is an explicit opt-in for mainstream usability, not a requirement.

---

**Metadata exposure in the APNs relay — acceptable for Tier B**
Styrene Lab relay observes: device APNs token (pseudonymous, rotates occasionally), timestamp (message arrival time), hub address (identifies which hub the user connects to).

For Tier B users who chose iCloud Keychain: they already trust Apple with their identity sync, their iCloud data, and their device. Styrene Lab observing "this device received a wakeup push at this time from this hub" is a lower exposure than what Apple already observes. Acceptable for this tier. The wakeup-only payload means message content is never exposed.

For Tier C/A users: they don't use this path. Not applicable.
