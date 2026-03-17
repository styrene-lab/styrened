---
id: rns-rpc-invocation-layer
title: Protobuf-over-RNS — Structured RPC Invocation Layer
status: exploring
parent: wire-protocol-idl
tags: [architecture, rpc, protobuf, rns, wire-protocol, grpc-inspired]
open_questions:
  - Should Styrene migrate Link-based RPC from StyreneEnvelope-over-LXMF to native RNS Channel MessageBase types, keeping LXMF only for async store-and-forward?
  - "Is the protobuf dependency acceptable on target hardware (Pi Zero 2W, RP2040, ESP32), or should the IDL generate msgpack-based pack/unpack instead?"
---

# Protobuf-over-RNS — Structured RPC Invocation Layer

## Overview

Explore using protobuf as the payload serialization and .proto service definitions as the IDL for a structured RPC invocation layer that runs over RNS Links (not HTTP/2). RNS handles discovery, identity, encryption, and transport. LXMF handles store-and-forward. The Styrene layer would handle service definition, request/response correlation, and typed payload encode/decode — borrowing gRPC's model without its transport.

## Research

### RNS already has three structured communication primitives

RNS provides three transport abstractions over an encrypted Link, each at a different level:

**1. `Link.request(path, data)` — Request/Response RPC**
Already exists. Path-based routing (like HTTP paths), msgpack-serialized data, response callbacks, automatic retry via Resource for large payloads, timeout handling. This is *already* an RPC mechanism — it just lacks typed schemas.

**2. `Channel` (via `Link.get_channel()`) — Structured Message Passing**
Bidirectional, reliable, ordered message delivery. Messages are typed classes inheriting `MessageBase` with a `MSGTYPE` (uint16), `pack()` → bytes, `unpack(bytes)`. Registration via `channel.register_message_type(MyMessage)`. Handlers via `channel.add_message_handler(callback)`. Automatic windowing, retransmission, and flow control. This is a **typed, multiplexed message bus over a single Link** — very close to what gRPC's streaming model provides.

**3. `Resource` — Large Binary Transfer**
For payloads exceeding a single packet (~295 bytes on LoRa). Automatic chunking, compression, progress callbacks, resumption. Used internally by `Link.request()` for large request/response payloads.

**4. `Buffer` — Stream Interface**
`RawChannelReader`/`RawChannelWriter` provide a stream-oriented interface over a Channel, wrapping the message-based Channel in a read/write byte-stream API. Used by `rnsh` for terminal sessions.

**Key insight**: RNS Channel is almost exactly the "compressed binary payload over a transport layer for invocation" model. It already provides: typed message dispatch (MSGTYPE), binary serialization (pack/unpack), reliable delivery, bidirectional streaming, flow control. What's missing is only the IDL — the schema definition that generates the MessageBase subclasses.

**LXST** (Lightweight Extensible Signal Transport) is a new protocol built on top of RNS Links/Channels for real-time audio/signal streaming. It demonstrates the pattern: use RNS Link as transport, Channel as multiplexer, custom MessageBase types for the application protocol.

### Two distinct transport modes require different strategies

Styrene currently uses two transport modes with different characteristics:

**Mode A: LXMF store-and-forward (current primary)**
- Asynchronous, unreliable delivery (minutes to days latency via propagation nodes)
- No bidirectional channel — fire-and-forget with optional delivery receipts
- Size limit: 256KB propagated, ~295 bytes opportunistic
- Used for: chat, RPC commands to offline/distant nodes, announce-based discovery
- gRPC model is a **poor fit** — no connection, no stream, no response guarantee

**Mode B: RNS Link direct connection (used by DirectLink, terminal, file transfer)**
- Synchronous, reliable, encrypted bidirectional channel
- Full request/response, streaming, flow control
- Size limit: effectively unlimited (Resource handles chunking)
- Used for: status queries, exec, file transfer, terminal sessions, VPN handshake
- gRPC model is a **natural fit** — this IS a connected bidirectional RPC channel

**Styrene currently conflates both modes under the same `StyreneEnvelope` wire format.** A status_request sent via LXMF and one sent over a direct Link use the same 28-byte header + msgpack encoding. This works but means the LXMF path carries overhead for features it can't use (request correlation, streaming), and the Link path doesn't leverage Channel's built-in typed dispatch.

**The opportunity**: For Mode B (Link-based), replace the hand-rolled StyreneEnvelope with RNS Channel MessageBase types. Use .proto files (or a lightweight IDL) to generate the MessageBase subclasses. This gives typed dispatch, automatic serialization, and the flow control that Channel already provides — without touching LXMF at all.

Mode A (LXMF) stays on msgpack StyreneEnvelope — it's the right tool for async store-and-forward.

### The gRPC model mapped onto RNS Channel

Mapping gRPC concepts to RNS primitives:

| gRPC concept | RNS equivalent | Gap |
|---|---|---|
| HTTP/2 connection | RNS Link (encrypted, authenticated) | None — Link is richer (identity-based) |
| HTTP/2 stream multiplexing | Channel MSGTYPE dispatch | None — same pattern |
| protobuf serialization | MessageBase.pack()/unpack() | **Schema**: pack/unpack are hand-written |
| .proto service definition | Nothing — ad hoc registration | **IDL**: no codegen for service stubs |
| Unary RPC | Link.request(path, data) | None — already works |
| Server streaming | Channel message handler + send() | None — bidirectional by default |
| Client streaming | Channel send() from client side | None |
| Bidirectional streaming | Channel is bidirectional by design | None |
| Deadline/timeout | Link timeout, RequestReceipt timeout | None |
| Metadata/headers | LXMF fields, announce app_data | None |
| Interceptors/middleware | Channel message handler chain | Minimal — handlers return bool for chaining |

**What's actually missing is only the top layer**: a schema language that generates MessageBase subclasses with typed pack/unpack. The transport, multiplexing, flow control, encryption, identity, and delivery guarantees are all handled by RNS.

**Protobuf as payload encoding inside MessageBase**: Instead of msgpack dicts, MessageBase.pack() would call `my_proto_message.SerializeToString()` and unpack() would call `MyProtoMessage.ParseFromString(raw)`. The Channel framing (MSGTYPE + sequence + length) stays as-is — it's the envelope. Protobuf is only the payload encoding inside that envelope.

**Practical concern**: protobuf adds ~2MB Python dependency and C extension compilation on ARM. An alternative is to keep msgpack but generate the pack/unpack methods from a schema — getting the IDL benefit without changing serialization.

## Open Questions

- Should Styrene migrate Link-based RPC from StyreneEnvelope-over-LXMF to native RNS Channel MessageBase types, keeping LXMF only for async store-and-forward?
- Is the protobuf dependency acceptable on target hardware (Pi Zero 2W, RP2040, ESP32), or should the IDL generate msgpack-based pack/unpack instead?
