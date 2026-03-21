---
id: styrene-wire-schema-idl
title: Styrene Wire Schema IDL — Format and Codegen
status: resolved
parent: rns-rpc-invocation-layer
tags: [architecture, wire-protocol, idl, codegen, msgpack, rust, python]
open_questions: []
issue_type: feature
priority: 2
---

# Styrene Wire Schema IDL — Format and Codegen

## Overview

Define the schema format and codegen pipeline that generates RNS Channel MessageBase subclasses (Python) and equivalent Rust structs from a single source of truth. Payloads serialize to msgpack. The schema covers both Link-based Channel messages and LXMF StyreneEnvelope payloads.

## Research

### Proposed schema format and codegen output

**Schema file**: `styrene-wire.toml` — lives in a shared location (either repo root or a `wire/` directory). Single source of truth for all message types, field names, types, and transport mode.

**Example schema**:
```toml
[meta]
version = 2
namespace = "styrene.io"

# ─── Transport modes ───
# "channel" = Link-based Channel MessageBase (bidirectional, reliable)
# "lxmf"    = LXMF StyreneEnvelope (async, store-and-forward)
# "both"    = available on either transport

# ─── Control ───
[messages.Ping]
msgtype = 0x01
transport = "both"

[messages.Pong]
msgtype = 0x02
transport = "both"

# ─── Status ───
[messages.StatusRequest]
msgtype = 0x10
transport = "channel"

[messages.StatusResponse]
msgtype = 0x11
transport = "channel"
[messages.StatusResponse.fields]
uptime = "int"
ip = "string"
services = "list[string]"
disk_used = "int"
disk_total = "int"
hostname = "string?"        # ? = optional
arch = "string?"
os_id = "string?"
os_version = "string?"
nixos_generation = "string?"
styrened_version = "string?"
available_commands = "list[string]?"

# ─── Chat (LXMF only) ───
[messages.Chat]
msgtype = 0x20
transport = "lxmf"
[messages.Chat.fields]
text = "string"

# ─── RPC ───
[messages.Exec]
msgtype = 0x40
transport = "channel"
[messages.Exec.fields]
command = "string"
args = "list[string]"

[messages.ExecResult]
msgtype = 0x60
transport = "channel"
[messages.ExecResult.fields]
exit_code = "int"
stdout = "string"
stderr = "string"
```

**Type system** (minimal, msgpack-native):
- `string`, `int`, `float`, `bool`, `bytes`
- `list[T]`, `map[string, T]`
- `?` suffix = optional (None/null)
- `any` = untyped msgpack value (escape hatch)

**Codegen outputs**:

**Python** (`styrene_wire_gen.py`):
```python
class StatusResponse(MessageBase):
    MSGTYPE = 0x11
    
    def __init__(self):
        self.uptime: int = 0
        self.ip: str = ""
        self.services: list[str] = []
        # ... optional fields default to None
        self.hostname: str | None = None
    
    def pack(self) -> bytes:
        d = {"uptime": self.uptime, "ip": self.ip, ...}
        # Only include optional fields if set
        if self.hostname is not None:
            d["hostname"] = self.hostname
        return msgpack.packb(d, use_bin_type=True)
    
    def unpack(self, raw: bytes):
        d = msgpack.unpackb(raw, raw=False)
        self.uptime = d.get("uptime", 0)
        self.ip = d.get("ip", "")
        # ...
```

**Rust** (`styrene_wire_gen.rs`):
```rust
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StatusResponse {
    pub uptime: i64,
    pub ip: String,
    pub services: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub hostname: Option<String>,
    // ...
}

impl MessageBase for StatusResponse {
    const MSGTYPE: u16 = 0x11;
    fn pack(&self) -> Vec<u8> { rmp_serde::to_vec(self).unwrap() }
    fn unpack(raw: &[u8]) -> Self { rmp_serde::from_slice(raw).unwrap() }
}
```

**Codegen script**: `tools/wire_codegen.py` — reads `styrene-wire.toml`, emits both Python and Rust. Run as `just wire-gen`. CI verifies generated files match schema (no stale codegen).

## Decisions

### Decision: Schema lives in styrene-rs under wire/ — not styrened or a standalone repo

**Status:** decided
**Rationale:** styrene-rs already implements the wire protocol (styrene-mesh crate). Collocating schema with implementation means the staleness CI check lives where generated Rust code lives. styrened is a consumer of the generated Python output, not the schema owner. A standalone styrene-wire repo adds cross-repo dependency management overhead with no current benefit — extractable later if a third independent consumer appears.

### Decision: Codegen is a standalone Python tool (tools/wire_codegen.py) invoked via just wire-gen — not build.rs

**Status:** decided
**Rationale:** build.rs would regenerate Python output on every cargo build, coupling the Rust build to a Python runtime and firing at the wrong trigger (Python lives in styrened, a separate repo). The codegen runs on developer demand and as a CI staleness check only. styrened pulls the committed generated file and has its own CI staleness guard. Both repos carry the schema version in the generated file header so drift is detectable.

### Decision: Schema expresses request/response pairing and correlation mode — not retry/timeout policy

**Status:** decided
**Rationale:** response_to = "StatusRequest" and correlation = "correlated"|"broadcast"|"fire-and-forget" are first-class fields. They cost nothing to add to the TOML schema and carry information that consumers need for send/receive pattern generation and documentation. Retry policy, timeout values, and ordering guarantees stay in the implementation — the IDL is a schema, not a service mesh config. This gives codegen enough information to generate typed send/await helpers on the Rust side and dispatch tables on the Python side.

## Open Questions

*No open questions.*
