---
id: styrene-wire-schema-idl
title: Styrene Wire Schema IDL — Format and Codegen
status: exploring
parent: rns-rpc-invocation-layer
tags: [architecture, wire-protocol, idl, codegen, msgpack, rust, python]
open_questions:
  - Should the schema live in styrened, styrene-rs, or a new shared repo (e.g. styrene-wire)?
  - Should the codegen script be a standalone Python tool, or a Cargo build.rs for the Rust side?
  - "Does the schema need to express request/response pairing (StatusRequest → StatusResponse) and transport-level semantics (fire-and-forget vs correlated), or just field definitions?"
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

## Open Questions

- Should the schema live in styrened, styrene-rs, or a new shared repo (e.g. styrene-wire)?
- Should the codegen script be a standalone Python tool, or a Cargo build.rs for the Rust side?
- Does the schema need to express request/response pairing (StatusRequest → StatusResponse) and transport-level semantics (fire-and-forget vs correlated), or just field definitions?
