"""Terminal service for styrened (server-side).

Handles terminal session requests from clients, manages PTY allocation,
and bridges terminal I/O over RNS Links.

Architecture:
    1. Client sends TERMINAL_REQUEST via LXMF (Styrene protocol)
    2. Service validates identity against authorized_identities
    3. Service allocates PTY and forks shell process
    4. Service responds with TERMINAL_ACCEPT containing Link destination
    5. Client establishes RNS Link for data plane
    6. Bidirectional I/O flows over Link until session ends

Usage:
    from styrened.terminal import TerminalService

    service = TerminalService(
        rns_service=rns_service,
        styrene_protocol=styrene_protocol,
        authorized_identities={"abc123...", "def456..."},
    )
    service.start()
"""

import asyncio
import fcntl
import logging
import os
import pty
import random
import shutil
import signal
import struct
import termios
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from styrened.models.styrene_wire import (
    StyreneEnvelope,
    StyreneMessageType,
    create_terminal_accept,
    create_terminal_closed,
    create_terminal_reject,
    decode_payload,
)
from styrened.protocols.base import LXMFMessage
from styrened.terminal.messages import (
    CommandExited,
    StreamData,
    VersionInfo,
    WindowSize,
    deserialize_message,
    register_message_types,
    serialize_message,
)

if TYPE_CHECKING:
    import RNS

    from styrened.protocols.styrene import StyreneProtocol
    from styrened.services.rns_service import RNSService

logger = logging.getLogger(__name__)

# Default shell if not specified
DEFAULT_SHELL = "/bin/bash"

# Default allowed shells for command validation
DEFAULT_ALLOWED_SHELLS: frozenset[str] = frozenset(
    {
        "/bin/bash",
        "/bin/sh",
        "/bin/zsh",
    }
)

# PTY read buffer size
PTY_READ_SIZE = 4096

# Session timeout (no data) in seconds
SESSION_IDLE_TIMEOUT = 3600  # 1 hour

# Rate limiting defaults
DEFAULT_MAX_SESSIONS_PER_IDENTITY = 5
DEFAULT_MAX_TOTAL_SESSIONS = 20
DEFAULT_SESSION_REQUEST_RATE_LIMIT = 10  # requests per minute per identity
RATE_LIMIT_WINDOW_SECONDS = 60

# Signal whitelist for terminal sessions
# These signals are safe for clients to send to their terminal processes
DEFAULT_ALLOWED_SIGNALS: frozenset[int] = frozenset(
    {
        signal.SIGINT,  # 2 - Interrupt (Ctrl+C)
        signal.SIGTERM,  # 15 - Termination request
        signal.SIGHUP,  # 1 - Hangup
        signal.SIGTSTP,  # 20 - Terminal stop (Ctrl+Z)
        signal.SIGCONT,  # 18 - Continue if stopped
        signal.SIGWINCH,  # 28 - Window size change
    }
)

# Signals that are explicitly dangerous and should never be allowed from clients
# These can bypass process cleanup, ignore signal handlers, or cause system issues
BLOCKED_SIGNALS: frozenset[int] = frozenset(
    {
        signal.SIGKILL,  # 9 - Unconditional kill (cannot be caught)
        signal.SIGSTOP,  # 19 - Unconditional stop (cannot be caught)
        signal.SIGQUIT,  # 3 - Quit with core dump
    }
)

# Identity verification retry configuration
# Used during Link establishment to handle race conditions where
# get_remote_identity() may return None before Link is fully established
# Identity verification may take a round-trip for the identity proof
# to be sent and verified, so we need to retry with reasonable delays
IDENTITY_VERIFICATION_RETRIES = 10
IDENTITY_VERIFICATION_DELAY_MS = 200

# Maximum packets to queue during link association
# Prevents memory exhaustion from malicious clients flooding packets
MAX_PENDING_PACKETS = 10

# Handoff timeout for sessions waiting for Link establishment
# Sessions without a Link after this time are closed to prevent DoS
HANDOFF_TIMEOUT_SECONDS = 30

# Idle check interval in seconds
IDLE_CHECK_INTERVAL = 60


@dataclass
class TerminalSession:
    """Active terminal session state.

    Attributes:
        session_id: Unique session identifier
        source_identity: RNS identity hash of the client
        master_fd: PTY master file descriptor
        child_pid: Shell/command process ID
        link: RNS Link for data plane (set when client connects)
        term_type: Terminal type (TERM env var)
        rows: Terminal height
        cols: Terminal width
        created_at: Unix timestamp of session creation
        last_activity: Unix timestamp of last activity (data received/sent)
    """

    session_id: bytes
    source_identity: str
    master_fd: int
    child_pid: int
    link: "RNS.Link | None" = None
    channel: "RNS.Channel.Channel | None" = field(default=None, repr=False)
    protocol_version: str = "1.0"
    term_type: str = "xterm-256color"
    rows: int = 24
    cols: int = 80
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    _read_task: asyncio.Task | None = field(default=None, repr=False)
    _closed: bool = field(default=False, repr=False)  # Prevent double-close
    _association_pending: bool = field(
        default=False, repr=False
    )  # Prevent concurrent Link association

    def update_activity(self) -> None:
        """Update last_activity timestamp to current time."""
        old_activity = self.last_activity
        self.last_activity = time.time()
        logger.debug(
            f"[METRICS] session={self.session_id.hex()[:16]} activity_update "
            f"idle_seconds={self.last_activity - old_activity:.2f}"
        )

    def set_window_size(self, rows: int, cols: int, xpixel: int = 0, ypixel: int = 0) -> None:
        """Update PTY window size.

        Args:
            rows: Terminal height
            cols: Terminal width
            xpixel: Width in pixels (optional)
            ypixel: Height in pixels (optional)
        """
        session_hex = self.session_id.hex()[:16]

        # Validate dimension ranges for struct.pack("HHHH") - unsigned short (0-65535)
        # Terminal dimensions must be at least 1x1
        if not isinstance(rows, int) or not isinstance(cols, int):
            logger.warning(
                f"[METRICS] session={session_hex} window_resize_rejected "
                f"reason=invalid_types rows={type(rows).__name__} cols={type(cols).__name__}"
            )
            return
        if not (1 <= rows <= 65535 and 1 <= cols <= 65535):
            logger.warning(
                f"[METRICS] session={session_hex} window_resize_rejected "
                f"reason=out_of_range rows={rows} cols={cols}"
            )
            return

        # Sanitize pixel values (optional, less critical)
        if not isinstance(xpixel, int) or not (0 <= xpixel <= 65535):
            xpixel = 0
        if not isinstance(ypixel, int) or not (0 <= ypixel <= 65535):
            ypixel = 0

        old_rows, old_cols = self.rows, self.cols
        self.rows = rows
        self.cols = cols
        logger.debug(
            f"[METRICS] session={session_hex} window_resize "
            f"old={old_cols}x{old_rows} new={cols}x{rows}"
        )
        try:
            winsize = struct.pack("HHHH", rows, cols, xpixel, ypixel)
            fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)
            logger.debug(f"[METRICS] session={session_hex} pty_resize_success")
        except OSError as e:
            logger.warning(f"[METRICS] session={session_hex} pty_resize_failed error={e}")


class TerminalService:
    """Terminal session service for styrened.

    Manages terminal sessions requested by remote clients. Handles:
    - Session request validation (identity-based authorization)
    - PTY allocation and process management
    - RNS Link establishment for data plane
    - Bidirectional I/O bridging

    Attributes:
        rns_service: RNS service for Link management
        styrene_protocol: Styrene protocol for LXMF messaging
        authorized_identities: Set of identity hashes allowed to connect
        default_shell: Default shell for new sessions
        sessions: Active sessions by session_id
        session_idle_timeout: Idle timeout in seconds (default: 3600)
    """

    def __init__(
        self,
        rns_service: "RNSService",
        styrene_protocol: "StyreneProtocol",
        authorized_identities: set[str] | None = None,
        authorized_identities_file: Path | None = None,
        default_shell: str = DEFAULT_SHELL,
        allow_unauthenticated: bool = False,
        allowed_signals: frozenset[int] | None = None,
        max_sessions_per_identity: int = DEFAULT_MAX_SESSIONS_PER_IDENTITY,
        max_total_sessions: int = DEFAULT_MAX_TOTAL_SESSIONS,
        session_request_rate_limit: int = DEFAULT_SESSION_REQUEST_RATE_LIMIT,
        session_idle_timeout: float = SESSION_IDLE_TIMEOUT,
        allowed_shells: set[str] | None = None,
        allowed_commands: set[str] | None = None,
        disable_command_validation: bool = False,
    ):
        """Initialize terminal service.

        Args:
            rns_service: RNS service for network operations
            styrene_protocol: Styrene protocol for message handling
            authorized_identities: Set of identity hashes allowed to connect
            authorized_identities_file: Path to file containing authorized identities
            default_shell: Default shell for new sessions
            allow_unauthenticated: If True, allow connections when no identities are
                configured. DANGEROUS - only for development. Default: False (fail-closed).
            allowed_signals: Set of signal numbers that clients can send to terminal
                processes. Defaults to DEFAULT_ALLOWED_SIGNALS (SIGINT, SIGTERM, SIGHUP,
                SIGTSTP, SIGCONT, SIGWINCH). Dangerous signals like SIGKILL, SIGSTOP,
                SIGQUIT are always blocked regardless of this setting.
            max_sessions_per_identity: Maximum concurrent sessions per identity (default: 5)
            max_total_sessions: Maximum total concurrent sessions (default: 20)
            session_request_rate_limit: Maximum session requests per minute per identity (default: 10)
            session_idle_timeout: Session idle timeout in seconds. Sessions with no
                activity for this duration will be closed. Default: 3600 (1 hour).
            allowed_shells: Set of allowed shell paths. Defaults to /bin/bash, /bin/sh, /bin/zsh.
                Paths are resolved to absolute paths for comparison.
            allowed_commands: Set of allowed command paths. If None (default), only shells
                are allowed (no arbitrary command execution). If empty set, no commands
                are allowed. Paths are resolved to absolute paths for comparison.
            disable_command_validation: If True, skip command validation entirely.
                DANGEROUS - allows arbitrary command execution. Default: False.
        """
        self.rns_service = rns_service
        self.styrene_protocol = styrene_protocol
        self.default_shell = default_shell
        self.sessions: dict[bytes, TerminalSession] = {}
        self._allow_unauthenticated = allow_unauthenticated
        self.session_idle_timeout = session_idle_timeout

        # Signal whitelist - remove any blocked signals from the allowed set
        provided_signals = (
            allowed_signals if allowed_signals is not None else DEFAULT_ALLOWED_SIGNALS
        )
        self._allowed_signals: frozenset[int] = provided_signals - BLOCKED_SIGNALS

        # Command validation
        self._disable_command_validation = disable_command_validation
        self._allowed_shells: frozenset[str] = (
            frozenset(allowed_shells) if allowed_shells is not None else DEFAULT_ALLOWED_SHELLS
        )
        self._allowed_commands: frozenset[str] | None = (
            frozenset(allowed_commands) if allowed_commands is not None else None
        )

        if disable_command_validation:
            logger.warning(
                "TerminalService command validation DISABLED - "
                "arbitrary command execution allowed (DANGEROUS)"
            )
        else:
            logger.info(
                f"TerminalService command validation enabled: "
                f"{len(self._allowed_shells)} shells, "
                f"{len(self._allowed_commands) if self._allowed_commands else 0} commands"
            )

        # Idle check background task
        self._idle_check_task: asyncio.Task | None = None

        # Event loop reference for thread-safe callbacks from RNS
        self._event_loop: asyncio.AbstractEventLoop | None = None

        # Rate limiting configuration
        self._max_sessions_per_identity = max_sessions_per_identity
        self._max_total_sessions = max_total_sessions
        self._session_request_rate_limit = session_request_rate_limit

        # Rate limiting tracking structures
        self._sessions_by_identity: dict[str, list[bytes]] = {}
        self._request_timestamps: dict[str, list[float]] = {}

        # Identity authorization
        self._authorized_identities: set[str] = authorized_identities or set()
        self._authorized_identities_file = authorized_identities_file
        if authorized_identities_file:
            self._load_authorized_identities()

        # RNS Link destination for data plane connections
        self._link_destination: RNS.Destination | None = None

        # Registered with styrene protocol
        self._registered = False

        if not self._authorized_identities and not allow_unauthenticated:
            logger.warning(
                "[METRICS] terminal_service_init mode=fail_closed "
                "authorized_identities=0 - all connections will be REJECTED"
            )
        elif allow_unauthenticated:
            logger.warning(
                "[METRICS] terminal_service_init mode=unauthenticated "
                "authorized_identities=0 - all connections will be ALLOWED (DANGEROUS)"
            )
        else:
            logger.info(
                f"[METRICS] terminal_service_init mode=authorized "
                f"authorized_identities={len(self._authorized_identities)} "
                f"max_sessions_per_identity={max_sessions_per_identity} "
                f"max_total_sessions={max_total_sessions} "
                f"rate_limit={session_request_rate_limit}/min "
                f"idle_timeout={session_idle_timeout}s "
                f"allowed_signals={len(self._allowed_signals)} "
                f"allowed_shells={len(self._allowed_shells)} "
                f"command_validation={'disabled' if disable_command_validation else 'enabled'}"
            )

    def _load_authorized_identities(self) -> None:
        """Load authorized identities from file.

        File format: one identity hash per line, # comments allowed.
        """
        if not self._authorized_identities_file:
            return

        if not self._authorized_identities_file.exists():
            logger.warning(
                f"Authorized identities file not found: {self._authorized_identities_file}"
            )
            return

        try:
            with open(self._authorized_identities_file) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        # Take first whitespace-separated token (allows comments after hash)
                        identity = line.split()[0]
                        self._authorized_identities.add(identity)

            logger.info(
                f"Loaded {len(self._authorized_identities)} authorized identities "
                f"from {self._authorized_identities_file}"
            )
        except Exception as e:
            logger.error(f"Failed to load authorized identities: {e}")

    def add_authorized_identity(self, identity_hash: str) -> None:
        """Add an identity to the authorized set.

        Args:
            identity_hash: RNS identity hash to authorize
        """
        self._authorized_identities.add(identity_hash)
        logger.info(f"Added authorized identity: {identity_hash[:16]}...")

    def remove_authorized_identity(self, identity_hash: str) -> None:
        """Remove an identity from the authorized set.

        Args:
            identity_hash: RNS identity hash to deauthorize
        """
        self._authorized_identities.discard(identity_hash)
        logger.info(f"Removed authorized identity: {identity_hash[:16]}...")

    def _send_link_packet(self, link: "RNS.Link", data: bytes) -> bool:
        """Send data packet over an RNS Link.

        Args:
            link: The RNS Link to send over
            data: Data to send

        Returns:
            True if sent successfully
        """
        import RNS

        if not link or link.status != RNS.Link.ACTIVE:
            return False

        try:
            packet = RNS.Packet(link, data)
            packet.send()
            return True
        except Exception as e:
            logger.error(f"Failed to send link packet: {e}")
            return False

    def is_authorized(self, identity_hash: str) -> bool:
        """Check if an identity is authorized.

        Args:
            identity_hash: RNS identity hash to check

        Returns:
            True if authorized, False otherwise
        """
        # If no authorized identities configured
        if not self._authorized_identities:
            if self._allow_unauthenticated:
                logger.warning(
                    f"[METRICS] auth_check identity={identity_hash[:16]} "
                    f"result=allowed reason=unauthenticated_mode"
                )
                return True
            else:
                logger.warning(
                    f"[METRICS] auth_check identity={identity_hash[:16]} "
                    f"result=rejected reason=fail_closed_no_identities"
                )
                return False

        authorized = identity_hash in self._authorized_identities
        logger.debug(
            f"[METRICS] auth_check identity={identity_hash[:16]} "
            f"result={'allowed' if authorized else 'rejected'} "
            f"reason={'in_authorized_set' if authorized else 'not_in_authorized_set'}"
        )
        return authorized

    def is_signal_allowed(self, sig: int) -> bool:
        """Check if a signal is allowed to be sent to terminal processes.

        Blocked signals (SIGKILL, SIGSTOP, SIGQUIT) are never allowed regardless
        of configuration, as they can bypass process cleanup or cause system issues.

        Args:
            sig: Signal number to check

        Returns:
            True if signal is allowed, False otherwise
        """
        # Always block dangerous signals
        if sig in BLOCKED_SIGNALS:
            logger.debug(
                f"[METRICS] signal_check signal={sig} result=blocked reason=blocked_signal_list"
            )
            return False

        allowed = sig in self._allowed_signals
        logger.debug(
            f"[METRICS] signal_check signal={sig} result={'allowed' if allowed else 'blocked'} "
            f"reason={'in_whitelist' if allowed else 'not_in_whitelist'}"
        )
        return allowed

    def _validate_command(self, shell: str, command: str | None) -> str | None:
        """Validate that shell/command is allowed.

        Checks that:
        1. If command is None (shell session), shell is in allowed_shells
        2. If command is provided, it is in allowed_commands (if configured)

        Args:
            shell: Shell path to validate
            command: Optional command path to validate

        Returns:
            None if allowed, otherwise an error message describing why it's disallowed
        """
        # Skip validation if disabled
        if self._disable_command_validation:
            return None

        # Resolve paths to absolute for comparison
        def resolve_path(path: str) -> str:
            """Resolve a command/shell path to absolute."""
            # If already absolute, use as-is
            if path.startswith("/"):
                return path
            # Try to find in PATH
            resolved = shutil.which(path)
            return resolved if resolved else path

        if command is not None:
            # Validate command
            if self._allowed_commands is None:
                # No commands allowed (only shells)
                logger.warning(f"Command execution not allowed: {command}")
                return "Command execution not allowed (only shell access permitted)"

            resolved_command = resolve_path(command)
            if resolved_command not in self._allowed_commands:
                logger.warning(
                    f"Command not in allowed list: {command} (resolved: {resolved_command})"
                )
                return f"Command not allowed: {command}"

            return None

        # Validate shell
        resolved_shell = resolve_path(shell)
        if resolved_shell not in self._allowed_shells:
            logger.warning(f"Shell not in allowed list: {shell} (resolved: {resolved_shell})")
            return f"Shell not allowed: {shell}"

        return None

    def _check_rate_limits(self, source_identity: str) -> str | None:
        """Check rate limits for a session request.

        Performs three checks:
        1. Request rate limiting (requests per minute per identity)
        2. Per-identity session limit
        3. Total session limit

        Args:
            source_identity: Client's RNS identity hash

        Returns:
            None if request is allowed, otherwise a string describing the limit exceeded
        """
        current_time = time.time()

        # Clean up old timestamps and record this request
        self._cleanup_request_timestamps(source_identity, current_time)

        # Check request rate limit
        timestamps = self._request_timestamps.get(source_identity, [])
        logger.debug(
            f"[METRICS] rate_limit_check identity={source_identity[:16]} "
            f"requests_in_window={len(timestamps)} limit={self._session_request_rate_limit}"
        )
        if len(timestamps) >= self._session_request_rate_limit:
            logger.warning(
                f"[METRICS] rate_limit_exceeded identity={source_identity[:16]} "
                f"requests={len(timestamps)} limit={self._session_request_rate_limit}"
            )
            return (
                f"Rate limit exceeded: max {self._session_request_rate_limit} requests per minute"
            )

        # Record this request timestamp
        if source_identity not in self._request_timestamps:
            self._request_timestamps[source_identity] = []
        self._request_timestamps[source_identity].append(current_time)

        # Check per-identity session limit
        identity_sessions = self._sessions_by_identity.get(source_identity, [])
        # Clean up any stale session references
        stale_count = len(identity_sessions)
        identity_sessions = [s for s in identity_sessions if s in self.sessions]
        stale_count -= len(identity_sessions)
        self._sessions_by_identity[source_identity] = identity_sessions

        if stale_count > 0:
            logger.debug(
                f"[METRICS] stale_sessions_cleaned identity={source_identity[:16]} "
                f"cleaned={stale_count}"
            )

        logger.debug(
            f"[METRICS] session_limit_check identity={source_identity[:16]} "
            f"identity_sessions={len(identity_sessions)} limit={self._max_sessions_per_identity} "
            f"total_sessions={len(self.sessions)} total_limit={self._max_total_sessions}"
        )

        if len(identity_sessions) >= self._max_sessions_per_identity:
            logger.warning(
                f"[METRICS] per_identity_session_limit_exceeded identity={source_identity[:16]} "
                f"sessions={len(identity_sessions)} limit={self._max_sessions_per_identity}"
            )
            return f"Session limit exceeded: max {self._max_sessions_per_identity} sessions per identity"

        # Check total session limit
        if len(self.sessions) >= self._max_total_sessions:
            logger.warning(
                f"[METRICS] total_session_limit_exceeded "
                f"sessions={len(self.sessions)} limit={self._max_total_sessions}"
            )
            return f"Server session limit exceeded: max {self._max_total_sessions} total sessions"

        logger.debug(f"[METRICS] rate_limit_passed identity={source_identity[:16]}")
        return None

    def _cleanup_request_timestamps(self, source_identity: str, current_time: float) -> None:
        """Clean up request timestamps older than the rate limit window.

        Args:
            source_identity: Identity to clean up timestamps for
            current_time: Current time in seconds since epoch
        """
        cutoff = current_time - RATE_LIMIT_WINDOW_SECONDS

        if source_identity in self._request_timestamps:
            self._request_timestamps[source_identity] = [
                ts for ts in self._request_timestamps[source_identity] if ts > cutoff
            ]
            # Remove empty lists to prevent memory growth
            if not self._request_timestamps[source_identity]:
                del self._request_timestamps[source_identity]

    def _track_session_for_identity(self, source_identity: str, session_id: bytes) -> None:
        """Track a session for rate limiting purposes.

        Args:
            source_identity: Client's identity hash
            session_id: Session ID to track
        """
        if source_identity not in self._sessions_by_identity:
            self._sessions_by_identity[source_identity] = []
        self._sessions_by_identity[source_identity].append(session_id)

    def _untrack_session_for_identity(self, source_identity: str, session_id: bytes) -> None:
        """Remove a session from rate limiting tracking.

        Args:
            source_identity: Client's identity hash
            session_id: Session ID to untrack
        """
        if source_identity in self._sessions_by_identity:
            try:
                self._sessions_by_identity[source_identity].remove(session_id)
            except ValueError:
                pass  # Session not in list
            # Clean up empty lists and rate limit timestamps when identity has no sessions
            if not self._sessions_by_identity[source_identity]:
                del self._sessions_by_identity[source_identity]
                # Also clean up rate limit timestamps for this identity
                if source_identity in self._request_timestamps:
                    del self._request_timestamps[source_identity]
                    logger.debug(
                        f"[METRICS] rate_limit_timestamps_cleaned identity={source_identity[:16]}"
                    )

    def _resolve_identity_hash(self, lxmf_dest_hash: str) -> str | None:
        """Resolve an LXMF destination hash to an RNS identity hash.

        The LXMF destination hash is derived from (identity + "lxmf" + "delivery"),
        but Link.get_remote_identity().hexhash returns the raw identity hash.
        This method looks up the identity hash for a given LXMF destination.

        Args:
            lxmf_dest_hash: LXMF destination hash (hex string)

        Returns:
            RNS identity hash (hex string) or None if not found
        """
        # Strategy 1: In-memory discovered devices lookup
        try:
            from styrened.services.reticulum import get_identity_for_lxmf_destination

            identity_hash = get_identity_for_lxmf_destination(lxmf_dest_hash)
            if identity_hash:
                logger.debug(
                    f"[HASH] Resolved LXMF dest {lxmf_dest_hash[:16]}... -> "
                    f"identity {identity_hash[:16]}... (discovered_devices)"
                )
                return identity_hash
        except Exception as e:
            logger.warning(f"[HASH] Discovered devices lookup failed: {e}")

        # Strategy 2: NodeStore lookup
        try:
            from styrened.services.node_store import get_node_store

            store = get_node_store()

            # Try LXMF destination lookup
            identity_hash = store.get_identity_for_lxmf_destination(lxmf_dest_hash)
            if identity_hash:
                logger.debug(
                    f"[HASH] Resolved LXMF dest {lxmf_dest_hash[:16]}... -> "
                    f"identity {identity_hash[:16]}... (NodeStore)"
                )
                return identity_hash
        except Exception as e:
            logger.warning(f"[HASH] NodeStore lookup failed: {e}")

        logger.warning(
            f"[HASH] Could not resolve identity hash for LXMF dest {lxmf_dest_hash[:16]}..."
        )
        return None

    def start(self) -> None:
        """Start the terminal service.

        Creates RNS destination for data plane Links and registers
        message handlers with Styrene protocol.
        """
        if self._registered:
            return

        # Capture event loop for thread-safe RNS callbacks
        try:
            self._event_loop = asyncio.get_running_loop()
        except RuntimeError:
            # No running loop, try to get the default loop
            self._event_loop = asyncio.get_event_loop()

        # Create destination for terminal data Links
        import RNS

        identity = self.rns_service.identity
        if not identity:
            raise RuntimeError("RNS identity not available")

        self._link_destination = RNS.Destination(
            identity,
            RNS.Destination.IN,
            RNS.Destination.SINGLE,
            "styrene",
            "terminal",
        )

        # Set Link callbacks
        self._link_destination.set_link_established_callback(self._on_link_established)

        # Register with Styrene protocol for control plane messages
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_REQUEST,
            self._handle_terminal_request,
        )
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_RESIZE,
            self._handle_terminal_resize,
        )
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_SIGNAL,
            self._handle_terminal_signal,
        )
        self.styrene_protocol.register_handler(
            StyreneMessageType.TERMINAL_CLOSE,
            self._handle_terminal_close,
        )

        # Start idle check background task
        self._idle_check_task = asyncio.create_task(self._idle_check_loop())

        self._registered = True
        logger.info(
            f"[METRICS] terminal_service_started "
            f"link_destination={self._link_destination.hexhash} "
            f"idle_check_interval={IDLE_CHECK_INTERVAL}s"
        )

    def stop(self) -> None:
        """Stop the terminal service.

        Closes all active sessions and deregisters handlers.
        """
        session_count = len(self.sessions)
        logger.info(f"[METRICS] terminal_service_stopping sessions_to_close={session_count}")

        # Cancel idle check task
        if self._idle_check_task:
            self._idle_check_task.cancel()
            self._idle_check_task = None
            logger.debug("[METRICS] idle_check_task_cancelled")

        # Close all sessions
        for session_id in list(self.sessions.keys()):
            self._close_session(session_id, exit_code=-1, reason="service_shutdown")

        # Deregister handlers
        if self._registered:
            self.styrene_protocol.unregister_handler(
                StyreneMessageType.TERMINAL_REQUEST,
                self._handle_terminal_request,
            )
            self.styrene_protocol.unregister_handler(
                StyreneMessageType.TERMINAL_RESIZE,
                self._handle_terminal_resize,
            )
            self.styrene_protocol.unregister_handler(
                StyreneMessageType.TERMINAL_SIGNAL,
                self._handle_terminal_signal,
            )
            self.styrene_protocol.unregister_handler(
                StyreneMessageType.TERMINAL_CLOSE,
                self._handle_terminal_close,
            )
            self._registered = False
            logger.debug("[METRICS] terminal_handlers_deregistered")

        logger.info(f"[METRICS] terminal_service_stopped sessions_closed={session_count}")

    async def _idle_check_loop(self) -> None:
        """Background task that checks for idle sessions and closes them.

        Runs every IDLE_CHECK_INTERVAL seconds and closes sessions that have
        exceeded the idle timeout.
        """
        logger.debug(
            f"[METRICS] idle_check_loop_started interval={IDLE_CHECK_INTERVAL}s "
            f"timeout={self.session_idle_timeout}s"
        )
        check_count = 0
        try:
            while True:
                await asyncio.sleep(IDLE_CHECK_INTERVAL)
                check_count += 1
                logger.debug(
                    f"[METRICS] idle_check_iteration check_number={check_count} "
                    f"active_sessions={len(self.sessions)}"
                )
                await self._check_idle_sessions()
        except asyncio.CancelledError:
            logger.debug(f"[METRICS] idle_check_loop_cancelled total_checks={check_count}")

    async def _check_idle_sessions(self) -> None:
        """Check all sessions for idle timeout and handoff timeout, closing expired ones."""
        now = time.time()
        sessions_to_close: list[tuple[bytes, TerminalSession, str]] = []  # (id, session, reason)

        for session_id, session in self.sessions.items():
            session_hex = session_id.hex()[:16]

            # Check handoff timeout - sessions waiting for Link establishment
            if session.link is None:
                handoff_age = now - session.created_at
                if handoff_age >= HANDOFF_TIMEOUT_SECONDS:
                    logger.warning(
                        f"[METRICS] session_handoff_timeout session={session_hex} "
                        f"age_seconds={handoff_age:.0f} timeout={HANDOFF_TIMEOUT_SECONDS}s"
                    )
                    sessions_to_close.append((session_id, session, "handoff_timeout"))
                    continue  # Don't also check idle timeout

            # Check idle timeout for established sessions
            idle_time = now - session.last_activity
            logger.debug(
                f"[METRICS] session_idle_check session={session_hex} "
                f"idle_seconds={idle_time:.2f} timeout={self.session_idle_timeout}s "
                f"expires_in={max(0, self.session_idle_timeout - idle_time):.2f}s"
            )
            if idle_time >= self.session_idle_timeout:
                logger.info(
                    f"[METRICS] session_idle_timeout_exceeded session={session_hex} "
                    f"idle_seconds={idle_time:.0f} timeout={self.session_idle_timeout}s"
                )
                sessions_to_close.append((session_id, session, "idle_timeout"))

        # Close expired sessions (outside iteration to avoid modifying dict during iteration)
        if sessions_to_close:
            logger.info(f"[METRICS] sessions_closing count={len(sessions_to_close)}")

        for session_id, session, reason in sessions_to_close:
            # Store identity before closing (session will be removed from dict)
            source_identity = session.source_identity
            session_hex = session_id.hex()[:16]

            self._close_session(session_id, exit_code=-1, reason=reason)

            # Send TERMINAL_CLOSED via LXMF control plane
            try:
                closed_envelope = create_terminal_closed(
                    exit_code=-1,
                    reason=reason,
                    session_id=session_id,
                )
                # Send via styrene protocol (async)
                asyncio.create_task(
                    self.styrene_protocol.send_to_identity(
                        source_identity,
                        closed_envelope,
                    )
                )
                logger.debug(
                    f"[METRICS] timeout_notification_sent session={session_hex} "
                    f"identity={source_identity[:16]} reason={reason}"
                )
            except Exception as e:
                logger.warning(
                    f"[METRICS] timeout_notification_failed session={session_hex} "
                    f"reason={reason} error={e}"
                )

    async def _handle_terminal_request(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_REQUEST from client.

        Args:
            message: LXMF message containing the request
            envelope: Request envelope
        """
        lxmf_dest_hash = message.source_hash
        request_id = envelope.request_id
        payload = decode_payload(envelope.payload)

        # Resolve the RNS identity hash from the LXMF destination hash
        # This is needed because Link.get_remote_identity().hexhash returns the identity hash,
        # not the LXMF destination hash
        source_identity = self._resolve_identity_hash(lxmf_dest_hash)
        if source_identity is None:
            logger.warning(
                f"[METRICS] terminal_request_rejected reason=identity_resolution_failed "
                f"lxmf_dest={lxmf_dest_hash[:16]}"
            )
            # Reject the request - we cannot verify identity without the hash mapping
            # Using LXMF dest hash as fallback would always fail identity verification later
            reject_response = create_terminal_reject(
                reason="Identity resolution failed - node not yet discovered",
                code=1,
                request_id=request_id,
            )
            try:
                await self.styrene_protocol.send_to_identity(lxmf_dest_hash, reject_response)
            except Exception as e:
                logger.error(f"Failed to send rejection response: {e}")
            return

        # Process request and get response envelope
        response = await self._process_terminal_request(source_identity, request_id, payload)

        # Send response to client - use the LXMF dest hash for routing
        if response:
            try:
                await self.styrene_protocol.send_to_identity(lxmf_dest_hash, response)
                logger.debug(f"Sent {response.message_type.name} to {lxmf_dest_hash[:16]}...")
            except Exception as e:
                logger.error(f"Failed to send terminal response: {e}")

    async def _process_terminal_request(
        self,
        source_identity: str,
        request_id: bytes | None,
        payload: dict,
    ) -> StyreneEnvelope | None:
        """Process TERMINAL_REQUEST and return response envelope.

        Args:
            source_identity: Client's RNS identity hash
            request_id: Request correlation ID
            payload: Decoded request payload

        Returns:
            TERMINAL_ACCEPT or TERMINAL_REJECT response envelope
        """

        logger.info(
            f"[METRICS] terminal_request_received identity={source_identity[:16]} "
            f"request_id={request_id.hex()[:16] if request_id else 'none'}"
        )

        # Validate request_id is present (required for session correlation)
        if request_id is None:
            import os

            request_id = os.urandom(16)
            logger.debug(f"Generated session ID: {request_id.hex()[:16]}")

        # Check authorization
        if not self.is_authorized(source_identity):
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=unauthorized code=1"
            )
            return create_terminal_reject(
                reason="Identity not authorized",
                code=1,
                request_id=request_id,
            )

        # Check rate limits
        rate_limit_result = self._check_rate_limits(source_identity)
        if rate_limit_result is not None:
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=rate_limit code=5 detail={rate_limit_result}"
            )
            return create_terminal_reject(
                reason=rate_limit_result,
                code=5,  # Resource limit
                request_id=request_id,
            )

        # Extract request parameters
        term_type = payload.get("term_type", "xterm-256color")
        rows = payload.get("rows", 24)
        cols = payload.get("cols", 80)
        shell = payload.get("shell", self.default_shell)
        command = payload.get("command")
        args = payload.get("args", [])

        # Validate terminal dimensions (must be positive integers within unsigned short range)
        if not isinstance(rows, int) or not isinstance(cols, int):
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=invalid_dimensions code=4 rows={type(rows).__name__} cols={type(cols).__name__}"
            )
            return create_terminal_reject(
                reason="Invalid terminal dimensions: must be integers",
                code=4,
                request_id=request_id,
            )
        if not (1 <= rows <= 65535 and 1 <= cols <= 65535):
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=dimensions_out_of_range code=4 rows={rows} cols={cols}"
            )
            return create_terminal_reject(
                reason="Invalid terminal dimensions: must be 1-65535",
                code=4,
                request_id=request_id,
            )

        # Validate term_type (must be a reasonable string)
        if not isinstance(term_type, str) or len(term_type) > 256 or len(term_type) == 0:
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=invalid_term_type code=4"
            )
            return create_terminal_reject(
                reason="Invalid terminal type",
                code=4,
                request_id=request_id,
            )

        # Validate args (must be a list of strings)
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=invalid_args code=4"
            )
            return create_terminal_reject(
                reason="Invalid args: must be a list of strings",
                code=4,
                request_id=request_id,
            )

        # Validate command/shell
        validation_error = self._validate_command(shell, command)
        if validation_error is not None:
            logger.warning(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=command_validation code=4 shell={shell} command={command} "
                f"detail={validation_error}"
            )
            return create_terminal_reject(
                reason=validation_error,
                code=4,  # Command validation failure
                request_id=request_id,
            )

        # Allocate PTY and fork process
        logger.debug(
            f"[METRICS] session_create_attempt identity={source_identity[:16]} "
            f"term={term_type} size={cols}x{rows} shell={shell} command={command}"
        )
        try:
            session = await self._create_session(
                session_id=request_id,
                source_identity=source_identity,
                term_type=term_type,
                rows=rows,
                cols=cols,
                shell=shell,
                command=command,
                args=args,
            )
        except Exception as e:
            # Log detailed error internally but return generic message to client
            # to avoid leaking implementation details
            logger.error(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=session_create_failed code=2 error={e}",
                exc_info=True,
            )
            return create_terminal_reject(
                reason="Failed to create session",
                code=2,
                request_id=request_id,
            )

        # Return accept with Link destination
        if not self._link_destination:
            logger.error(
                f"[METRICS] terminal_request_rejected identity={source_identity[:16]} "
                f"reason=service_not_ready code=3"
            )
            return create_terminal_reject(
                reason="Terminal service not ready",
                code=3,
                request_id=request_id,
            )

        logger.info(
            f"[METRICS] terminal_request_accepted identity={source_identity[:16]} "
            f"session={session.session_id.hex()[:16]} pid={session.child_pid} "
            f"link_dest={self._link_destination.hexhash[:16]}"
        )

        # Get identity hash for Link establishment
        identity_hash = None
        if self.rns_service.identity:
            identity_hash = self.rns_service.identity.hash.hex()

        return create_terminal_accept(
            link_destination=self._link_destination.hexhash,
            session_id=session.session_id,
            request_id=request_id,
            identity_hash=identity_hash,
        )

    async def _create_session(
        self,
        session_id: bytes,
        source_identity: str,
        term_type: str,
        rows: int,
        cols: int,
        shell: str,
        command: str | None,
        args: list[str],
    ) -> TerminalSession:
        """Create a new terminal session.

        Allocates PTY and forks shell/command process.

        Args:
            session_id: Unique session identifier
            source_identity: Client's identity hash
            term_type: Terminal type
            rows: Initial terminal rows
            cols: Initial terminal columns
            shell: Shell to execute
            command: Command to run (instead of shell)
            args: Command arguments

        Returns:
            Created TerminalSession
        """
        logger.debug(
            f"[METRICS] pty_allocate_start session={session_id.hex()[:16]} "
            f"identity={source_identity[:16]}"
        )
        # Allocate PTY
        master_fd, slave_fd = pty.openpty()
        logger.debug(
            f"[METRICS] pty_allocated session={session_id.hex()[:16]} "
            f"master_fd={master_fd} slave_fd={slave_fd}"
        )

        # Set initial window size
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)

        # Fork child process
        pid = os.fork()

        if pid == 0:
            # Child process
            try:
                # Start new session and set controlling terminal
                os.setsid()
                os.close(master_fd)

                # Duplicate slave to stdin/stdout/stderr
                os.dup2(slave_fd, 0)
                os.dup2(slave_fd, 1)
                os.dup2(slave_fd, 2)

                if slave_fd > 2:
                    os.close(slave_fd)

                # Set controlling terminal
                fcntl.ioctl(0, termios.TIOCSCTTY, 0)

                # Set environment
                os.environ["TERM"] = term_type
                os.environ["RNS_REMOTE_IDENTITY"] = source_identity

                # Execute shell or command
                if command:
                    os.execvp(command, [command] + args)
                else:
                    os.execvp(shell, [shell, "-l"])

            except Exception:
                os._exit(127)
        else:
            # Parent process
            os.close(slave_fd)

            logger.debug(f"[METRICS] child_forked session={session_id.hex()[:16]} pid={pid}")

            # Make master non-blocking
            flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
            fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

            session = TerminalSession(
                session_id=session_id,
                source_identity=source_identity,
                master_fd=master_fd,
                child_pid=pid,
                term_type=term_type,
                rows=rows,
                cols=cols,
            )

            self.sessions[session_id] = session

            # Track session for rate limiting
            self._track_session_for_identity(source_identity, session_id)

            # Start monitoring child process
            asyncio.create_task(self._monitor_child(session))

            logger.info(
                f"[METRICS] session_created session={session_id.hex()[:16]} "
                f"identity={source_identity[:16]} pid={pid} "
                f"total_sessions={len(self.sessions)}"
            )

            return session

    async def _monitor_child(self, session: TerminalSession) -> None:
        """Monitor child process for termination.

        Args:
            session: Session to monitor
        """
        session_hex = session.session_id.hex()[:16]

        logger.debug(
            f"[METRICS] child_monitor_started session={session_hex} pid={session.child_pid}"
        )

        try:
            # Wait for child process to exit
            poll_count = 0
            while True:
                poll_count += 1
                try:
                    pid, status = os.waitpid(session.child_pid, os.WNOHANG)
                    if pid != 0:
                        # Child exited
                        if os.WIFEXITED(status):
                            exit_code = os.WEXITSTATUS(status)
                            reason = "exited"
                        elif os.WIFSIGNALED(status):
                            exit_code = 128 + os.WTERMSIG(status)
                            reason = "signal"
                        else:
                            exit_code = -1
                            reason = "unknown"

                        logger.info(
                            f"[METRICS] child_exited session={session_hex} pid={session.child_pid} "
                            f"exit_code={exit_code} reason={reason} poll_count={poll_count}"
                        )

                        self._close_session(session.session_id, exit_code, reason)
                        return

                except ChildProcessError:
                    # Child already reaped
                    logger.debug(
                        f"[METRICS] child_reaped session={session_hex} pid={session.child_pid} "
                        f"poll_count={poll_count}"
                    )
                    self._close_session(session.session_id, -1, "reaped")
                    return

                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            logger.debug(
                f"[METRICS] child_monitor_cancelled session={session_hex} poll_count={poll_count}"
            )

    def _on_link_established(self, link: "RNS.Link") -> None:
        """Handle new RNS Link connection.

        Client must send session_id as first packet to associate Link.

        Args:
            link: Newly established Link
        """
        link_hash = link.destination.hexhash[:16] if link.destination else "unknown"
        logger.info(
            f"[METRICS] link_established link_dest={link_hash} "
            f"pending_sessions={len(self.sessions)}"
        )

        # Set packet callback for session association
        link.set_packet_callback(lambda data, pkt: self._on_link_packet(link, data, pkt))
        # Note: RNS link_closed callback receives only (link), not (link, reason)
        # Access reason via link.teardown_reason
        link.set_link_closed_callback(lambda lnk: self._on_link_closed(lnk, lnk.teardown_reason))

    def _on_link_packet(self, link: "RNS.Link", data: bytes, packet: "RNS.Packet") -> None:
        """Handle packet received on terminal Link.

        Args:
            link: Link that received the packet
            data: Packet data
            packet: RNS Packet object
        """
        # Check if Link is associated with a session
        session = getattr(link, "_terminal_session", None)

        if session is None:
            # Check if we're already processing association for this link
            if getattr(link, "_association_in_progress", False):
                # Queue this packet for later processing (bounded to prevent memory exhaustion)
                if not hasattr(link, "_pending_packets"):
                    link._pending_packets = []
                if len(link._pending_packets) < MAX_PENDING_PACKETS:
                    link._pending_packets.append((data, packet))
                    logger.debug(
                        f"[METRICS] packet_queued_during_association data_len={len(data)} "
                        f"queue_size={len(link._pending_packets)}"
                    )
                else:
                    logger.warning(
                        f"[METRICS] packet_dropped_queue_full data_len={len(data)} "
                        f"max_queue={MAX_PENDING_PACKETS}"
                    )
                return

            # First packet must be session_id for association
            logger.info(
                f"[METRICS] first_packet_received data_len={len(data)} "
                f"data_hex={data.hex()[:64]}{'...' if len(data) > 32 else ''}"
            )

            # Mark that we're processing association to prevent race conditions
            link._association_in_progress = True

            if len(data) < 16:
                logger.warning(
                    f"[METRICS] link_association_failed reason=invalid_packet data_len={len(data)}"
                )
                link.teardown()
                return

            session_id = data[:16]
            session_hex = session_id.hex()[:16]
            logger.info(f"[METRICS] extracted_session_id={session_hex}")
            session = self.sessions.get(session_id)

            if session is None:
                logger.warning(
                    f"[METRICS] link_association_failed reason=unknown_session "
                    f"session={session_hex}"
                )
                link.teardown()
                return

            # Check session-level association lock to prevent race conditions
            # between multiple Links trying to associate with the same session
            if session._association_pending:
                logger.warning(
                    f"[METRICS] link_association_rejected reason=association_already_pending "
                    f"session={session_hex}"
                )
                link._association_in_progress = False
                link.teardown()
                return

            # Set session-level lock before async verification
            session._association_pending = True

            # Schedule async identity verification to avoid blocking RNS thread
            # The remote identity may not be immediately available during Link establishment
            if self._event_loop is not None:
                asyncio.run_coroutine_threadsafe(
                    self._async_verify_and_associate(link, session_id, session),
                    self._event_loop,
                )
            else:
                logger.error(
                    f"[METRICS] link_association_failed reason=no_event_loop session={session_hex}"
                )
                session._association_pending = False
                link._association_in_progress = False
                link.teardown()

            return

        # Update activity timestamp on any data received
        session.update_activity()

        # Handle terminal data plane messages
        session_hex = session.session_id.hex()[:16]
        try:
            msg = deserialize_message(data)

            if isinstance(msg, StreamData):
                # Write to PTY (stdin)
                if msg.is_stdin:
                    try:
                        bytes_written = os.write(session.master_fd, msg.data)
                        logger.debug(
                            f"[METRICS] stdin_data session={session_hex} "
                            f"bytes={len(msg.data)} written={bytes_written}"
                        )
                    except OSError as e:
                        logger.error(
                            f"[METRICS] pty_write_error session={session_hex} "
                            f"bytes={len(msg.data)} error={e}"
                        )

            elif isinstance(msg, WindowSize):
                logger.debug(
                    f"[METRICS] window_size_received session={session_hex} "
                    f"size={msg.cols}x{msg.rows}"
                )
                session.set_window_size(msg.rows, msg.cols, msg.xpixel, msg.ypixel)

            elif isinstance(msg, VersionInfo):
                logger.debug(
                    f"[METRICS] client_version session={session_hex} "
                    f"version={msg.version} software={msg.software}"
                )

        except Exception as e:
            logger.error(
                f"[METRICS] packet_handler_error session={session_hex} "
                f"data_len={len(data)} error={e}"
            )

    def _on_channel_message(self, session: TerminalSession, message: "RNS.Channel.MessageBase") -> bool:
        """Handle a message received via RNS Channel (v2.0 data plane).

        Dispatches typed Channel messages to appropriate handlers.

        Args:
            session: Terminal session that received the message
            message: Received Channel message (already unpacked by Channel)

        Returns:
            True to indicate the message was consumed
        """
        session_hex = session.session_id.hex()[:16]
        session.update_activity()

        try:
            if isinstance(message, StreamData):
                if message.is_stdin:
                    try:
                        bytes_written = os.write(session.master_fd, message.data)
                        logger.debug(
                            f"[METRICS] channel_stdin session={session_hex} "
                            f"bytes={len(message.data)} written={bytes_written}"
                        )
                    except OSError as e:
                        logger.error(
                            f"[METRICS] channel_pty_write_error session={session_hex} "
                            f"bytes={len(message.data)} error={e}"
                        )

            elif isinstance(message, WindowSize):
                logger.debug(
                    f"[METRICS] channel_window_size session={session_hex} "
                    f"size={message.cols}x{message.rows}"
                )
                session.set_window_size(message.rows, message.cols, message.xpixel, message.ypixel)

            elif isinstance(message, VersionInfo):
                logger.debug(
                    f"[METRICS] channel_version_info session={session_hex} "
                    f"version={message.version} software={message.software}"
                )

            else:
                logger.debug(
                    f"[METRICS] channel_unknown_message session={session_hex} "
                    f"type={type(message).__name__}"
                )

        except Exception as e:
            logger.error(
                f"[METRICS] channel_message_handler_error session={session_hex} "
                f"type={type(message).__name__} error={e}"
            )

        return True

    async def _async_verify_and_associate(
        self,
        link: "RNS.Link",
        session_id: bytes,
        session: TerminalSession,
    ) -> None:
        """Verify client identity and associate Link with session asynchronously.

        This runs in the asyncio event loop, not the RNS thread, to avoid
        blocking RNS network operations during identity verification retries.

        Args:
            link: RNS Link to verify and associate
            session_id: Session ID from first packet
            session: Session to associate with
        """
        session_hex = session_id.hex()[:16]

        try:
            # Verify client identity matches session with retry logic
            # The remote identity may not be immediately available during Link establishment
            remote_identity = None
            for attempt in range(IDENTITY_VERIFICATION_RETRIES):
                remote_identity = link.get_remote_identity()
                if remote_identity is not None:
                    logger.debug(
                        f"[METRICS] identity_verification_success session={session_hex} "
                        f"attempt={attempt + 1}/{IDENTITY_VERIFICATION_RETRIES}"
                    )
                    break
                if attempt < IDENTITY_VERIFICATION_RETRIES - 1:
                    # Add jitter (±25%) to prevent timing analysis attacks
                    jitter = random.uniform(0.75, 1.25)
                    delay_ms = int(IDENTITY_VERIFICATION_DELAY_MS * jitter)
                    logger.debug(
                        f"[METRICS] identity_verification_retry session={session_hex} "
                        f"attempt={attempt + 1}/{IDENTITY_VERIFICATION_RETRIES} "
                        f"delay_ms={delay_ms}"
                    )
                    # Use async sleep instead of blocking time.sleep()
                    await asyncio.sleep(delay_ms / 1000.0)

            if remote_identity is None:
                # Identity could not be verified after retries - reject the connection
                logger.warning(
                    f"[METRICS] identity_verification_failed session={session_hex} "
                    f"reason=unavailable attempts={IDENTITY_VERIFICATION_RETRIES}"
                )
                session._association_pending = False
                link._association_in_progress = False
                link.teardown()
                return

            remote_hash = remote_identity.hexhash
            if remote_hash != session.source_identity:
                logger.warning(
                    f"[METRICS] identity_verification_failed session={session_hex} "
                    f"reason=mismatch expected={session.source_identity[:16]} "
                    f"actual={remote_hash[:16]}"
                )
                session._association_pending = False
                link._association_in_progress = False
                link.teardown()
                return

            # CRITICAL: Check if session already has a link (prevent session hijacking)
            # This prevents an attacker from associating their Link with an existing session
            if session.link is not None:
                logger.warning(
                    f"[METRICS] link_association_rejected session={session_hex} "
                    f"reason=session_already_has_link"
                )
                session._association_pending = False
                link._association_in_progress = False
                link.teardown()
                return

            # Associate Link with session
            link._terminal_session = session
            session.link = link

            # Update activity on link association
            session.update_activity()

            logger.info(
                f"[METRICS] link_associated session={session_hex} "
                f"identity={session.source_identity[:16]} pid={session.child_pid}"
            )

            # Process any packets that arrived during association
            # (may include VersionInfo from client needed for Channel setup)
            pending = getattr(link, "_pending_packets", [])
            client_version = "1.0"
            remaining_pending: list[tuple[bytes, Any]] = []
            if pending:
                logger.debug(f"[METRICS] processing_pending_packets count={len(pending)}")
                link._pending_packets = []
                for pending_data, pending_packet in pending:
                    # Check for VersionInfo in pending packets
                    try:
                        msg = deserialize_message(pending_data)
                        if isinstance(msg, VersionInfo):
                            client_version = msg.version
                            logger.debug(
                                f"[METRICS] client_version_from_pending session={session_hex} "
                                f"version={msg.version} software={msg.software}"
                            )
                            continue  # Consumed
                    except Exception:
                        pass
                    remaining_pending.append((pending_data, pending_packet))

            # Set up Channel if both sides support v2.0
            server_version = "2.0"
            if client_version >= "2.0":
                try:
                    channel = link.get_channel()
                    register_message_types(channel)
                    channel.add_message_handler(
                        lambda msg: self._on_channel_message(session, msg)
                    )
                    session.channel = channel
                    session.protocol_version = "2.0"
                    logger.info(
                        f"[METRICS] channel_established session={session_hex} "
                        f"mdu={channel.mdu} client_version={client_version}"
                    )
                except Exception as e:
                    logger.warning(
                        f"[METRICS] channel_setup_failed session={session_hex} "
                        f"error={e} falling_back_to_raw_packets"
                    )
                    server_version = "1.0"
            else:
                server_version = "1.0"

            # Send version info (always via raw packet — handshake stays on raw path)
            version_msg = VersionInfo(version=server_version, software="styrened")
            self._send_link_packet(link, serialize_message(version_msg))
            logger.debug(
                f"[METRICS] version_info_sent session={session_hex} version={server_version}"
            )

            # Start PTY read loop
            session._read_task = asyncio.create_task(self._pty_read_loop(session))

            # Dispatch remaining pending packets
            for pending_data, pending_packet in remaining_pending:
                self._on_link_packet(link, pending_data, pending_packet)

            # Clear association flags
            session._association_pending = False
            link._association_in_progress = False

        except Exception as e:
            logger.error(
                f"[METRICS] async_verify_failed session={session_hex} error={e}",
                exc_info=True,
            )
            session._association_pending = False
            link._association_in_progress = False
            link.teardown()

    def _on_link_closed(self, link: "RNS.Link", reason: int) -> None:
        """Handle Link closure.

        Args:
            link: Closed Link
            reason: RNS Link closure reason code
        """
        # Clear any pending packets to prevent memory leak
        if hasattr(link, "_pending_packets"):
            pending_count = len(link._pending_packets)
            link._pending_packets = []
            if pending_count > 0:
                logger.debug(f"[METRICS] pending_packets_cleared count={pending_count}")

        session = getattr(link, "_terminal_session", None)
        if session:
            session_hex = session.session_id.hex()[:16]
            session_age = time.time() - session.created_at
            logger.info(
                f"[METRICS] link_closed session={session_hex} "
                f"reason_code={reason} session_age_seconds={session_age:.2f}"
            )
            self._close_session(session.session_id, -1, "link_closed")
        else:
            logger.debug(f"[METRICS] link_closed_unassociated reason_code={reason}")

    def _get_max_payload_size(self, session: TerminalSession) -> int:
        """Calculate maximum payload size for StreamData messages.

        In Channel mode, uses Channel.mdu minus msgpack framing overhead.
        In raw packet mode, uses Link MTU minus framing overhead.

        Args:
            session: Terminal session to check payload limits for

        Returns:
            Maximum data bytes that can be sent in a single StreamData message
        """
        if session.channel:
            # Channel mode: mdu is the max pack() result size
            # Reserve 20 bytes for msgpack framing overhead within pack()
            return max(64, session.channel.mdu - 20)
        else:
            # Raw packet mode: use link MTU
            if not session.link:
                return 64
            mtu: int = session.link.get_mtu()
            # Reserve space for StreamData message framing
            # msgpack overhead: 1 (fixmap) + keys/vals + bin header
            # Plus 1 byte for message type prefix
            # Total overhead: ~10 bytes, use 32 for safety margin
            overhead = 32
            return max(64, mtu - overhead)  # Minimum 64 bytes per chunk

    async def _pty_read_loop(self, session: TerminalSession) -> None:
        """Read from PTY and send to client via Link.

        When Channel is available (v2.0), uses Channel.send() with backpressure
        via is_ready_to_send(). Falls back to raw packets for v1.0 sessions.

        Args:
            session: Session to read from
        """
        loop = asyncio.get_running_loop()
        session_hex = session.session_id.hex()[:16]
        total_bytes_read = 0
        read_count = 0
        chunk_count = 0
        backpressure_waits = 0

        logger.debug(
            f"[METRICS] pty_read_loop_started session={session_hex} "
            f"buffer_size={PTY_READ_SIZE} mode={'channel' if session.channel else 'raw'}"
        )

        try:
            while session.link and session.link.status == 0x00:  # RNS.Link.ACTIVE
                try:
                    # Non-blocking read from PTY
                    data = await loop.run_in_executor(
                        None,
                        lambda: os.read(session.master_fd, PTY_READ_SIZE),
                    )

                    if data:
                        read_count += 1
                        total_bytes_read += len(data)
                        # Update activity on output
                        session.update_activity()

                        # Chunk data to respect payload limits
                        max_payload = self._get_max_payload_size(session)
                        for i in range(0, len(data), max_payload):
                            chunk = data[i : i + max_payload]
                            chunk_count += 1
                            msg = StreamData(stream=StreamData.STDOUT, data=chunk)

                            if session.channel:
                                # Channel mode: backpressure via is_ready_to_send()
                                while not session.channel.is_ready_to_send():
                                    if not session.link or session.link.status != 0x00:
                                        return
                                    backpressure_waits += 1
                                    await asyncio.sleep(0.01)
                                session.channel.send(msg)
                            else:
                                # Raw packet mode (v1.0 fallback)
                                self._send_link_packet(session.link, serialize_message(msg))

                        logger.debug(
                            f"[METRICS] stdout_data session={session_hex} "
                            f"bytes={len(data)} chunks={chunk_count} "
                            f"total_bytes={total_bytes_read} read_count={read_count}"
                            f"{f' bp_waits={backpressure_waits}' if backpressure_waits else ''}"
                        )
                    else:
                        # EOF - shell exited
                        logger.debug(
                            f"[METRICS] pty_eof session={session_hex} "
                            f"total_bytes={total_bytes_read}"
                        )
                        break

                except BlockingIOError:
                    await asyncio.sleep(0.01)
                except OSError as e:
                    if e.errno == 5:  # EIO - PTY closed
                        logger.debug(
                            f"[METRICS] pty_closed session={session_hex} "
                            f"errno=EIO total_bytes={total_bytes_read}"
                        )
                        break
                    logger.error(
                        f"[METRICS] pty_read_error session={session_hex} errno={e.errno} error={e}"
                    )
                    break

        except asyncio.CancelledError:
            logger.debug(
                f"[METRICS] pty_read_loop_cancelled session={session_hex} "
                f"total_bytes={total_bytes_read}"
            )

        logger.debug(
            f"[METRICS] pty_read_loop_ended session={session_hex} "
            f"total_bytes={total_bytes_read} read_count={read_count} "
            f"chunk_count={chunk_count} backpressure_waits={backpressure_waits}"
        )

    def _close_session(
        self,
        session_id: bytes,
        exit_code: int,
        reason: str,
    ) -> None:
        """Close a terminal session.

        Args:
            session_id: Session to close
            exit_code: Process exit code
            reason: Closure reason
        """
        session_hex = session_id.hex()[:16]
        session = self.sessions.pop(session_id, None)
        if not session:
            logger.debug(f"[METRICS] session_close_noop session={session_hex} reason=not_found")
            return

        # Prevent double-close race condition
        if session._closed:
            logger.debug(
                f"[METRICS] session_close_noop session={session_hex} reason=already_closed"
            )
            return
        session._closed = True

        session_age = time.time() - session.created_at
        idle_time = time.time() - session.last_activity

        logger.debug(
            f"[METRICS] session_closing session={session_hex} "
            f"exit_code={exit_code} reason={reason} "
            f"session_age_seconds={session_age:.2f} idle_seconds={idle_time:.2f}"
        )

        # Untrack session for rate limiting
        self._untrack_session_for_identity(session.source_identity, session_id)

        # Cancel read task
        if session._read_task:
            session._read_task.cancel()
            logger.debug(f"[METRICS] read_task_cancelled session={session_hex}")

        # Send CommandExited to client
        if session.link and session.link.status == 0x00:  # ACTIVE
            try:
                msg = CommandExited(return_code=exit_code)
                if session.channel and session.channel.is_ready_to_send():
                    session.channel.send(msg)
                else:
                    self._send_link_packet(session.link, serialize_message(msg))
                logger.debug(
                    f"[METRICS] command_exited_sent session={session_hex} "
                    f"exit_code={exit_code} via={'channel' if session.channel else 'raw'}"
                )
            except Exception as e:
                logger.debug(
                    f"[METRICS] command_exited_send_failed session={session_hex} error={e}"
                )

            # Close Link
            try:
                session.link.teardown()
                logger.debug(f"[METRICS] link_teardown session={session_hex}")
            except Exception as e:
                logger.debug(f"[METRICS] link_teardown_failed session={session_hex} error={e}")

        # Close PTY
        try:
            os.close(session.master_fd)
            logger.debug(f"[METRICS] pty_closed session={session_hex} fd={session.master_fd}")
        except OSError as e:
            logger.debug(f"[METRICS] pty_close_failed session={session_hex} error={e}")

        # Kill child process if still running
        # First try SIGTERM, then SIGKILL if process doesn't exit
        try:
            os.kill(session.child_pid, signal.SIGTERM)
            logger.debug(
                f"[METRICS] child_sigterm_sent session={session_hex} pid={session.child_pid}"
            )
            # Check if process exited after a brief wait
            try:
                pid, status = os.waitpid(session.child_pid, os.WNOHANG)
                if pid == 0:
                    # Process still running, give it a moment then SIGKILL
                    time.sleep(0.1)
                    pid, status = os.waitpid(session.child_pid, os.WNOHANG)
                    if pid == 0:
                        os.kill(session.child_pid, signal.SIGKILL)
                        logger.debug(
                            f"[METRICS] child_sigkill_sent session={session_hex} pid={session.child_pid}"
                        )
                        os.waitpid(session.child_pid, 0)  # Reap zombie
            except ChildProcessError:
                pass  # Child already reaped
        except ProcessLookupError:
            logger.debug(
                f"[METRICS] child_already_exited session={session_hex} pid={session.child_pid}"
            )

        logger.info(
            f"[METRICS] session_closed session={session_hex} "
            f"identity={session.source_identity[:16]} pid={session.child_pid} "
            f"exit_code={exit_code} reason={reason} "
            f"session_age_seconds={session_age:.2f} "
            f"remaining_sessions={len(self.sessions)}"
        )

    async def _handle_terminal_resize(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_RESIZE from client (via LXMF control plane)."""
        lxmf_dest_hash = message.source_hash
        payload = decode_payload(envelope.payload)
        session_id = (
            bytes.fromhex(payload["session_id"]) if "session_id" in payload else envelope.request_id
        )
        session_hex = session_id.hex()[:16] if session_id else "none"

        # Resolve LXMF dest hash to identity hash for comparison with session.source_identity
        source_identity = self._resolve_identity_hash(lxmf_dest_hash)
        if source_identity is None:
            logger.debug(
                f"[METRICS] terminal_resize_ignored session={session_hex} "
                f"reason=identity_resolution_failed lxmf_dest={lxmf_dest_hash[:16]}"
            )
            return

        logger.debug(
            f"[METRICS] terminal_resize_received session={session_hex} "
            f"identity={source_identity[:16]} size={payload.get('cols', '?')}x{payload.get('rows', '?')}"
        )

        session = self.sessions.get(session_id) if session_id else None
        if session and session_id and session.source_identity == source_identity:
            # Validate dimensions before calling set_window_size
            rows = payload.get("rows")
            cols = payload.get("cols")
            if rows is None or cols is None:
                logger.debug(
                    f"[METRICS] terminal_resize_ignored session={session_hex} "
                    f"reason=missing_dimensions"
                )
                return
            session.update_activity()
            session.set_window_size(rows, cols)
        else:
            logger.debug(
                f"[METRICS] terminal_resize_ignored session={session_hex} "
                f"reason={'not_found' if not session else 'identity_mismatch'}"
            )

    async def _handle_terminal_signal(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> None:
        """Handle TERMINAL_SIGNAL from client.

        Validates the signal against the allowed signals whitelist before sending.
        Blocked signals (SIGKILL, SIGSTOP, SIGQUIT) are always rejected.

        Args:
            message: LXMF message containing the signal request
            envelope: Request envelope
        """
        lxmf_dest_hash = message.source_hash
        payload = decode_payload(envelope.payload)
        session_id = (
            bytes.fromhex(payload["session_id"]) if "session_id" in payload else envelope.request_id
        )
        sig = payload.get("signal", signal.SIGINT)
        session_hex = session_id.hex()[:16] if session_id else "none"

        # Validate signal type before any processing
        if not isinstance(sig, int):
            logger.warning(
                f"[METRICS] terminal_signal_ignored session={session_hex} "
                f"reason=invalid_signal_type type={type(sig).__name__}"
            )
            return

        # Resolve LXMF dest hash to identity hash for comparison with session.source_identity
        source_identity = self._resolve_identity_hash(lxmf_dest_hash)
        if source_identity is None:
            logger.debug(
                f"[METRICS] terminal_signal_ignored session={session_hex} "
                f"reason=identity_resolution_failed lxmf_dest={lxmf_dest_hash[:16]}"
            )
            return

        logger.debug(
            f"[METRICS] terminal_signal_received session={session_hex} "
            f"identity={source_identity[:16]} signal={sig}"
        )

        session = self.sessions.get(session_id) if session_id else None
        if session and session_id and session.source_identity == source_identity:
            session.update_activity()

            # Validate signal against whitelist
            if not self.is_signal_allowed(sig):
                logger.warning(
                    f"[METRICS] terminal_signal_blocked session={session_hex} "
                    f"identity={source_identity[:16]} signal={sig} reason=not_allowed"
                )
                return

            try:
                os.kill(session.child_pid, sig)
                logger.debug(
                    f"[METRICS] terminal_signal_sent session={session_hex} "
                    f"pid={session.child_pid} signal={sig}"
                )
            except ProcessLookupError:
                logger.debug(
                    f"[METRICS] terminal_signal_failed session={session_hex} "
                    f"pid={session.child_pid} signal={sig} reason=process_not_found"
                )
        else:
            logger.debug(
                f"[METRICS] terminal_signal_ignored session={session_hex} "
                f"reason={'not_found' if not session else 'identity_mismatch'}"
            )

    async def _handle_terminal_close(
        self,
        message: "LXMFMessage",
        envelope: StyreneEnvelope,
    ) -> StyreneEnvelope | None:
        """Handle TERMINAL_CLOSE from client.

        Args:
            message: LXMF message containing the close request
            envelope: Request envelope
        """
        lxmf_dest_hash = message.source_hash
        payload = decode_payload(envelope.payload) if envelope.payload else {}
        session_id = (
            bytes.fromhex(payload["session_id"]) if "session_id" in payload else envelope.request_id
        )
        session_hex = session_id.hex()[:16] if session_id else "none"

        # Resolve LXMF dest hash to identity hash for comparison with session.source_identity
        source_identity = self._resolve_identity_hash(lxmf_dest_hash)
        if source_identity is None:
            logger.debug(
                f"[METRICS] terminal_close_ignored session={session_hex} "
                f"reason=identity_resolution_failed lxmf_dest={lxmf_dest_hash[:16]}"
            )
            return None

        logger.debug(
            f"[METRICS] terminal_close_received session={session_hex} "
            f"identity={source_identity[:16]}"
        )

        session = self.sessions.get(session_id) if session_id else None
        if session and session_id and session.source_identity == source_identity:
            session_age = time.time() - session.created_at
            logger.info(
                f"[METRICS] terminal_close_accepted session={session_hex} "
                f"identity={source_identity[:16]} session_age_seconds={session_age:.2f}"
            )
            self._close_session(session_id, 0, "client_close")

            return create_terminal_closed(
                exit_code=0,
                reason="client_close",
                session_id=session_id,
                request_id=envelope.request_id,
            )

        logger.debug(
            f"[METRICS] terminal_close_ignored session={session_hex} "
            f"reason={'not_found' if not session else 'identity_mismatch'}"
        )
        return None
