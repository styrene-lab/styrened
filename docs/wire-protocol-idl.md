---
id: wire-protocol-idl
title: Wire Protocol IDL — gRPC Proto vs. Status Quo
status: resolved
tags: [architecture, wire-protocol, grpc, protobuf, msgpack, rns, cross-language]
open_questions: []
---

# Wire Protocol IDL — gRPC Proto vs. Status Quo

## Overview

Assess whether gRPC .proto files should replace or complement the current hand-rolled Styrene wire protocol (styrene_wire.py / styrene-mesh wire.rs). Current protocol: 28-byte header (namespace + version + type + request_id) + msgpack payload, carried inside LXMF FIELD_CUSTOM_DATA. ~50 message types across 8 allocation ranges. Must be byte-identical between Python and Rust implementations.

## Research

### Current wire protocol characteristics

**Format**: `[styrene.io:][version:1][type:1][request_id:16][msgpack payload]` — 28-byte fixed header + variable payload.

**Transport**: Carried inside LXMF `FIELD_CUSTOM_DATA` (0xFC). LXMF itself runs over RNS, which runs over LoRa/packet radio/TCP/I2P/Yggdrasil. This is NOT an IP transport — RNS has no concept of TCP connections, HTTP, or sockets in the traditional sense.

**Constraints**:
- LXMF propagated messages max **256KB** — hard ceiling from RNS
- LXMF opportunistic (direct) messages ~**295 bytes** — the LoRa path
- Single-byte type field — 256 possible message types (50 allocated)
- No schema negotiation — both sides must agree on msgpack dict keys by convention
- Payload schemas defined only in code (Python dataclasses + Rust serde structs)

**Cross-language contract**: styrene-mesh Rust crate's `wire.rs` must produce byte-identical output to Python's `styrene_wire.py`. Currently enforced by matching IntEnum values and msgpack key names by hand.

**Message types**: 50 types across 8 ranges (control, status, content, network, RPC command, RPC response, datalink, terminal, PQC). Each type's payload is a msgpack dict with type-specific keys — no formal schema.

### gRPC proto assessment — what fits, what doesn't

**gRPC is a service framework, not just a serialization format.** It bundles three things: (1) Protocol Buffers (protobuf) as the IDL/serialization, (2) HTTP/2 as the transport, (3) code generation for client/server stubs.

**What Styrene actually needs**: an IDL — a single source of truth for message schemas that generates type-safe code in both Python and Rust. The transport (LXMF over RNS) and the framing (28-byte header) are already solved and non-negotiable.

**gRPC's HTTP/2 transport is a non-starter.** RNS is not IP-based. Messages travel over LoRa, packet radio, I2P tunnels, and Yggdrasil mesh — none of which speak HTTP/2. gRPC's service definitions (`rpc StatusRequest(...) returns (...)`) assume a connected bidirectional stream, which doesn't exist in store-and-forward LXMF delivery.

**Protobuf (the serialization) vs. msgpack**:
| Dimension | Protobuf | msgpack |
|-----------|----------|---------|
| Schema | .proto files, mandatory | None — convention only |
| Code gen | protoc → typed classes | Manual dataclasses |
| Wire size | ~10-30% smaller (varint) | Slightly larger |
| Dependencies | protobuf lib (~2MB py) | msgpack (~100KB py, already dep of RNS) |
| RNS ecosystem alignment | Foreign | Native — RNS/LXMF use msgpack internally |
| Extensibility | Field numbers, unknown field preservation | Dict keys, unknown keys silently dropped |
| LoRa 295-byte budget | Tight but possible | Same — no meaningful difference at this scale |

**Protobuf without gRPC** is viable but adds friction:
- Python protobuf library is heavy and has C extension compilation issues on ARM SBCs (Pi Zero 2W, RP2040)
- Rust prost/tonic is clean but adds a build.rs protoc step
- Every payload encode/decode now goes through protobuf instead of msgpack — requires converting the LXMF wrapper to carry protobuf bytes inside the existing framing
- RNS itself still uses msgpack everywhere — mixing serialization formats creates cognitive overhead

### Alternatives that solve the real problem

The real problem is: **payload schemas are defined only in code, duplicated between Python and Rust, and drift is caught by manual inspection.** Three alternatives address this without replacing the transport or serialization:

**1. msgpack + JSON Schema / TypeSpec IDL**
Write schemas in JSON Schema or TypeSpec. Generate Python dataclasses and Rust serde structs. Keep msgpack on the wire. Adds a codegen step but doesn't change the serialization or transport.

**2. Cap'n Proto / FlatBuffers**
Zero-copy serialization with .capnp/.fbs IDL files. Better fit than protobuf for constrained networks (no varint overhead, direct memory access). But adds binary dependencies and is less familiar.

**3. Shared schema file (pragmatic approach)**
A single `styrene-wire-schema.toml` or `.yaml` defining every message type's field names, types, and version. A small codegen script emits Python dataclasses and Rust structs from the same source. Keep msgpack serialization, keep the 28-byte header, keep RNS alignment. Minimal new dependencies. The contract is the schema file, tested by cross-language roundtrip tests.

**4. Proto files as IDL only (no gRPC runtime)**
Use .proto files purely as the schema language. Run protoc to generate docs and validate field numbering. But serialize to msgpack, not protobuf wire format. The .proto file is the contract; the generated code is thrown away. This gives the structured IDL benefit without the dependency cost — but it's unconventional and confusing (proto files that don't use protobuf encoding).

## Decisions

### Decision: gRPC proto files are the wrong tool for Styrene's wire protocol

**Status:** decided
**Rationale:** gRPC couples three things: protobuf serialization, HTTP/2 transport, and service stubs. Styrene's transport is LXMF over RNS — not IP, not HTTP, not bidirectional streams. Only the IDL aspect of .proto files is relevant, and using protobuf as IDL-only without the encoding is confusing and non-standard.

The actual need — a single source of truth for message schemas generating typed code in Python and Rust — is better served by a lightweight shared schema file (TOML/YAML) with a codegen script, or by a serialization-agnostic IDL like TypeSpec. These approaches keep msgpack on the wire (aligned with RNS internals), avoid the protobuf C extension dependency on ARM SBCs, and don't introduce a foreign serialization format into a msgpack-native ecosystem.

Protobuf the serialization format has marginal wire size benefits (~10-30% smaller) but adds compilation complexity (protoc, C extensions on ARM) and ecosystem friction (RNS uses msgpack everywhere). The 295-byte LoRa budget constraint doesn't meaningfully change between msgpack and protobuf.

## Open Questions

*No open questions.*
