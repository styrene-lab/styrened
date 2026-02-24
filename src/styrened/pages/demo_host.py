"""Demo host for the Styrene NomadNet Page Extension system.

Registers static test pages and dynamic handlers that exercise every
feature of the page extension protocol. Intended for dogfooding and
interactive end-to-end verification during development.

Usage::

    from styrened.pages.demo_host import register_demo_pages
    register_demo_pages(page_server_service)

Or enable via config::

    page_server:
      enabled: true
      demo: true
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING

from styrened.pages.builder import build_page
from styrened.pages.directives import MAX_BLOCK_SIZE

if TYPE_CHECKING:
    from styrened.services.page_server import PageServerService

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Handler path constants (exported for tests and wiring)
# ---------------------------------------------------------------------------

DEMO_PATH_NODE_STATUS = "/page/demo/node_status.mu"
DEMO_PATH_FLEET = "/page/demo/fleet.mu"
DEMO_PATH_FORM_ECHO = "/page/demo/form_echo.mu"
DEMO_PATH_FULL_METADATA = "/page/demo/full_metadata.mu"
DEMO_PATH_ENCODING_B85 = "/page/demo/encoding_b85.mu"
DEMO_PATH_ENCODING_JSON = "/page/demo/encoding_json.mu"
DEMO_PATH_ERROR = "/page/demo/error.mu"
DEMO_PATH_LARGE_PAYLOAD = "/page/demo/large_payload.mu"
DEMO_PATH_IDENTITY = "/page/demo/identity.mu"

# Simulated fleet data (shared by node_status and fleet handlers)
_DEMO_START_TIME = 1708000000  # Fixed epoch for deterministic uptime

_FLEET_NODES = [
    {"name": "edge-03", "status": "active", "uptime": 86400},
    {"name": "edge-07", "status": "active", "uptime": 259200},
    {"name": "edge-12", "status": "offline", "uptime": 0},
    {"name": "hub-01", "status": "active", "uptime": 604800},
    {"name": "edge-15", "status": "degraded", "uptime": 43200},
]

_ENCODING_TEST_DATA = {
    "comparison": True,
    "string_value": "hello world",
    "int_value": 42,
    "float_value": 3.14159,
    "nested": {"list": [1, 2, 3], "bool": True},
    "unicode": "Reticulum \u2192 mesh \u2192 freedom",
}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def register_demo_pages(
    page_server: PageServerService,
    pages_dir: Path | None = None,
) -> None:
    """Register all demo/test pages on the given page server.

    Writes static ``.mu`` files to the pages directory and registers
    dynamic handlers for programmatic pages.

    Args:
        page_server: Started PageServerService instance.
        pages_dir: Override pages directory (defaults to server's pages_dir).
    """
    target_dir = pages_dir or page_server.pages_dir
    if target_dir is None:
        logger.warning("No pages directory available, skipping demo pages")
        return

    target_dir.mkdir(parents=True, exist_ok=True)

    # Write static pages
    _write_static_pages(target_dir)

    # Register dynamic handlers
    page_server.register_dynamic_handler(DEMO_PATH_NODE_STATUS, handle_node_status)
    page_server.register_dynamic_handler(DEMO_PATH_FLEET, handle_fleet_overview)
    page_server.register_dynamic_handler(DEMO_PATH_FORM_ECHO, handle_form_echo)
    page_server.register_dynamic_handler(DEMO_PATH_FULL_METADATA, handle_full_metadata)
    page_server.register_dynamic_handler(DEMO_PATH_ENCODING_B85, handle_encoding_b85)
    page_server.register_dynamic_handler(DEMO_PATH_ENCODING_JSON, handle_encoding_json)
    page_server.register_dynamic_handler(DEMO_PATH_ERROR, handle_error)
    page_server.register_dynamic_handler(DEMO_PATH_LARGE_PAYLOAD, handle_large_payload)
    page_server.register_dynamic_handler(DEMO_PATH_IDENTITY, handle_identity)

    logger.info(
        "Demo pages registered: %d static, %d dynamic",
        4,
        9,
    )


# ---------------------------------------------------------------------------
# Static page generation
# ---------------------------------------------------------------------------


def _write_static_pages(pages_dir: Path) -> None:
    """Write static .mu test files to the pages directory."""
    from styrened import __version__

    # 1. Index page
    (pages_dir / "index.mu").write_text(
        f">Styrene Page Extension Lab\n"
        f"\n"
        f"Welcome to the Styrene page extension test host. Each link\n"
        f"exercises a specific capability of the directive protocol.\n"
        f"\n"
        f"-\n"
        f"\n"
        f">>Static Pages\n"
        f"`[Plain Micron (no directives)`:/page/plain.mu]\n"
        f"`[Static Directives (hand-crafted)`:/page/static_directives.mu]\n"
        f"\n"
        f">>Dynamic Handlers\n"
        f"`[Node Status (TUI renderer)`:{DEMO_PATH_NODE_STATUS}]\n"
        f"`[Fleet Overview (TUI renderer)`:{DEMO_PATH_FLEET}]\n"
        f"`[Form Echo (form submission)`:{DEMO_PATH_FORM_ECHO}]\n"
        f"`[Full Metadata (all directives)`:{DEMO_PATH_FULL_METADATA}]\n"
        f"`[Encoding: b85`:{DEMO_PATH_ENCODING_B85}]\n"
        f"`[Encoding: JSON`:{DEMO_PATH_ENCODING_JSON}]\n"
        f"`[Error Handler (intentional error)`:{DEMO_PATH_ERROR}]\n"
        f"`[Large Payload (size limit test)`:{DEMO_PATH_LARGE_PAYLOAD}]\n"
        f"`[Identity Mirror (who are you?)`:{DEMO_PATH_IDENTITY}]\n"
        f"\n"
        f">>Hub Bridge\n"
        f"`[Hub Bridge Example`:/page/hub_bridge_example.mu]\n"
        f"\n"
        f"-\n"
        f"`Fg50Styrene v{__version__} | Page Extension Protocol v1`f\n",
        encoding="utf-8",
    )

    # 2. Plain micron (no directives)
    (pages_dir / "plain.mu").write_text(
        ">Plain Micron Page\n"
        "\n"
        "This page contains no Styrene directives. It is standard NomadNet\n"
        "micron markup and should render identically in any client.\n"
        "\n"
        "`!Key features tested:`!\n"
        "- Static .mu file serving from pages_dir\n"
        "- No #! directive lines present\n"
        "- Parser returns None (graceful fallback)\n"
        "- Standard NomadNet formatting: `!bold`!, `*italic`*, `_underline`_\n"
        "\n"
        "-\n"
        "\n"
        "`[Back to Index`:/page/index.mu]\n",
        encoding="utf-8",
    )

    # 3. Static page with embedded directives (generated via build_page)
    static_data = {
        "test_key": "static_value",
        "numbers": [1, 2, 3],
        "nested": {"inner": True},
    }
    static_content = build_page(
        micron=(
            ">Static Directives Page\n"
            "\n"
            "This page was generated at startup using build_page() and written\n"
            "as a static .mu file. The directives are embedded in the file.\n"
            "\n"
            "`!Validation checklist:`!\n"
            "- Parser should find StructuredPageData (not None)\n"
            "- page_type should be 'demo_static'\n"
            "- capabilities should be ['demo', 'static']\n"
            "- data.test_key should be 'static_value'\n"
            "- data.numbers should be [1, 2, 3]\n"
            "\n"
            "`[Back to Index`:/page/index.mu]\n"
        ),
        data=static_data,
        page_type="demo_static",
        encoding="json",
        capabilities=["demo", "static"],
        cache_ttl=300,
    )
    (pages_dir / "static_directives.mu").write_text(static_content, encoding="utf-8")

    # 4. Hub bridge example (documentation page)
    (pages_dir / "hub_bridge_example.mu").write_text(
        ">Hub Bridge Example\n"
        "\n"
        "This page shows the pattern for executable .mu scripts that run\n"
        "on a NomadNet hub using the hub_bridge module.\n"
        "\n"
        ">>Source Code\n"
        "`=\n"
        "#!/usr/bin/env python3\n"
        "from styrened.pages.hub_bridge import serve_dynamic_page\n"
        "\n"
        "def generate(remote_identity, form_data):\n"
        '    micron = ">Hub Fleet Status\\n"\n'
        '    data = {"nodes": [...]}\n'
        "    return micron, data\n"
        "\n"
        'if __name__ == "__main__":\n'
        '    serve_dynamic_page(generate, page_type="fleet")\n'
        "`=\n"
        "\n"
        ">>Environment Variables\n"
        "NomadNet sets these for executable pages:\n"
        "- `!remote_identity`! - Hex hash of requesting identity\n"
        "- `!field_<name>`! - Form field values (one per field)\n"
        "\n"
        ">>API Reference\n"
        "- `!get_remote_identity()`! - Read identity from environment\n"
        "- `!get_form_data()`! - Parse field vars into dict\n"
        "- `!serve_dynamic_page(generator, page_type, ...)`! - Entry point\n"
        "\n"
        "`[Back to Index`:/page/index.mu]\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Dynamic handlers
# ---------------------------------------------------------------------------


async def handle_node_status(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a realistic node status page."""
    uptime = int(time.time()) - _DEMO_START_TIME

    data = {
        "node_name": "edge-03-demo",
        "status": "active",
        "uptime": uptime,
        "version": _get_version(),
        "services": ["rpc", "pages", "terminal", "lxmf"],
        "interfaces": [
            {"name": "AutoInterface", "status": "up", "peers": 3},
            {"name": "TCPServerInterface", "status": "up", "peers": 1},
            {"name": "RNodeInterface/LoRa", "status": "up", "peers": 7},
        ],
    }

    micron = (
        ">Node Status: edge-03-demo\n"
        "\n"
        f"Status: `Fa00ACTIVE`f\n"
        f"Uptime: {_format_uptime(uptime)}\n"
        f"Version: {data['version']}\n"
        f"Services: rpc, pages, terminal, lxmf\n"
        "\n"
        ">>Interfaces\n"
        "  AutoInterface        UP   3 peers\n"
        "  TCPServerInterface   UP   1 peer\n"
        "  RNodeInterface/LoRa  UP   7 peers\n"
        "\n"
        "-\n"
        f"`[Refresh`:{DEMO_PATH_NODE_STATUS}]\n"
        "`[Back to Index`:/page/index.mu]\n"
    )

    return build_page(
        micron=micron,
        data=data,
        page_type="node_status",
        capabilities=["rpc", "pages", "terminal"],
        refresh={"status": 30},
    )


async def handle_fleet_overview(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a fleet overview page with multiple nodes."""
    nodes = _FLEET_NODES
    active_count = sum(1 for n in nodes if n["status"] == "active")

    data = {
        "nodes": nodes,
        "total": len(nodes),
        "active": active_count,
    }

    lines = [
        ">Fleet Overview",
        "",
        f"Total: {len(nodes)}  Active: {active_count}  "
        f"Offline: {len(nodes) - active_count}",
        "",
    ]
    for node in nodes:
        status_str = node["status"].upper()
        uptime_str = _format_uptime(node["uptime"]) if node["uptime"] > 0 else "-"
        lines.append(f"  {node['name']:<14} {status_str:<10} {uptime_str}")

    lines.extend([
        "",
        "-",
        f"`[Refresh`:{DEMO_PATH_FLEET}]",
        "`[Back to Index`:/page/index.mu]",
    ])

    return build_page(
        micron="\n".join(lines) + "\n",
        data=data,
        page_type="fleet",
        capabilities=["fleet"],
        refresh={"fleet": 60},
    )


async def handle_form_echo(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Echo form submissions back to the user, or show a form."""
    if form_data:
        lines = [
            ">Form Echo Response",
            "",
            "You submitted the following data:",
            "",
        ]
        for key, value in sorted(form_data.items()):
            lines.append(f"  `!{key}`!: {value}")

        identity = remote_identity_hash or "(anonymous)"
        lines.extend([
            "",
            f"Your identity hash: {identity}",
            "",
            "-",
            f"`[Submit Again`:{DEMO_PATH_FORM_ECHO}]",
            "`[Back to Index`:/page/index.mu]",
        ])

        echo_data = {
            "submitted_fields": form_data,
            "identity": remote_identity_hash,
            "field_count": len(form_data),
        }
        return build_page(
            micron="\n".join(lines) + "\n",
            data=echo_data,
            page_type="form_echo",
            encoding="json",
        )

    # Render the input form
    micron = (
        ">Form Echo Test\n"
        "\n"
        "Enter values below and submit. The handler will echo\n"
        "back exactly what it received.\n"
        "\n"
        "Name: `<name|32|Enter your name`>\n"
        "Message: `<message|48|Hello from the mesh`>\n"
        "Secret: `<!|secret`>\n"
        "\n"
        "Options:\n"
        "`<?verbose|yes`>Verbose output\n"
        "`<?debug|yes`>Debug mode\n"
        "\n"
        "Encoding preference:\n"
        "`<^encoding|b85`>Base85 (production)\n"
        "`<^encoding|json`>JSON (debug)\n"
        "\n"
        f"`[Submit`:{DEMO_PATH_FORM_ECHO}]\n"
        "`[Back to Index`:/page/index.mu]\n"
    )
    return build_page(
        micron=micron,
        data={},
        page_type="form_echo",
        encoding="json",
    )


async def handle_full_metadata(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a page exercising every metadata directive."""
    ts = time.time()
    etag = hashlib.sha256(f"demo-{ts}".encode()).hexdigest()[:16]

    data = {
        "metadata_test": True,
        "generated_at": ts,
        "etag": etag,
    }

    micron = (
        ">Full Metadata Test\n"
        "\n"
        "This page has EVERY metadata directive populated:\n"
        f"- Protocol version: 1\n"
        f"- Page type: full_metadata_test\n"
        f"- Capabilities: rpc, terminal, pages, fleet, lxmf\n"
        f"- Timestamp: {ts:.6f}\n"
        f"- ETag: {etag}\n"
        f"- Refresh: status:30, fleet:60, metrics:10\n"
        f"- Cache TTL: 120s\n"
        "\n"
        "Your client should parse all of these from the page source.\n"
        "\n"
        f"`[Refresh (new etag)`:{DEMO_PATH_FULL_METADATA}]\n"
        "`[Back to Index`:/page/index.mu]\n"
    )

    return build_page(
        micron=micron,
        data=data,
        page_type="full_metadata_test",
        capabilities=["rpc", "terminal", "pages", "fleet", "lxmf"],
        cache_ttl=120,
        timestamp=ts,
        etag=etag,
        refresh={"status": 30, "fleet": 60, "metrics": 10},
    )


async def handle_encoding_b85(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a page with b85-encoded structured data."""
    micron = (
        ">Encoding Test: Base85\n"
        "\n"
        "This page uses `!b85`! encoding (base85-encoded msgpack).\n"
        "This is the production encoding -- compact and binary-safe.\n"
        "\n"
        f"Compare with: `[JSON version`:{DEMO_PATH_ENCODING_JSON}]\n"
        "\n"
        "Both pages embed identical structured data. Your client should\n"
        "parse both to the same dict, despite different raw encodings.\n"
        "\n"
        "`[Back to Index`:/page/index.mu]\n"
    )
    return build_page(
        micron=micron,
        data=_ENCODING_TEST_DATA,
        page_type="encoding_test",
        encoding="b85",
    )


async def handle_encoding_json(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a page with JSON-encoded structured data."""
    micron = (
        ">Encoding Test: JSON\n"
        "\n"
        "This page uses `!json`! encoding (plain JSON, human-readable).\n"
        "This is the debug encoding -- larger but inspectable.\n"
        "\n"
        f"Compare with: `[b85 version`:{DEMO_PATH_ENCODING_B85}]\n"
        "\n"
        "Both pages embed identical structured data. Your client should\n"
        "parse both to the same dict, despite different raw encodings.\n"
        "\n"
        "`[Back to Index`:/page/index.mu]\n"
    )
    return build_page(
        micron=micron,
        data=_ENCODING_TEST_DATA,
        page_type="encoding_test",
        encoding="json",
    )


async def handle_error(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Intentionally raises to test error handling."""
    raise RuntimeError(
        "This is an intentional error from the demo host. "
        "If you see this in an error page, error handling is working correctly."
    )


async def handle_large_payload(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Generate a page with a large structured data payload."""
    items = []
    for i in range(500):
        items.append({
            "id": i,
            "name": f"device-{i:04d}",
            "status": "active" if i % 3 != 0 else "offline",
            "metrics": {
                "cpu": round(0.1 + (i % 90) * 0.01, 2),
                "memory_mb": 128 + (i * 7 % 1024),
                "disk_pct": round(10 + (i * 3 % 80), 1),
                "uptime_s": i * 360,
            },
            "tags": [f"rack-{i // 50}", f"row-{i // 10}", f"region-{i // 200}"],
        })

    data = {
        "items": items,
        "total_count": len(items),
        "generated_at": time.time(),
    }

    micron = (
        ">Large Payload Test\n"
        "\n"
        f"This page embeds {len(items)} device records as structured data.\n"
        f"The payload stress-tests the encoding pipeline near the\n"
        f"{MAX_BLOCK_SIZE // 1024}KB block size limit.\n"
        "\n"
        "If you can see this text AND your client parsed the structured\n"
        "data successfully, large payload handling is working.\n"
        "\n"
        f"`[Regenerate`:{DEMO_PATH_LARGE_PAYLOAD}]\n"
        "`[Back to Index`:/page/index.mu]\n"
    )

    return build_page(
        micron=micron,
        data=data,
        page_type="large_payload",
        encoding="b85",
    )


async def handle_identity(
    path: str, form_data: dict | None, remote_identity_hash: str
) -> str:
    """Show the requesting identity hash back to the user."""
    identity = remote_identity_hash or "(anonymous / unknown)"

    data = {
        "remote_identity_hash": remote_identity_hash,
        "request_path": path,
        "has_identity": bool(remote_identity_hash),
    }

    micron = (
        ">Identity Mirror\n"
        "\n"
        "This page shows who YOU are, as seen by the page server.\n"
        "\n"
        f"Your identity hash: `!{identity}`!\n"
        f"Requested path: {path}\n"
        "\n"
        "If the identity hash above matches your RNS identity,\n"
        "the identity plumbing is working correctly.\n"
        "\n"
        f"`[Refresh`:{DEMO_PATH_IDENTITY}]\n"
        "`[Back to Index`:/page/index.mu]\n"
    )

    return build_page(
        micron=micron,
        data=data,
        page_type="identity_mirror",
        encoding="json",
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_uptime(seconds: int | float) -> str:
    """Format seconds into a human-readable duration string."""
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    days = seconds // 86400
    hours = (seconds % 86400) // 3600
    return f"{days}d {hours}h" if hours else f"{days}d"


def _get_version() -> str:
    """Get styrened version string."""
    try:
        from styrened import __version__

        return __version__
    except ImportError:
        return "unknown"
