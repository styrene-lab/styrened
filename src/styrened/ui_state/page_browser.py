"""Canonical page-browser session state."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from styrened.ui_state.base import CapabilityState, LoadState, RefreshMeta


class PageTransport(StrEnum):
    """Canonical transport selected for a page session."""

    NOMADNET = "nomadnet"
    HTTPS = "https"
    I2P = "i2p"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PageActionCapabilities:
    """Actions exposed by the current page session."""

    can_go_back: bool = False
    can_reload: bool = True
    can_save_site: bool = False
    can_crawl_site: bool = False
    can_submit_forms: bool = False


@dataclass(frozen=True)
class PageBrowserSessionState:
    """Canonical page-browser session state separate from rendering concerns."""

    transport: PageTransport = PageTransport.UNKNOWN
    location: str | None = None
    destination_hash: str | None = None
    external_url: str | None = None
    history: tuple[str, ...] = ()
    cache_fallback_used: bool = False
    cache_capability: CapabilityState = CapabilityState.UNSUPPORTED
    action_capabilities: PageActionCapabilities = field(default_factory=PageActionCapabilities)
    status: str = "idle"
    error_message: str | None = None
    refresh: RefreshMeta = field(default_factory=RefreshMeta)


@dataclass(frozen=True)
class PageBrowserSessionInputs:
    """Authoritative inputs for page-browser session state construction."""

    destination_hash: str | None = None
    current_path: str | None = None
    external_url: str | None = None
    history: tuple[str, ...] = ()
    status: str = "idle"
    cache_fallback_used: bool = False
    cache_available: bool = False
    can_submit_forms: bool = False
    error_message: str | None = None
    now: float | None = None


def _infer_transport(inputs: PageBrowserSessionInputs) -> PageTransport:
    if inputs.external_url:
        url = inputs.external_url.lower()
        if ".i2p" in url:
            return PageTransport.I2P
        if url.startswith("http://") or url.startswith("https://"):
            return PageTransport.HTTPS
    if inputs.destination_hash:
        return PageTransport.NOMADNET
    return PageTransport.UNKNOWN


def _location(inputs: PageBrowserSessionInputs) -> str | None:
    if inputs.external_url:
        return inputs.external_url
    if inputs.destination_hash:
        path = inputs.current_path or "/page/index.mu"
        return f"{inputs.destination_hash}:{path}"
    return inputs.current_path


def build_page_browser_session_state(
    inputs: PageBrowserSessionInputs,
) -> PageBrowserSessionState:
    """Build canonical page-browser session state."""
    import time

    transport = _infer_transport(inputs)
    cache_capability = (
        CapabilityState.AVAILABLE if inputs.cache_available else CapabilityState.UNSUPPORTED
    )
    is_nomadnet = transport is PageTransport.NOMADNET
    now = inputs.now if inputs.now is not None else time.time()

    return PageBrowserSessionState(
        transport=transport,
        location=_location(inputs),
        destination_hash=inputs.destination_hash,
        external_url=inputs.external_url,
        history=tuple(inputs.history),
        cache_fallback_used=inputs.cache_fallback_used,
        cache_capability=cache_capability,
        action_capabilities=PageActionCapabilities(
            can_go_back=bool(inputs.history),
            can_reload=True,
            can_save_site=is_nomadnet,
            can_crawl_site=is_nomadnet,
            can_submit_forms=bool(inputs.can_submit_forms),
        ),
        status=inputs.status,
        error_message=inputs.error_message,
        refresh=RefreshMeta(
            load_state=LoadState.READY if inputs.status != "error" else LoadState.ERROR,
            refreshed_at=now,
            error_message=inputs.error_message,
        ),
    )
