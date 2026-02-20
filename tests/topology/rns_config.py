"""RNS INI config generator from topology specs.

Produces the INI-format config file that Reticulum reads, with correct
interface types, ports, and transport settings derived from the topology.
"""

from __future__ import annotations

from .spec import InterfaceType, MeshNode, MeshTopology


def generate_rns_config(topology: MeshTopology, node: MeshNode) -> str:
    """Generate RNS INI config for a single node.

    Args:
        topology: The full topology spec (for global settings).
        node: The node to generate config for.

    Returns:
        INI-format config string ready to write to disk.
    """
    lines: list[str] = []

    # [reticulum] section
    lines.append("[reticulum]")
    lines.append(f"  enable_transport = {node.enable_transport}")
    lines.append(f"  share_instance = {topology.share_instance}")
    lines.append("")

    # [logging] section
    lines.append("[logging]")
    lines.append(f"  loglevel = {topology.loglevel}")
    lines.append("")

    # [interfaces] section
    lines.append("[interfaces]")

    for iface in node.interfaces:
        lines.append(f"  [[{iface.name}]]")
        lines.append(f"    type = {iface.type.value}")
        lines.append("    enabled = True")

        if iface.type == InterfaceType.TCP_SERVER:
            lines.append("    listen_ip = 0.0.0.0")
            lines.append(f"    listen_port = {iface.listen_port}")
        elif iface.type == InterfaceType.TCP_CLIENT:
            lines.append(f"    target_host = {iface.target_host}")
            lines.append(f"    target_port = {iface.target_port}")

        if iface.ingress_control is not None:
            lines.append(f"    ingress_control = {iface.ingress_control}")

        lines.append("")

    return "\n".join(lines)


def generate_all_configs(topology: MeshTopology) -> dict[str, str]:
    """Generate RNS configs for all nodes in a topology.

    Args:
        topology: The topology spec.

    Returns:
        Dict mapping node name to config string.
    """
    return {node.name: generate_rns_config(topology, node) for node in topology.nodes}
