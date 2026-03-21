---
id: remote-terminal-service
title: Remote Terminal Service
status: seed
parent: styrene-rs-daemon-port-execution-plan
tags: [daemon, fleet, rpc, defer]
open_questions:
  - What is the session lifecycle model — does the daemon own a PTY per session, or does it relay through an existing shell multiplexer?
  - What RBAC capabilities gate terminal access, and should there be a separate capability tier from exec (one-shot commands)?
  - How does terminal data flow over LXMF — chunked messages, or does it require a direct RNS link for low-latency bidirectional streaming?
issue_type: feature
priority: 3
---

# Remote Terminal Service

## Overview

Remote terminal session management — open interactive shell sessions on remote Styrene nodes over the mesh. Currently exists in the Python daemon as an unnamed terminal service wired through StyreneProtocol, consumed by the TUI's DeviceConsoleScreen and TerminalWidget. The Rust IPC contract already defines DaemonFleet::terminal_open/input/resize/close methods. This node covers the daemon-side session lifecycle, PTY management, and security model for the Rust port.

## Open Questions

- What is the session lifecycle model — does the daemon own a PTY per session, or does it relay through an existing shell multiplexer?
- What RBAC capabilities gate terminal access, and should there be a separate capability tier from exec (one-shot commands)?
- How does terminal data flow over LXMF — chunked messages, or does it require a direct RNS link for low-latency bidirectional streaming?
