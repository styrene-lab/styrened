# TUI Comms Workspace Model — Design Spec (extracted)

> Auto-extracted from docs/tui-comms-workspace.md at decide-time.

## Decisions

### Split asynchronous Mail from synchronous Comms in the primary workspace model (decided)

Operators expect inbox-style, store-and-forward communication to behave differently from live or session-oriented communication. Mail should own asynchronous LXMF-style threads, inbox triage, search, compose, and sync. Comms should own direct text sessions, presence, voice/video, invites, bridge-mediated communication, and other live interaction modes. This prevents the UI from overloading one workspace with incompatible time models.

### Comms should contain transport-aware modes such as Direct and Bridges rather than a single undifferentiated chat list (decided)

A transport- and session-aware comms area better matches the planned ecosystem. A useful initial shape is Comms with submodes like Direct, Active Sessions, Presence, and Bridges. 'Direct' can include synchronous text chat and future calls. 'Bridges' can surface Meshtastic and other cross-network connectors without making them feel like second-class hidden features. This preserves feature parity first while leaving room for Styrene-native enhancements.

### Peer workspace should show peer-specific comms capabilities but not replace the global Comms workspace (decided)

The peer workspace remains the selected-peer drill-down for status, comms, pages, ops, and terminal. It should expose what this peer supports—mail, direct text, voice/video readiness, bridges, transport availability, fallback path—but the aggregate view of live sessions, reachable peers, bridge health, and cross-network activity belongs to the global Comms workspace. This avoids recreating duplicate chat surfaces while preserving a strong peer-centric interaction model.

### Mail should present a unified inbox across asynchronous transports with transport as metadata, not as the primary partition (decided)

Operators should reason about correspondence as conversations and messages first, not by protocol silo. The UI should normalize transport-specific async payloads into canonical message and thread records, then expose transport identity, delivery path, and fallback information as secondary metadata or filters. This preserves a simple default inbox while still allowing debugging, trust, and routing visibility when needed.

### Mail threading should be identity-centric, with transport-specific message records unified under the same peer/thread identity (decided)

The stable operator concept is the peer identity and its conversation history, not the underlying transport. Multiple async transports may carry messages for the same peer over time, but they should collapse into one canonical thread when the authoritative identity relationship is known. Transport remains attached to each message or delivery event as metadata for filtering, trust, and debugging, while thread grouping is driven primarily by identity.

## Research Summary

### Separate async mail from synchronous comms at the IA level

The operator expectation is a meaningful split between asynchronous communication and real-time communication. Async correspondence (store-and-forward LXMF style threads, inbox triage, mail-like workflows) should not be forced into the same primary surface as live sessions. A clean model is: Mail for asynchronous message history, inbox/search/sync/compose, and Comms for real-time or near-real-time activity such as direct chat, voice, video, presence, session invites, and transport-bridged live i…

### Bridge and transport surfaces belong in global comms, not hidden inside peer detail only

Bridged communication with external or adjacent networks (for example Meshtastic, other RNS-adjacent transports, Yggdrasil-native peers, I2P-mediated sessions, or future gateways) is better represented in the global Comms workspace than buried only inside a peer detail screen. Operators will expect to see active live-capable routes, bridge presence, reachable identities, and ongoing sessions in one place. The peer workspace should still show peer-specific transport/capability details, but global…

### Unified inbox should normalize transport-specific mail into one message model

The Mail workspace should not fragment the operator experience into per-transport tabs for every asynchronous transport. A better model is a unified inbox built from canonical message/thread records that carry transport metadata as attributes rather than using transport as the primary UI partition. Transport remains visible for trust/debug/routing context, but the default operator view is 'messages as messages'. This implies the shared UI state layer will eventually need a normalized mail/messag…

### Aggregate communication coverage now spans Mail, Comms, and Contacts launch boundaries

The recent TUI test expansion now covers three adjacent communication entry surfaces at the aggregate-workspace level. Mail has direct tests for resume refresh and layered escape, Comms has direct tests for its Direct/Active/Bridges/Presence shell contract, and Contacts now has explicit tests for directory-first behavior plus launch-routing into conversations with preserved origin metadata. Together this gives stronger regression coverage around the intended split: Contacts manages identities, M…

### Mail compatibility destinations now have stronger regression coverage

The latest coverage pass now explicitly exercises the communication destinations launched from Mail and Contacts, not just the aggregate indices. `ConversationScreen` is covered as a mail-thread compatibility surface with origin-aware routing and path-info display, while `MailGroupThreadScreen` and `ForumThreadScreen` are covered as distinct non-direct destinations for room/topic-oriented communication. This gives better protection against accidental collapse back into a single undifferentiated …
