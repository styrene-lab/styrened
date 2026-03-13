"""AdapterRegistry — open, extensibility-first registry for network adapters.

Design decisions:
- Adapter registration interface is a Protocol/ABC — each adapter class
  implements AdapterProtocol directly.
- The registry is open: not hardcoded to I2P/Yggdrasil.
- DISABLED adapters remain visible with inactive state — not hidden.
- Warm-up actionability is per-adapter — no universal WARMING behavior.
- Adapter status reflects actual probe reality; state is set explicitly by
  the probe loop, not inferred from cached data.
- adapter_changed is a 6th EventBus top-level type emitted on every
  meaningful state transition.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AdapterState(Enum):
    """Operational state of a network adapter.

    Values mirror the ``adapter_changed`` EventBus action strings so that
    the probe loop can emit events without a lookup table.
    """

    READY = "ready"
    WARMING = "warming"
    DEGRADED = "degraded"
    PROBING = "probing"
    DISABLED = "disabled"


@dataclass
class WarmupBehavior:
    """Per-adapter warm-up configuration.

    Attributes:
        expected_seconds: Expected duration of the warm-up phase.  The probe
            loop uses this to determine whether a WARMING state is still
            within normal bounds.
        actionable: When ``True``, the TUI renders an affordance (e.g.
            "Warming up…") so the operator knows the adapter will become
            ready.  When ``False``, the state is purely informational.
        description: Human-readable description shown in the TUI warm-up
            tooltip or situation line.
    """

    expected_seconds: float = 0.0
    actionable: bool = False
    description: str = ""


@dataclass
class AdapterStateRecord:
    """Point-in-time snapshot of an adapter's reported state.

    Instances are stored inside AdapterRegistry and updated by the probe
    loop on each cycle.  Consumers (TUI, EventBus) read from here; they
    never mutate it directly.

    Attributes:
        adapter_id: Stable identifier matching ``AdapterProtocol.adapter_id``.
        state: Current operational state.
        details: Adapter-specific detail dict (addresses, peer counts, etc.).
        updated_at: Monotonic timestamp of the last probe that set this record.
        error: Optional human-readable error string when state is DEGRADED.
    """

    adapter_id: str
    state: AdapterState
    details: dict[str, Any] = field(default_factory=dict)
    updated_at: float = field(default_factory=time.monotonic)
    error: str | None = None


class AdapterProtocol(ABC):
    """Abstract base class for network adapters managed by AdapterRegistry.

    Every adapter class implements this interface directly — no separate
    wrapper objects.  The registry calls ``probe()`` on a schedule and
    records the returned state.

    Subclasses must:
    1. Define a stable ``adapter_id`` property (e.g. ``"i2p"``, ``"ygg"``).
    2. Implement ``probe()`` to return the current ``AdapterState``.
    3. Implement ``warmup_behavior`` to describe warm-up characteristics.
    4. Optionally override ``gather_details()`` for rich status payloads.
    """

    @property
    @abstractmethod
    def adapter_id(self) -> str:
        """Stable, lowercase identifier for this adapter (e.g. ``"i2p"``)."""

    @property
    @abstractmethod
    def warmup_behavior(self) -> WarmupBehavior:
        """Per-adapter warm-up configuration."""

    @abstractmethod
    async def probe(self) -> AdapterState:
        """Probe the adapter and return its current ``AdapterState``."""

    async def gather_details(self) -> dict[str, Any]:
        """Return a detail dict for inclusion in ``AdapterStateRecord``.

        The default implementation returns an empty dict.  Override to
        provide richer data (e.g. peer counts, tunnel count, proxy port).
        """
        return {}


class AdapterRegistry:
    """Open registry of :class:`AdapterProtocol` instances.

    The registry stores one :class:`AdapterStateRecord` per adapter.
    The probe loop (in the daemon service layer) calls
    :meth:`update_state` after each ``probe()`` invocation.

    Usage::

        registry = AdapterRegistry()
        registry.register(my_adapter)
        registry.update_state("i2p", AdapterState.READY, details={"peers": 12})
        record = registry.get("i2p")
        all_records = registry.get_all()
    """

    def __init__(self) -> None:
        self._adapters: dict[str, AdapterProtocol] = {}
        self._records: dict[str, AdapterStateRecord] = {}

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register(self, adapter: AdapterProtocol) -> None:
        """Register an adapter with the registry.

        The adapter is initialised with an :attr:`AdapterState.PROBING`
        record so it is immediately visible to consumers before the first
        probe cycle completes.

        Args:
            adapter: An :class:`AdapterProtocol` implementation.

        Raises:
            ValueError: If an adapter with the same ``adapter_id`` is
                already registered.
        """
        aid = adapter.adapter_id
        if aid in self._adapters:
            raise ValueError(f"Adapter already registered: {aid!r}")
        self._adapters[aid] = adapter
        self._records[aid] = AdapterStateRecord(
            adapter_id=aid,
            state=AdapterState.PROBING,
        )

    def unregister(self, adapter_id: str) -> None:
        """Remove an adapter from the registry.

        Args:
            adapter_id: The ``adapter_id`` of the adapter to remove.

        Raises:
            KeyError: If the adapter is not registered.
        """
        if adapter_id not in self._adapters:
            raise KeyError(f"Adapter not registered: {adapter_id!r}")
        del self._adapters[adapter_id]
        del self._records[adapter_id]

    # ------------------------------------------------------------------
    # State updates (called by the probe loop)
    # ------------------------------------------------------------------

    def update_state(
        self,
        adapter_id: str,
        state: AdapterState,
        *,
        details: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> AdapterStateRecord:
        """Record the result of a probe cycle for an adapter.

        Args:
            adapter_id: The adapter to update.
            state: The new ``AdapterState``.
            details: Optional adapter-specific detail dict.
            error: Optional error string (typically set when state is
                ``AdapterState.DEGRADED``).

        Returns:
            The updated :class:`AdapterStateRecord`.

        Raises:
            KeyError: If the adapter is not registered.
        """
        if adapter_id not in self._records:
            raise KeyError(f"Adapter not registered: {adapter_id!r}")
        record = AdapterStateRecord(
            adapter_id=adapter_id,
            state=state,
            details=details or {},
            updated_at=time.monotonic(),
            error=error,
        )
        self._records[adapter_id] = record
        return record

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get(self, adapter_id: str) -> AdapterStateRecord | None:
        """Return the current state record for an adapter, or ``None``."""
        return self._records.get(adapter_id)

    def get_all(self) -> list[AdapterStateRecord]:
        """Return a snapshot of all registered adapter state records.

        Includes adapters in any state — DISABLED adapters are not hidden.
        """
        return list(self._records.values())

    def get_adapter(self, adapter_id: str) -> AdapterProtocol | None:
        """Return the registered adapter instance, or ``None``."""
        return self._adapters.get(adapter_id)

    def adapter_ids(self) -> list[str]:
        """Return the sorted list of registered adapter IDs."""
        return sorted(self._adapters)

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, adapter_id: object) -> bool:
        return adapter_id in self._adapters
