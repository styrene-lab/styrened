"""CLI for styrened - interactive tooling for mesh network operations.

Provides subcommands for:
- daemon: Run the headless daemon (default)
- devices: List discovered mesh devices
- status: Query status of a remote node
- send: Send a message to a node
- exec: Execute a command on a remote node
- announce: Trigger an announce
- identity: Show local operator identity

Usage:
    styrened                      # Run daemon (default)
    styrened daemon               # Run daemon explicitly
    styrened devices              # List discovered devices
    styrened status <dest>        # Query remote node status
    styrened send <dest> <msg>    # Send chat message
    styrened exec <dest> <cmd>    # Execute command on remote
    styrened announce             # Trigger local announce
    styrened identity             # Show local identity info
"""

import argparse
import asyncio
import logging
import sys
import time
from typing import NoReturn

logger = logging.getLogger(__name__)


def setup_logging(verbose: bool = False) -> None:
    """Configure logging for CLI commands.

    Args:
        verbose: If True, set DEBUG level; otherwise INFO.
    """
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


# -----------------------------------------------------------------------------
# Subcommand: daemon
# -----------------------------------------------------------------------------


def cmd_daemon(args: argparse.Namespace) -> int:
    """Run the styrened daemon.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened.daemon import main as daemon_main

    daemon_main()
    return 0


# -----------------------------------------------------------------------------
# Subcommand: devices
# -----------------------------------------------------------------------------


def cmd_devices(args: argparse.Namespace) -> int:
    """List discovered mesh devices.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_devices_async(args))


async def _cmd_devices_async(args: argparse.Namespace) -> int:
    """Async implementation of devices command."""
    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.reticulum import discover_devices, start_discovery

    # Load config
    try:
        config = load_core_config()
    except FileNotFoundError:
        config = get_default_core_config()

    # Initialize services (client_only=True to avoid binding server port)
    lifecycle = CoreLifecycle(config, client_only=True)
    if not lifecycle.initialize():
        print("Failed to initialize services", file=sys.stderr)
        return 1

    # Start discovery
    start_discovery()

    # Wait for announces
    wait_time = args.wait if hasattr(args, "wait") else 5
    print(f"Listening for announces ({wait_time}s)...")
    await asyncio.sleep(wait_time)

    # Get discovered devices
    devices = discover_devices()

    if not devices:
        print("No devices discovered")
        lifecycle.shutdown()
        return 0

    # Display devices
    print(f"\nDiscovered {len(devices)} device(s):\n")

    if args.json:
        import json

        output = [
            {
                "name": d.name,
                "destination_hash": d.destination_hash,
                "identity_hash": d.identity_hash,
                "device_type": d.device_type.value,
                "status": d.status.value,
                "is_styrene": d.is_styrene_node,
                "announce_count": d.announce_count,
            }
            for d in devices
        ]
        print(json.dumps(output, indent=2))
    else:
        for device in devices:
            styrene_marker = " [styrene]" if device.is_styrene_node else ""
            print(f"  {device.name}{styrene_marker}")
            print(f"    Destination: {device.destination_hash[:32]}...")
            print(f"    Identity:    {device.identity_hash[:32]}...")
            print(f"    Type:        {device.device_type.value}")
            print(f"    Status:      {device.status.value}")
            print(f"    Announces:   {device.announce_count}")
            print()

    lifecycle.shutdown()
    return 0


# -----------------------------------------------------------------------------
# Subcommand: status
# -----------------------------------------------------------------------------


def cmd_status(args: argparse.Namespace) -> int:
    """Query status of a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_status_async(args))


async def _cmd_status_async(args: argparse.Namespace) -> int:
    """Async implementation of status command."""
    from styrened.rpc import RPCClient
    from styrened.rpc.errors import RPCTimeoutError, RPCTransportError
    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.services.reticulum import (
        discover_devices,
        get_operator_identity_object,
        start_discovery,
        stop_discovery,
    )

    # Load config
    try:
        config = load_core_config()
    except FileNotFoundError:
        config = get_default_core_config()

    # Initialize services (client_only=True to avoid binding server port)
    lifecycle = CoreLifecycle(config, client_only=True)
    if not lifecycle.initialize():
        print("Failed to initialize services", file=sys.stderr)
        return 1

    # Initialize LXMF
    lxmf_service = get_lxmf_service()
    identity = get_operator_identity_object()
    if not identity or not lxmf_service.initialize(identity):
        print("Failed to initialize LXMF", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    destination = args.destination
    timeout = args.timeout if hasattr(args, "timeout") else 30.0
    discovery_wait = getattr(args, "wait", 10)

    # Start discovery and wait for target device to announce
    # Pass node_store for persistence so we can look up identity later
    from styrened.services.node_store import get_node_store

    node_store = get_node_store()

    print(f"Waiting for {destination[:16]}... to announce ({discovery_wait}s)...")
    start_discovery(node_store=node_store)

    # Wait for announce from target device
    target_device = None
    start_time = time.time()
    while time.time() - start_time < discovery_wait:
        devices = discover_devices()
        for device in devices:
            # Match by destination hash prefix
            if device.destination_hash and device.destination_hash.startswith(destination[:16]):
                target_device = device
                break
        if target_device:
            break
        await asyncio.sleep(0.5)

    # Stop discovery BEFORE sending - discovery handler interferes with path responses
    stop_discovery()
    await asyncio.sleep(0.5)  # Delay to ensure handler is fully deregistered

    if not target_device:
        print(f"Device {destination[:16]}... not found after {discovery_wait}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    # Use LXMF destination from announce if available
    lxmf_dest = target_device.lxmf_destination_hash
    if not lxmf_dest:
        print(f"Device {target_device.name} has no LXMF destination in announce", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    print(f"Found {target_device.name}, LXMF dest {lxmf_dest[:16]}...")

    # The identity from the announce can be used to construct the LXMF destination
    # Store the identity hash so send_message can recall it
    identity_hash = target_device.identity_hash
    if identity_hash:
        print(f"Identity hash: {identity_hash[:16]}...")

        # Try to recall the identity from RNS (should be known from the announce)
        import RNS

        identity_bytes = bytes.fromhex(identity_hash)
        # Use from_identity_hash=True since we have identity hash, not destination hash
        recalled_identity = RNS.Identity.recall(identity_bytes, from_identity_hash=True)
        if recalled_identity:
            print(f"Identity recalled successfully")
        else:
            print(f"Warning: Identity not recalled - may need to wait for LXMF announce")

    # Create RPC client
    rpc_client = RPCClient(lxmf_service)

    print(f"Querying status (timeout: {timeout}s)...")

    try:
        response = await rpc_client.call_status(lxmf_dest, timeout=timeout)

        if args.json:
            import json

            output = {
                "uptime": response.uptime,
                "uptime_formatted": response.format_uptime(),
                "ip": response.ip,
                "disk_used": response.disk_used,
                "disk_total": response.disk_total,
                "disk_formatted": response.format_disk_usage(),
                "services": response.services,
            }
            print(json.dumps(output, indent=2))
        else:
            print(f"\nStatus of {destination[:16]}...:")
            print(f"  Uptime:   {response.format_uptime()}")
            print(f"  IP:       {response.ip}")
            print(f"  Disk:     {response.format_disk_usage()}")
            print(f"  Services: {', '.join(response.services) or 'none'}")

        lifecycle.shutdown()
        return 0

    except RPCTimeoutError:
        print(f"Timeout: no response from {destination[:16]}... after {timeout}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1
    except RPCTransportError as e:
        print(f"Transport error: {e}", file=sys.stderr)
        lifecycle.shutdown()
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        lifecycle.shutdown()
        return 1


# -----------------------------------------------------------------------------
# Subcommand: send
# -----------------------------------------------------------------------------


def cmd_send(args: argparse.Namespace) -> int:
    """Send a message to a node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_send_async(args))


async def _cmd_send_async(args: argparse.Namespace) -> int:
    """Async implementation of send command."""
    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.services.node_store import get_node_store
    from styrened.services.reticulum import (
        discover_devices,
        get_operator_identity_object,
        start_discovery,
        stop_discovery,
    )

    # Load config
    try:
        config = load_core_config()
    except FileNotFoundError:
        config = get_default_core_config()

    # Initialize services (client_only=True to avoid binding server port)
    lifecycle = CoreLifecycle(config, client_only=True)
    if not lifecycle.initialize():
        print("Failed to initialize services", file=sys.stderr)
        return 1

    # Initialize LXMF
    lxmf_service = get_lxmf_service()
    identity = get_operator_identity_object()
    if not identity or not lxmf_service.initialize(identity):
        print("Failed to initialize LXMF", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    destination = args.destination
    message = args.message
    retry = args.retry if hasattr(args, "retry") else False
    max_wait = args.max_wait if hasattr(args, "max_wait") else 30.0
    discovery_wait = getattr(args, "wait", 10)

    # Start discovery and wait for target device to announce
    # This is required to get the identity into memory for sending
    node_store = get_node_store()
    print(f"Waiting for {destination[:16]}... to announce ({discovery_wait}s)...")
    start_discovery(node_store=node_store)

    # Wait for announce from target device
    target_device = None
    start_time = time.time()
    while time.time() - start_time < discovery_wait:
        devices = discover_devices()
        for device in devices:
            # Match by destination hash prefix
            if device.destination_hash and device.destination_hash.startswith(destination[:16]):
                target_device = device
                break
        if target_device:
            break
        await asyncio.sleep(0.5)

    # Stop discovery before sending
    stop_discovery()
    await asyncio.sleep(0.5)

    if not target_device:
        print(f"Device {destination[:16]}... not found after {discovery_wait}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    # Use the LXMF destination for sending
    lxmf_dest = target_device.lxmf_destination_hash or destination
    print(f"Found {target_device.name or 'device'}, sending to LXMF dest {lxmf_dest[:16]}...")

    payload = {"type": "chat", "protocol": "chat", "content": message}

    if retry:
        success = lxmf_service.send_with_retry(
            lxmf_dest, payload, max_wait=max_wait, check_interval=2.0
        )
    else:
        success = lxmf_service.send_message(lxmf_dest, payload)

    if success:
        print("Message sent successfully")
        lifecycle.shutdown()
        return 0
    else:
        print("Failed to send message (no path or identity not known)", file=sys.stderr)
        lifecycle.shutdown()
        return 1


# -----------------------------------------------------------------------------
# Subcommand: exec
# -----------------------------------------------------------------------------


def cmd_exec(args: argparse.Namespace) -> int:
    """Execute a command on a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_exec_async(args))


async def _cmd_exec_async(args: argparse.Namespace) -> int:
    """Async implementation of exec command."""
    from styrened.rpc import RPCClient
    from styrened.rpc.errors import RPCTimeoutError, RPCTransportError
    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.services.node_store import get_node_store
    from styrened.services.reticulum import (
        discover_devices,
        get_operator_identity_object,
        start_discovery,
        stop_discovery,
    )

    # Load config
    try:
        config = load_core_config()
    except FileNotFoundError:
        config = get_default_core_config()

    # Initialize services (client_only=True to avoid binding server port)
    lifecycle = CoreLifecycle(config, client_only=True)
    if not lifecycle.initialize():
        print("Failed to initialize services", file=sys.stderr)
        return 1

    # Initialize LXMF
    lxmf_service = get_lxmf_service()
    identity = get_operator_identity_object()
    if not identity or not lxmf_service.initialize(identity):
        print("Failed to initialize LXMF", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    destination = args.destination
    command = args.command
    cmd_args = args.args if hasattr(args, "args") and args.args else []
    timeout = args.timeout if hasattr(args, "timeout") else 60.0
    discovery_wait = getattr(args, "wait", 10)

    # Start discovery and wait for target device to announce
    node_store = get_node_store()
    print(f"Waiting for {destination[:16]}... to announce ({discovery_wait}s)...")
    start_discovery(node_store=node_store)

    # Wait for announce from target device
    target_device = None
    start_time = time.time()
    while time.time() - start_time < discovery_wait:
        devices = discover_devices()
        for device in devices:
            if device.destination_hash and device.destination_hash.startswith(destination[:16]):
                target_device = device
                break
        if target_device:
            break
        await asyncio.sleep(0.5)

    # Stop discovery before sending
    stop_discovery()
    await asyncio.sleep(0.5)

    if not target_device:
        print(f"Device {destination[:16]}... not found after {discovery_wait}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    # Use the LXMF destination for RPC
    lxmf_dest = target_device.lxmf_destination_hash or destination
    print(f"Found {target_device.name or 'device'}, LXMF dest {lxmf_dest[:16]}...")

    # Create RPC client
    rpc_client = RPCClient(lxmf_service)

    print(f"Executing '{command} {' '.join(cmd_args)}'...")

    try:
        result = await rpc_client.call_exec(lxmf_dest, command, cmd_args, timeout=timeout)

        if args.json:
            import json

            output = {
                "exit_code": result.exit_code,
                "success": result.success,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
            print(json.dumps(output, indent=2))
        else:
            if result.stdout:
                print(result.stdout)
            if result.stderr:
                print(result.stderr, file=sys.stderr)
            if not result.success:
                print(f"\nExit code: {result.exit_code}", file=sys.stderr)

        lifecycle.shutdown()
        return result.exit_code

    except RPCTimeoutError:
        print(f"Timeout: no response after {timeout}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1
    except RPCTransportError as e:
        print(f"Transport error: {e}", file=sys.stderr)
        lifecycle.shutdown()
        return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        lifecycle.shutdown()
        return 1


# -----------------------------------------------------------------------------
# Subcommand: announce
# -----------------------------------------------------------------------------


def cmd_announce(args: argparse.Namespace) -> int:
    """Trigger an announce of local identity.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_announce_async(args))


async def _cmd_announce_async(args: argparse.Namespace) -> int:
    """Async implementation of announce command."""
    import socket

    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.reticulum import get_operator_identity_object
    from styrened.services.rns_service import get_rns_service

    # Load config
    try:
        config = load_core_config()
    except FileNotFoundError:
        config = get_default_core_config()

    # Initialize services (client_only=True to avoid binding server port)
    lifecycle = CoreLifecycle(config, client_only=True)
    if not lifecycle.initialize():
        print("Failed to initialize services", file=sys.stderr)
        return 1

    identity = get_operator_identity_object()
    if not identity:
        print("No operator identity", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    # Create destination and announce
    rns_service = get_rns_service()
    destination = rns_service.get_or_create_destination(
        identity, app_name="styrene_node", aspect="operator"
    )

    if not destination:
        print("Failed to create destination", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    hostname = socket.gethostname()
    version = "0.2.0"
    app_data = f"styrene:{hostname}:{version}:cli:".encode()
    destination.announce(app_data=app_data)

    print(f"Announced as {hostname}")
    print(f"  Destination: {destination.hexhash}")

    lifecycle.shutdown()
    return 0


# -----------------------------------------------------------------------------
# Subcommand: identity
# -----------------------------------------------------------------------------


def cmd_identity(args: argparse.Namespace) -> int:
    """Show local operator identity information.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened.services.reticulum import (
        OPERATOR_IDENTITY_PATH,
        ensure_operator_identity,
        get_operator_identity,
    )

    # Get or create identity
    try:
        if args.create:
            identity_hash = ensure_operator_identity()
            print(f"Identity ensured: {identity_hash}")
        else:
            identity_hash = get_operator_identity()
            if not identity_hash:
                print("No operator identity found. Use --create to generate one.")
                return 1
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        import json

        output = {
            "identity_hash": identity_hash,
            "identity_path": str(OPERATOR_IDENTITY_PATH),
            "exists": OPERATOR_IDENTITY_PATH.exists(),
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"Operator Identity:")
        print(f"  Hash: {identity_hash}")
        print(f"  Path: {OPERATOR_IDENTITY_PATH}")

    return 0


# -----------------------------------------------------------------------------
# Argument parser
# -----------------------------------------------------------------------------


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for styrened CLI.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="styrened",
        description="Styrene headless daemon and mesh network tools",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # daemon (default when no subcommand given)
    daemon_parser = subparsers.add_parser("daemon", help="Run the daemon")
    daemon_parser.set_defaults(func=cmd_daemon)

    # devices
    devices_parser = subparsers.add_parser("devices", help="List discovered devices")
    devices_parser.add_argument(
        "-w", "--wait", type=int, default=5, help="Seconds to wait for announces (default: 5)"
    )
    devices_parser.add_argument("--json", action="store_true", help="Output as JSON")
    devices_parser.set_defaults(func=cmd_devices)

    # status
    status_parser = subparsers.add_parser("status", help="Query remote node status")
    status_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    status_parser.add_argument(
        "-w",
        "--wait",
        type=int,
        default=10,
        help="Seconds to wait for device announce (default: 10)",
    )
    status_parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, help="RPC timeout in seconds (default: 30)"
    )
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")
    status_parser.set_defaults(func=cmd_status)

    # send
    send_parser = subparsers.add_parser("send", help="Send message to node")
    send_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    send_parser.add_argument("message", help="Message content")
    send_parser.add_argument(
        "-r", "--retry", action="store_true", help="Retry until path available"
    )
    send_parser.add_argument(
        "-w", "--wait", type=int, default=10, help="Discovery wait time in seconds (default: 10)"
    )
    send_parser.add_argument(
        "--max-wait", type=float, default=30.0, help="Max wait for path (default: 30s)"
    )
    send_parser.set_defaults(func=cmd_send)

    # exec
    exec_parser = subparsers.add_parser("exec", help="Execute command on remote node")
    exec_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    exec_parser.add_argument("command", help="Command to execute")
    exec_parser.add_argument("args", nargs="*", help="Command arguments")
    exec_parser.add_argument(
        "-t", "--timeout", type=float, default=60.0, help="Timeout in seconds (default: 60)"
    )
    exec_parser.add_argument(
        "-w", "--wait", type=int, default=10, help="Discovery wait time in seconds (default: 10)"
    )
    exec_parser.add_argument("--json", action="store_true", help="Output as JSON")
    exec_parser.set_defaults(func=cmd_exec)

    # announce
    announce_parser = subparsers.add_parser("announce", help="Trigger local announce")
    announce_parser.set_defaults(func=cmd_announce)

    # identity
    identity_parser = subparsers.add_parser("identity", help="Show operator identity")
    identity_parser.add_argument("--create", action="store_true", help="Create identity if missing")
    identity_parser.add_argument("--json", action="store_true", help="Output as JSON")
    identity_parser.set_defaults(func=cmd_identity)

    return parser


def main() -> NoReturn:
    """Main entry point for styrened CLI."""
    parser = create_parser()
    args = parser.parse_args()

    setup_logging(args.verbose)

    # Default to daemon if no subcommand given
    if args.command is None:
        args.func = cmd_daemon

    try:
        exit_code = args.func(args)
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\nInterrupted", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Unexpected error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
