"""Unit tests for AdapterRegistry, AdapterProtocol ABC, and WarmupBehavior."""

from __future__ import annotations

import pytest

from styrened.services.adapter_registry import (
    AdapterProtocol,
    AdapterRegistry,
    AdapterState,
    AdapterStateRecord,
    WarmupBehavior,
)

# ---------------------------------------------------------------------------
# Helpers — concrete adapter stubs for testing
# ---------------------------------------------------------------------------

class _StubAdapter(AdapterProtocol):
    """Minimal concrete adapter for registry tests."""

    def __init__(self, aid: str = "stub", state: AdapterState = AdapterState.READY) -> None:
        self._id = aid
        self._state = state

    @property
    def adapter_id(self) -> str:
        return self._id

    @property
    def warmup_behavior(self) -> WarmupBehavior:
        return WarmupBehavior(expected_seconds=30.0, actionable=True, description="Test warmup")

    async def probe(self) -> AdapterState:
        return self._state


class _NoWarmupAdapter(AdapterProtocol):
    """Adapter with no warm-up phase."""

    @property
    def adapter_id(self) -> str:
        return "no_warmup"

    @property
    def warmup_behavior(self) -> WarmupBehavior:
        return WarmupBehavior(expected_seconds=0.0, actionable=False)

    async def probe(self) -> AdapterState:
        return AdapterState.READY


class _DisabledAdapter(AdapterProtocol):
    """Adapter that always reports DISABLED."""

    @property
    def adapter_id(self) -> str:
        return "disabled_net"

    @property
    def warmup_behavior(self) -> WarmupBehavior:
        return WarmupBehavior()

    async def probe(self) -> AdapterState:
        return AdapterState.DISABLED


# ---------------------------------------------------------------------------
# ABC compliance
# ---------------------------------------------------------------------------

class TestAdapterProtocolABC:
    def test_cannot_instantiate_abstract_class(self):
        """AdapterProtocol cannot be instantiated directly."""
        with pytest.raises(TypeError):
            AdapterProtocol()  # type: ignore[abstract]

    def test_concrete_subclass_missing_adapter_id_raises(self):
        """Subclass missing adapter_id abstract property raises TypeError."""
        class _Bad(AdapterProtocol):
            @property
            def warmup_behavior(self) -> WarmupBehavior:
                return WarmupBehavior()

            async def probe(self) -> AdapterState:
                return AdapterState.READY

        with pytest.raises(TypeError):
            _Bad()  # type: ignore[abstract]

    def test_concrete_subclass_missing_probe_raises(self):
        """Subclass missing probe() abstract method raises TypeError."""
        class _Bad(AdapterProtocol):
            @property
            def adapter_id(self) -> str:
                return "bad"

            @property
            def warmup_behavior(self) -> WarmupBehavior:
                return WarmupBehavior()

        with pytest.raises(TypeError):
            _Bad()  # type: ignore[abstract]

    def test_concrete_subclass_missing_warmup_behavior_raises(self):
        """Subclass missing warmup_behavior abstract property raises TypeError."""
        class _Bad(AdapterProtocol):
            @property
            def adapter_id(self) -> str:
                return "bad"

            async def probe(self) -> AdapterState:
                return AdapterState.READY

        with pytest.raises(TypeError):
            _Bad()  # type: ignore[abstract]

    def test_valid_concrete_subclass_instantiates(self):
        """A fully implemented subclass instantiates without error."""
        adapter = _StubAdapter()
        assert adapter.adapter_id == "stub"

    def test_default_gather_details_returns_empty_dict(self):
        """gather_details() default returns empty dict."""
        import asyncio
        adapter = _StubAdapter()
        result = asyncio.run(adapter.gather_details())
        assert result == {}

    def test_probe_returns_adapter_state(self):
        """probe() returns an AdapterState value."""
        import asyncio
        adapter = _StubAdapter(state=AdapterState.DEGRADED)
        result = asyncio.run(adapter.probe())
        assert result == AdapterState.DEGRADED


# ---------------------------------------------------------------------------
# WarmupBehavior
# ---------------------------------------------------------------------------

class TestWarmupBehavior:
    def test_default_values(self):
        wb = WarmupBehavior()
        assert wb.expected_seconds == 0.0
        assert wb.actionable is False
        assert wb.description == ""

    def test_custom_values(self):
        wb = WarmupBehavior(expected_seconds=480.0, actionable=True, description="i2p warmup")
        assert wb.expected_seconds == 480.0
        assert wb.actionable is True
        assert wb.description == "i2p warmup"

    def test_non_actionable_warmup(self):
        """Non-actionable warmup is valid — informational only."""
        wb = WarmupBehavior(expected_seconds=10.0, actionable=False, description="Quick probe")
        assert wb.actionable is False

    def test_zero_warmup_is_valid(self):
        """expected_seconds=0.0 is valid for adapters with no warm-up phase."""
        wb = WarmupBehavior(expected_seconds=0.0)
        assert wb.expected_seconds == 0.0


# ---------------------------------------------------------------------------
# AdapterState enum
# ---------------------------------------------------------------------------

class TestAdapterState:
    def test_all_states_defined(self):
        states = {s.value for s in AdapterState}
        assert states == {"ready", "warming", "degraded", "probing", "disabled"}

    def test_state_values_match_eventbus_actions(self):
        """State values must match adapter_changed EventBus action strings."""
        assert AdapterState.READY.value == "ready"
        assert AdapterState.WARMING.value == "warming"
        assert AdapterState.DEGRADED.value == "degraded"
        assert AdapterState.PROBING.value == "probing"
        assert AdapterState.DISABLED.value == "disabled"


# ---------------------------------------------------------------------------
# AdapterRegistry — registration
# ---------------------------------------------------------------------------

class TestAdapterRegistryRegistration:
    def test_register_adapter(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        assert "stub" in reg

    def test_duplicate_registration_raises(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        with pytest.raises(ValueError, match="already registered"):
            reg.register(_StubAdapter())

    def test_initial_state_is_probing(self):
        """Newly registered adapters start in PROBING state."""
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        record = reg.get("stub")
        assert record is not None
        assert record.state == AdapterState.PROBING

    def test_unregister_adapter(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        reg.unregister("stub")
        assert "stub" not in reg
        assert reg.get("stub") is None

    def test_unregister_unknown_raises(self):
        reg = AdapterRegistry()
        with pytest.raises(KeyError):
            reg.unregister("nonexistent")

    def test_len_reflects_registered_adapters(self):
        reg = AdapterRegistry()
        assert len(reg) == 0
        reg.register(_StubAdapter("a"))
        reg.register(_StubAdapter("b"))
        assert len(reg) == 2

    def test_adapter_ids_sorted(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter("z"))
        reg.register(_StubAdapter("a"))
        reg.register(_StubAdapter("m"))
        assert reg.adapter_ids() == ["a", "m", "z"]

    def test_get_adapter_returns_instance(self):
        reg = AdapterRegistry()
        adapter = _StubAdapter()
        reg.register(adapter)
        assert reg.get_adapter("stub") is adapter

    def test_get_adapter_unknown_returns_none(self):
        reg = AdapterRegistry()
        assert reg.get_adapter("nope") is None


# ---------------------------------------------------------------------------
# AdapterRegistry — get_all()
# ---------------------------------------------------------------------------

class TestAdapterRegistryGetAll:
    def test_get_all_empty(self):
        reg = AdapterRegistry()
        assert reg.get_all() == []

    def test_get_all_returns_all_records(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter("i2p"))
        reg.register(_StubAdapter("ygg"))
        records = reg.get_all()
        assert len(records) == 2
        ids = {r.adapter_id for r in records}
        assert ids == {"i2p", "ygg"}

    def test_get_all_includes_disabled_adapters(self):
        """DISABLED adapters must not be hidden from get_all()."""
        reg = AdapterRegistry()
        reg.register(_DisabledAdapter())
        reg.update_state("disabled_net", AdapterState.DISABLED)
        records = reg.get_all()
        assert len(records) == 1
        assert records[0].state == AdapterState.DISABLED

    def test_get_all_returns_snapshot(self):
        """Mutating the returned list does not affect the registry."""
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        records = reg.get_all()
        records.clear()
        assert len(reg.get_all()) == 1

    def test_get_all_reflects_updated_states(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter("i2p"))
        reg.update_state("i2p", AdapterState.READY, details={"peers": 5})
        records = reg.get_all()
        assert records[0].state == AdapterState.READY
        assert records[0].details == {"peers": 5}


# ---------------------------------------------------------------------------
# AdapterRegistry — update_state()
# ---------------------------------------------------------------------------

class TestAdapterRegistryUpdateState:
    def test_update_state_changes_record(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        reg.update_state("stub", AdapterState.READY)
        assert reg.get("stub").state == AdapterState.READY  # type: ignore[union-attr]

    def test_update_state_sets_details(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        reg.update_state("stub", AdapterState.WARMING, details={"elapsed": 30})
        record = reg.get("stub")
        assert record is not None
        assert record.details == {"elapsed": 30}

    def test_update_state_sets_error(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        reg.update_state("stub", AdapterState.DEGRADED, error="probe timeout")
        record = reg.get("stub")
        assert record is not None
        assert record.error == "probe timeout"

    def test_update_state_unknown_raises(self):
        reg = AdapterRegistry()
        with pytest.raises(KeyError):
            reg.update_state("nope", AdapterState.READY)

    def test_update_state_returns_record(self):
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        record = reg.update_state("stub", AdapterState.PROBING)
        assert isinstance(record, AdapterStateRecord)
        assert record.state == AdapterState.PROBING

    def test_update_state_refreshes_updated_at(self):
        import time
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        before = time.monotonic()
        record = reg.update_state("stub", AdapterState.READY)
        after = time.monotonic()
        assert before <= record.updated_at <= after

    def test_update_state_empty_details_default(self):
        """Not passing details defaults to empty dict, not None."""
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        record = reg.update_state("stub", AdapterState.READY)
        assert record.details == {}

    def test_update_state_no_error_default(self):
        """Not passing error defaults to None."""
        reg = AdapterRegistry()
        reg.register(_StubAdapter())
        record = reg.update_state("stub", AdapterState.READY)
        assert record.error is None


# ---------------------------------------------------------------------------
# AdapterStateRecord
# ---------------------------------------------------------------------------

class TestAdapterStateRecord:
    def test_defaults(self):
        import time
        before = time.monotonic()
        record = AdapterStateRecord(adapter_id="x", state=AdapterState.PROBING)
        after = time.monotonic()
        assert record.details == {}
        assert record.error is None
        assert before <= record.updated_at <= after

    def test_all_fields(self):
        record = AdapterStateRecord(
            adapter_id="i2p",
            state=AdapterState.READY,
            details={"peers": 7},
            updated_at=1.0,
            error=None,
        )
        assert record.adapter_id == "i2p"
        assert record.state == AdapterState.READY
        assert record.details == {"peers": 7}
        assert record.updated_at == 1.0


# ---------------------------------------------------------------------------
# EventBus docstring — adapter_changed event type is documented
# ---------------------------------------------------------------------------

class TestEventBusDocstring:
    def test_adapter_changed_in_event_bus_docstring(self):
        """The EventBus docstring must document adapter_changed as a 6th type."""
        from styrened.services.event_bus import EventBus
        doc = EventBus.__module__
        import importlib
        mod = importlib.import_module(doc)
        assert "adapter_changed" in (mod.__doc__ or ""), (
            "adapter_changed must be listed in event_bus module docstring"
        )
