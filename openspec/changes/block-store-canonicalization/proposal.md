# Block Store Canonicalization — rns_identity_hash as canonical block key

## Intent

Replace the current broken block system (LXMF dest hash used as block key, blocks lost on restart, three inconsistent stores) with a clean canonical architecture: peer_blocks SQLite table as the authoritative runtime store keyed on rns_identity_hash, in-memory RBAC seeded from it at startup, _handle_lxmf_message fixed to resolve source hash before RBAC check, MeshDevice.identity legacy alias removed, and IPC layer updated with a deprecation shim for the peer_hash parameter. Targets v0.16.0rc1.

## Scope

<!-- Define what is in scope and out of scope -->

## Success Criteria

<!-- How will we know this change is complete and correct? -->
