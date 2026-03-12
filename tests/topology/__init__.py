"""Topology abstraction for programmatic mesh test deployment.

Defines N-node mesh topologies and deploys them to either Docker Compose
(fast local path) or Kubernetes (scale/multi-host path).

Usage:
    from tests.topology import presets

    topo = presets.two_node_direct()
    # -> MeshTopology with 2 nodes, 1 network, matching existing compose tests

    topo = presets.star_hub(peer_count=5)
    # -> MeshTopology with 1 hub + 5 peers on a single network
"""
from __future__ import annotations


from .presets import (
    linear_chain,
    star_hub,
    three_node_multihop,
    two_node_direct,
)
from .spec import (
    InterfaceType,
    MeshNode,
    MeshTopology,
    NetworkSegment,
    NodeRole,
    RNSInterface,
)

__all__ = [
    # Data model
    "InterfaceType",
    "MeshNode",
    "MeshTopology",
    "NetworkSegment",
    "NodeRole",
    "RNSInterface",
    # Presets
    "linear_chain",
    "star_hub",
    "three_node_multihop",
    "two_node_direct",
]
