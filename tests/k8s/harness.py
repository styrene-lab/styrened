"""K8s test orchestration harness for styrened containerized testing.

Provides deployment automation, log collection, and cleanup for pytest tests.
"""

import asyncio
import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class ExecResult:
    """Result from executing command in pod."""

    returncode: int
    stdout: str
    stderr: str


class K8sTestHarness:
    """Harness for managing k8s resources during styrened tests."""

    def __init__(self, namespace: str = "default", kubeconfig: Optional[str] = None):
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
        extra_values: Optional[Dict[str, Any]] = None,
    ) -> List[str]:
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
            raise RuntimeError(
                f"Helm install failed: {result.stderr}\nStdout: {result.stdout}"
            )

        # Return list of pod names (StatefulSet naming)
        return [f"{release_name}-styrened-test-{i}" for i in range(replica_count)]

    def wait_for_ready(
        self, pods: List[str], timeout: int = 60, check_interval: int = 5
    ) -> bool:
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

    def exec_in_pod(
        self, pod: str, command: List[str], timeout: int = 30
    ) -> ExecResult:
        """Execute command in pod.

        Args:
            pod: Pod name
            command: Command to execute
            timeout: Timeout in seconds

        Returns:
            ExecResult with returncode, stdout, stderr
        """
        cmd = ["kubectl", "exec", pod, "-n", self.namespace, "--"] + command

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout
        )

        return ExecResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
        )

    def exec_in_pod_async(
        self, pod: str, command: List[str]
    ) -> asyncio.Task:
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

    def get_pod_logs(
        self, pod: str, tail: int = 100, since_seconds: Optional[int] = None
    ) -> str:
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

    def collect_logs(self, pods: List[str], output_dir: Optional[Path] = None) -> Dict[str, str]:
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

    def get_pod_status(self, pod: str) -> Dict[str, Any]:
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

    def get_pod_events(self, pod: str) -> List[Dict[str, Any]]:
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

    def get_pod_metrics(self, pod: str) -> Dict[str, float]:
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

    def get_pods(self, label: Optional[str] = None) -> List[str]:
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

    def apply_manifest(self, manifest: Dict[str, Any]) -> None:
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

    def helm_upgrade(
        self, release_name: str, chart_path: str, set_values: Dict[str, Any]
    ) -> None:
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
