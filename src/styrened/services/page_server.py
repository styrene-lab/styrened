"""NomadNet-compatible page server service.

Serves pages over RNS using the ``("nomadnetwork", "node")`` destination
aspect, with optional Styrene directive enhancement. Static ``.mu`` files
are served from a pages directory; dynamic handlers can be registered by
other services for programmatic page generation.

Hub coexistence: On hub nodes where NomadNet runs as a separate process and
already owns the destination, the service detects the conflict and skips
destination creation. Page serving then falls back to the executable page
bridge (hub_bridge.py).

On edge nodes (no NomadNet process), the service creates the destination
directly and serves pages itself.
"""

import logging
import platform
import sys
from collections.abc import Callable, Coroutine
from pathlib import Path
from typing import Any

from styrened.models.config import PageServerConfig

logger = logging.getLogger(__name__)

# NomadNet destination aspects
NOMADNET_APP_NAME = "nomadnetwork"
NOMADNET_ASPECT = "node"

# Default pages directory
DEFAULT_PAGES_DIR_NAME = "pages"

# Type alias for dynamic page handlers
DynamicHandler = Callable[
    [str, dict | None, str],  # path, form_data, remote_identity_hash
    Coroutine[Any, Any, str],  # Returns micron string
]


def _detect_hardware() -> str:
    """Detect hardware model string (best-effort)."""
    system = platform.system()

    if system == "Darwin":
        try:
            import subprocess

            result = subprocess.run(
                ["sysctl", "-n", "hw.model"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception:
            pass

    elif system == "Linux":
        # Try device-tree model (RPi, SBCs)
        for model_path in ("/proc/device-tree/model", "/sys/firmware/devicetree/base/model"):
            try:
                model = Path(model_path).read_text().strip().rstrip("\x00")
                if model:
                    return model
            except Exception:
                pass

        # Try DMI product name (x86 servers/desktops)
        try:
            model = Path("/sys/class/dmi/id/product_name").read_text().strip()
            if model and model != "System Product Name":
                return model
        except Exception:
            pass

    return ""


def _detect_capabilities() -> list[str]:
    """Detect active styrened capabilities."""
    caps: list[str] = []

    try:
        from styrened.services.lxmf_service import get_lxmf_service

        svc = get_lxmf_service()
        if svc and svc.is_initialized:
            caps.append("📨 LXMF Messaging")
    except Exception:
        pass

    try:
        from styrened.services.rns_service import get_rns_service

        svc = get_rns_service()
        if svc and svc.is_initialized:
            caps.append("🔀 Reticulum Transport")
    except Exception:
        pass

    try:
        from styrened.rpc.server import get_rpc_server

        rpc = get_rpc_server()
        if rpc:
            caps.append("⚡ RPC Server")
    except Exception:
        pass

    return caps


class PageServerService:
    """Serves NomadNet pages over RNS with optional Styrene enhancement.

    Follows the TerminalService lifecycle pattern: init with config,
    start() to register destination and handlers, stop() to teardown.
    """

    def __init__(self, config: PageServerConfig) -> None:
        self._config = config
        self._pages_dir: Path | None = None
        self._destination: Any = None  # RNS.Destination
        self._identity: Any = None  # RNS.Identity
        self._dynamic_handlers: dict[str, DynamicHandler] = {}
        self._started = False
        self._owns_destination = False

    @property
    def pages_dir(self) -> Path | None:
        """Resolved pages directory path."""
        return self._pages_dir

    @property
    def owns_destination(self) -> bool:
        """Whether this service created the RNS destination."""
        return self._owns_destination

    @property
    def is_started(self) -> bool:
        return self._started

    @property
    def registered_handlers(self) -> list[str]:
        """Paths with registered dynamic handlers."""
        return list(self._dynamic_handlers.keys())

    @property
    def static_pages(self) -> list[str]:
        """List of static .mu files found in pages directory."""
        if self._pages_dir is None or not self._pages_dir.is_dir():
            return []
        return sorted(p.name for p in self._pages_dir.glob("*.mu"))

    def start(self) -> None:
        """Start the page server.

        Resolves pages directory, checks for destination conflicts,
        and creates the RNS destination if available.
        """
        if self._started:
            return

        # Resolve pages directory
        if self._config.pages_dir is not None:
            self._pages_dir = self._config.pages_dir
        else:
            from styrened import paths

            self._pages_dir = paths.data_dir() / DEFAULT_PAGES_DIR_NAME

        # Ensure pages directory exists
        self._pages_dir.mkdir(parents=True, exist_ok=True)

        # Attempt to create NomadNet destination
        try:
            self._create_destination()
        except DestinationConflictError:
            logger.warning(
                "NomadNet destination already registered — "
                "running in bridge mode (executable .mu scripts only)"
            )
            self._owns_destination = False

        # Generate default index page if none exists
        self._ensure_default_index()

        self._started = True
        logger.info(
            "PageServerService started (pages_dir=%s, owns_destination=%s, static_pages=%d)",
            self._pages_dir,
            self._owns_destination,
            len(self.static_pages),
        )

    def _ensure_default_index(self) -> None:
        """Generate a default index.mu if no index page exists.

        Creates a node info page showing version, platform, hardware,
        and capabilities. Skips if an index.mu already exists (operator
        may have customized it).
        """
        if self._pages_dir is None:
            return

        index_path = self._pages_dir / "index.mu"
        if index_path.exists():
            return

        try:
            micron = self._generate_node_info_page()
            index_path.write_text(micron, encoding="utf-8")
            logger.info("Generated default index page: %s", index_path)
        except Exception as e:
            logger.warning("Failed to generate default index page: %s", e)

    def regenerate_index(self) -> bool:
        """Regenerate the default index page with current node info.

        Overwrites any existing index.mu. Call from TUI settings or CLI.

        Returns:
            True if page was written successfully.
        """
        if self._pages_dir is None:
            return False

        try:
            self._pages_dir.mkdir(parents=True, exist_ok=True)
            index_path = self._pages_dir / "index.mu"
            micron = self._generate_node_info_page()
            index_path.write_text(micron, encoding="utf-8")
            logger.info("Regenerated index page: %s", index_path)
            return True
        except Exception as e:
            logger.warning("Failed to regenerate index page: %s", e)
            return False

    def _generate_node_info_page(self) -> str:
        """Generate micron markup for a node information page."""
        from styrened import __version__

        # Node name
        node_name = self._config.node_name or "Styrene Node"

        # Platform info
        arch = platform.machine() or "unknown"
        os_name = platform.system() or "unknown"
        os_version = platform.release() or ""
        py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"

        # Hardware detection
        hw_model = _detect_hardware()

        # Identity hash
        identity_hex = ""
        if self._identity is not None:
            try:
                identity_hex = self._identity.hexhash
            except Exception:
                pass

        # Capabilities
        caps = _detect_capabilities()

        # Build the micron page
        lines = [
            f">{node_name}",
            "",
            f"A node on the Styrene mesh network running styrened v{__version__}.",
            "",
            "-",
            "",
            ">>System",
            f"  Platform: `!{os_name} {os_version}`! ({arch})",
            f"  Python:   `!{py_version}`!",
            f"  Styrened: `!v{__version__}`!",
        ]

        if hw_model:
            lines.append(f"  Hardware: `!{hw_model}`!")

        if identity_hex:
            lines.append(f"  Identity: `!{identity_hex}`!")

        lines.append("")
        lines.append("-")
        lines.append("")

        if caps:
            lines.append(">>Capabilities")
            for cap in caps:
                lines.append(f"  {cap}")
            lines.append("")
            lines.append("-")
            lines.append("")

        # About / links
        lines.extend([
            ">>About Styrene",
            "",
            "This page is automatically generated by `!styrened`!,",
            "a daemon for operating on Reticulum mesh networks.",
            "",
            "  Docs:          `!https://docs.styrene.io`!",
            "  Source:         `!https://github.com/styrene-lab/styrened`!",
            "  Community Hub:  `[Styrene Community Hub`:/page/index.mu]",
            "  Install:       `!pipx install styrene`!",
            "",
            "Connect to the Styrene Community Hub at `!rns.styrene.io:4242`!",
            "for public transport, LXMF propagation, and a NomadNet BBS.",
            "",
            "-",
            "",
            f"`Fg50Powered by styrened v{__version__}`f",
            "",
        ])

        return "\n".join(lines)

    def stop(self) -> None:
        """Stop the page server and teardown destination."""
        if not self._started:
            return

        if self._destination is not None and self._owns_destination:
            try:
                self._destination.deregister()
            except Exception as e:
                logger.warning("Error deregistering page server destination: %s", e)
            self._destination = None

        self._dynamic_handlers.clear()
        self._started = False
        logger.info("PageServerService stopped")

    def register_dynamic_handler(self, path: str, handler: DynamicHandler) -> None:
        """Register a dynamic page handler for a path.

        Args:
            path: Page path (e.g. ``"/page/styrene/status.mu"``).
            handler: Async callable returning micron markup string.
        """
        self._dynamic_handlers[path] = handler
        logger.debug("Registered dynamic page handler: %s", path)

    def unregister_dynamic_handler(self, path: str) -> bool:
        """Remove a dynamic page handler.

        Returns:
            True if handler was found and removed.
        """
        return self._dynamic_handlers.pop(path, None) is not None

    async def serve_page(
        self,
        path: str,
        form_data: dict | None,
        remote_identity_hash: str,
    ) -> bytes:
        """Serve a page request.

        Dispatches to dynamic handler if registered, otherwise serves
        static ``.mu`` file from pages directory.

        Args:
            path: Requested page path.
            form_data: Optional form submission data.
            remote_identity_hash: Hex hash of requesting identity.

        Returns:
            UTF-8 encoded page content.
        """
        # Try dynamic handler first
        handler = self._dynamic_handlers.get(path)
        if handler is not None:
            try:
                micron = await handler(path, form_data, remote_identity_hash)
                return micron.encode("utf-8")
            except Exception as e:
                logger.error("Dynamic handler error for %s: %s", path, e)
                return self._error_page(f"Internal error: {e}").encode("utf-8")

        # Try static file
        if self._pages_dir is not None:
            # Extract filename from path (e.g. "/page/styrene/fleet.mu" → "fleet.mu")
            filename = path.rsplit("/", 1)[-1] if "/" in path else path
            page_file = self._pages_dir / filename
            if page_file.is_file() and page_file.suffix == ".mu":
                try:
                    content = page_file.read_text(encoding="utf-8")
                    return content.encode("utf-8")
                except Exception as e:
                    logger.error("Error reading page file %s: %s", page_file, e)
                    return self._error_page(f"Error reading page: {e}").encode("utf-8")

        return self._not_found_page(path).encode("utf-8")

    def _create_destination(self) -> None:
        """Create the NomadNet destination for page serving.

        Raises:
            DestinationConflictError: If destination already registered.
        """
        try:
            import RNS

            from styrened.services.rns_service import get_rns_service

            rns_service = get_rns_service()
            if not rns_service.is_initialized:
                logger.warning("RNS not initialized, skipping destination creation")
                return

            identity = rns_service.identity
            if identity is None:
                logger.warning("No identity available, skipping destination creation")
                return

            self._identity = identity

            # Check if destination aspect is already registered
            # This detects if NomadNet is already running
            try:
                self._destination = RNS.Destination(
                    identity,
                    RNS.Destination.IN,
                    RNS.Destination.SINGLE,
                    NOMADNET_APP_NAME,
                    NOMADNET_ASPECT,
                )
                self._owns_destination = True

                # Set announce display name if configured
                if self._config.node_name:
                    self._destination.set_default_app_data(
                        self._config.node_name.encode("utf-8")
                    )

                logger.info(
                    "Created NomadNet page server destination: %s",
                    RNS.prettyhexrep(self._destination.hash),
                )

            except Exception as e:
                # RNS raises if destination aspect is already registered
                raise DestinationConflictError(str(e)) from e

        except ImportError:
            logger.warning("RNS not available, page server running without destination")
        except DestinationConflictError:
            raise
        except Exception as e:
            logger.error("Failed to create page server destination: %s", e)

    @staticmethod
    def _not_found_page(path: str) -> str:
        """Generate a 404-style page."""
        return f">Page Not Found\nThe requested page was not found: {path}\n"

    @staticmethod
    def _error_page(message: str) -> str:
        """Generate an error page."""
        return f">Error\n{message}\n"


class DestinationConflictError(Exception):
    """Raised when the NomadNet destination is already registered."""
