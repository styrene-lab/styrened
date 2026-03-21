# YggdrasilService — styrened-managed Yggdrasil daemon

## Intent

Explore what it means for styrened to own and manage the Yggdrasil daemon lifecycle — similar to how MeshVPNService manages WireGuard interfaces and how batman-mesh.nix manages BATMAN-ADV in styrene-edge. Covers: binary packaging, config generation, admin socket queries, dynamic peer management, NixOS module, and OCI container story.

See [design doc](../../../docs/yggdrasil-service.md).
