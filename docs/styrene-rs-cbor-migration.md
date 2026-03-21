---
id: styrene-rs-cbor-migration
title: CBOR migration — styrene-mesh MessagePack → ciborium
status: decided
parent: styrene-rs-architecture
open_questions: []
branches: ["feature/styrene-rs-cbor-migration"]
openspec_change: styrene-rs-cbor-migration
---

# CBOR migration — styrene-mesh MessagePack → ciborium

## Overview

styrene-mesh uses rmp_serde (MessagePack). Migrate to ciborium (CBOR, RFC 8949) for deterministic encoding (required for content-hash event IDs in identity manifest), COSE support (RFC 9052, needed for signed identity manifest), and formal IETF governance. Migration is mechanical — swap rmp_serde for ciborium in Cargo.toml, update error types. All serde derives remain identical. Must be synchronized with Python styrened (msgpack → cbor2). Wire protocol version bump required; both sides must upgrade together.

## Decisions

### Decision: Migrate styrene-mesh from MessagePack to CBOR via ciborium

**Status:** decided
**Rationale:** CBOR provides deterministic encoding for content-hash event IDs, COSE support for signed identity manifests, and IETF governance. Migration is mechanical — serde derives unchanged.

## Open Questions

*No open questions.*
