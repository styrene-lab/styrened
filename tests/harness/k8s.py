"""Kubernetes-based test harness for containerized testing."""

from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from .base import CommandResult, ExecutionBackend, NodeInfo, TestHarness


class K8sHarness(TestHarness):
    """Kubernetes-based test harness.

    Provides deployment automation, log collection, and cleanup for pytest tests.
    Uses kubectl and Helm for orchestration.
    """

    def __init__(
        self,
        namespace: str = "default",
        kubeconfig: str | None = None,
    ):
        """Initialize K8s harness.

        Args:
            namespace: K8s namespace to use
            kubeconfig: Path to kubeconfig (None = auto-detect)
        """
        self.namespace = namespace
        self.kubeconfig = kubeconfig or os.environ.get("KUBECONFIG")
        self.helm_dir = Path(__file__).parent.parent / "k8s" / "helm" / "styrened-test"

        # Detect cluster type
        self.cluster_type = self._detect_cluster_type()

        # Pod cache
        self._pods: dict[str, NodeInfo] = {}

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

    def _kubectl_cmd(self) -> list[str]:
        """Base kubectl command with kubeconfig if set."""
        cmd = ["kubectl"]
        if self.kubeconfig:
            cmd.extend(["--kubeconfig", self.kubeconfig])
        return cmd

    # -------------------------------------------------------------------------
    # TestHarness ABC Implementation
    # -------------------------------------------------------------------------

    @property
    def backend(self) -> ExecutionBackend:
        return ExecutionBackend.K8S

    def refresh_pods(self, label: str = "app.kubernetes.io/name=styrened-test") -> None:
        """Refresh pod list from cluster.

        Args:
            label: Label selector for pods
        """
        cmd = self._kubectl_cmd() + [
            "get",
            "pods",
            "-n",
            self.namespace,
            "-l",
            label,
            "-o",
            "json",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            return

        data = json.loads(result.stdout)
        self._pods.clear()

        for pod in data.get("items", []):
            name = pod["metadata"]["name"]
            self._pods[name] = NodeInfo(
                name=name,
                address=f"{name}/{self.namespace}",
                identity_hash=None,  # Populated on first query
                backend=ExecutionBackend.K8S,
                capabilities=["helm_managed"],
                metadata={
                    "phase": pod["status"]["phase"],
                    "node": pod["spec"].get("nodeName"),
                    "labels": pod["metadata"].get("labels", {}),
                },
            )

    def get_nodes(self) -> list[NodeInfo]:
        """Return all available test nodes (pods)."""
        self.refresh_pods()
        return list(self._pods.values())

    def _resolve_node(self, node: str | NodeInfo) -> NodeInfo:
        """Resolve node identifier to NodeInfo."""
        if isinstance(node, NodeInfo):
            return node
        if node in self._pods:
            return self._pods[node]
        # Assume it's a pod name - create ephemeral NodeInfo
        return NodeInfo(
            name=node,
            address=f"{node}/{self.namespace}",
            identity_hash=None,
            backend=ExecutionBackend.K8S,
        )

    def run(
        self,
        node: str | NodeInfo,
        command: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute command in pod via kubectl exec."""
        node_info = self._resolve_node(node)
        start = time.time()

        cmd = self._kubectl_cmd() + [
            "exec",
            "-n",
            self.namespace,
            node_info.name,
            "--",
            "sh",
            "-c",
            command,
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start

            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration=duration,
                backend=ExecutionBackend.K8S,
                target=node_info.name,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1,
                duration=time.time() - start,
                backend=ExecutionBackend.K8S,
                target=node_info.name,
            )

    def run_styrened(
        self,
        node: str | NodeInfo,
        subcommand: str,
        timeout: float = 30.0,
    ) -> CommandResult:
        """Execute styrened CLI command."""
        return self.run(node, f"styrened {subcommand}", timeout)

    def start_daemon(self, node: str | NodeInfo) -> CommandResult:
        """In K8s, daemon runs as container entrypoint - restart pod."""
        node_info = self._resolve_node(node)
        cmd = self._kubectl_cmd() + [
            "delete",
            "pod",
            "-n",
            self.namespace,
            node_info.name,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        # Pod will be recreated by StatefulSet/Deployment
        return CommandResult(
            success=result.returncode == 0,
            stdout=result.stdout,
            stderr=result.stderr,
            return_code=result.returncode,
            backend=ExecutionBackend.K8S,
            target=node_info.name,
        )

    def stop_daemon(self, node: str | NodeInfo) -> CommandResult:
        """In K8s, daemon lifecycle is managed by container - cannot stop individually."""
        # Return success as daemon lifecycle is managed by K8s
        return CommandResult(
            success=True,
            stdout="K8s manages daemon lifecycle via container entrypoint",
            stderr="",
            return_code=0,
            backend=ExecutionBackend.K8S,
            target=self._resolve_node(node).name,
        )

    def is_daemon_running(self, node: str | NodeInfo) -> bool:
        """Check if pod is running and ready."""
        node_info = self._resolve_node(node)
        cmd = self._kubectl_cmd() + [
            "get",
            "pod",
            "-n",
            self.namespace,
            node_info.name,
            "-o",
            "jsonpath={.status.phase}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout.strip() == "Running"

    def get_identity(self, node: str | NodeInfo) -> str | None:
        """Get LXMF identity hash for node from daemon logs."""
        node_info = self._resolve_node(node)
        logs = self.get_pod_logs(node_info.name, tail=200)

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

        # Try CLI as last resort
        result = self.run_styrened(node, "identity --json")
        if result.success:
            try:
                data = json.loads(result.stdout)
                if isinstance(data, dict):
                    return data.get("identity_hash") or data.get("hash")
            except json.JSONDecodeError:
                pass

        return None

    def discover_devices(
        self,
        node: str | NodeInfo,
        wait_seconds: int = 10,
    ) -> list[dict[str, Any]]:
        """Discover mesh devices by parsing daemon logs.

        Note: CLI discovery doesn't work because it creates a separate RNS instance.
        Instead, we parse daemon logs for announce entries.

        The wait_seconds parameter is used to poll for new announces, giving the
        mesh time to propagate discovery information.

        Log patterns we search for:
        - "Storing identity: identity_hash=<hash>..."
        - "Discovered: <name> (styrene_node)"
        - "announce from destination <hash>..."
        """
        node_info = self._resolve_node(node)

        # Poll logs over the wait period to catch new announces
        seen: set[str] = set()
        poll_interval = min(5, wait_seconds)
        elapsed = 0

        while elapsed < wait_seconds:
            logs = self.get_pod_logs(node_info.name, tail=500)

            # Pattern 1: "Storing identity: identity_hash=<hash>..."
            # Example: [HASH] Storing identity: identity_hash=d6b52b562be9d7c2...
            pattern1 = re.compile(r"identity_hash=([a-f0-9]{16,})")
            for match in pattern1.finditer(logs):
                seen.add(match.group(1))

            # Pattern 2: "announce from destination <hash>..."
            # Example: (source: announce from destination 8ad89cd606b5e39d...)
            pattern2 = re.compile(r"announce from destination ([a-f0-9]{16,})")
            for match in pattern2.finditer(logs):
                seen.add(match.group(1))

            # Pattern 3: Legacy "Announce from <hash>" (older log format)
            pattern3 = re.compile(r"Announce from ([a-f0-9]{16,})")
            for match in pattern3.finditer(logs):
                seen.add(match.group(1))

            # Wait before next poll (unless we've reached wait_seconds)
            if elapsed + poll_interval < wait_seconds:
                time.sleep(poll_interval)
            elapsed += poll_interval

        return [{"identity": hash_val} for hash_val in seen]

    # -------------------------------------------------------------------------
    # K8s-Specific Methods (preserved from original harness)
    # -------------------------------------------------------------------------

    def get_image_config_for_ci(self, commit_sha: str) -> dict[str, str]:
        """Get image configuration for CI/CD with GHCR."""
        return {
            "image_repository": "ghcr.io/styrene-lab/styrened-test",
            "image_tag": commit_sha,
            "image_pull_policy": "Always",
        }

    def get_image_config_for_local(self) -> dict[str, str]:
        """Get image configuration for local testing."""
        return {
            "image_repository": "styrened-test",
            "image_tag": "local-amd64",
            "image_pull_policy": "Never",
        }

    def _get_image_values(self) -> list[str]:
        """Get Helm --set values for image configuration based on cluster type.

        Environment variable overrides (for CI):
          STYRENED_TEST_IMAGE_REPO - image repository (e.g. ghcr.io/styrene-lab/styrened-test)
          STYRENED_TEST_IMAGE_TAG  - image tag (e.g. pr-7, dev, 0.4.0)
        """
        repo = os.environ.get("STYRENED_TEST_IMAGE_REPO")
        tag = os.environ.get("STYRENED_TEST_IMAGE_TAG")

        if self.cluster_type in ("kind", "k3d"):
            return [
                "--set",
                f"image.repository={repo or 'styrened-test'}",
                "--set",
                f"image.tag={tag or 'local-amd64'}",
                "--set",
                "image.pullPolicy=Never",
            ]
        else:
            return [
                "--set",
                f"image.repository={repo or 'ghcr.io/styrene-lab/styrened-test'}",
                "--set",
                f"image.tag={tag or 'dev'}",
                "--set",
                "image.pullPolicy=Always",
                "--set",
                "imagePullSecrets[0].name=ghcr-secret",
            ]

    def _ensure_ghcr_secret(self, namespace: str) -> None:
        """Ensure ghcr-secret exists in the target namespace."""
        if self.cluster_type in ("kind", "k3d"):
            return

        result = subprocess.run(
            ["kubectl", "get", "secret", "ghcr-secret", "-n", namespace],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return

        # Copy from VSO-managed source
        source_ns = "styrene-infra"
        jq_result = subprocess.run(
            ["kubectl", "get", "secret", "ghcr-secret", "-n", source_ns, "-o", "json"],
            capture_output=True,
            text=True,
        )
        if jq_result.returncode == 0:
            try:
                secret = json.loads(jq_result.stdout)
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

                subprocess.run(
                    ["kubectl", "apply", "-f", "-"],
                    input=json.dumps(secret),
                    capture_output=True,
                    text=True,
                )
            except json.JSONDecodeError:
                pass

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
        ipc_relay: bool = False,
        ipc_relay_port: int = 9000,
    ) -> list[str]:
        """Deploy styrened stack using Helm.

        Args:
            ipc_relay: Enable IPC TCP relay sidecar for MeshControlClient access.
            ipc_relay_port: Container port for the IPC relay (default 9000).
        """
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

        if ipc_relay:
            set_values.append(f"ipcRelay.enabled=true")
            set_values.append(f"ipcRelay.port={ipc_relay_port}")

        if image_repository:
            set_values.append(f"image.repository={image_repository}")
        if image_tag:
            set_values.append(f"image.tag={image_tag}")
        if image_pull_policy:
            set_values.append(f"image.pullPolicy={image_pull_policy}")

        if extra_values:
            for key, value in extra_values.items():
                set_values.append(f"{key}={value}")

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
            raise RuntimeError(f"Helm install failed: {result.stderr}\nStdout: {result.stdout}")

        return [f"{release_name}-styrened-test-{i}" for i in range(replica_count)]

    def deploy_hub(
        self,
        release_name: str,
        announce_interval: int = 30,
        extra_values: dict[str, Any] | None = None,
    ) -> str:
        """Deploy a single hub node with transport enabled."""
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

    def deploy_peers(
        self,
        release_name: str,
        hub_address: str,
        count: int = 3,
        announce_interval: int = 60,
        extra_values: dict[str, Any] | None = None,
    ) -> list[str]:
        """Deploy peer nodes that connect to a hub."""
        self._ensure_ghcr_secret(self.namespace)

        set_values = [
            f"replicaCount={count}",
            "styrene.reticulum.mode=peer",
            "styrene.reticulum.transport_enabled=false",
            f"styrene.reticulum.announce_interval={announce_interval}",
            f"styrene.discovery.announce_interval={announce_interval}",
            "rns.enable_transport=false",
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

    def wait_for_ready(
        self,
        pods: list[str],
        timeout: int = 60,
        check_interval: int = 5,
    ) -> bool:
        """Wait for pods to be ready."""
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

    def exec_in_pod(
        self,
        pod: str,
        command: list[str],
        timeout: int = 30,
    ) -> CommandResult:
        """Execute command in pod (legacy API compatibility)."""
        node_info = self._resolve_node(pod)
        start = time.time()

        cmd = ["kubectl", "exec", pod, "-n", self.namespace, "--"] + command

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start

            return CommandResult(
                success=result.returncode == 0,
                stdout=result.stdout,
                stderr=result.stderr,
                return_code=result.returncode,
                duration=duration,
                backend=ExecutionBackend.K8S,
                target=node_info.name,
            )
        except subprocess.TimeoutExpired:
            return CommandResult(
                success=False,
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                return_code=-1,
                duration=time.time() - start,
                backend=ExecutionBackend.K8S,
                target=node_info.name,
            )

    def exec_in_pod_async(self, pod: str, command: list[str]) -> asyncio.Task:
        """Execute command in pod asynchronously."""

        async def _exec():
            cmd = ["kubectl", "exec", pod, "-n", self.namespace, "--"] + command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            return CommandResult(
                success=proc.returncode == 0,
                stdout=stdout.decode(),
                stderr=stderr.decode(),
                return_code=proc.returncode or 0,
                backend=ExecutionBackend.K8S,
                target=pod,
            )

        return asyncio.create_task(_exec())

    def get_pod_logs(
        self,
        pod: str,
        tail: int = 100,
        since_seconds: int | None = None,
    ) -> str:
        """Get logs from pod."""
        cmd = ["kubectl", "logs", pod, "-n", self.namespace, f"--tail={tail}"]

        if since_seconds:
            cmd.append(f"--since={since_seconds}s")

        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.stdout

    def get_logs(
        self,
        node: str | NodeInfo,
        lines: int = 100,
        since: str | None = None,
    ) -> CommandResult:
        """Get daemon logs from a K8s pod.

        Args:
            node: Node (pod) to get logs from
            lines: Number of lines to retrieve
            since: Time filter (e.g., "1h", "30m") - converted to seconds

        Returns:
            CommandResult with log content in stdout
        """
        node_info = self._resolve_node(node)

        # Convert since to seconds if provided
        since_seconds = None
        if since:
            # Parse common time formats: "1h", "30m", "60s"
            import re

            match = re.match(r"(\d+)([hms])", since)
            if match:
                value = int(match.group(1))
                unit = match.group(2)
                if unit == "h":
                    since_seconds = value * 3600
                elif unit == "m":
                    since_seconds = value * 60
                else:
                    since_seconds = value

        logs = self.get_pod_logs(node_info.name, tail=lines, since_seconds=since_seconds)

        return CommandResult(
            success=True,
            stdout=logs,
            stderr="",
            return_code=0,
            backend=ExecutionBackend.K8S,
            target=node_info.name,
        )

    def collect_logs(
        self,
        pods: list[str],
        output_dir: Path | None = None,
    ) -> dict[str, str]:
        """Collect logs from all pods."""
        logs = {}

        for pod in pods:
            log_content = self.get_pod_logs(pod, tail=1000)
            logs[pod] = log_content

            if output_dir:
                output_dir.mkdir(parents=True, exist_ok=True)
                log_file = output_dir / f"{pod}.log"
                log_file.write_text(log_content)

        return logs

    def get_pod_ip(self, pod: str) -> str:
        """Get IP address of a pod."""
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

    def get_pod_status(self, pod: str) -> dict[str, Any]:
        """Get pod status."""
        result = subprocess.run(
            ["kubectl", "get", "pod", pod, "-n", self.namespace, "-o", "json"],
            capture_output=True,
            text=True,
        )
        return json.loads(result.stdout)

    def get_pod_events(self, pod: str) -> list[dict[str, Any]]:
        """Get events for pod."""
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
        data = json.loads(result.stdout)
        return data.get("items", [])

    def get_pod_metrics(self, pod: str) -> dict[str, float]:
        """Get resource metrics for pod (requires metrics-server)."""
        result = subprocess.run(
            ["kubectl", "top", "pod", pod, "-n", self.namespace],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        lines = result.stdout.strip().split("\n")
        if len(lines) < 2:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        parts = lines[1].split()
        if len(parts) < 3:
            return {"cpu_usage_millicores": 0, "memory_usage_mb": 0}

        cpu_str = parts[1].replace("m", "")
        cpu_usage = int(cpu_str) if cpu_str.isdigit() else 0

        mem_str = parts[2].replace("Mi", "").replace("M", "")
        mem_usage = int(mem_str) if mem_str.isdigit() else 0

        return {
            "cpu_usage_millicores": cpu_usage,
            "memory_usage_mb": mem_usage,
        }

    def get_pods(self, label: str | None = None) -> list[str]:
        """Get list of pods in namespace."""
        cmd = ["kubectl", "get", "pods", "-n", self.namespace, "-o", "name"]

        if label:
            cmd.extend(["-l", label])

        result = subprocess.run(cmd, capture_output=True, text=True)
        pods = [line.split("/")[1] for line in result.stdout.strip().split("\n") if line]
        return pods

    def delete_pod(self, pod: str) -> None:
        """Delete pod."""
        subprocess.run(
            ["kubectl", "delete", "pod", pod, "-n", self.namespace],
            capture_output=True,
        )

    def cleanup(self, release_name: str) -> None:
        """Cleanup Helm release and resources."""
        subprocess.run(
            ["helm", "uninstall", release_name, "-n", self.namespace],
            capture_output=True,
        )
        time.sleep(10)
        pods = self.get_pods(label=f"app.kubernetes.io/instance={release_name}")
        for pod in pods:
            self.delete_pod(pod)

    # -------------------------------------------------------------------------
    # Mesh Discovery and Convergence
    # -------------------------------------------------------------------------

    def get_identity_hash(self, pod: str) -> str:
        """Get the LXMF delivery destination hash for a pod from daemon logs."""
        identity = self.get_identity(pod)
        if identity:
            return identity
        raise RuntimeError("Identity hash not found in pod logs")

    def get_discovered_peers(self, pod: str, wait_seconds: int = 5) -> list[str]:
        """Get list of discovered peer hashes from pod logs."""
        devices = self.discover_devices(pod, wait_seconds)
        return [d["identity"] for d in devices if "identity" in d]

    def wait_for_mesh_convergence(
        self,
        pods: list[str],
        timeout: int = 180,
        check_interval: int = 15,
    ) -> float:
        """Wait for all pods to discover each other."""
        start_time = time.time()
        expected_count = len(pods) - 1

        pod_hashes = {}
        for pod in pods:
            try:
                pod_hashes[pod] = self.get_identity_hash(pod)
            except RuntimeError:
                pass

        while time.time() - start_time < timeout:
            all_converged = True

            for pod in pods:
                discovered = self.get_discovered_peers(pod, wait_seconds=5)
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
        """Send a message and measure delivery time."""
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
        success = result.return_code == 0 or "sent" in result.stdout.lower()

        return success, latency

    def verify_rpc_round_trip(
        self,
        from_pod: str,
        to_pod: str,
        timeout: int = 90,
        check_interval: int = 5,
    ) -> tuple[bool, float]:
        """Verify complete RPC round-trip between two daemon pods."""
        to_dest_hash = self.get_identity_hash(to_pod)
        start_time = time.time()

        # Trigger RPC via CLI
        self.exec_in_pod(
            from_pod,
            ["styrened", "status", to_dest_hash, "-w", "30"],
            timeout=45,
        )

        # Check if request was received
        to_pod_logs = self.get_pod_logs(to_pod, tail=300, since_seconds=timeout)
        request_received = "STATUS_REQUEST from" in to_pod_logs

        if not request_received:
            return False, time.time() - start_time

        # Wait for response
        while time.time() - start_time < timeout:
            from_pod_logs = self.get_pod_logs(from_pod, tail=300, since_seconds=timeout)
            if "STATUS_RESPONSE from" in from_pod_logs:
                return True, time.time() - start_time
            time.sleep(check_interval)

        return False, time.time() - start_time


# Backward compatibility alias
K8sTestHarness = K8sHarness
