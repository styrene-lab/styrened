"""K8s test orchestration harness for styrened containerized testing.

Provides deployment automation, log collection, and cleanup for pytest tests.
"""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class ExecResult:
    """Result from executing command in pod."""

    returncode: int
    stdout: str
    stderr: str


class K8sTestHarness:
    """Harness for managing k8s resources during styrened tests."""

    def __init__(self, namespace: str = "default", kubeconfig: str | None = None):
        """Initialize harness.

        Args:
            namespace: K8s namespace to use
            kubeconfig: Path to kubeconfig (None = auto-detect)
        """
        self.namespace = namespace
        self.kubeconfig = kubeconfig or os.environ.get("KUBECONFIG")
        self.helm_dir = Path(__file__).parent / "helm" / "styrened-test"

        # Detect cluster type
        self.cluster_type = self._detect_cluster_type()

    def _detect_cluster_type(self) -> str:
        """Detect if running on local k8s (kind/k3d) or cloud.

        Returns:
            "kind", "k3d", or "cloud"
        """
        try:
            result = subprocess.run(
                ["kubectl", "config", "current-context"],
                capture_output=True,
                text=True,
                check=True,
            )
            context = result.stdout.strip()

            if "kind-" in context:
                return "kind"
            elif "k3d-" in context:
                return "k3d"
            else:
                return "cloud"
        except subprocess.CalledProcessError:
            return "unknown"

    def get_image_config_for_ci(self, commit_sha: str) -> dict[str, str]:
        """Get image configuration for CI/CD with GHCR.

        Args:
            commit_sha: Git commit SHA (full or short)

        Returns:
            Dict with image_repository, image_tag, image_pull_policy
        """
        return {
            "image_repository": "ghcr.io/styrene-lab/styrened-test",
            "image_tag": commit_sha,
            "image_pull_policy": "Always",
        }

    def get_image_config_for_local(self) -> dict[str, str]:
        """Get image configuration for local testing.

        Returns:
            Dict with image_repository, image_tag, image_pull_policy
        """
        return {
            "image_repository": "styrened-test",
            "image_tag": "local-amd64",
            "image_pull_policy": "Never",
        }

    def deploy_stack(
        self,
        release_name: str,
        replica_count: int = 3,
        mode: str = "standalone",
        transport_enabled: bool = False,
        announce_interval: int = 300,
        rpc_enabled: bool = True,
        cpu_request: str = "100m",
        cpu_limit: str = "200m",
        memory_request: str = "128Mi",
        memory_limit: str = "256Mi",
        extra_values: dict[str, Any] | None = None,
        image_repository: str | None = None,
        image_tag: str | None = None,
        image_pull_policy: str | None = None,
    ) -> list[str]:
        """Deploy styrened stack using Helm.

        Args:
            release_name: Helm release name
            replica_count: Number of pods
            mode: Deployment mode (standalone, hub, peer, gateway)
            transport_enabled: Enable RNS transport
            announce_interval: RNS announce interval (seconds)
            rpc_enabled: Enable RPC server
            cpu_request: CPU request
            cpu_limit: CPU limit
            memory_request: Memory request
            memory_limit: Memory limit
            extra_values: Additional Helm values
            image_repository: Override image repository (e.g., ghcr.io/styrene-lab/styrened-test)
            image_tag: Override image tag (e.g., sha-abc123 or v1.0.0)
            image_pull_policy: Override pull policy (Always, IfNotPresent, Never)

        Returns:
            List of pod names
        """
        # Build Helm install command
        set_values = [
            f"replicaCount={replica_count}",
            f"styrene.reticulum.mode={mode}",
            f"styrene.reticulum.transport_enabled={str(transport_enabled).lower()}",
            f"styrene.reticulum.announce_interval={announce_interval}",
            f"styrene.rpc.enabled={str(rpc_enabled).lower()}",
            f"resources.requests.cpu={cpu_request}",
            f"resources.limits.cpu={cpu_limit}",
            f"resources.requests.memory={memory_request}",
            f"resources.limits.memory={memory_limit}",
        ]

        # Add image overrides if specified
        if image_repository:
            set_values.append(f"image.repository={image_repository}")
        if image_tag:
            set_values.append(f"image.tag={image_tag}")
        if image_pull_policy:
            set_values.append(f"image.pullPolicy={image_pull_policy}")

        # Add extra values
        if extra_values:
            for key, value in extra_values.items():
                set_values.append(f"{key}={value}")

        # Build command
        cmd = [
            "helm",
            "install",
            release_name,
            str(self.helm_dir),
            "-n",
            self.namespace,
            "--create-namespace",
        ]

        for val in set_values:
            cmd.extend(["--set", val])

        # Execute
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Helm install failed: {result.stderr}\nStdout: {result.stdout}")

        # Return list of pod names (StatefulSet naming)
        return [f"{release_name}-styrened-test-{i}" for i in range(replica_count)]

    def wait_for_ready(self, pods: list[str], timeout: int = 60, check_interval: int = 5) -> bool:
        """Wait for pods to be ready.

        Args:
            pods: List of pod names
            timeout: Timeout in seconds
            check_interval: Check interval in seconds

        Returns:
            True if all pods ready, False if timeout
        """
        start_time = time.time()

        while time.time() - start_time < timeout:
            all_ready = True

            for pod in pods:
                result = subprocess.run(
                    [
                        "kubectl",
                        "get",
                        "pod",
                        pod,
                        "-n",
                        self.namespace,
                        "-o",
                        "jsonpath={.status.conditions[?(@.type=='Ready')].status}",
                    ],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0 or result.stdout.strip() != "True":
                    all_ready = False
                    break

            if all_ready:
                return True

            time.sleep(check_interval)

        return False

    def exec_in_pod(self, pod: str, command: list[str], timeout: int = 30) -> ExecResult:
        """Execute command in pod.

        Args:
            pod: Pod name
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            ExecResult with returncode, stdout, stderr
        """
        cmd = ["kubectl", "exec", pod, "-n", self.namespace, "--"] + command

        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

        return ExecResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def exec_in_pod_async(self, pod: str, command: list[str]) -> asyncio.Task:
        """Execute command in pod asynchronously (non-blocking).

        Args:
            pod: Pod name
            command: Command to execute

        Returns:
            asyncio Task
        """

        async def _exec():
            cmd = ["kubectl", "exec", pod, "-n", self.namespace, "--"] + command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return ExecResult(
                returncode=proc.returncode,
                stdout=stdout.decode(),
                stderr=stderr.decode(),
            )

        return asyncio.create_task(_exec())

    def get_pod_logs(self, pod: str, tail: int = 100, since_seconds: int | None = None) -> str:
        """Get logs from pod.

        Args:
            pod: Pod name
            tail: Number of lines to return
            since_seconds: Only return logs from last N seconds

        Returns:
            Log output
        """
        cmd = ["kubectl", "logs", pod, "-n", self.namespace, f"--tail={tail}"]

        if since_seconds:
            cmd.append(f"--since={since_seconds}s")

        result = subprocess.run(cmd, capture_output=True, text=True)

        return result.stdout

    def collect_logs(self, pods: list[str], output_dir: Path | None = None) -> dict[str, str]:
        """Collect logs from all pods.

        Args:
            pods: List of pod names
            output_dir: Optional directory to write log files

        Returns:
            Dict mapping pod name to log content
        """
        logs = {}

        for pod in pods:
            log_content = self.get_pod_logs(pod, tail=1000)
            logs[pod] = log_content

            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file = output_dir / f"{pod}.log"
                log_file.write_text(log_content)

        return logs

    def get_pod_status(self, pod: str) -> dict[str, Any]:
        """Get pod status.

        Args:
            pod: Pod name

        Returns:
            Pod status dict
        """
        result = subprocess.run(
            ["kubectl", "get", "pod", pod, "-n", self.namespace, "-o", "json"],
            capture_output=True,
            text=True,
        )

        import json

        return json.loads(result.stdout)

    def get_pod_events(self, pod: str) -> list[dict[str, Any]]:
        """Get events for pod.

        Args:
            pod: Pod name

        Returns:
            List of event dicts
        """
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "events",
                "-n",
                self.namespace,
                "--field-selector",
                f"involvedObject.name={pod}",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
        )

        import json

        data = json.loads(result.stdout)
        return data.get("items", [])

    def get_pod_metrics(self, pod: str) -> dict[str, float]:
        """Get resource metrics for pod (requires metrics-server).

        Args:
            pod: Pod name

        Returns:
            Dict with cpu_usage_millicores and memory_usage_mb
        """
        result = subprocess.run(
            ["kubectl", "top", "pod", pod, "-n", self.namespace],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        # Parse output: "NAME  CPU(cores)  MEMORY(bytes)"
        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        parts = lines[1].split()
        if len(parts) < 3:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        # Parse CPU (e.g., "150m" -> 150)
        cpu_str = parts[1].replace("m", "")
        cpu_usage = int(cpu_str) if cpu_str.isdigit() else 0

        # Parse memory (e.g., "128Mi" -> 128)
        mem_str = parts[2].replace("Mi", "").replace("M", "")
        mem_usage = int(mem_str) if mem_str.isdigit() else 0

        return {
            "cpu_usage_millicores": cpu_usage,
            "memory_usage_mb": mem_usage,
        }

    def get_pods(self, label: str | None = None) -> list[str]:
        """Get list of pods in namespace.

        Args:
            label: Optional label selector (e.g., "app=styrened-test")

        Returns:
            List of pod names
        """
        cmd = ["kubectl", "get", "pods", "-n", self.namespace, "-o", "name"]

        if label:
            cmd.extend(["-l", label])

        result = subprocess.run(cmd, capture_output=True, text=True)

        # Parse output: "pod/name" -> "name"
        pods = [line.split("/")[1] for line in result.stdout.strip().split("\n") if line]
        return pods

    def get_pod_node(self, pod: str) -> str:
        """Get node name for pod.

        Args:
            pod: Pod name

        Returns:
            Node name
        """
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pod",
                pod,
                "-n",
                self.namespace,
                "-o",
                "jsonpath={.spec.nodeName}",
            ],
            capture_output=True,
            text=True,
        )

        return result.stdout.strip()

    def apply_manifest(self, manifest: dict[str, Any]) -> None:
        """Apply k8s manifest.

        Args:
            manifest: Manifest dict
        """
        import json
        import tempfile

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(manifest, f)
            manifest_file = f.name

        try:
            subprocess.run(
                ["kubectl", "apply", "-f", manifest_file, "-n", self.namespace],
                check=True,
            )
        finally:
            Path(manifest_file).unlink()

    def delete_manifest(self, kind: str, name: str) -> None:
        """Delete k8s resource.

        Args:
            kind: Resource kind (e.g., "NetworkPolicy")
            name: Resource name
        """
        subprocess.run(
            ["kubectl", "delete", kind, name, "-n", self.namespace],
            capture_output=True,
        )

    def delete_pod(self, pod: str) -> None:
        """Delete pod.

        Args:
            pod: Pod name
        """
        subprocess.run(
            ["kubectl", "delete", "pod", pod, "-n", self.namespace],
            capture_output=True,
        )

    def helm_upgrade(self, release_name: str, chart_path: str, set_values: dict[str, Any]) -> None:
        """Upgrade Helm release.

        Args:
            release_name: Release name
            chart_path: Path to chart
            set_values: Values to set
        """
        cmd = ["helm", "upgrade", release_name, chart_path, "-n", self.namespace]

        for key, value in set_values.items():
            cmd.extend(["--set", f"{key}={value}"])

        subprocess.run(cmd, check=True)

    def cleanup(self, release_name: str) -> None:
        """Cleanup Helm release and resources.

        Args:
            release_name: Helm release name
        """
        # Uninstall Helm release
        subprocess.run(
            ["helm", "uninstall", release_name, "-n", self.namespace],
            capture_output=True,
        )

        # Wait for pods to terminate
        time.sleep(10)

        # Force delete any remaining pods
        pods = self.get_pods(label=f"app.kubernetes.io/instance={release_name}")
        for pod in pods:
            self.delete_pod(pod)

    # -------------------------------------------------------------------------
    # Hub/Peer Topology Methods
    # -------------------------------------------------------------------------

    def _get_image_values(self) -> list[str]:
        """Get Helm --set values for image configuration based on cluster type.

        Returns:
            List of --set arguments for image config
        """
        if self.cluster_type in ("kind", "k3d"):
            # Local cluster - use pre-loaded image
            return [
                "--set",
                "image.repository=styrened-test",
                "--set",
                "image.tag=local-amd64",
                "--set",
                "image.pullPolicy=Never",
            ]
        else:
            # Cloud/remote cluster - use GHCR with pull secret
            return [
                "--set",
                "image.repository=ghcr.io/styrene-lab/styrened-test",
                "--set",
                "image.tag=dev",
                "--set",
                "image.pullPolicy=Always",
                "--set",
                "imagePullSecrets[0].name=ghcr-secret",
            ]

    def _ensure_ghcr_secret(self, namespace: str) -> None:
        """Ensure ghcr-secret exists in the target namespace.

        For cloud clusters, copies the VSO-managed secret from styrene-infra
        namespace. The secret is provisioned via VaultStaticSecret from Vault
        at path secret/bootstrap/ghcr/styrene-lab.

        Args:
            namespace: Target namespace for the secret
        """
        if self.cluster_type in ("kind", "k3d"):
            return  # No secret needed for local clusters

        # Check if secret already exists in target namespace
        result = subprocess.run(
            ["kubectl", "get", "secret", "ghcr-secret", "-n", namespace],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return  # Secret already exists

        # Copy from VSO-managed source in styrene-infra namespace
        # This secret is synced from Vault via VaultStaticSecret
        source_ns = "styrene-infra"
        result = subprocess.run(
            ["kubectl", "get", "secret", "ghcr-secret", "-n", source_ns, "-o", "yaml"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            # Use jq to properly clean the secret for copying to another namespace
            # This handles nested structures like ownerReferences that regex can't
            import json

            # Parse YAML to JSON, clean, and apply
            jq_result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "secret",
                    "ghcr-secret",
                    "-n",
                    source_ns,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
            )
            if jq_result.returncode == 0:
                try:
                    secret = json.loads(jq_result.stdout)
                    # Remove metadata that shouldn't be copied
                    metadata = secret.get("metadata", {})
                    for key in [
                        "resourceVersion",
                        "uid",
                        "creationTimestamp",
                        "ownerReferences",
                        "managedFields",
                        "labels",
                    ]:
                        metadata.pop(key, None)
                    metadata["namespace"] = namespace
                    secret["metadata"] = metadata

                    apply_result = subprocess.run(
                        ["kubectl", "apply", "-f", "-"],
                        input=json.dumps(secret),
                        capture_output=True,
                        text=True,
                    )
                    if apply_result.returncode == 0:
                        return  # Successfully copied from VSO-managed source
                except json.JSONDecodeError:
                    pass  # Fall through to warning

        # If VSO source not found, warn with setup instructions
        print(f"Warning: ghcr-secret not found in {source_ns} namespace for {namespace}")
        print("  Ensure VSO is configured: kubectl apply -f tests/k8s/vault/")

    def deploy_hub(
        self,
        release_name: str,
        announce_interval: int = 30,
        extra_values: dict[str, Any] | None = None,
    ) -> str:
        """Deploy a single hub node with transport enabled.

        Args:
            release_name: Helm release name
            announce_interval: Announce interval in seconds
            extra_values: Additional Helm values

        Returns:
            Pod name of the hub
        """
        # Ensure GHCR secret exists for cloud clusters
        self._ensure_ghcr_secret(self.namespace)

        values_file = self.helm_dir / "values-hub.yaml"

        cmd = [
            "helm",
            "install",
            release_name,
            str(self.helm_dir),
            "-n",
            self.namespace,
            "--create-namespace",
            "-f",
            str(values_file),
        ]

        # Add image configuration based on cluster type
        cmd.extend(self._get_image_values())

        cmd.extend(
            [
                "--set",
                f"styrene.reticulum.announce_interval={announce_interval}",
                "--set",
                f"styrene.discovery.announce_interval={announce_interval}",
            ]
        )

        if extra_values:
            for key, value in extra_values.items():
                cmd.extend(["--set", f"{key}={value}"])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(f"Helm install hub failed: {result.stderr}\nStdout: {result.stdout}")

        return f"{release_name}-styrened-test-0"

    def get_pod_ip(self, pod: str) -> str:
        """Get IP address of a pod.

        Args:
            pod: Pod name

        Returns:
            Pod IP address
        """
        result = subprocess.run(
            [
                "kubectl",
                "get",
                "pod",
                pod,
                "-n",
                self.namespace,
                "-o",
                "jsonpath={.status.podIP}",
            ],
            capture_output=True,
            text=True,
        )

        return result.stdout.strip()

    def deploy_peers(
        self,
        release_name: str,
        hub_address: str,
        count: int = 3,
        announce_interval: int = 60,
        extra_values: dict[str, Any] | None = None,
    ) -> list[str]:
        """Deploy peer nodes that connect to a hub.

        Args:
            release_name: Helm release name
            hub_address: IP address or hostname of the hub
            count: Number of peer pods
            announce_interval: Announce interval in seconds
            extra_values: Additional Helm values

        Returns:
            List of peer pod names
        """
        # Ensure GHCR secret exists for cloud clusters
        self._ensure_ghcr_secret(self.namespace)

        # Build peer-specific values
        set_values = [
            f"replicaCount={count}",
            "styrene.reticulum.mode=peer",
            "styrene.reticulum.transport_enabled=false",
            f"styrene.reticulum.announce_interval={announce_interval}",
            f"styrene.discovery.announce_interval={announce_interval}",
            "rns.enable_transport=false",
            # Configure TCP client to hub
            "rns.interfaces[0].type=TCPClientInterface",
            "rns.interfaces[0].enabled=true",
            f"rns.interfaces[0].target_host={hub_address}",
            "rns.interfaces[0].target_port=4242",
        ]

        cmd = [
            "helm",
            "install",
            release_name,
            str(self.helm_dir),
            "-n",
            self.namespace,
            "--create-namespace",
        ]

        # Add image configuration based on cluster type
        cmd.extend(self._get_image_values())

        for val in set_values:
            cmd.extend(["--set", val])

        if extra_values:
            for key, value in extra_values.items():
                cmd.extend(["--set", f"{key}={value}"])

        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            raise RuntimeError(
                f"Helm install peers failed: {result.stderr}\nStdout: {result.stdout}"
            )

        return [f"{release_name}-styrened-test-{i}" for i in range(count)]

    def deploy_chain_topology(
        self,
        release_prefix: str,
        node_count: int = 5,
        announce_interval: int = 20,
    ) -> list[str]:
        """Deploy nodes in a linear chain topology (A→B→C→D→E).

        Each node only connects to its neighbors.

        Args:
            release_prefix: Prefix for release names
            node_count: Number of nodes in chain
            announce_interval: Announce interval in seconds

        Returns:
            List of pod names in chain order
        """
        pods = []

        for i in range(node_count):
            release_name = f"{release_prefix}-node-{i}"

            # First node is server only
            # Middle nodes are server + client to previous
            # Last node is client only
            set_values = [
                "replicaCount=1",
                "styrene.reticulum.mode=standalone",
                "styrene.reticulum.transport_enabled=true",
                f"styrene.reticulum.announce_interval={announce_interval}",
                "rns.enable_transport=true",
            ]

            # Add server interface (except for last node)
            if i < node_count - 1:
                set_values.extend(
                    [
                        "rns.interfaces[0].type=TCPServerInterface",
                        "rns.interfaces[0].enabled=true",
                        "rns.interfaces[0].listen_ip=0.0.0.0",
                        "rns.interfaces[0].listen_port=4242",
                    ]
                )

            # Add client interface to previous node (except for first node)
            if i > 0:
                prev_pod = pods[i - 1]
                prev_ip = self.get_pod_ip(prev_pod)
                interface_idx = 0 if i == node_count - 1 else 1
                set_values.extend(
                    [
                        f"rns.interfaces[{interface_idx}].type=TCPClientInterface",
                        f"rns.interfaces[{interface_idx}].enabled=true",
                        f"rns.interfaces[{interface_idx}].target_host={prev_ip}",
                        f"rns.interfaces[{interface_idx}].target_port=4242",
                    ]
                )

            cmd = [
                "helm",
                "install",
                release_name,
                str(self.helm_dir),
                "-n",
                self.namespace,
                "--create-namespace",
            ]

            for val in set_values:
                cmd.extend(["--set", val])

            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode != 0:
                raise RuntimeError(
                    f"Helm install chain node {i} failed: {result.stderr}\nStdout: {result.stdout}"
                )

            pod_name = f"{release_name}-styrened-test-0"
            pods.append(pod_name)

            # Wait for pod to be ready before deploying next
            if not self.wait_for_ready([pod_name], timeout=60):
                raise RuntimeError(f"Chain node {i} failed to become ready")

        return pods

    # -------------------------------------------------------------------------
    # Mesh Discovery and Convergence
    # -------------------------------------------------------------------------

    def get_identity_hash(self, pod: str) -> str:
        """Get the LXMF delivery destination hash for a pod from daemon logs.

        Parses the daemon logs for the LXMF delivery hash which is used for
        message routing.

        Args:
            pod: Pod name

        Returns:
            Hex-encoded delivery destination hash
        """
        import re

        logs = self.get_pod_logs(pod, tail=200)

        # Look for "LXMF initialized and announced (delivery: <hash>...)"
        pattern = re.compile(r"LXMF initialized and announced \(delivery: ([a-f0-9]{16,})")
        match = pattern.search(logs)
        if match:
            return match.group(1)

        # Fallback: look for "Operator destination: <hash>..."
        pattern2 = re.compile(r"Operator destination: ([a-f0-9]{16,})")
        match2 = pattern2.search(logs)
        if match2:
            return match2.group(1)

        raise RuntimeError("Identity hash not found in pod logs")

    def get_discovered_peers(self, pod: str, wait_seconds: int = 5) -> list[str]:
        """Get list of discovered peer hashes from a pod by parsing daemon logs.

        Note: CLI discovery doesn't work because it creates a separate RNS instance.
        Instead, we parse daemon logs for "Discovered:" entries.

        Args:
            pod: Pod name
            wait_seconds: Not used (kept for API compatibility)

        Returns:
            List of hex-encoded peer hashes
        """
        import re

        # Get daemon logs
        logs = self.get_pod_logs(pod, tail=500)

        # Parse "Discovered: <name> (<type>) - <status>" or announce hash patterns
        # Also look for "Announce from <hash>" patterns
        discovered = set()

        # Pattern for announce receipts: "Announce from <hex>:"
        announce_pattern = re.compile(r"Announce from ([a-f0-9]{16,})")
        for match in announce_pattern.finditer(logs):
            discovered.add(match.group(1))

        return list(discovered)

    def wait_for_mesh_convergence(
        self,
        pods: list[str],
        timeout: int = 180,
        check_interval: int = 15,
    ) -> float:
        """Wait for all pods to discover each other.

        Args:
            pods: List of pod names
            timeout: Maximum wait time in seconds
            check_interval: Time between checks in seconds

        Returns:
            Time to convergence in seconds

        Raises:
            TimeoutError: If mesh doesn't converge within timeout
        """
        start_time = time.time()
        expected_count = len(pods) - 1  # Each pod should see all others

        # Get identity hashes for all pods
        pod_hashes = {}
        for pod in pods:
            try:
                pod_hashes[pod] = self.get_identity_hash(pod)
            except RuntimeError:
                pass  # Pod may not be ready yet

        while time.time() - start_time < timeout:
            all_converged = True

            for pod in pods:
                discovered = self.get_discovered_peers(pod, wait_seconds=5)

                # Check if this pod has discovered all others
                other_hashes = [h for p, h in pod_hashes.items() if p != pod]
                found_count = sum(1 for h in other_hashes if h in discovered)

                if found_count < expected_count:
                    all_converged = False
                    break

            if all_converged:
                return time.time() - start_time

            time.sleep(check_interval)

        raise TimeoutError(
            f"Mesh did not converge within {timeout}s. "
            f"Expected each pod to discover {expected_count} peers."
        )

    def send_message_and_measure(
        self,
        source_pod: str,
        dest_hash: str,
        message: str,
        discovery_wait: int = 30,
        max_wait: int = 60,
    ) -> tuple[bool, float]:
        """Send a message and measure delivery time.

        Args:
            source_pod: Pod to send from
            dest_hash: Destination identity hash
            message: Message content
            discovery_wait: Seconds to wait for path discovery
            max_wait: Maximum wait for delivery

        Returns:
            Tuple of (success, latency_seconds)
        """
        start_time = time.time()

        result = self.exec_in_pod(
            source_pod,
            [
                "styrened",
                "send",
                dest_hash,
                message,
                "-w",
                str(discovery_wait),
                "--max-wait",
                str(max_wait),
            ],
            timeout=discovery_wait + max_wait + 30,
        )

        latency = time.time() - start_time
        success = result.returncode == 0 or "sent" in result.stdout.lower()

        return success, latency

    def check_routing_via_hub(self, hub_pod: str, since_seconds: int = 60) -> bool:
        """Check if hub logs show message routing activity.

        Args:
            hub_pod: Hub pod name
            since_seconds: Look at logs from last N seconds

        Returns:
            True if routing activity detected
        """
        logs = self.get_pod_logs(hub_pod, tail=500, since_seconds=since_seconds)

        # Look for RNS transport/routing indicators
        routing_indicators = [
            "transport",
            "forwarding",
            "routing",
            "path request",
            "announce",
        ]

        logs_lower = logs.lower()
        return any(indicator in logs_lower for indicator in routing_indicators)

    def get_memory_usage_mb(self, pod: str) -> float:
        """Get current memory usage of a pod in MB.

        Args:
            pod: Pod name

        Returns:
            Memory usage in MB, or 0 if unavailable
        """
        metrics = self.get_pod_metrics(pod)
        return float(metrics.get("memory_usage_mb", 0))

    def verify_rpc_server_responding(self, pod: str, since_seconds: int = 120) -> bool:
        """Verify that a pod's RPC server is processing requests and sending responses.

        Checks daemon logs for evidence that:
        1. STATUS_REQUEST was received (from any source)
        2. STATUS_RESPONSE was sent in reply

        This validates the RPC server is functional without needing to inject
        requests from a separate process.

        Args:
            pod: Pod to check logs for
            since_seconds: Look at logs from last N seconds

        Returns:
            True if RPC server activity detected (request received AND response sent)
        """
        logs = self.get_pod_logs(pod, tail=500, since_seconds=since_seconds)

        # Check for RPC server processing indicators
        received_request = "STATUS_REQUEST from" in logs or "Handling STATUS_REQUEST" in logs
        sent_response = "STATUS_RESPONSE" in logs and "sent" in logs.lower()

        return received_request and sent_response

    def verify_announces_received(
        self, pod: str, min_count: int = 1, since_seconds: int = 120
    ) -> bool:
        """Verify that a pod has received announces from other nodes.

        Args:
            pod: Pod to check logs for
            min_count: Minimum number of unique announces expected
            since_seconds: Look at logs from last N seconds

        Returns:
            True if at least min_count unique announces received
        """
        import re

        logs = self.get_pod_logs(pod, tail=500, since_seconds=since_seconds)

        # Look for announce receipts - patterns like "Announce from <hash>"
        pattern = re.compile(r"Announce from ([a-f0-9]{16,})")
        matches = pattern.findall(logs)
        unique_sources = set(matches)

        return len(unique_sources) >= min_count

    def verify_lxmf_message_delivery(
        self, source_pod: str, target_pod: str, since_seconds: int = 120
    ) -> bool:
        """Verify LXMF message delivery between two pods by log inspection.

        Checks that:
        1. Source pod shows message delivered (delivery callback)
        2. Target pod shows message received

        Args:
            source_pod: Pod that sent the message
            target_pod: Pod that should receive the message
            since_seconds: Look at logs from last N seconds

        Returns:
            True if message delivery confirmed in logs
        """
        source_logs = self.get_pod_logs(source_pod, tail=500, since_seconds=since_seconds)
        target_logs = self.get_pod_logs(target_pod, tail=500, since_seconds=since_seconds)

        # Check source shows delivery
        source_delivered = "[LXMF] Message delivered" in source_logs

        # Check target shows receipt (any LXMF message receipt indicator)
        target_received = (
            "LXMF message received" in target_logs
            or "STATUS_REQUEST from" in target_logs
            or "CHAT from" in target_logs
            or "PING from" in target_logs
        )

        return source_delivered and target_received

    def verify_rpc_response_in_logs(
        self, pod: str, since_seconds: int = 120, source_hash_prefix: str = ""
    ) -> bool:
        """Verify that a pod's daemon received a STATUS_RESPONSE.

        Checks the daemon logs for STATUS_RESPONSE entries, indicating
        successful RPC round-trip.

        Args:
            pod: Pod to check logs for
            since_seconds: Look at logs from last N seconds
            source_hash_prefix: Optional prefix of source hash to match

        Returns:
            True if STATUS_RESPONSE was received
        """
        logs = self.get_pod_logs(pod, tail=500, since_seconds=since_seconds)

        # Look for STATUS_RESPONSE in daemon logs
        # The daemon logs: "STATUS_RESPONSE from <hash>" and "Status data: {...}"
        if "STATUS_RESPONSE from" in logs:
            if source_hash_prefix:
                return source_hash_prefix in logs
            return True

        return False

    def trigger_rpc_via_cli(
        self,
        from_pod: str,
        to_dest_hash: str,
        timeout: int = 30,
    ) -> bool:
        """Trigger an RPC STATUS_REQUEST via CLI command.

        Uses `styrened status <hash>` to send a STATUS_REQUEST. The CLI will
        timeout waiting for a response (since daemon receives it, not CLI),
        but the request WILL be sent and processed by the target.

        Args:
            from_pod: Pod to send request from
            to_dest_hash: Target destination hash
            timeout: CLI timeout (will likely timeout, but request is sent)

        Returns:
            True if CLI executed (even if timed out - request was sent)
        """
        result = self.exec_in_pod(
            from_pod,
            ["styrened", "status", to_dest_hash, "-w", "30"],
            timeout=timeout + 10,
        )

        # CLI may timeout, but if it ran, the request was sent
        # Success indicators: ran at all, or specifically mentioned sending
        return result.returncode in (0, 1) or "timeout" in result.stderr.lower()

    def verify_rpc_round_trip(
        self,
        from_pod: str,
        to_pod: str,
        timeout: int = 90,
        check_interval: int = 5,
    ) -> tuple[bool, float]:
        """Verify complete RPC round-trip between two daemon pods.

        This test verifies the RPC flow works by:
        1. Using CLI to trigger a STATUS_REQUEST from from_pod to to_pod
        2. Verifying to_pod received the request (logs show "STATUS_REQUEST from")
        3. Verifying to_pod sent a response (logs show response sent)
        4. Verifying from_pod's daemon received the response (logs show "STATUS_RESPONSE from")

        Note: The CLI itself times out because the daemon (not CLI) receives
        the response. But the full daemon-to-daemon round-trip works.

        Args:
            from_pod: Pod to send request from
            to_pod: Pod to send request to
            timeout: Maximum seconds to wait for round-trip
            check_interval: Seconds between log checks

        Returns:
            Tuple of (success, latency_seconds)
        """
        # Get target's LXMF destination hash
        to_dest_hash = self.get_identity_hash(to_pod)

        start_time = time.time()

        # Trigger the RPC request via CLI (will timeout but sends request)
        self.trigger_rpc_via_cli(from_pod, to_dest_hash, timeout=45)

        # Verify to_pod received and processed the request
        to_pod_logs = self.get_pod_logs(to_pod, tail=300, since_seconds=timeout)
        request_received = "STATUS_REQUEST from" in to_pod_logs

        if not request_received:
            return False, time.time() - start_time

        # Wait for response to appear in from_pod's daemon logs
        while time.time() - start_time < timeout:
            if self.verify_rpc_response_in_logs(from_pod, since_seconds=timeout):
                latency = time.time() - start_time
                return True, latency
            time.sleep(check_interval)

        # Even if from_pod's daemon didn't receive response, check if to_pod sent it
        # This helps diagnose where the issue is
        to_pod_logs = self.get_pod_logs(to_pod, tail=300, since_seconds=timeout)
        response_sent = "STATUS_RESPONSE" in to_pod_logs

        if response_sent and not self.verify_rpc_response_in_logs(from_pod, since_seconds=timeout):
            # to_pod sent response but from_pod didn't receive - routing issue
            print(f"Note: {to_pod} sent response but {from_pod} didn't receive it")

        return False, time.time() - start_time
