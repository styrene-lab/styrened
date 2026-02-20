"""kubectl port-forward subprocess manager for K8s mesh tests.

Manages concurrent port-forward processes that tunnel IPC relay ports
from K8s pods to the test host. Auto-restarts dead forwards.
"""

from __future__ import annotations

import logging
import subprocess
import time

from tests.topology.port_manager import find_free_port

logger = logging.getLogger(__name__)


class PortForwardManager:
    """Manages kubectl port-forward subprocesses for multiple pods.

    Each pod gets a dedicated port-forward process that tunnels
    localhost:allocated_port -> pod:relay_port.

    kubectl port-forward bypasses NetworkPolicy (uses apiserver->kubelet path),
    so IPC access works regardless of segment isolation.

    Args:
        namespace: K8s namespace containing the pods.
        relay_port: Container port to forward (default 9000).
        kubeconfig: Path to kubeconfig file (optional).
    """

    def __init__(
        self,
        namespace: str,
        relay_port: int = 9000,
        kubeconfig: str | None = None,
    ) -> None:
        self._namespace = namespace
        self._relay_port = relay_port
        self._kubeconfig = kubeconfig
        self._forwards: dict[str, _ForwardEntry] = {}

    def start(self, pods: list[str]) -> None:
        """Start port-forward for each pod.

        Args:
            pods: List of pod names to forward.
        """
        for pod in pods:
            if pod in self._forwards and self._forwards[pod].is_alive():
                continue
            self._start_one(pod)

    def _start_one(self, pod: str) -> None:
        """Start a single port-forward subprocess."""
        local_port = find_free_port()

        cmd = ["kubectl", "port-forward"]
        if self._kubeconfig:
            cmd.extend(["--kubeconfig", self._kubeconfig])
        cmd.extend([
            "-n", self._namespace,
            pod,
            f"{local_port}:{self._relay_port}",
        ])

        logger.info("Starting port-forward: %s (localhost:%d -> %s:%d)",
                     pod, local_port, pod, self._relay_port)

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        self._forwards[pod] = _ForwardEntry(
            process=proc,
            local_port=local_port,
            pod=pod,
        )

        # Brief wait for port-forward to establish
        time.sleep(0.5)

        if proc.poll() is not None:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            raise RuntimeError(
                f"port-forward for {pod} exited immediately: {stderr}"
            )

    def get_endpoint(self, pod: str) -> tuple[str, int]:
        """Get (host, port) for connecting to a pod.

        Auto-restarts dead port-forwards.

        Args:
            pod: Pod name.

        Returns:
            Tuple of (host, port) for MeshControlClient connection.

        Raises:
            KeyError: If pod was never started.
        """
        if pod not in self._forwards:
            raise KeyError(f"No port-forward for pod '{pod}'. Call start() first.")

        entry = self._forwards[pod]
        if not entry.is_alive():
            logger.warning("port-forward for %s died, restarting", pod)
            self._start_one(pod)
            entry = self._forwards[pod]

        return ("127.0.0.1", entry.local_port)

    def is_healthy(self, pod: str) -> bool:
        """Check if port-forward subprocess is alive.

        Args:
            pod: Pod name.

        Returns:
            True if subprocess is running.
        """
        if pod not in self._forwards:
            return False
        return self._forwards[pod].is_alive()

    def stop(self, pod: str) -> None:
        """Stop port-forward for a single pod.

        Args:
            pod: Pod name.
        """
        if pod in self._forwards:
            self._forwards[pod].terminate()
            del self._forwards[pod]

    def stop_all(self) -> None:
        """Stop all port-forward subprocesses."""
        for entry in self._forwards.values():
            entry.terminate()
        self._forwards.clear()

    @property
    def endpoints(self) -> dict[str, tuple[str, int]]:
        """All active endpoints as {pod: (host, port)}."""
        return {pod: self.get_endpoint(pod) for pod in self._forwards}


class _ForwardEntry:
    """Internal state for a single port-forward subprocess."""

    def __init__(
        self,
        process: subprocess.Popen,
        local_port: int,
        pod: str,
    ) -> None:
        self.process = process
        self.local_port = local_port
        self.pod = pod

    def is_alive(self) -> bool:
        return self.process.poll() is None

    def terminate(self) -> None:
        if self.is_alive():
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
