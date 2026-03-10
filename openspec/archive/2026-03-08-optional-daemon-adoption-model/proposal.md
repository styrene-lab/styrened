# Optional Daemon Adoption Model — three-tier pattern

## Intent

Defines the universal three-tier pattern for optional system daemons (Yggdrasil, i2pd, and future additions): disabled (do without), adopt (detect and use an existing installation without touching it), and managed (styrened provisions a pre-built Nix package and owns the process). The principle: don't prescribe, but provide a happy path for those who want one.
