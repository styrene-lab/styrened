"""Topology data model for programmatic mesh test definitions.

Dataclasses defining the topology spec that both Docker Compose and
Kubernetes backends consume to produce deployable artifacts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class NodeRole(Enum):
    """Role a node plays in the mesh topology."""

    EDGE = "edge"
    TRANSPORT = "transport"
    HUB = "hub"


class InterfaceType(Enum):
    """RNS interface types supported by the topology generator."""

    TCP_SERVER = "TCPServerInterface"
    TCP_CLIENT = "TCPClientInterface"


@dataclass(frozen=True)
class RNSInterface:
    """A single RNS interface on a mesh node.

    For TCP_SERVER: listen_port is required.
    For TCP_CLIENT: target_host and target_port are required.
    """

    name: str
    type: InterfaceType
    listen_port: int | None = None
    target_host: str | None = None
    target_port: int | None = None
    ingress_control: bool | None = None

    def __post_init__(self) -> None:
        if self.type == InterfaceType.TCP_SERVER and self.listen_port is None:
            raise ValueError(f"TCP_SERVER interface '{self.name}' requires listen_port")
        if self.type == InterfaceType.TCP_CLIENT:
            if self.target_host is None or self.target_port is None:
                raise ValueError(
                    f"TCP_CLIENT interface '{self.name}' requires target_host and target_port"
                )


@dataclass(frozen=True)
class NetworkSegment:
    """A named network segment connecting a subset of nodes.

    Maps to a Docker bridge network or K8s NetworkPolicy group.
    """

    name: str
    members: frozenset[str]

    def __post_init__(self) -> None:
        if len(self.members) < 2:
            raise ValueError(
                f"Network segment '{self.name}' must have at least 2 members, "
                f"got {len(self.members)}"
            )


@dataclass
class MeshNode:
    """A single node in the mesh topology.

    Attributes:
        name: Unique node identifier (becomes hostname/pod name).
        role: Node role (edge, transport, hub).
        networks: Network segments this node belongs to.
        interfaces: RNS interfaces configured on this node.
        relay_port: TCP relay port for IPC access from test host.
        enable_transport: Whether RNS transport is enabled.
    """

    name: str
    role: NodeRole
    networks: list[str] = field(default_factory=list)
    interfaces: list[RNSInterface] = field(default_factory=list)
    relay_port: int = 9000
    enable_transport: bool = False

    def __post_init__(self) -> None:
        # Transport nodes must have transport enabled
        if self.role in (NodeRole.TRANSPORT, NodeRole.HUB):
            self.enable_transport = True


@dataclass
class MeshTopology:
    """Complete mesh topology specification.

    Attributes:
        name: Topology identifier (used in compose project names, helm releases).
        nodes: All nodes in the topology.
        networks: Network segments defining connectivity.
        description: Human-readable description.
        share_instance: RNS share_instance setting (False for isolated test nodes).
        loglevel: RNS log level (4 = verbose).
    """

    name: str
    nodes: list[MeshNode]
    networks: list[NetworkSegment]
    description: str = ""
    share_instance: bool = False
    loglevel: int = 4

    def validate(self) -> list[str]:
        """Validate topology consistency.

        Returns:
            List of validation error messages (empty if valid).
        """
        errors: list[str] = []
        node_names = {n.name for n in self.nodes}

        # Check for duplicate node names
        if len(node_names) != len(self.nodes):
            errors.append("Duplicate node names detected")

        # Validate network segment members exist
        for net in self.networks:
            for member in net.members:
                if member not in node_names:
                    errors.append(
                        f"Network '{net.name}' references unknown node '{member}'"
                    )

        # Validate node network references exist
        net_names = {n.name for n in self.networks}
        for node in self.nodes:
            for net_name in node.networks:
                if net_name not in net_names:
                    errors.append(
                        f"Node '{node.name}' references unknown network '{net_name}'"
                    )

        # Validate TCP client targets exist as node names
        for node in self.nodes:
            for iface in node.interfaces:
                if iface.type == InterfaceType.TCP_CLIENT and iface.target_host:
                    if iface.target_host not in node_names:
                        errors.append(
                            f"Node '{node.name}' interface '{iface.name}' targets "
                            f"unknown host '{iface.target_host}'"
                        )

        # Check relay port uniqueness
        relay_ports = [n.relay_port for n in self.nodes]
        if len(set(relay_ports)) != len(relay_ports):
            errors.append("Duplicate relay ports detected")

        return errors

    def get_node(self, name: str) -> MeshNode:
        """Get node by name.

        Raises:
            KeyError: If node not found.
        """
        for node in self.nodes:
            if node.name == name:
                return node
        raise KeyError(f"Node '{name}' not found in topology '{self.name}'")

    def get_networks_for_node(self, node_name: str) -> list[NetworkSegment]:
        """Get all network segments a node belongs to."""
        return [net for net in self.networks if node_name in net.members]
