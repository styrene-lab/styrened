"""Kubernetes manifest generator from topology specs.

Deploys each node as a separate Helm release with replicaCount=1 and
fullnameOverride, because each node needs different RNS config, transport
settings, and network segment labels.

Generates:
  1. Per-node Helm values overrides
  2. NetworkPolicy for segment isolation
  3. Hostname resolution via K8s headless service DNS
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from .rns_config import generate_rns_config
from .spec import InterfaceType, MeshTopology, NodeRole

logger = logging.getLogger(__name__)


def _k8s_safe_name(name: str) -> str:
    """Convert a node name to a K8s-safe DNS label (lowercase, hyphens only)."""
    return name.lower().replace("_", "-")


def _service_dns(fullname: str, namespace: str) -> str:
    """Build K8s headless service DNS for a StatefulSet pod-0.

    For a StatefulSet with serviceName=fullname, the pod DNS is:
        {fullname}-0.{fullname}.{namespace}.svc.cluster.local
    """
    return f"{fullname}-0.{fullname}.{namespace}.svc.cluster.local"


def generate_node_values(
    topology: MeshTopology,
    node_name: str,
    namespace: str,
    relay_port: int = 9000,
) -> dict[str, Any]:
    """Generate Helm values override for a single node.

    Args:
        topology: The topology spec.
        node_name: Name of the node to generate values for.
        namespace: K8s namespace for DNS resolution.
        relay_port: IPC relay port (default 9000).

    Returns:
        Dict of Helm values suitable for --values file.
    """
    node = topology.get_node(node_name)
    fullname = _k8s_safe_name(node_name)

    # Transform interfaces: replace Docker hostnames with K8s DNS
    rns_interfaces: list[dict[str, Any]] = []
    for iface in node.interfaces:
        if iface.type == InterfaceType.TCP_SERVER:
            rns_interfaces.append({
                "type": "TCPServerInterface",
                "enabled": True,
                "listen_ip": "0.0.0.0",
                "listen_port": iface.listen_port,
            })
        elif iface.type == InterfaceType.TCP_CLIENT:
            # Transform Docker hostname to K8s headless service DNS
            target_fullname = _k8s_safe_name(iface.target_host)
            target_dns = _service_dns(target_fullname, namespace)
            rns_interfaces.append({
                "type": "TCPClientInterface",
                "enabled": True,
                "target_host": target_dns,
                "target_port": iface.target_port,
            })

    # Determine mode from role
    mode_map = {
        NodeRole.HUB: "hub",
        NodeRole.TRANSPORT: "standalone",
        NodeRole.EDGE: "peer",
    }

    values: dict[str, Any] = {
        "replicaCount": 1,
        "fullnameOverride": fullname,
        "styrene": {
            "reticulum": {
                "mode": mode_map.get(node.role, "standalone"),
                "transport_enabled": node.enable_transport,
                "announce_interval": 30,
            },
            "rpc": {"enabled": True},
            "discovery": {"announce_interval": 30},
            "chat": {"auto_reply_enabled": False},
        },
        "rns": {
            "enable_transport": node.enable_transport,
            "share_instance": topology.share_instance,
            "interfaces": rns_interfaces,
        },
        "ipcRelay": {
            "enabled": True,
            "port": relay_port,
        },
    }

    return values


def generate_network_policies(
    topology: MeshTopology,
    namespace: str,
) -> list[dict[str, Any]]:
    """Generate NetworkPolicy manifests for segment isolation.

    Creates:
      1. Default-deny policy for all topology pods
      2. Per-segment allow policy: pods in the same segment can communicate
      3. DNS egress always allowed

    Args:
        topology: The topology spec.
        namespace: K8s namespace.

    Returns:
        List of NetworkPolicy manifest dicts.
    """
    topology_label = f"styrene.io/topology"
    policies: list[dict[str, Any]] = []

    # Default-deny for all topology pods
    policies.append({
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{topology.name}-default-deny",
            "namespace": namespace,
        },
        "spec": {
            "podSelector": {
                "matchLabels": {topology_label: topology.name},
            },
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [],
            "egress": [
                # Always allow DNS
                {
                    "to": [{"namespaceSelector": {}}],
                    "ports": [{"protocol": "TCP", "port": 53}, {"protocol": "UDP", "port": 53}],
                },
            ],
        },
    })

    # Per-segment allow policy
    for net in topology.networks:
        segment_label = f"styrene.io/net-{net.name}"
        policies.append({
            "apiVersion": "networking.k8s.io/v1",
            "kind": "NetworkPolicy",
            "metadata": {
                "name": f"{topology.name}-allow-{net.name}",
                "namespace": namespace,
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {segment_label: "true"},
                },
                "policyTypes": ["Ingress", "Egress"],
                "ingress": [
                    {
                        "from": [{"podSelector": {"matchLabels": {segment_label: "true"}}}],
                    },
                ],
                "egress": [
                    {
                        "to": [{"podSelector": {"matchLabels": {segment_label: "true"}}}],
                    },
                    # DNS
                    {
                        "to": [{"namespaceSelector": {}}],
                        "ports": [{"protocol": "TCP", "port": 53}, {"protocol": "UDP", "port": 53}],
                    },
                ],
            },
        })

    return policies


def get_pod_labels(topology: MeshTopology, node_name: str) -> dict[str, str]:
    """Get the labels to apply to a node's pod for NetworkPolicy matching.

    Args:
        topology: The topology spec.
        node_name: Name of the node.

    Returns:
        Dict of labels.
    """
    node = topology.get_node(node_name)
    labels = {
        f"styrene.io/topology": topology.name,
        f"styrene.io/role": node.role.value,
    }
    for net_name in node.networks:
        labels[f"styrene.io/net-{net_name}"] = "true"
    return labels


def deploy_topology(
    topology: MeshTopology,
    namespace: str,
    helm_dir: Path,
    kubeconfig: str | None = None,
    image_values: list[str] | None = None,
    relay_port: int = 9000,
) -> list[str]:
    """Deploy a full topology to K8s as separate Helm releases.

    Args:
        topology: The topology spec.
        namespace: K8s namespace to deploy into.
        helm_dir: Path to the Helm chart directory.
        kubeconfig: Path to kubeconfig (optional).
        image_values: Extra --set values for image config (e.g., from _get_image_values).
        relay_port: IPC relay port.

    Returns:
        List of pod names (one per node).

    Raises:
        RuntimeError: If any Helm install fails.
    """
    errors = topology.validate()
    if errors:
        raise ValueError(f"Invalid topology: {errors}")

    pod_names: list[str] = []

    # Apply NetworkPolicies first
    policies = generate_network_policies(topology, namespace)
    for policy in policies:
        _kubectl_apply(policy, namespace, kubeconfig)

    # Deploy each node as a separate Helm release
    for node in topology.nodes:
        fullname = _k8s_safe_name(node.name)
        release_name = f"{topology.name}-{fullname}"

        values = generate_node_values(topology, node.name, namespace, relay_port)

        # Write values to temp file
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False, prefix=f"helm-{fullname}-"
        ) as f:
            import yaml
            yaml.dump(values, f, default_flow_style=False)
            values_file = f.name

        cmd = [
            "helm", "install",
            release_name,
            str(helm_dir),
            "-n", namespace,
            "--create-namespace",
            "-f", values_file,
        ]

        if kubeconfig:
            cmd.extend(["--kubeconfig", kubeconfig])

        # Add image values
        if image_values:
            cmd.extend(image_values)

        # Add pod labels for NetworkPolicy
        labels = get_pod_labels(topology, node.name)
        for key, value in labels.items():
            cmd.extend(["--set", f"podAnnotations.{key}={value}"])

        logger.info("Deploying node %s as Helm release %s", node.name, release_name)
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"Helm install for {node.name} failed: {result.stderr}\n"
                f"Stdout: {result.stdout}"
            )

        # Pod name follows StatefulSet naming: {fullname}-0
        pod_names.append(f"{fullname}-0")

        # Clean up temp file
        Path(values_file).unlink(missing_ok=True)

    return pod_names


def teardown_topology(
    topology: MeshTopology,
    namespace: str,
    kubeconfig: str | None = None,
) -> None:
    """Remove all Helm releases and NetworkPolicies for a topology.

    Args:
        topology: The topology spec.
        namespace: K8s namespace.
        kubeconfig: Path to kubeconfig (optional).
    """
    for node in topology.nodes:
        fullname = _k8s_safe_name(node.name)
        release_name = f"{topology.name}-{fullname}"

        cmd = ["helm", "uninstall", release_name, "-n", namespace]
        if kubeconfig:
            cmd.extend(["--kubeconfig", kubeconfig])

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.warning("Failed to uninstall %s: %s", release_name, result.stderr)

    # Clean up NetworkPolicies
    policy_names = [f"{topology.name}-default-deny"]
    for net in topology.networks:
        policy_names.append(f"{topology.name}-allow-{net.name}")

    for name in policy_names:
        cmd = ["kubectl", "delete", "networkpolicy", name, "-n", namespace, "--ignore-not-found"]
        if kubeconfig:
            cmd.extend(["--kubeconfig", kubeconfig])
        subprocess.run(cmd, capture_output=True, text=True)


def _kubectl_apply(manifest: dict[str, Any], namespace: str, kubeconfig: str | None = None) -> None:
    """Apply a K8s manifest via kubectl."""
    cmd = ["kubectl", "apply", "-f", "-", "-n", namespace]
    if kubeconfig:
        cmd.extend(["--kubeconfig", kubeconfig])

    result = subprocess.run(
        cmd,
        input=json.dumps(manifest),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("kubectl apply failed: %s", result.stderr)
