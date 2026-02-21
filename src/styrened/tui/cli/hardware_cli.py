#!/usr/bin/env python3
"""CLI tool for hardware detection functionality.

Usage:
    python -m styrene.cli.hardware_cli system
    python -m styrene.cli.hardware_cli disks
    python -m styrene.cli.hardware_cli network
    python -m styrene.cli.hardware_cli all
"""

import argparse
import sys

from styrened.tui.services.hardware import (
    PlatformNotSupportedError,
    get_disks,
    get_network_interfaces,
    get_system_info,
)


def cmd_system(args: argparse.Namespace) -> int:
    """Show system information."""
    try:
        info = get_system_info()

        print("\n=== System Information ===\n")
        print(f"  CPU Model:    {info.cpu_model}")
        print(f"  CPU Cores:    {info.cpu_cores}")
        print(f"  RAM Total:    {info.ram_total_gb:.2f} GB")
        print()

        return 0

    except PlatformNotSupportedError as e:
        print(f"Error: {e}")
        return 1


def cmd_disks(args: argparse.Namespace) -> int:
    """Show disk information."""
    try:
        disks = get_disks()

        if not disks:
            print("No disks detected")
            return 0

        print(f"\n=== Disk Information ({len(disks)} disks) ===\n")

        # Group by type
        internal = [d for d in disks if not d.is_removable]
        removable = [d for d in disks if d.is_removable]

        if internal:
            print("INTERNAL DISKS:")
            for disk in internal:
                mount = disk.mount_point or "unmounted"
                print(f"  {disk.name:<15} {disk.size_human:>8} ({mount})")

        if removable:
            print("\nREMOVABLE DISKS:")
            for disk in removable:
                mount = disk.mount_point or "unmounted"
                print(f"  {disk.name:<15} {disk.size_human:>8} ({mount})")

        print()
        return 0

    except PlatformNotSupportedError as e:
        print(f"Error: {e}")
        return 1


def cmd_network(args: argparse.Namespace) -> int:
    """Show network interface information."""
    try:
        interfaces = get_network_interfaces()

        if not interfaces:
            print("No network interfaces detected")
            return 0

        print(f"\n=== Network Interfaces ({len(interfaces)} total) ===\n")

        # Group by hardware vs virtual
        hardware = [i for i in interfaces if i.is_hardware]
        virtual = [i for i in interfaces if not i.is_hardware]

        if hardware:
            print("HARDWARE INTERFACES:")
            for iface in hardware:
                ip = iface.ip_address or "no ip"
                status = "UP" if iface.is_up else "DOWN"
                status_color = "\033[92m" if iface.is_up else "\033[91m"
                print(
                    f"  {iface.name:<15} ({iface.interface_type.value:<10}) "
                    f"{status_color}{status}\033[0m  {ip}"
                )

        if virtual:
            print("\nVIRTUAL INTERFACES:")
            for iface in virtual:
                ip = iface.ip_address or "no ip"
                status = "UP" if iface.is_up else "DOWN"
                print(f"  {iface.name:<15} ({iface.interface_type.value:<10}) {status}  {ip}")

        print()
        return 0

    except PlatformNotSupportedError as e:
        print(f"Error: {e}")
        return 1


def cmd_all(args: argparse.Namespace) -> int:
    """Show all hardware information."""
    cmd_system(args)
    cmd_disks(args)
    cmd_network(args)
    return 0


def main() -> int:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Styrene Hardware Detection CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # System command
    subparsers.add_parser("system", help="Show system information")

    # Disks command
    subparsers.add_parser("disks", help="Show disk information")

    # Network command
    subparsers.add_parser("network", help="Show network interfaces")

    # All command
    subparsers.add_parser("all", help="Show all hardware information")

    args = parser.parse_args()

    # Dispatch command
    if args.command == "system":
        return cmd_system(args)
    elif args.command == "disks":
        return cmd_disks(args)
    elif args.command == "network":
        return cmd_network(args)
    elif args.command == "all":
        return cmd_all(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
