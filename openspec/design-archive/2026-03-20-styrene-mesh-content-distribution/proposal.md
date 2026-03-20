# Styrene Mesh Content Distribution — P2P file sharing over RNS/Yggdrasil

## Intent

BitTorrent-inspired content distribution over the Styrene mesh. Builds on RNS Resources (chunked file transfer) and Styrene identity (authenticated content). A signed chunk manifest (StyreneResourceDescriptor) replaces .torrent files; multi-peer swarming requests different chunks from different peers; discovery via LXMF RESOURCE_AVAILABLE announces or NomadNet pages. Over Yggdrasil overlay: fully encrypted, authenticated participants, no cleartext metadata. Primary use cases: fleet firmware updates, emergency data packs, NomadNet page mirroring, encrypted document distribution. Reference: nyaa (provider/source trait pattern for TUI layer).

See [design doc](../../../docs/styrene-mesh-content-distribution.md).
