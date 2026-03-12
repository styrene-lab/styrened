from __future__ import annotations

#!/usr/bin/env python3
"""CLI tool for fleet management functionality.

Usage:
    python -m styrene.cli.fleet_cli list
    python -m styrene.cli.fleet_cli summary
    python -m styrene.cli.fleet_cli device <name>
"""

import argparse
import sys
from datetime import datetime

from styrened.tui.services.fleet import (
    FleetInventoryError,
    get_device,
    get_fleet_summary,
    load_inventory,
)


def cmd_list(args: argparse.Namespace) -> int:
    """List all devices in fleet inventory."""
    try:
        devices = load_inventory()

        if not devices:
            print("No devices in fleet inventory")
            return 0

        print(f"\n=== Fleet Inventory ({len(devices)} devices) ===\n")
        print(f"{'NAME':<20} {'PROFILE':<15} {'STATUS':<10} {'IP ADDRESS':<15} {'LAST SEEN'}")
        print("-" * 80)

        for device in devices:
            name = device.name[:20]
            profile = device.profile[:15]
            status = device.status.upper()
            ip = device.ip_address or "--"
            last_seen = device.last_seen_display

            # Colorize status
            status_color = {
                "ONLINE": "\033[92m",  # Green
                "OFFLINE": "\033[91m",  # Red
                "PENDING": "\033[93m",  # Yellow
                "ERROR": "\033[91m",  # Red
            }.get(status, "")
            reset = "\033[0m" if status_color else ""

            print(
                f"{name:<20} {profile:<15} {status_color}{status:<10}{reset} {ip:<15} {last_seen}"
            )

        return 0

    except FleetInventoryError as e:
        print(f"Error loading inventory: {e}")
        return 1


def cmd_summary(args: argparse.Namespace) -> int:
    """Show fleet status summary."""
    try:
        summary = get_fleet_summary()

        print("\n=== Fleet Summary ===\n")
        print(f"  Online:  \033[92m{summary['online']:3d}\033[0m")
        print(f"  Offline: \033[91m{summary['offline']:3d}\033[0m")
        print(f"  Pending: \033[93m{summary['pending']:3d}\033[0m")
        print(f"  Error:   \033[91m{summary['error']:3d}\033[0m")
        print("  ───────────────")
        print(f"  Total:   {summary['total']:3d}\n")

        return 0

    except FleetInventoryError as e:
        print(f"Error getting summary: {e}")
        return 1


def cmd_device(args: argparse.Namespace) -> int:
    """Show detailed information for a device."""
    device_name = args.name

    try:
        device = get_device(device_name)

        if not device:
            print(f"Device not found: {device_name}")
            return 1

        print(f"\n=== Device: {device.name} ===\n")
        print(f"  Profile:           {device.profile}")
        print(f"  Hardware:          {device.hardware}")
        print(f"  Status:            {device.status.upper()}")

        if device.ip_address:
            print(f"  IP Address:        {device.ip_address}")

        if device.reticulum_identity:
            print(f"  Reticulum ID:      {device.reticulum_identity}")

        if device.last_seen:
            last_seen_str = (
                device.last_seen
                if isinstance(device.last_seen, str)
                else device.last_seen.isoformat()
            )
            last_seen_dt = datetime.fromisoformat(last_seen_str)
            print(f"  Last Seen:         {last_seen_dt.strftime('%Y-%m-%d %H:%M:%S')}")

        if device.notes:
            print(f"  Notes:             {device.notes}")

        print()
        return 0

    except FleetInventoryError as e:
        print(f"Error: {e}")
        return 1


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Styrene Fleet Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # List command
    subparsers.add_parser("list", help="List all devices")

    # Summary command
    subparsers.add_parser("summary", help="Show fleet summary")

    # Device command
    device_parser = subparsers.add_parser("device", help="Show device details")
    device_parser.add_argument("name", help="Device name")

    args = parser.parse_args()

    # Dispatch command
    if args.command == "list":
        return cmd_list(args)
    elif args.command == "summary":
        return cmd_summary(args)
    elif args.command == "device":
        return cmd_device(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
