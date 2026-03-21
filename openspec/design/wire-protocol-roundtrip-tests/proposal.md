# Cross-Language Wire Protocol Roundtrip Tests

## Intent

Build a cross-language roundtrip test suite that encodes every Styrene message type in Python (styrene_wire.py), decodes in Rust (styrene-mesh/wire.rs), and vice versa. Catches schema drift between the two implementations without introducing a shared IDL or changing the serialization format.\n\nScope:\n- Generate canonical test vectors from Python for all ~50 message types\n- Rust test that deserialises each vector and re-serialises to byte-identical output\n- Python test that deserialises Rust-generated vectors\n- CI job that runs both sides and fails on any mismatch\n- Test vectors checked into repo as fixtures (JSON or binary files)\n\nThis is the pragmatic first step before a shared schema codegen (option 1 from the IDL assessment). If drift becomes frequent, graduate to a TOML/YAML schema with codegen.

See [Cross-Language Wire Protocol Roundtrip Tests design doc](../../../docs/wire-protocol-roundtrip-tests.md) for full context.
