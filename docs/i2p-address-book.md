---
id: i2p-address-book
title: I2P Address Book — Hub-signed eepsite directory
status: exploring
parent: i2p-pages-strategy
dependencies: [i2p-integration]
related: [styrene-contacts-page]
open_questions:
  - Should the Hub maintain a signed eepsite address book (I2P jump-service equivalent) that operators can subscribe to, enabling I2P browsability without prior knowledge of addresses?
  - "What is the submission and curation model — Hub-operator-curated only, open self-submit from any connected Styrene node, or trust-gated (submitter must be in operator's RBAC roster)?"
  - Should the daemon health-check address book entries (probe .b32.i2p via I2P proxy) before surfacing them in the Pages tab, and how often?
issue_type: feature
priority: 3
---

# I2P Address Book — Hub-signed eepsite directory

## Overview

> Parent: [I2P Content Strategy — Transport vs. Rendering](i2p-pages-strategy.md)
> Spawned from: "Should the Hub maintain a signed eepsite address book (I2P jump-service equivalent) that operators can subscribe to, enabling I2P browsability without prior knowledge of addresses?"

*To be explored.*

## Research

### Problem statement

I2P has no passive discovery mechanism analogous to Reticulum announces. To browse an eepsite you must know its .b32.i2p address ahead of time. This makes the Pages tab useless for I2P content that hasn't been manually introduced to the operator.

NomadNet pages are auto-populated because nodes announce over the mesh. I2P needs an equivalent — a curated, trusted list of eepsites that operators can pull from without needing to manually collect addresses from forums, pastebins, or word-of-mouth.

The Styrene Hub is the natural distribution point: operators already trust the Hub for announce propagation and fleet management. A Hub-maintained address book can be fetched over the authenticated DirectLink channel, giving it the same trust properties as other Hub-distributed data.

### Design sketch

The Hub serves a signed address book document over its DirectLink /meta or a new /i2p-directory endpoint. Each entry contains:
- display_name: human-readable name
- b32_address: the .b32.i2p address
- description: short blurb shown in the Pages tab
- categories: tags (e.g. "community", "news", "tools")
- added_by: Styrene identity hash of the operator who submitted it (optional, for web-of-trust extension later)
- added_at: timestamp

The document is signed by the Hub's RNS identity — operators can verify the signature against the Hub's known identity hash. Entries submitted by Styrene nodes that the operator already trusts (via RBAC roster) could be highlighted.

Distribution: fetched periodically by the daemon (e.g. daily, or on Pages tab activation). Stored locally in a lightweight DB table or JSON file. Merged with locally-known addresses from /meta discovery. Presented in the Pages tab under an "I2P" section alongside NomadNet nodes.

Trust model: Hub signature gives provenance ("the Hub vouches this address existed"), not content endorsement. Operators can disable address book sync entirely in config. Future: operators can run their own address book hub and configure the daemon to trust it.

### Open questions

- Submission flow: how does a site get listed? Self-submit via Hub web UI? Operator-curated only? Open to any Styrene node with a hub connection?
- Staleness: .b32.i2p addresses for Styrene nodes are derived from their I2P keypair and are stable. For non-Styrene eepsites (static .b32 or vanity .i2p), addresses can go stale if the site rotates its keypair. Address book needs a last-seen or verified-at field, and the daemon should health-check entries before surfacing them in the Pages tab.
- Relationship to Styrene identity: Styrene nodes already expose their b32_address via /meta — these entries should be auto-populated from DirectLink discovery without needing the Hub address book at all. The address book is for non-Styrene eepsites and for nodes not yet reachable over the mesh.
- Offline/airgap: operators without a Hub connection can import address book files manually (signed JSON). Useful for fleet deployments where Hub connectivity is intermittent.

## Open Questions

- Should the Hub maintain a signed eepsite address book (I2P jump-service equivalent) that operators can subscribe to, enabling I2P browsability without prior knowledge of addresses?
- What is the submission and curation model — Hub-operator-curated only, open self-submit from any connected Styrene node, or trust-gated (submitter must be in operator's RBAC roster)?
- Should the daemon health-check address book entries (probe .b32.i2p via I2P proxy) before surfacing them in the Pages tab, and how often?
