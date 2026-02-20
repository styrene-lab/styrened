"""Docker Compose YAML generator from topology specs.

Produces docker-compose.yaml files with per-node services, networks,
and RNS configs that match the topology definition.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .port_manager import PortManager
from .rns_config import generate_all_configs
from .spec import InterfaceType, MeshTopology, NodeRole


def generate_compose(
    topology: MeshTopology,
    port_manager: PortManager | None = None,
    build_context: str = "../..",
    dockerfile: str = "tests/mesh/Dockerfile",
    image: str = "styrened-mesh-dev:latest",
) -> dict[str, Any]:
    """Generate docker-compose services dict from a topology spec.

    Args:
        topology: The topology specification.
        port_manager: Port allocator for host relay ports. If None, uses
            the relay_port values from each node directly.
        build_context: Docker build context path (relative to compose file).
        dockerfile: Dockerfile path (relative to build context).
        image: Image name for built containers.

    Returns:
        Complete docker-compose dict ready for yaml.dump().
    """
    services: dict[str, Any] = {}
    networks: dict[str, Any] = {}

    # Determine which nodes are TCP servers (others depend_on them)
    server_nodes = set()
    for node in topology.nodes:
        for iface in node.interfaces:
            if iface.type == InterfaceType.TCP_SERVER:
                server_nodes.add(node.name)
                break

    for node in topology.nodes:
        # Determine host relay port
        if port_manager:
            host_port = port_manager.allocate()
        else:
            host_port = node.relay_port

        container_relay_port = node.relay_port

        service: dict[str, Any] = {
            "build": {
                "context": build_context,
                "dockerfile": dockerfile,
            },
            "image": image,
            "container_name": f"styrene-{topology.name}-{node.name}",
            "hostname": node.name,
            "entrypoint": ["bash", "-c"],
            "command": [
                f"styrened daemon &\n"
                f"sleep 3\n"
                f"python3 /relay/tcp_relay.py /run/styrened/control.sock {container_relay_port}"
            ],
            "volumes": [
                f"./rns/{node.name}.conf:/root/.reticulum/config:ro",
                "./tcp_relay.py:/relay/tcp_relay.py:ro",
            ],
            "environment": [
                "STYRENED_SOCKET=/run/styrened/control.sock",
                "STYRENE_CONFIG_DIR=/config",
                "RNS_LOGLEVEL=4",
                "PYTHONUNBUFFERED=1",
            ],
            "ports": [f"{host_port}:{container_relay_port}"],
            "networks": list(node.networks),
        }

        # Edge nodes depend on their TCP client targets (which should be servers)
        if node.role == NodeRole.EDGE:
            deps = []
            for iface in node.interfaces:
                if iface.type == InterfaceType.TCP_CLIENT and iface.target_host:
                    if iface.target_host in server_nodes:
                        deps.append(iface.target_host)
            if deps:
                service["depends_on"] = deps

        services[node.name] = service

    # Create network definitions
    for net in topology.networks:
        networks[net.name] = {"driver": "bridge"}

    compose: dict[str, Any] = {
        "services": services,
        "networks": networks,
    }

    return compose


def write_compose(
    topology: MeshTopology,
    output_dir: Path,
    port_manager: PortManager | None = None,
    build_context: str = "../..",
    dockerfile: str = "tests/mesh/Dockerfile",
    image: str = "styrened-mesh-dev:latest",
) -> Path:
    """Write RNS configs and docker-compose.yaml to a directory.

    Args:
        topology: The topology specification.
        output_dir: Directory to write files to (created if needed).
        port_manager: Port allocator for host relay ports.
        build_context: Docker build context path.
        dockerfile: Dockerfile path.
        image: Image name.

    Returns:
        Path to the generated docker-compose.yaml.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Write RNS configs
    rns_dir = output_dir / "rns"
    rns_dir.mkdir(exist_ok=True)

    configs = generate_all_configs(topology)
    for node_name, config_text in configs.items():
        (rns_dir / f"{node_name}.conf").write_text(config_text)

    # Generate and write compose file
    compose = generate_compose(
        topology,
        port_manager=port_manager,
        build_context=build_context,
        dockerfile=dockerfile,
        image=image,
    )

    compose_path = output_dir / "docker-compose.yaml"
    compose_path.write_text(
        yaml.dump(compose, default_flow_style=False, sort_keys=False)
    )

    return compose_path
