# CBOR migration — styrene-mesh MessagePack → ciborium

## Intent

styrene-mesh uses rmp_serde (MessagePack). Migrate to ciborium (CBOR, RFC 8949) for deterministic encoding (required for content-hash event IDs in identity manifest), COSE support (RFC 9052, needed for signed identity manifest), and formal IETF governance. Migration is mechanical — swap rmp_serde for ciborium in Cargo.toml, update error types. All serde derives remain identical. Must be synchronized with Python styrened (msgpack → cbor2). Wire protocol version bump required; both sides must upgrade together.
