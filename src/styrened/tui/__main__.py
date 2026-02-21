"""Styrene TUI entry point."""

from __future__ import annotations

import argparse
import sys

from styrened.tui.models.config import DeploymentMode, PeerConfig


def parse_peer(peer_str: str) -> PeerConfig:
    """Parse peer string in format host:port or host.

    Args:
        peer_str: Peer string (e.g., "home.vanderlyn.house:4242")

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
  styrene --peer home.vanderlyn.house    # Connect to specific peer
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

    # Remote mode
    parser.add_argument(
        "--remote",
        type=str,
        metavar="URL",
        help="Connect to remote Styrene API (e.g., https://styrene.vanderlyn.house)",
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

    # Dashboard mode - lightweight local status display
    if args.dashboard:
        import logging

        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            filename="/tmp/styrene-dashboard.log",
            filemode="w",
        )

        from styrened.tui.dashboard_app import LocalDashboardApp

        app = LocalDashboardApp()
        app.run()
        return

    # Dispatch to headless daemon or TUI
    if args.headless:
        import asyncio
        import logging

        from styrened.daemon import run_daemon
        from styrened.tui.services.config import load_config, update_styrene_config_from_cli

        # Setup logging for headless mode
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        )

        # Load and apply CLI overrides to config
        config = load_config()
        config = update_styrene_config_from_cli(
            config,
            mode=DeploymentMode(args.mode),
            server_port=args.port,
            peers=peer_configs,
            api_port=args.api_port,
            headless=True,
        )

        # Run daemon
        asyncio.run(run_daemon(config))
    else:
        # Setup logging for TUI mode
        import logging
        logging.basicConfig(
            level=logging.DEBUG,
            format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            filename="/tmp/styrene.log",
            filemode="w",
        )

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
