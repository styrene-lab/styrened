"""Built-in topology presets reproducing existing test topologies and adding new ones.

Each preset returns a fully-configured MeshTopology that can be deployed
via Docker Compose or Kubernetes backends.
"""

from __future__ import annotations

from .spec import (
    InterfaceType,
    MeshNode,
    MeshTopology,
    NetworkSegment,
    NodeRole,
    RNSInterface,
)


def two_node_direct() -> MeshTopology:
    """Two-node direct topology matching existing docker-compose.yaml.

    Topology:
        node-a (hub, TCPServer:4242) <--mesh--> node-b (edge, TCPClient)

    Relay ports: node-a=9001, node-b=9002
    """
    node_a = MeshNode(
        name="node-a",
        role=NodeRole.HUB,
        networks=["mesh"],
        interfaces=[
            RNSInterface(
                name="TCP Server",
                type=InterfaceType.TCP_SERVER,
                listen_port=4242,
            ),
        ],
        relay_port=9001,
    )

    node_b = MeshNode(
        name="node-b",
        role=NodeRole.EDGE,
        networks=["mesh"],
        interfaces=[
            RNSInterface(
                name="TCP Client to Node A",
                type=InterfaceType.TCP_CLIENT,
                target_host="node-a",
                target_port=4242,
            ),
        ],
        relay_port=9002,
    )

    return MeshTopology(
        name="two-node-direct",
        nodes=[node_a, node_b],
        networks=[
            NetworkSegment(name="mesh", members=frozenset({"node-a", "node-b"})),
        ],
        description="Two-node direct mesh: hub + peer on single network",
    )


def three_node_multihop() -> MeshTopology:
    """Three-node multihop topology matching existing docker-compose.multihop.yaml.

    Topology:
        alpha network: node-a-edge <-> node-b-transport
        beta  network: node-b-transport <-> node-c-edge

    Node A and C have no direct network — messages route through B.

    Relay ports: node-a-edge=9011, node-b-transport=9012, node-c-edge=9013
    """
    node_b = MeshNode(
        name="node-b-transport",
        role=NodeRole.TRANSPORT,
        networks=["alpha", "beta"],
        interfaces=[
            RNSInterface(
                name="TCP Server Alpha",
                type=InterfaceType.TCP_SERVER,
                listen_port=4242,
                ingress_control=False,
            ),
            RNSInterface(
                name="TCP Server Beta",
                type=InterfaceType.TCP_SERVER,
                listen_port=4243,
                ingress_control=False,
            ),
        ],
        relay_port=9012,
    )

    node_a = MeshNode(
        name="node-a-edge",
        role=NodeRole.EDGE,
        networks=["alpha"],
        interfaces=[
            RNSInterface(
                name="TCP Client to Relay",
                type=InterfaceType.TCP_CLIENT,
                target_host="node-b-transport",
                target_port=4242,
                ingress_control=False,
            ),
        ],
        relay_port=9011,
    )

    node_c = MeshNode(
        name="node-c-edge",
        role=NodeRole.EDGE,
        networks=["beta"],
        interfaces=[
            RNSInterface(
                name="TCP Client to Relay",
                type=InterfaceType.TCP_CLIENT,
                target_host="node-b-transport",
                target_port=4243,
                ingress_control=False,
            ),
        ],
        relay_port=9013,
    )

    return MeshTopology(
        name="three-node-multihop",
        nodes=[node_b, node_a, node_c],
        networks=[
            NetworkSegment(
                name="alpha",
                members=frozenset({"node-a-edge", "node-b-transport"}),
            ),
            NetworkSegment(
                name="beta",
                members=frozenset({"node-b-transport", "node-c-edge"}),
            ),
        ],
        description="Three-node multihop: A <-> B(transport) <-> C across two networks",
    )


def star_hub(peer_count: int = 3) -> MeshTopology:
    """Star topology with 1 hub + N peers on a single network.

    The hub runs a TCPServerInterface; each peer connects via TCPClient.

    Args:
        peer_count: Number of peer nodes (default 3).

    Returns:
        MeshTopology with 1 + peer_count nodes.
    """
    hub = MeshNode(
        name="hub",
        role=NodeRole.HUB,
        networks=["star"],
        interfaces=[
            RNSInterface(
                name="TCP Server",
                type=InterfaceType.TCP_SERVER,
                listen_port=4242,
                ingress_control=False,
            ),
        ],
        relay_port=9100,
    )

    peers: list[MeshNode] = []
    all_members = {"hub"}

    for i in range(peer_count):
        name = f"peer-{i}"
        all_members.add(name)
        peers.append(
            MeshNode(
                name=name,
                role=NodeRole.EDGE,
                networks=["star"],
                interfaces=[
                    RNSInterface(
                        name="TCP Client to Hub",
                        type=InterfaceType.TCP_CLIENT,
                        target_host="hub",
                        target_port=4242,
                        ingress_control=False,
                    ),
                ],
                relay_port=9101 + i,
            )
        )

    return MeshTopology(
        name=f"star-hub-{peer_count}",
        nodes=[hub, *peers],
        networks=[
            NetworkSegment(name="star", members=frozenset(all_members)),
        ],
        description=f"Star topology: 1 hub + {peer_count} peers on single network",
    )


def linear_chain(node_count: int = 5) -> MeshTopology:
    """Linear chain topology: A-B-C-D-E with per-segment networks.

    Each adjacent pair shares a network segment. Interior nodes are transports
    that bridge their segments. Edge nodes (first and last) are edges.

    Args:
        node_count: Number of nodes in the chain (minimum 2).

    Returns:
        MeshTopology with node_count nodes and node_count-1 network segments.
    """
    if node_count < 2:
        raise ValueError("linear_chain requires at least 2 nodes")

    # Name nodes alphabetically: chain-a, chain-b, chain-c, ...
    node_names = [f"chain-{chr(ord('a') + i)}" for i in range(node_count)]

    nodes: list[MeshNode] = []
    networks: list[NetworkSegment] = []

    # Create network segments for each adjacent pair
    for i in range(node_count - 1):
        seg_name = f"seg-{i}"
        networks.append(
            NetworkSegment(
                name=seg_name,
                members=frozenset({node_names[i], node_names[i + 1]}),
            )
        )

    # Create nodes
    for i, name in enumerate(node_names):
        is_first = i == 0
        is_last = i == node_count - 1
        is_interior = not is_first and not is_last

        # Determine role
        if is_interior:
            role = NodeRole.TRANSPORT
        elif is_first:
            role = NodeRole.HUB  # First node serves as hub
        else:
            role = NodeRole.EDGE

        # Determine networks
        node_networks: list[str] = []
        if not is_first:
            node_networks.append(f"seg-{i - 1}")
        if not is_last:
            node_networks.append(f"seg-{i}")

        # Build interfaces
        interfaces: list[RNSInterface] = []

        # Server interfaces for downstream segments (segments where this node is the left member)
        if not is_last:
            seg_name = f"seg-{i}"
            # Use sequential ports starting at 4242
            server_port = 4242 + (0 if is_first else node_networks.index(f"seg-{i}"))
            interfaces.append(
                RNSInterface(
                    name=f"TCP Server {seg_name}",
                    type=InterfaceType.TCP_SERVER,
                    listen_port=server_port,
                    ingress_control=False,
                )
            )

        # Client interfaces for upstream segments (connect to previous node's server)
        if not is_first:
            prev_name = node_names[i - 1]
            # The previous node's server port for this segment
            prev_node_networks = []
            if i - 1 > 0:
                prev_node_networks.append(f"seg-{i - 2}")
            prev_node_networks.append(f"seg-{i - 1}")
            target_port = 4242 + prev_node_networks.index(f"seg-{i - 1}")
            interfaces.append(
                RNSInterface(
                    name=f"TCP Client to {prev_name}",
                    type=InterfaceType.TCP_CLIENT,
                    target_host=prev_name,
                    target_port=target_port,
                    ingress_control=False,
                )
            )

        nodes.append(
            MeshNode(
                name=name,
                role=role,
                networks=node_networks,
                interfaces=interfaces,
                relay_port=9200 + i,
            )
        )

    return MeshTopology(
        name=f"linear-chain-{node_count}",
        nodes=nodes,
        networks=networks,
        description=f"Linear chain: {node_count} nodes with per-segment networks",
    )
