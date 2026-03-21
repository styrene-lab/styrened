"""Styrene TUI entry point."""

from __future__ import annotations

import argparse
import os
import sys

from styrened.tui.models.config import DeploymentMode, PeerConfig


def parse_peer(peer_str: str) -> PeerConfig:
    """Parse peer string in format host:port or host.

    Args:
        peer_str: Peer string (e.g., "rns.styrene.io:4242")

    Returns:
        PeerConfig object

    Raises:
        ValueError: If peer string is invalid
    """
    if ":" in peer_str:
        host, port_str = peer_str.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError as e:
            raise ValueError(f"Invalid port number in peer: {peer_str}") from e
        return PeerConfig(host=host, port=port)
    else:
        return PeerConfig(host=peer_str, port=4242)


def main() -> None:
    """Run the Styrene TUI application."""
    parser = argparse.ArgumentParser(
        description="Styrene TUI - Mesh fleet provisioning and management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  styrene                                # Run in standalone mode (default)
  styrene --mode hub                     # Run as transport hub
  styrene --peer rns.styrene.io           # Connect to specific peer
  styrene --headless                     # Run without TUI
  styrene --headless --api-port 8000     # Headless with HTTP API
        """,
    )

    # Deployment mode
    parser.add_argument(
        "--mode",
        type=str,
        choices=["standalone", "hub", "peer"],
        default="standalone",
        help="Deployment mode (default: standalone)",
    )

    # Interface options
    parser.add_argument(
        "--port",
        type=int,
        metavar="PORT",
        help="TCP server port for hub mode (default: 4242)",
    )

    parser.add_argument(
        "--peer",
        action="append",
        dest="peers",
        metavar="HOST[:PORT]",
        help="Add peer hub to connect to (repeatable)",
    )

    # Headless mode
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Run in headless mode (no TUI)",
    )

    # API options
    parser.add_argument(
        "--api-port",
        type=int,
        metavar="PORT",
        help="HTTP API port for headless mode (default: 8000)",
    )

    # Config file
    parser.add_argument(
        "--config",
        type=str,
        metavar="PATH",
        help="Custom config file path",
    )

    # Reset
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Reset all config to defaults, restart daemon, and launch TUI",
    )

    # Self-upgrade
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="Upgrade styrene to the latest version from PyPI",
    )

    # Restart daemon
    parser.add_argument(
        "--restart-daemon",
        action="store_true",
        help="Restart the daemon (preserves identity and config)",
    )

    # Remote mode
    parser.add_argument(
        "--remote",
        type=str,
        metavar="URL",
        help="Connect to remote Styrene API (e.g., https://api.styrene.io)",
    )

    # Dashboard mode
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Run compact local dashboard (for Zellij panes)",
    )

    args = parser.parse_args()

    # Validate: remote mode incompatible with headless
    if args.remote and args.headless:
        print("Error: --remote and --headless are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    # Validate: dashboard mode incompatible with headless and remote
    if args.dashboard and args.headless:
        print("Error: --dashboard and --headless are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    if args.dashboard and args.remote:
        print("Error: --dashboard and --remote are mutually exclusive", file=sys.stderr)
        sys.exit(1)

    # Validate: API port only valid with headless
    if args.api_port and not args.headless:
        print("Error: --api-port requires --headless", file=sys.stderr)
        sys.exit(1)

    # Parse peers
    peer_configs = []
    if args.peers:
        try:
            peer_configs = [parse_peer(peer) for peer in args.peers]
        except ValueError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    # Restart daemon mode
    if args.restart_daemon:
        import subprocess
        import time as _time

        print("Stopping daemon...")
        subprocess.run(
            ["pkill", "-f", r"^.*/styrened daemon"],
            capture_output=True,
        )
        _time.sleep(2)
        check = subprocess.run(
            ["pgrep", "-f", r"^.*/styrened daemon"],
            capture_output=True,
        )
        if check.returncode == 0:
            print("✅ Daemon restarted.")
        else:
            print("⚠️  Daemon stopped but did not auto-restart.")
            print("   Start manually: styrened daemon")
        sys.exit(0)

    # Self-upgrade mode
    if args.upgrade:
        import subprocess

        print("Upgrading styrene...")
        # Detect if running under pipx.  Check PIPX_BIN_DIR first (set by
        # pipx inside managed venvs), then fall back to path heuristic.
        exe = sys.executable
        pipx_bin_dir = os.environ.get("PIPX_BIN_DIR", "")
        pipx_venvs = os.path.join(
            os.environ.get("PIPX_HOME", os.path.expanduser("~/.local/pipx")),
            "venvs",
        )
        if pipx_bin_dir or pipx_venvs in exe:
            cmd = ["pipx", "upgrade", "styrene", "--pip-args=--upgrade-strategy=eager"]
        else:
            cmd = [exe, "-m", "pip", "install", "--upgrade", "--upgrade-strategy=eager", "styrene"]

        result = subprocess.run(cmd)
        if result.returncode == 0:
            print("\n✅ Upgrade complete. Restarting daemon...")
            subprocess.run(
                ["pkill", "-f", r"^.*/styrened daemon"],
                capture_output=True,
            )
            import time
            time.sleep(1)
            print("Run 'styrene' to launch the updated TUI.")
        else:
            print("\n❌ Upgrade failed.", file=sys.stderr)
        sys.exit(result.returncode)

    # Reset mode — nuke configs, kill daemon, regenerate defaults
    if args.reset:
        print("This will reset ALL styrene and Reticulum config to defaults.")
        print("Existing configs will be backed up as .bak files.")
        confirm = input("Continue? [y/N] ").strip().lower()
        if confirm not in ("y", "yes"):
            print("Aborted.")
            sys.exit(0)

        import shutil
        import subprocess
        from pathlib import Path

        from styrened import paths
        from styrened.services.config import get_default_core_config, save_core_config
        from styrened.services.reticulum import generate_rns_config

        config_file = paths.config_file()
        rns_config = Path.home() / ".reticulum" / "config"

        # Back up existing configs
        if config_file.exists():
            bak = config_file.with_suffix(".yaml.bak")
            shutil.copy2(config_file, bak)
            print(f"Backed up {config_file} → {bak}")

        if rns_config.exists():
            bak = rns_config.with_suffix(".bak")
            shutil.copy2(rns_config, bak)
            print(f"Backed up {rns_config} → {bak}")

        # Regenerate from defaults
        default_config = get_default_core_config()
        save_core_config(default_config)
        print(f"Regenerated {config_file}")

        rns_content = generate_rns_config(default_config)
        rns_config.parent.mkdir(parents=True, exist_ok=True)
        rns_config.write_text(rns_content)
        print(f"Regenerated {rns_config}")

        # Kill existing daemon
        try:
            subprocess.run(["pkill", "-f", r"^.*/styrened daemon"], timeout=5)
            print("Stopped running daemon")
        except Exception:
            pass

        print("Config reset complete. Launching TUI...\n")

    # Dashboard mode - lightweight local status display
    if args.dashboard:
        import logging

        from styrened import paths

        log_file = paths.log_dir() / "dashboard.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            filename=str(log_file),
            filemode="w",
        )

        from styrened.tui.dashboard_app import LocalDashboardApp

        app = LocalDashboardApp()
        app.run()
        return

    # Dispatch to headless daemon or TUI
    if args.headless:
        import os

        from styrened import paths
        from styrened.rust_daemon import exec_rust_daemon

        # Headless mode now starts the Rust daemon directly.
        os.environ.setdefault("STYRENE_CONFIG_DIR", str(paths.config_dir()))
        os.environ.setdefault("STYRENE_DATA_DIR", str(paths.data_dir()))
        os.environ.setdefault("STYRENED_SOCKET", str(paths.control_socket()))

        result = exec_rust_daemon()
        if result == -1:
            print(
                "[headless] Rust daemon binary not found.\n"
                "  Install via: cargo install styrened\n"
                "  Or download from GitHub releases.",
                file=sys.stderr,
            )
            sys.exit(1)
        sys.exit(result)
    else:
        # Setup logging for TUI mode
        import logging

        from styrened import paths

        log_file = paths.log_dir() / "tui.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            filename=str(log_file),
            filemode="w",
        )

        # Probe terminal image capabilities before Textual takes over
        try:
            import textual_image.renderable  # noqa: F401
        except ImportError:
            pass

        from styrened.tui.app import StyreneApp

        # Create TUI app with CLI overrides
        tui_app = StyreneApp(
            mode=DeploymentMode(args.mode),
            headless=False,
            server_port=args.port,
            peers=peer_configs,
            api_port=args.api_port,
            config_path=args.config,
            remote_url=args.remote,
        )

        tui_app.run()


if __name__ == "__main__":
    main()
