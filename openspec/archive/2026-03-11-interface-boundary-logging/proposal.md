# Interface Boundary Logging — Differentiated Error Telemetry Across Tech Stacks

## Intent

Styrene is absorbing multiple independent networking stacks (RNS, LXMF, Yggdrasil, I2P, WireGuard, launchd/systemd, NomadNet page protocol) each with its own error taxonomy, log format, and thread model. When something breaks it's currently hard to tell which layer failed — an RNS path-not-found looks similar to an LXMF delivery timeout which looks similar to a WireGuard handshake failure at the log level we surface.

Goal: a structured "up-flow" logging layer that tags errors with their interface boundary of origin, normalises severity across stacks, and gives the operator (and doctor) enough signal to diagnose cross-stack failures without grepping through interleaved third-party log lines.

Motivating example: the RNS ratchet persist race (d246a39 / b405828) required reading CPython threading internals to determine it was benign. With boundary logging that context would be encoded in the log record itself.
