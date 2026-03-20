---
id: styrene-rs-s3-bytestream-trait
title: "S3: ByteStream trait — dedup interface layer"
status: implemented
parent: styrene-rs-architecture
open_questions: []
---

# S3: ByteStream trait — dedup interface layer

## Overview

TCP client, TCP server, and UDP each reimplement the full read→HDLC→deserialize→channel pipeline (~200 LOC each, mostly duplicated). Extract ByteStream trait so a single generic run_framed_interface&lt;S: ByteStream&gt;() handles HDLC encode/decode for all transports. Platform-specific code shrinks to constructing the stream. Prerequisite for Serial/KISS interface (1.2) and WASM transport.

## Open Questions

*No open questions.*
