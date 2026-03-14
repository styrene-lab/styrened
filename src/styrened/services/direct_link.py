"""Direct data link service for persistent RNS.Link connections.

Manages outgoing RNS.Links to Styrene peers via the ("styrene", "datalink")
destination aspect.  Links are persistent, cached, and automatically
renegotiated on path changes.

This is the initialization point for the direct-highest-bandwidth-datalink
mesh system — providing low-latency request/response that bypasses LXMF
store-and-forward overhead.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from styrened.models.relay import LinkType

if TYPE_CHECKING:
    import RNS

logger = logging.getLogger(__name__)

# Timeouts — sized for LoRa multi-hop (3+ hops, SF10-SF12).
# TCP links complete in <1s; these generous defaults keep LoRa working.
PATH_DISCOVERY_TIMEOUT = 45.0
LINK_ESTABLISHMENT_TIMEOUT = 45.0
REQUEST_TIMEOUT = 30.0
# Shorter timeout for anonymous discovery probes (/meta, /info).
# These run in background without user interaction, so we don't want
# a 30s block per unreachable node.  If a node doesn't respond in
# DISCOVERY_TIMEOUT seconds it's considered unavailable for now.
DISCOVERY_TIMEOUT = 10.0
# Maximum times we'll retry a /meta probe for an unreachable node
# before giving up for the lifetime of the tree widget session.
META_MAX_RETRIES = 3
CLEANUP_INTERVAL = 120.0
IDLE_LINK_TIMEOUT = 900.0  # 15 min — link establishment is expensive on LoRa

# Maximum response body size from any datalink endpoint.  Responses larger
# than this are discarded without parsing — prevents memory exhaustion from
# malicious or buggy nodes returning unbounded JSON.
MAX_RESPONSE_BYTES = 32_768  # 32 KiB — no legitimate /meta or /info response is larger

# Field length caps for external-sourced strings rendered in the TUI.
# Prevents both markup injection and runaway label widths.
_MAX_VERSION_LEN = 32
_MAX_PROFILE_LEN = 32
_MAX_ARCH_LEN = 20
_MAX_OSID_LEN = 32
_MAX_CAP_LEN = 64
_MAX_NAME_LEN = 64
_MAX_LABEL_LEN = 64
_MAX_CAPS_COUNT = 32
_MAX_ADDRESS_LEN = 128  # Ygg IPv6 / I2P b32 addresses
_MAX_URL_LEN = 256  # web_url (HTTPS URL)

# Compiled pattern strips all Rich/Textual markup tags ([tag], [/tag], [#hex]).
_RICH_MARKUP_RE = re.compile(r"\[/?[^\]]{0,64}\]")

# Speedtest payload sets — selected by link RTT
PAYLOAD_SET_FAST = [256, 1024, 4096, 16384, 65536, 262144]  # TCP/UDP, RTT <200ms
PAYLOAD_SET_MEDIUM = [64, 256, 1024, 4096, 16384]  # WiFi mesh / fast LoRa, RTT 200ms-2s
PAYLOAD_SET_SLOW = [64, 256, 1024, 4096]  # LoRa SF7-SF9, RTT 2s-5s
PAYLOAD_SET_MINIMAL = [64, 256, 1024]  # LoRa SF10-SF12 / very slow, RTT >5s


# ---------------------------------------------------------------------------
# External-content sanitization helpers
# ---------------------------------------------------------------------------


def _sanitize_str(value: Any, max_len: int) -> str:
    """Sanitize an externally-sourced string before use in the TUI.

    Strips Rich/Textual markup tags, removes non-printable characters,
    and caps the result at *max_len* characters.  Returns ``""`` for
    non-string inputs so callers can treat a missing value and a bad
    value identically.

    This prevents a malicious remote node from injecting markup tags
    (e.g. ``[red]evil[/red]``, ``][b]`` ) into the Textual widget tree.
    """
    if not isinstance(value, str):
        return ""
    # Remove Rich markup tags — e.g. [bold], [/bold], [#ff0000]
    clean = _RICH_MARKUP_RE.sub("", value)
    # Remove non-printable characters (control chars, null bytes, etc.)
    clean = "".join(c for c in clean if c.isprintable())
    return clean[:max_len]


def _validate_meta_response(data: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and sanitize a /meta response received from a remote peer.

    Enforces:
    - Only known fields are passed through
    - All string fields are sanitized (markup stripped, length capped)
    - ``capabilities`` must be a list of strings (non-strings are dropped)
    - Non-conforming or empty responses return ``None``

    This is the single ingress point for externally-sourced meta content
    and must be called before any field is displayed or stored.
    """
    if not isinstance(data, dict):
        return None
    result: dict[str, Any] = {}
    if "styrene_version" in data:
        v = _sanitize_str(data["styrene_version"], _MAX_VERSION_LEN)
        if v:
            result["styrene_version"] = v
    if "profile" in data:
        p = _sanitize_str(data["profile"], _MAX_PROFILE_LEN)
        if p:
            result["profile"] = p
    if "capabilities" in data:
        raw_caps = data["capabilities"]
        if isinstance(raw_caps, list):
            clean_caps = [
                _sanitize_str(c, _MAX_CAP_LEN)
                for c in raw_caps
                if isinstance(c, str)
            ]
            # Drop empty strings after sanitization
            result["capabilities"] = [c for c in clean_caps if c][:_MAX_CAPS_COUNT]
        # Non-list capabilities are silently dropped
    if "arch" in data:
        result["arch"] = _sanitize_str(data["arch"], _MAX_ARCH_LEN)
    if "os_id" in data:
        result["os_id"] = _sanitize_str(data["os_id"], _MAX_OSID_LEN)
    # Overlay network addresses — sanitize but allow through
    if "ygg_address" in data:
        addr = _sanitize_str(data["ygg_address"], _MAX_ADDRESS_LEN)
        if addr:
            result["ygg_address"] = addr
    if "ygg_port" in data and isinstance(data["ygg_port"], int):
        port = data["ygg_port"]
        if 1 <= port <= 65535:
            result["ygg_port"] = port
    if "b32_address" in data:
        addr = _sanitize_str(data["b32_address"], _MAX_ADDRESS_LEN)
        if addr:
            result["b32_address"] = addr
    if "web_url" in data:
        url = _sanitize_str(data["web_url"], _MAX_URL_LEN)
        if url and url.lower().startswith(("https://", "http://")):
            result["web_url"] = url
    return result if result else None


def _validate_info_response(data: dict[str, Any]) -> dict[str, Any] | None:
    """Validate and sanitize a /info response received from a remote peer.

    Only ``name`` and ``operator_label`` are accepted.  At least one of
    them must be non-empty for the response to be considered a positive
    identification (rather than a silent decline).
    """
    if not isinstance(data, dict):
        return None
    name = _sanitize_str(data.get("name", ""), _MAX_NAME_LEN)
    label = _sanitize_str(data.get("operator_label", ""), _MAX_LABEL_LEN)
    if not name and not label:
        return None
    return {"name": name, "operator_label": label}

# Inter-test delay — longer for slow links to respect airtime
SPEEDTEST_DELAY_FAST = 0.2
SPEEDTEST_DELAY_SLOW = 2.0

# Destination aspect for Styrene direct data links
DATALINK_APP = "styrene"
DATALINK_ASPECT = "datalink"


@dataclass
class LinkInfo:
    """Public link status information."""

    destination_hash: str
    status: str  # "active", "establishing", "closed", "failed", "path_not_found", "identity_unknown"
    rtt: float | None = None  # seconds (from RNS)
    established_at: float | None = None
    last_activity: float | None = None
    link_type: LinkType = LinkType.DIRECT


@dataclass
class _LinkEntry:
    """Internal link tracking."""

    link: RNS.Link
    destination_hash: str  # keyed by LXMF dest hash (user-facing ID)
    datalink_hash: str  # the ("styrene","datalink") destination hash
    established: bool = False
    established_at: float | None = None
    last_used: float = field(default_factory=time.time)
    link_type: LinkType = LinkType.DIRECT


class DirectLinkService:
    """Manages persistent outgoing RNS.Links to Styrene peers.

    Links target the ("styrene", "datalink") destination aspect
    registered on remote daemons.  Peers are identified by their
    LXMF destination hash (the user-visible identity).
    """

    def __init__(self) -> None:
        self._links: dict[str, _LinkEntry] = {}
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._cleanup_task: asyncio.Task | None = None
        self._started = False
        self._force_path_rediscovery = False
        self._speedtest_lock: asyncio.Lock | None = None  # Created on start()

    async def start(self) -> None:
        """Start the service and background cleanup task."""
        if self._started:
            return
        self._event_loop = asyncio.get_running_loop()
        self._speedtest_lock = asyncio.Lock()
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        self._started = True
        logger.info("DirectLinkService started")

    async def stop(self) -> None:
        """Stop the service and tear down all links."""
        self._started = False
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        for entry in list(self._links.values()):
            try:
                entry.link.teardown()
            except Exception:
                pass
        self._links.clear()
        logger.info("DirectLinkService stopped")

    def handle_reconnection(self) -> None:
        """Flag path re-discovery on network reconnection."""
        self._force_path_rediscovery = True
        logger.info("[RECONNECT] DirectLinkService flagged for path re-discovery")

    async def establish(self, lxmf_destination_hash: str) -> LinkInfo:
        """Establish or retrieve a direct link to a Styrene peer.

        Args:
            lxmf_destination_hash: Peer's LXMF destination hash (hex).

        Returns:
            LinkInfo with current status.
        """
        import RNS

        # Check existing active link
        entry = self._links.get(lxmf_destination_hash)
        if entry is not None and entry.link.status == RNS.Link.ACTIVE:
            entry.last_used = time.time()
            return self._entry_to_info(entry)

        # Remove stale entry
        if entry is not None:
            try:
                entry.link.teardown()
            except Exception:
                pass
            self._links.pop(lxmf_destination_hash, None)

        # Resolve identity from the provided hash.
        # Callers may pass a destination hash OR an identity hash (the
        # NodeStore sometimes stores identity hashes in both fields).
        # Try identity recall both ways before falling back to path discovery.
        dest_hash_bytes = bytes.fromhex(lxmf_destination_hash)

        logger.info(f"Establishing link to {lxmf_destination_hash[:16]}...")

        identity = RNS.Identity.recall(dest_hash_bytes)
        if identity is None:
            logger.debug(f"recall(dest_hash) failed for {lxmf_destination_hash[:16]}")
            identity = RNS.Identity.recall(dest_hash_bytes, from_identity_hash=True)

        if identity is None:
            logger.info(
                f"Identity not in RNS cache for {lxmf_destination_hash[:16]} — "
                f"requesting path (timeout={PATH_DISCOVERY_TIMEOUT}s)"
            )
            # Identity not cached — try path discovery to trigger announce recall
            if self._force_path_rediscovery or not RNS.Transport.has_path(dest_hash_bytes):
                self._force_path_rediscovery = False
                RNS.Transport.request_path(dest_hash_bytes)
                start = time.time()
                while not RNS.Transport.has_path(dest_hash_bytes):
                    if time.time() - start > PATH_DISCOVERY_TIMEOUT:
                        logger.warning(f"Path discovery timed out for {lxmf_destination_hash[:16]}")
                        return LinkInfo(
                            destination_hash=lxmf_destination_hash,
                            status="path_not_found",
                        )
                    await asyncio.sleep(0.2)
                logger.info(f"Path found for {lxmf_destination_hash[:16]}")
            else:
                logger.info(f"Path already known for {lxmf_destination_hash[:16]}")

            # Retry recall after path discovery
            identity = RNS.Identity.recall(dest_hash_bytes)
            if identity is None:
                identity = RNS.Identity.recall(dest_hash_bytes, from_identity_hash=True)

        if identity is None:
            logger.warning(f"Identity unknown for {lxmf_destination_hash[:16]} after path discovery")
            return LinkInfo(
                destination_hash=lxmf_destination_hash,
                status="identity_unknown",
            )

        logger.info(f"Identity resolved for {lxmf_destination_hash[:16]}: {identity.hash.hex()[:16]}")

        # Compute the datalink destination (different hash from LXMF dest)
        datalink_dest = RNS.Destination(
            identity,
            RNS.Destination.OUT,
            RNS.Destination.SINGLE,
            DATALINK_APP,
            DATALINK_ASPECT,
        )
        datalink_hash = datalink_dest.hash.hex()
        logger.info(f"Datalink dest for {lxmf_destination_hash[:16]}: {datalink_hash[:16]}")

        # Request path to datalink destination (may differ from LXMF path)
        if not RNS.Transport.has_path(datalink_dest.hash):
            logger.info(f"No path to datalink {datalink_hash[:16]} — requesting...")
            RNS.Transport.request_path(datalink_dest.hash)
            start = time.time()
            while not RNS.Transport.has_path(datalink_dest.hash):
                if time.time() - start > PATH_DISCOVERY_TIMEOUT:
                    return LinkInfo(
                        destination_hash=lxmf_destination_hash,
                        status="path_not_found",
                    )
                await asyncio.sleep(0.2)

        # Create link
        link = await self._create_link(lxmf_destination_hash, datalink_dest, datalink_hash)
        if link is None:
            return LinkInfo(
                destination_hash=lxmf_destination_hash,
                status="failed",
            )

        entry = self._links.get(lxmf_destination_hash)
        if entry:
            return self._entry_to_info(entry)
        return LinkInfo(destination_hash=lxmf_destination_hash, status="failed")

    async def teardown(self, lxmf_destination_hash: str) -> bool:
        """Tear down a link to a peer."""
        entry = self._links.pop(lxmf_destination_hash, None)
        if entry is None:
            return False
        try:
            entry.link.teardown()
        except Exception:
            pass
        logger.info(f"Datalink torn down to {lxmf_destination_hash[:16]}...")
        return True

    async def request(
        self,
        lxmf_destination_hash: str,
        path: str,
        data: Any = None,
        timeout: float = REQUEST_TIMEOUT,
    ) -> bytes | None:
        """Send a generic request over a direct link.

        Args:
            lxmf_destination_hash: Target peer's LXMF dest hash.
            path: Request path (e.g. "/vpn/handshake").
            data: Request payload (bytes or serializable).
            timeout: Response timeout in seconds.

        Returns:
            Raw response bytes, or None on failure/timeout.
        """
        import RNS

        entry = self._links.get(lxmf_destination_hash)
        if not entry or entry.link.status != RNS.Link.ACTIVE:
            return None

        entry.last_used = time.time()
        response_future: asyncio.Future[bytes | None] = asyncio.Future()

        def on_response(receipt: Any) -> None:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, receipt.response),
                    self._event_loop,
                )

        def on_failed(receipt: Any) -> None:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, None),
                    self._event_loop,
                )

        try:
            entry.link.request(
                path,
                data=data,
                response_callback=on_response,
                failed_callback=on_failed,
            )
        except Exception as e:
            logger.error(f"Failed to send {path} over datalink: {e}")
            return None

        try:
            return await asyncio.wait_for(response_future, timeout=timeout)
        except TimeoutError:
            logger.warning(f"Datalink {path} timed out for {lxmf_destination_hash[:16]}...")
        except Exception as e:
            logger.warning(f"Datalink {path} error: {e}")
        return None

    async def request_status(
        self,
        lxmf_destination_hash: str,
        timeout: float = REQUEST_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Request status from peer over direct link.

        Returns:
            Status dict or None if link not active / request failed.
        """
        data = await self.request(lxmf_destination_hash, "/status", timeout=timeout)
        if data:
            try:
                result: dict[str, Any] = json.loads(data)
                return result
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Datalink /status decode error: {e}")
        return None

    async def request_meta(
        self,
        lxmf_destination_hash: str,
        timeout: float = DISCOVERY_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Request non-identifiable metadata from peer over direct link.

        Returns styrene_version, profile, capabilities, arch, os_id.
        Safe to call against any discovered node — remote default is allow.

        Returns:
            Meta dict or None if link not active / request failed.
        """
        data = await self.request(lxmf_destination_hash, "/meta", timeout=timeout)
        if data:
            if len(data) > MAX_RESPONSE_BYTES:
                logger.warning(
                    "Datalink /meta response too large (%d bytes) from %s — discarding",
                    len(data),
                    lxmf_destination_hash[:16],
                )
                return None
            try:
                raw = json.loads(data)
                if not raw:
                    return None  # Empty dict = older node without /meta support
                return _validate_meta_response(raw)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Datalink /meta decode error from %s: %s",
                               lxmf_destination_hash[:16], e)
        return None

    async def request_info(
        self,
        lxmf_destination_hash: str,
        timeout: float = DISCOVERY_TIMEOUT,
    ) -> dict[str, Any] | None:
        """Request identifiable operator metadata from peer over direct link.

        Returns name and operator_label only if the remote node has
        discovery.info_respond=True.  An empty response means the node
        declined to identify (default behaviour) — treat as anonymous.

        Returns:
            Info dict with at least one non-empty field, or None if declined/failed.
        """
        data = await self.request(lxmf_destination_hash, "/info", timeout=timeout)
        if data:
            if len(data) > MAX_RESPONSE_BYTES:
                logger.warning(
                    "Datalink /info response too large (%d bytes) from %s — discarding",
                    len(data),
                    lxmf_destination_hash[:16],
                )
                return None
            try:
                raw = json.loads(data)
                if not raw:
                    return None  # Empty dict = node declined
                return _validate_info_response(raw)
            except (json.JSONDecodeError, Exception) as e:
                logger.warning("Datalink /info decode error from %s: %s",
                               lxmf_destination_hash[:16], e)
        return None

    async def run_speedtest(
        self,
        lxmf_destination_hash: str,
        payload_sizes: list[int] | None = None,
        timeout_per_transfer: float | None = None,
    ) -> list[dict[str, Any]]:
        """Run bandwidth test over direct link with RTT-adaptive payload sizes.

        Probes link RTT first, then selects an appropriate payload set:
        - RTT <200ms (TCP/UDP): up to 256KB
        - RTT 200ms-2s (WiFi mesh): up to 16KB
        - RTT 2s-5s (fast LoRa): up to 4KB
        - RTT >5s (slow LoRa): up to 1KB

        Per-transfer timeout scales with payload size and estimated link
        throughput to avoid killing slow LoRa transfers.

        Args:
            lxmf_destination_hash: Peer LXMF destination hash.
            payload_sizes: Override automatic payload selection.
            timeout_per_transfer: Override per-transfer timeout (auto-scales if None).

        Returns:
            List of result dicts with link_rtt and per-payload metrics.
        """
        import RNS

        entry = self._links.get(lxmf_destination_hash)
        if not entry or entry.link.status != RNS.Link.ACTIVE:
            return [{"size": 0, "status": "no_link"}]

        # One speedtest at a time per service (link can't handle concurrent bulk transfers)
        if self._speedtest_lock and self._speedtest_lock.locked():
            return [{"size": 0, "status": "busy", "reason": "speedtest already running"}]

        async with self._speedtest_lock or asyncio.Lock():
            return await self._run_speedtest_inner(entry, payload_sizes, timeout_per_transfer)

    async def _run_speedtest_inner(
        self,
        entry: _LinkEntry,
        payload_sizes: list[int] | None,
        timeout_per_transfer: float | None,
    ) -> list[dict[str, Any]]:
        """Inner speedtest logic, called under lock."""
        entry.last_used = time.time()

        # Probe RTT from the link (RNS maintains this from keepalives)
        link_rtt = None
        try:
            link_rtt = entry.link.rtt
        except Exception:
            pass

        # Select payload set based on RTT
        if payload_sizes is None:
            payload_sizes = self._select_payloads(link_rtt)

        # Select inter-test delay
        delay = SPEEDTEST_DELAY_SLOW if (link_rtt and link_rtt > 0.5) else SPEEDTEST_DELAY_FAST

        results: list[dict[str, Any]] = []
        estimated_bps: float | None = None

        for size in payload_sizes:
            # Auto-scale timeout: at least 30s, or 4x estimated transfer time
            if timeout_per_transfer is not None:
                t = timeout_per_transfer
            elif estimated_bps and estimated_bps > 0:
                t = max(30.0, (size * 8 / estimated_bps) * 4)
            elif link_rtt and link_rtt > 1.0:
                # LoRa: very generous — assume ~1kbps minimum
                t = max(60.0, (size * 8 / 1000) * 3)
            else:
                t = max(30.0, size / 1000)  # ~1KB/s baseline for unknowns

            result = await self._speedtest_single(entry, size, t)
            result["link_rtt"] = link_rtt
            results.append(result)

            # Update throughput estimate from successful transfer
            if result.get("status") == "ok" and result.get("throughput_bps", 0) > 0:
                estimated_bps = result["throughput_bps"]

            # Bail early if transfer failed (link probably dead)
            if result.get("status") in ("timeout", "failed", "send_failed", "send_error"):
                # Mark remaining sizes as skipped
                idx = payload_sizes.index(size)
                for remaining in payload_sizes[idx + 1 :]:
                    results.append({
                        "size": remaining,
                        "status": "skipped",
                        "reason": f"previous {size}B transfer {result['status']}",
                    })
                break

            await asyncio.sleep(delay)

        return results

    @staticmethod
    def _select_payloads(rtt: float | None) -> list[int]:
        """Select payload sizes based on link RTT."""
        if rtt is None:
            return list(PAYLOAD_SET_MEDIUM)  # conservative default
        elif rtt < 0.2:
            return list(PAYLOAD_SET_FAST)
        elif rtt < 2.0:
            return list(PAYLOAD_SET_MEDIUM)
        elif rtt < 5.0:
            return list(PAYLOAD_SET_SLOW)
        else:
            return list(PAYLOAD_SET_MINIMAL)

    async def _speedtest_single(
        self,
        entry: _LinkEntry,
        size: int,
        timeout: float,
    ) -> dict[str, Any]:
        """Run a single speedtest transfer."""
        import os

        payload = os.urandom(size)
        response_future: asyncio.Future[tuple[bytes | None, float]] = asyncio.Future()
        send_time = time.time()

        def on_response(receipt: Any) -> None:
            recv_time = time.time()
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, (receipt.response, recv_time)),
                    self._event_loop,
                )

        def on_failed(receipt: Any) -> None:
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(response_future, (None, time.time())),
                    self._event_loop,
                )

        try:
            receipt = entry.link.request(
                "/speedtest",
                data=payload,
                response_callback=on_response,
                failed_callback=on_failed,
            )
            if receipt is False:
                return {"size": size, "status": "send_failed"}
        except Exception as e:
            logger.error(f"Speedtest send failed ({size}B): {e}")
            return {"size": size, "status": "send_error", "error": str(e)}

        try:
            resp_data, recv_time = await asyncio.wait_for(
                response_future, timeout=timeout
            )
        except TimeoutError:
            return {"size": size, "status": "timeout", "timeout": timeout}

        if resp_data is None:
            return {"size": size, "status": "failed"}

        rtt = recv_time - send_time

        # Parse peer's acknowledgement
        try:
            ack = json.loads(resp_data)
            peer_received = ack.get("bytes_received", 0)
            peer_process_ms = ack.get("process_ms", 0)
        except (json.JSONDecodeError, Exception):
            peer_received = 0
            peer_process_ms = 0

        # Calculate throughput: total bytes transferred = upload + download ack
        # But the meaningful metric is the payload size over RTT
        throughput_bps = (size * 8) / rtt if rtt > 0 else 0
        throughput_kbps = throughput_bps / 1000

        return {
            "size": size,
            "rtt": round(rtt, 4),
            "throughput_bps": round(throughput_bps),
            "throughput_kbps": round(throughput_kbps, 1),
            "peer_received": peer_received,
            "peer_process_ms": round(peer_process_ms, 2),
            "status": "ok",
        }

    def get_link_info(self, lxmf_destination_hash: str) -> LinkInfo | None:
        """Get link info for a peer, or None if no link."""
        entry = self._links.get(lxmf_destination_hash)
        if entry is None:
            return None
        return self._entry_to_info(entry)

    # Alias used by daemon relay handler
    def get_link(self, lxmf_destination_hash: str) -> LinkInfo | None:
        """Alias for get_link_info."""
        return self.get_link_info(lxmf_destination_hash)

    def set_link_type(self, lxmf_destination_hash: str, link_type: LinkType) -> None:
        """Update the link_type for a tracked link entry.

        Called by the relay handler to mark a link as RELAYED when a relay
        session is established through the hub.
        """
        entry = self._links.get(lxmf_destination_hash)
        if entry is not None:
            entry.link_type = link_type

    def get_all_links(self) -> list[LinkInfo]:
        """Get info for all managed links."""
        return [self._entry_to_info(e) for e in self._links.values()]

    def _entry_to_info(self, entry: _LinkEntry) -> LinkInfo:
        """Convert internal entry to public LinkInfo."""
        import RNS

        status_map = {
            RNS.Link.ACTIVE: "active",
            RNS.Link.PENDING: "establishing",
            RNS.Link.CLOSED: "closed",
        }
        status = status_map.get(entry.link.status, "unknown")
        rtt = None
        try:
            rtt = entry.link.rtt
        except Exception:
            pass
        return LinkInfo(
            destination_hash=entry.destination_hash,
            status=status,
            rtt=rtt,
            established_at=entry.established_at,
            last_activity=entry.last_used,
            link_type=entry.link_type,
        )

    async def _create_link(
        self,
        lxmf_destination_hash: str,
        datalink_dest: RNS.Destination,
        datalink_hash: str,
    ) -> RNS.Link | None:
        """Create and cache a new RNS.Link."""
        import RNS

        established_future: asyncio.Future[bool] = asyncio.Future()

        logger.info(
            f"Creating datalink to {lxmf_destination_hash[:16]}... "
            f"(datalink_hash={datalink_hash[:16]}...)"
        )
        link = RNS.Link(datalink_dest)

        def on_established(lnk: RNS.Link) -> None:
            logger.info(f"Datalink ESTABLISHED to {lxmf_destination_hash[:16]}...")
            if self._event_loop:
                asyncio.run_coroutine_threadsafe(
                    _resolve(established_future, True),
                    self._event_loop,
                )

        def on_closed(lnk: RNS.Link) -> None:
            logger.info(f"Datalink CLOSED to {lxmf_destination_hash[:16]}...")
            self._links.pop(lxmf_destination_hash, None)
            if self._event_loop and not established_future.done():
                asyncio.run_coroutine_threadsafe(
                    _resolve(established_future, False),
                    self._event_loop,
                )

        link.set_link_established_callback(on_established)
        link.set_link_closed_callback(on_closed)

        try:
            success = await asyncio.wait_for(
                established_future, timeout=LINK_ESTABLISHMENT_TIMEOUT
            )
        except TimeoutError:
            logger.warning(f"Datalink establishment timed out for {lxmf_destination_hash[:16]}...")
            try:
                link.teardown()
            except Exception:
                pass
            return None

        if not success:
            return None

        now = time.time()
        self._links[lxmf_destination_hash] = _LinkEntry(
            link=link,
            destination_hash=lxmf_destination_hash,
            datalink_hash=datalink_hash,
            established=True,
            established_at=now,
            last_used=now,
        )
        return link

    async def _cleanup_loop(self) -> None:
        """Background task to tear down idle links."""
        try:
            while self._started:
                await asyncio.sleep(CLEANUP_INTERVAL)
                now = time.time()
                stale = [
                    dh
                    for dh, entry in self._links.items()
                    if now - entry.last_used > IDLE_LINK_TIMEOUT
                ]
                for dh in stale:
                    entry = self._links.pop(dh, None)
                    if entry:
                        try:
                            entry.link.teardown()
                        except Exception:
                            pass
                        logger.debug(f"Cleaned up idle datalink to {dh[:16]}...")
        except asyncio.CancelledError:
            pass


async def _resolve(future: asyncio.Future, value: object) -> None:
    """Safely resolve a future if not already done."""
    try:
        future.set_result(value)
    except asyncio.InvalidStateError:
        pass  # Already resolved by another callback
