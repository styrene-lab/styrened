---
id: styrene-rs-ifac-fix
title: IFAC multi-hop bug fix — authenticated interface forwarding
status: implemented
parent: styrene-rs-architecture
open_questions: []
---

# IFAC multi-hop bug fix — authenticated interface forwarding

## Overview

Authenticated interfaces (IFAC) reject forwarded packets because HMAC validation doesn't account for hop-modified headers. Single-hop works; multi-hop — the actual deployment topology — does not. Fix scope: ~100-200 lines in handler.rs / core.rs. Requires auditing how Python RNS strips/reattaches IFAC before forwarding. Blocks real multi-hop mesh deployment. Inherited from FreeTAKTeam/LXMF-rs upstream.

## Open Questions

*No open questions.*
