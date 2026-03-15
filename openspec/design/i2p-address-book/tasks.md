# I2P Address Book — Hub-signed eepsite directory — Design Tasks

## 1. Open Questions

- [ ] 1.1 Should the Hub maintain a signed eepsite address book (I2P jump-service equivalent) that operators can subscribe to, enabling I2P browsability without prior knowledge of addresses?
- [ ] 1.2 What is the submission and curation model — Hub-operator-curated only, open self-submit from any connected Styrene node, or trust-gated (submitter must be in operator's RBAC roster)?
- [ ] 1.3 Should the daemon health-check address book entries (probe .b32.i2p via I2P proxy) before surfacing them in the Pages tab, and how often?
