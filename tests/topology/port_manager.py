"""Host port allocation for topology deployments.

Provides sequential port allocation with xdist-aware base offsets to
prevent conflicts when running parallel test workers.
"""

from __future__ import annotations

import os
import socket


class PortManager:
    """Sequential port allocator with xdist worker isolation.

    Each xdist worker gets a non-overlapping port range:
        master: base + 0..stride-1
        gw0:    base + stride..2*stride-1
        gw1:    base + 2*stride..3*stride-1
        ...

    Args:
        base: Starting port for the master worker.
        stride: Number of ports reserved per worker.
    """

    def __init__(self, base: int = 9100, stride: int = 100) -> None:
        self._base = base
        self._stride = stride
        self._offset = self._worker_offset()
        self._next = self._base + self._offset
        self._allocated: list[int] = []

    def _worker_offset(self) -> int:
        """Calculate port offset based on xdist worker ID."""
        worker_id = os.environ.get("PYTEST_XDIST_WORKER", "master")
        if worker_id == "master":
            return 0
        # Worker IDs are gw0, gw1, gw2, ...
        try:
            worker_num = int(worker_id.replace("gw", ""))
            return (worker_num + 1) * self._stride
        except ValueError:
            return 0

    def allocate(self) -> int:
        """Allocate the next sequential port.

        Returns:
            An unused port number within this worker's range.
        """
        port = self._next
        self._next += 1
        self._allocated.append(port)
        return port

    def allocate_n(self, n: int) -> list[int]:
        """Allocate N sequential ports.

        Args:
            n: Number of ports to allocate.

        Returns:
            List of allocated port numbers.
        """
        return [self.allocate() for _ in range(n)]

    @property
    def allocated(self) -> list[int]:
        """All ports allocated so far."""
        return list(self._allocated)


def find_free_port() -> int:
    """Find an OS-assigned ephemeral port.

    Useful for kubectl port-forward where the exact port doesn't matter.

    Returns:
        A free port number (briefly held, then released).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return s.getsockname()[1]
