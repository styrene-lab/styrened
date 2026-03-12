from __future__ import annotations

#!/usr/bin/env python3
"""CLI tool for testing Reticulum functionality.

Usage:
    python -m styrene.cli.reticulum_cli status
    python -m styrene.cli.reticulum_cli init
    python -m styrene.cli.reticulum_cli discover
    python -m styrene.cli.reticulum_cli hub-connect <address>
"""

import argparse
import logging
import sys
import time

from styrened.models.mesh_device import MeshDevice
from styrened.services.hub_connection import get_hub_connection
from styrened.tui.services.app_lifecycle import get_service_status, initialize_styrene
from styrened.tui.services.config import load_config
from styrened.tui.services.reticulum import discover_devices, get_styrene_devices, start_discovery


def setup_logging(verbose: bool = False) -> None:
    """Configure logging."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
    )


def cmd_status(args: argparse.Namespace) -> int:
    """Show Reticulum service status."""
    status = get_service_status()

    print("=== Reticulum Service Status ===")
    print(f"RNS Initialized: {status['rns_initialized']}")
    print(f"Operator Identity: {status['operator_identity'] or 'not set'}")
    print(f"Transport Enabled: {status['transport_enabled']}")
    print(f"Interface Count: {status['interface_count']}")
    print(f"\nHub Connected: {status['hub_connected']}")
    if status["hub_address"]:
        print(f"Hub Address: {status['hub_address'][:16]}...")

    return 0


def cmd_init(args: argparse.Namespace) -> int:
    """Initialize Reticulum services."""
    print("Initializing Styrene services...")

    try:
        config = load_config()
    except Exception as e:
        print(f"Warning: Failed to load config: {e}")
        print("Using default configuration")
        config = None

    lifecycle = initialize_styrene(config)

    if lifecycle.is_initialized:
        print("✓ Services initialized successfully")
        status = get_service_status()
        print(f"✓ Operator identity: {status['operator_identity']}")
        if status["hub_connected"]:
            print(f"✓ Connected to hub: {status['hub_address'][:16]}...")
        return 0
    else:
        print("✗ Initialization failed")
        return 1


def cmd_discover(args: argparse.Namespace) -> int:
    """Start device discovery and listen for announces."""
    print("Initializing services...")
    lifecycle = initialize_styrene()

    if not lifecycle.is_initialized:
        print("✗ Failed to initialize services")
        return 1

    print("✓ Services initialized")
    print("\nStarting device discovery...")
    print("Listening for announces (Ctrl+C to stop)...\n")

    # Callback for discovered devices
    def on_device_discovered(device: MeshDevice) -> None:
        is_styrene = device.is_styrene_node
        marker = "✓ STYRENE" if is_styrene else "  OTHER"
        name = device.name or "unknown"
        identity = device.identity_hash[:16] if device.identity_hash else ""
        announces = device.announce_count

        print(f"{marker} | {name:20s} | {identity}... | announces: {announces}")

    # Start discovery
    start_discovery(callback=on_device_discovered)

    try:
        # Keep running and show periodic summary
        while True:
            time.sleep(10)

            # Show summary
            all_devices = discover_devices()
            styrene_devices = get_styrene_devices()

            print(f"\n--- Summary: {len(all_devices)} total, {len(styrene_devices)} styrene ---\n")

    except KeyboardInterrupt:
        print("\n\nStopping discovery...")
        lifecycle.shutdown()
        print("✓ Shutdown complete")
        return 0


def cmd_hub_connect(args: argparse.Namespace) -> int:
    """Connect to a Styrene hub."""
    hub_address = args.address

    if len(hub_address) != 64:
        print(f"✗ Invalid hub address: must be 64 hex characters (got {len(hub_address)})")
        return 1

    print("Initializing services...")
    lifecycle = initialize_styrene()

    if not lifecycle.is_initialized:
        print("✗ Failed to initialize services")
        return 1

    print("✓ Services initialized")
    print(f"\nConnecting to hub at {hub_address[:16]}...")

    hub_connection = get_hub_connection()
    if hub_connection.connect(hub_address):
        print("✓ Connected to hub")
        print(f"  Address: {hub_address}")
        print(f"  Destination: {hub_connection.hub_destination}")
        return 0
    else:
        print("✗ Connection failed")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Styrene Reticulum CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Status command
    subparsers.add_parser("status", help="Show Reticulum service status")

    # Init command
    subparsers.add_parser("init", help="Initialize Reticulum services")

    # Discover command
    subparsers.add_parser("discover", help="Listen for device announces")

    # Hub connect command
    hub_parser = subparsers.add_parser("hub-connect", help="Connect to Styrene hub")
    hub_parser.add_argument("address", help="64-character hex hub address")

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)

    # Dispatch command
    if args.command == "status":
        return cmd_status(args)
    elif args.command == "init":
        return cmd_init(args)
    elif args.command == "discover":
        return cmd_discover(args)
    elif args.command == "hub-connect":
        return cmd_hub_connect(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
