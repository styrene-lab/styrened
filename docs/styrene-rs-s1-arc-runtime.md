---
id: styrene-rs-s1-arc-runtime
title: "S1: Rc→Arc, multi-thread tokio runtime"
status: implemented
parent: styrene-rs-architecture
open_questions: []
---

# S1: Rc→Arc, multi-thread tokio runtime

## Overview

Replace Rc&lt;RpcDaemon&gt; with Arc&lt;RpcDaemon&gt;, remove LocalSet, switch tokio::main to multi_thread flavor. Mechanical change — all 40+ Mutex fields are already Send+Sync. The Rc in test_bridge.rs (Rc&lt;dyn Fn&gt;) needs Arc&lt;dyn Fn + Send + Sync&gt;. Unblocks all concurrent service work and is required before any other structural change.

## Open Questions

*No open questions.*
