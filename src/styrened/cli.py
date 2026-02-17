"""CLI for styrened - interactive tooling for mesh network operations.

Provides subcommands for:
- daemon: Run the headless daemon (default)
- devices: List discovered mesh devices
- status: Query status of a remote node
- send: Send a message to a node
- exec: Execute a command on a remote node
- announce: Trigger an announce
- identity: Show local operator identity
- conversations: List conversations
- messages: List messages for a conversation

Usage:
    styrened                      # Run daemon (default)
    styrened daemon               # Run daemon explicitly
    styrened devices              # List discovered devices
    styrened status <dest>        # Query remote node status
    styrened send <dest> <msg>    # Send chat message
    styrened exec <dest> <cmd>    # Execute command on remote
    styrened announce             # Trigger local announce
    styrened identity             # Show local identity info
    styrened conversations        # List conversations
    styrened messages <peer>      # List messages with peer
"""

import argparse
import asyncio
import logging
import sys
import time
from typing import Any, NoReturn, cast

logger = logging.getLogger(__name__)


# -----------------------------------------------------------------------------
# IPC Helper
# -----------------------------------------------------------------------------


async def _try_ipc_client():
    """Try to connect to a running daemon via IPC.

    Returns:
        Connected ControlClient if daemon is running, None otherwise.
    """
    try:
        from styrened.ipc import get_daemon_client

        return await get_daemon_client()
    except Exception as e:
        logger.debug(f"IPC connection failed: {e}")
        return None


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
    # Try IPC first (instant if daemon is running)
    client = await _try_ipc_client()
    if client:
        try:
            devices = await client.query_devices()
            await client.disconnect()

            if not devices:
                print("No devices discovered")
                return 0

            print(f"\nDiscovered {len(devices)} device(s):\n")

            if args.json:
                import json

                output = [d.to_dict() for d in devices]
                print(json.dumps(output, indent=2))
            else:
                for device in devices:
                    styrene_marker = " [styrene]" if device.is_styrene_node else ""
                    print(f"  {device.name}{styrene_marker}")
                    dest = device.destination_hash or ""
                    ident = device.identity_hash or ""
                    print(
                        f"    Destination: {dest[:32]}..." if dest else "    Destination: (unknown)"
                    )
                    print(
                        f"    Identity:    {ident[:32]}..." if ident else "    Identity: (unknown)"
                    )
                    print(f"    Type:        {device.device_type}")
                    print(f"    Status:      {device.status}")
                    print(f"    Announces:   {device.announce_count}")
                    print()

            return 0
        except Exception as e:
            logger.warning(f"IPC query failed, falling back to standalone: {e}")
            await client.disconnect()

    # Fallback: standalone discovery mode
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

    try:
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

        return 0
    finally:
        lifecycle.shutdown()


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
    destination = args.destination
    timeout = args.timeout if hasattr(args, "timeout") else 30.0

    # Try IPC first (uses daemon's mesh stack)
    client = await _try_ipc_client()
    if client:
        try:
            print(f"Querying status via daemon (timeout: {timeout}s)...")
            status = await client.device_status(destination, timeout=timeout)
            await client.disconnect()

            if args.json:
                import json

                output = status.to_dict()
                # Add formatted fields
                hours, remainder = divmod(int(status.uptime), 3600)
                minutes, seconds = divmod(remainder, 60)
                output["uptime_formatted"] = f"{hours}h {minutes}m {seconds}s"
                if status.disk_total > 0:
                    pct = (status.disk_used / status.disk_total) * 100
                    output["disk_formatted"] = (
                        f"{status.disk_used // (1024**3)}GB / {status.disk_total // (1024**3)}GB ({pct:.1f}%)"
                    )
                print(json.dumps(output, indent=2))
            else:
                hours, remainder = divmod(int(status.uptime), 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = f"{hours}h {minutes}m {seconds}s"
                disk_str = "unknown"
                if status.disk_total > 0:
                    pct = (status.disk_used / status.disk_total) * 100
                    disk_str = f"{status.disk_used // (1024**3)}GB / {status.disk_total // (1024**3)}GB ({pct:.1f}%)"

                print(f"\nStatus of {destination[:16]}...:")
                print(f"  Uptime:   {uptime_str}")
                print(f"  IP:       {status.ip}")
                print(f"  Disk:     {disk_str}")
                print(f"  Services: {', '.join(status.services) or 'none'}")

            return 0
        except Exception as e:
            logger.warning(f"IPC status failed, falling back to standalone: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass

    # Fallback: standalone mode
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

    discovery_wait = getattr(args, "wait", 10)

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
            # Match by any hash: destination, LXMF destination, or identity
            prefix = destination[:16]
            if (
                (device.destination_hash and device.destination_hash.startswith(prefix))
                or (
                    device.lxmf_destination_hash and device.lxmf_destination_hash.startswith(prefix)
                )
                or (device.identity_hash and device.identity_hash.startswith(prefix))
            ):
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
            print("Identity recalled successfully")
        else:
            print("Warning: Identity not recalled - may need to wait for LXMF announce")

    # Create StyreneProtocol for RPC transport
    # RPCClient requires StyreneProtocol, not LXMFService
    from styrened.models.messages import init_db
    from styrened.protocols.base import LXMFMessage
    from styrened.protocols.styrene import StyreneProtocol

    db_engine = init_db()
    styrene_protocol = StyreneProtocol(
        router=lxmf_service.router,
        identity=lxmf_service._identity,
        db_engine=db_engine,
    )

    # Register LXMF callback to dispatch messages to StyreneProtocol
    # This is required for receiving RPC responses
    def dispatch_to_styrene(lxmf_message: Any) -> None:
        import asyncio

        wrapped = LXMFMessage(
            source_hash=lxmf_message.source_hash.hex(),
            destination_hash=lxmf_message.destination_hash.hex()
            if lxmf_message.destination_hash
            else "",
            timestamp=lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else 0.0,
            content=lxmf_message.content.decode("utf-8")
            if isinstance(lxmf_message.content, bytes)
            else (lxmf_message.content or ""),
            fields=lxmf_message.fields or {},
        )
        if styrene_protocol.can_handle(wrapped):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(styrene_protocol.handle_message(wrapped))
            except RuntimeError:
                asyncio.run(styrene_protocol.handle_message(wrapped))

    lxmf_service.register_callback(dispatch_to_styrene, raw_mode=True)

    # Create RPC client with StyreneProtocol
    rpc_client = RPCClient(styrene_protocol)

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
    destination = args.destination
    message = args.message
    retry = args.retry if hasattr(args, "retry") else False
    max_wait = args.max_wait if hasattr(args, "max_wait") else 30.0

    # Try IPC first (uses daemon's mesh stack)
    client = await _try_ipc_client()
    if client:
        try:
            print("Sending message via daemon...")
            success = await client.send_message(destination, message, retry=retry, timeout=max_wait)
            await client.disconnect()

            if success:
                print("Message sent successfully")
                return 0
            else:
                print("Failed to send message", file=sys.stderr)
                return 1
        except Exception as e:
            logger.warning(f"IPC send failed, falling back to standalone: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass

    # Fallback: standalone mode
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

    discovery_wait = getattr(args, "wait", 10)

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

    # Start discovery and wait for target device to announce
    # This is required to get the identity into memory for sending
    node_store = get_node_store()
    print(f"Waiting for {destination[:16]}... to announce ({discovery_wait}s)...")
    start_discovery(node_store=node_store)

    # Wait for announce from target device
    target_device = None
    start_time = time.time()
    prefix = destination[:16]
    while time.time() - start_time < discovery_wait:
        devices = discover_devices()
        for device in devices:
            # Match by any hash: destination, LXMF destination, or identity
            if (
                (device.destination_hash and device.destination_hash.startswith(prefix))
                or (
                    device.lxmf_destination_hash and device.lxmf_destination_hash.startswith(prefix)
                )
                or (device.identity_hash and device.identity_hash.startswith(prefix))
            ):
                target_device = device
                break
        if target_device:
            # Wait a bit more for LXMF destination announce (arrives shortly after operator announce)
            await asyncio.sleep(1.0)
            # Refresh device info to get LXMF destination if it arrived
            devices = discover_devices()
            for device in devices:
                if (
                    (device.destination_hash and device.destination_hash.startswith(prefix))
                    or (
                        device.lxmf_destination_hash
                        and device.lxmf_destination_hash.startswith(prefix)
                    )
                    or (device.identity_hash and device.identity_hash.startswith(prefix))
                ):
                    target_device = device
                    break
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
        result = lxmf_service.send_message(lxmf_dest, payload)
        success = result is not None

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
    destination = args.destination
    command = args.command
    cmd_args = args.args if hasattr(args, "args") and args.args else []
    timeout = args.timeout if hasattr(args, "timeout") else 60.0

    # Try IPC first (uses daemon's mesh stack)
    client = await _try_ipc_client()
    if client:
        try:
            print(f"Executing '{command} {' '.join(cmd_args)}' via daemon...")
            result = await client.exec_command(destination, command, cmd_args, timeout=timeout)
            await client.disconnect()

            if args.json:
                import json

                output = result.to_dict()
                output["success"] = result.success
                print(json.dumps(output, indent=2))
            else:
                if result.stdout:
                    print(result.stdout)
                if result.stderr:
                    print(result.stderr, file=sys.stderr)
                if not result.success:
                    print(f"\nExit code: {result.exit_code}", file=sys.stderr)

            return cast(int, result.exit_code)
        except Exception as e:
            logger.warning(f"IPC exec failed, falling back to standalone: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass

    # Fallback: standalone mode
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

    discovery_wait = getattr(args, "wait", 10)

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

    # Start discovery and wait for target device to announce
    node_store = get_node_store()
    print(f"Waiting for {destination[:16]}... to announce ({discovery_wait}s)...")
    start_discovery(node_store=node_store)

    # Wait for announce from target device
    target_device = None
    start_time = time.time()
    prefix = destination[:16]
    while time.time() - start_time < discovery_wait:
        devices = discover_devices()
        for device in devices:
            # Match by any hash: destination, LXMF destination, or identity
            if (
                (device.destination_hash and device.destination_hash.startswith(prefix))
                or (
                    device.lxmf_destination_hash and device.lxmf_destination_hash.startswith(prefix)
                )
                or (device.identity_hash and device.identity_hash.startswith(prefix))
            ):
                target_device = device
                break
        if target_device:
            # Wait a bit more for LXMF destination announce (arrives shortly after operator announce)
            await asyncio.sleep(1.0)
            # Refresh device info to get LXMF destination if it arrived
            devices = discover_devices()
            for device in devices:
                if (
                    (device.destination_hash and device.destination_hash.startswith(prefix))
                    or (
                        device.lxmf_destination_hash
                        and device.lxmf_destination_hash.startswith(prefix)
                    )
                    or (device.identity_hash and device.identity_hash.startswith(prefix))
                ):
                    target_device = device
                    break
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

    # Create StyreneProtocol for RPC transport
    # RPCClient requires StyreneProtocol, not LXMFService
    from styrened.models.messages import init_db
    from styrened.protocols.base import LXMFMessage
    from styrened.protocols.styrene import StyreneProtocol

    db_engine = init_db()
    styrene_protocol = StyreneProtocol(
        router=lxmf_service.router,
        identity=lxmf_service._identity,
        db_engine=db_engine,
    )

    # Register LXMF callback to dispatch messages to StyreneProtocol
    # This is required for receiving RPC responses
    def dispatch_to_styrene(lxmf_message: Any) -> None:
        import asyncio

        wrapped = LXMFMessage(
            source_hash=lxmf_message.source_hash.hex(),
            destination_hash=lxmf_message.destination_hash.hex()
            if lxmf_message.destination_hash
            else "",
            timestamp=lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else 0.0,
            content=lxmf_message.content.decode("utf-8")
            if isinstance(lxmf_message.content, bytes)
            else (lxmf_message.content or ""),
            fields=lxmf_message.fields or {},
        )
        if styrene_protocol.can_handle(wrapped):
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(styrene_protocol.handle_message(wrapped))
            except RuntimeError:
                asyncio.run(styrene_protocol.handle_message(wrapped))

    lxmf_service.register_callback(dispatch_to_styrene, raw_mode=True)

    # Create RPC client with StyreneProtocol
    rpc_client = RPCClient(styrene_protocol)

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
    # Try IPC first (uses daemon's destination)
    client = await _try_ipc_client()
    if client:
        try:
            dest_hash = await client.announce()
            await client.disconnect()

            print("Announced via daemon")
            print(f"  Destination: {dest_hash}")
            return 0
        except Exception as e:
            logger.warning(f"IPC announce failed, falling back to standalone: {e}")
            try:
                await client.disconnect()
            except Exception:
                pass

    # Fallback: standalone mode
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
        _resolve_identity_path,
        ensure_operator_identity,
        get_operator_identity,
    )

    # Get or create identity
    identity_hash: str | None = None
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

    active_path = _resolve_identity_path()

    if args.json:
        import json

        output = {
            "identity_hash": identity_hash,
            "identity_path": str(active_path) if active_path else None,
            "exists": active_path is not None,
        }
        print(json.dumps(output, indent=2))
    else:
        print("Operator Identity:")
        print(f"  Hash: {identity_hash}")
        print(f"  Path: {active_path or 'not found'}")

    return 0


def cmd_identity_status(args: argparse.Namespace) -> int:
    """Show identity sharing status with other LXMF applications.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened.services.reticulum import (
        _resolve_identity_path,
        get_identity_sharing_status,
        get_operator_identity,
    )

    identity_hash = get_operator_identity()
    active_path = _resolve_identity_path()

    if args.json:
        import json

        status = get_identity_sharing_status()
        # Convert Path objects to strings for JSON
        output = {
            "styrened": {
                "identity_hash": identity_hash,
                "identity_path": str(active_path) if active_path else None,
                "exists": active_path is not None,
            },
            "apps": {
                app: {
                    "path": str(info["path"]),
                    "exists": info["exists"],
                    "is_symlink": info["is_symlink"],
                    "points_to_styrened": info["points_to_styrened"],
                    "symlink_target": str(info["symlink_target"])
                    if info["symlink_target"]
                    else None,
                }
                for app, info in status.items()
            },
        }
        print(json.dumps(output, indent=2))
    else:
        print("Styrened Identity:")
        if identity_hash:
            print(f"  Hash: {identity_hash}")
            print(f"  Path: {active_path or 'not found'}")
        else:
            print("  Not created yet (use 'styrened identity --create')")
        print()

        print("LXMF Application Status:")
        status = get_identity_sharing_status()
        for app, info in status.items():
            status_str = ""
            if info["points_to_styrened"]:
                status_str = "-> styrened (shared)"
            elif info["is_symlink"]:
                status_str = f"-> {info['symlink_target']} (other)"
            elif info["exists"]:
                status_str = "(independent identity)"
            else:
                status_str = "(not installed)"
            print(f"  {app}: {status_str}")
            print(f"    Path: {info['path']}")

    return 0


def cmd_identity_share(args: argparse.Namespace) -> int:
    """Share styrened identity with other LXMF applications.

    Creates symlinks from other applications' identity paths to styrened's identity,
    making styrened the source of truth for mesh identity.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened.services.reticulum import (
        LXMF_SYMLINK_TARGETS,
        share_identity_with_apps,
    )

    apps = args.apps if args.apps else None  # None means all apps

    if apps:
        # Validate app names
        invalid = [a for a in apps if a not in LXMF_SYMLINK_TARGETS]
        if invalid:
            print(f"Unknown apps: {', '.join(invalid)}", file=sys.stderr)
            print(f"Valid apps: {', '.join(LXMF_SYMLINK_TARGETS.keys())}", file=sys.stderr)
            return 1

    try:
        results = share_identity_with_apps(
            apps=apps,
            backup=not args.no_backup,
            force=args.force,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        import json

        output = [
            {
                "app": r.app,
                "path": str(r.path),
                "success": r.success,
                "message": r.message,
                "backed_up_to": str(r.backed_up_to) if r.backed_up_to else None,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        for r in results:
            status = "OK" if r.success else "FAILED"
            print(f"[{status}] {r.app}: {r.message}")
            if r.backed_up_to:
                print(f"       Backup: {r.backed_up_to}")

    # Return error if any failed
    return 0 if all(r.success for r in results) else 1


def cmd_identity_unshare(args: argparse.Namespace) -> int:
    """Remove identity sharing with other LXMF applications.

    Removes symlinks from other applications and optionally restores their
    original identity files from backups.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened.services.reticulum import (
        LXMF_SYMLINK_TARGETS,
        unshare_identity_from_apps,
    )

    apps = args.apps if args.apps else None  # None means all apps

    if apps:
        # Validate app names
        invalid = [a for a in apps if a not in LXMF_SYMLINK_TARGETS]
        if invalid:
            print(f"Unknown apps: {', '.join(invalid)}", file=sys.stderr)
            print(f"Valid apps: {', '.join(LXMF_SYMLINK_TARGETS.keys())}", file=sys.stderr)
            return 1

    results = unshare_identity_from_apps(
        apps=apps,
        restore_backup=not args.no_restore,
    )

    if args.json:
        import json

        output = [
            {
                "app": r.app,
                "path": str(r.path),
                "success": r.success,
                "message": r.message,
            }
            for r in results
        ]
        print(json.dumps(output, indent=2))
    else:
        for r in results:
            status = "OK" if r.success else "SKIPPED"
            print(f"[{status}] {r.app}: {r.message}")

    return 0


# -----------------------------------------------------------------------------
# Argument parser
# -----------------------------------------------------------------------------


def cmd_shell(args: argparse.Namespace) -> int:
    """Start an interactive shell session on a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code from remote shell, or error code on failure.
    """
    return asyncio.run(_cmd_shell_async(args))


async def _cmd_shell_async(args: argparse.Namespace) -> int:
    """Async implementation of shell command."""
    import os

    destination = args.destination

    # Validate destination format (32 hex chars = 16 bytes)
    try:
        dest_bytes = bytes.fromhex(destination)
        if len(dest_bytes) != 16:
            print("Invalid destination: must be 32 hex characters", file=sys.stderr)
            return 1
    except ValueError:
        print("Invalid destination: must be hexadecimal", file=sys.stderr)
        return 1

    # Get terminal size
    rows = args.rows
    cols = args.cols
    if rows is None or cols is None:
        try:
            term_size = os.get_terminal_size()
            rows = rows or term_size.lines
            cols = cols or term_size.columns
        except OSError:
            # Not a terminal, use defaults
            rows = rows or 24
            cols = cols or 80

    term_type = args.term_type or os.environ.get("TERM", "xterm-256color")

    # TODO: IPC mode for terminal sessions not yet implemented.
    # Terminal sessions require bidirectional I/O streaming which is more
    # complex than the request/response IPC pattern. For now, always use
    # standalone mode which initializes its own mesh stack.
    #
    # Future: Implement IPC protocol for terminal sessions that:
    # 1. Proxies session establishment through daemon
    # 2. Forwards stdin/stdout/stderr via IPC
    # 3. Handles window resize and signals

    # Standalone mode
    import RNS

    from styrened.services.config import get_default_core_config, load_core_config
    from styrened.services.lifecycle import CoreLifecycle
    from styrened.services.lxmf_service import get_lxmf_service
    from styrened.services.node_store import get_node_store
    from styrened.services.reticulum import (
        discover_devices,
        get_operator_identity_object,
        start_discovery,
    )
    from styrened.terminal.client import TerminalClient

    discovery_wait = getattr(args, "wait", 15)

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

    # Try to resolve the destination identity first via RNS path resolution
    # This allows connecting without waiting for fresh announces
    print(f"Resolving path to {destination[:16]}...")

    # Check if we already know this identity (from previous sessions)
    dest_identity = RNS.Identity.recall(bytes.fromhex(destination))
    if dest_identity:
        print(f"Found cached identity for {destination[:16]}...")
    else:
        # Request path discovery and wait
        print(f"Requesting path to {destination[:16]}... (waiting {discovery_wait}s)")
        RNS.Transport.request_path(bytes.fromhex(destination))

        start_time = time.time()
        while time.time() - start_time < discovery_wait:
            dest_identity = RNS.Identity.recall(bytes.fromhex(destination))
            if dest_identity:
                break
            await asyncio.sleep(0.5)

    if not dest_identity:
        # Fall back to announce-based discovery
        node_store = get_node_store()
        print(f"Path not found, waiting for announce ({discovery_wait}s)...")
        start_discovery(node_store=node_store)

        target_device = None
        start_time = time.time()
        prefix = destination[:16]
        while time.time() - start_time < discovery_wait:
            devices = discover_devices()
            for device in devices:
                if (
                    (device.destination_hash and device.destination_hash.startswith(prefix))
                    or (
                        device.lxmf_destination_hash
                        and device.lxmf_destination_hash.startswith(prefix)
                    )
                    or (device.identity_hash and device.identity_hash.startswith(prefix))
                ):
                    target_device = device
                    break
            if target_device:
                print(f"Found device: {target_device.name}")
                break
            await asyncio.sleep(0.5)

        if not target_device:
            print(
                f"Device {destination[:16]}... not found after {discovery_wait}s", file=sys.stderr
            )
            lifecycle.shutdown()
            return 1
    else:
        print(f"Path resolved to {destination[:16]}...")

    # Create Styrene protocol for terminal client
    from styrened.models.messages import init_db
    from styrened.protocols.base import LXMFMessage
    from styrened.protocols.styrene import StyreneProtocol

    db_engine = init_db()
    styrene_protocol = StyreneProtocol(
        router=lxmf_service.router,
        identity=lxmf_service._identity,
        db_engine=db_engine,
    )

    # Get reference to the main event loop for thread-safe dispatch
    main_loop = asyncio.get_event_loop()

    # Register callback to dispatch incoming messages to StyreneProtocol
    def _dispatch_to_styrene(lxmf_message: Any) -> None:
        """Bridge LXMF messages to StyreneProtocol."""
        wrapped = LXMFMessage(
            source_hash=lxmf_message.source_hash.hex(),
            destination_hash=lxmf_message.destination_hash.hex()
            if lxmf_message.destination_hash
            else "",
            timestamp=lxmf_message.timestamp if hasattr(lxmf_message, "timestamp") else 0.0,
            content=lxmf_message.content.decode("utf-8")
            if isinstance(lxmf_message.content, bytes)
            else (lxmf_message.content or ""),
            fields=lxmf_message.fields or {},
        )
        if styrene_protocol.can_handle(wrapped):
            # Schedule on main event loop (thread-safe)
            main_loop.call_soon_threadsafe(
                lambda: main_loop.create_task(styrene_protocol.handle_message(wrapped))
            )

    lxmf_service.register_callback(_dispatch_to_styrene, raw_mode=True)

    # Create terminal client
    terminal_client = TerminalClient(styrene_protocol=styrene_protocol)

    try:
        # Request terminal session
        print("Requesting terminal session...")
        session = await terminal_client.connect(
            destination=destination,
            term_type=term_type,
            rows=rows,
            cols=cols,
        )

        if not session:
            print("Failed to establish terminal session", file=sys.stderr)
            return 1

        # Run interactive session
        print("Connected. Type 'exit' or Ctrl-D to disconnect.\n")
        exit_code = await session.run_interactive()

        return exit_code

    except KeyboardInterrupt:
        print("\nInterrupted")
        return 130  # Standard exit code for SIGINT
    except Exception as e:
        print(f"Terminal session error: {e}", file=sys.stderr)
        return 1
    finally:
        lifecycle.shutdown()


# -----------------------------------------------------------------------------
# Subcommand: conversations
# -----------------------------------------------------------------------------


def cmd_conversations(args: argparse.Namespace) -> int:
    """List conversations.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_conversations_async(args))


async def _cmd_conversations_async(args: argparse.Namespace) -> int:
    """Async implementation of conversations command."""
    client = await _try_ipc_client()
    if not client:
        print("Daemon not running (conversations require a running daemon)", file=sys.stderr)
        return 1

    try:
        conversations = await client.query_conversations()
        await client.disconnect()

        if not conversations:
            print("No conversations")
            return 0

        if args.json:
            import json

            print(json.dumps(conversations, indent=2))
        else:
            print(f"\n{len(conversations)} conversation(s):\n")
            for conv in conversations:
                peer = conv.get("peer_hash", "unknown")
                unread = conv.get("unread_count", 0)
                count = conv.get("message_count", 0)
                preview = conv.get("last_message_preview", "")
                unread_str = f" ({unread} unread)" if unread else ""
                preview_str = f" - {preview[:60]}..." if len(preview) > 60 else f" - {preview}" if preview else ""
                print(f"  {peer[:16]}...{unread_str} [{count} msgs]{preview_str}")

        return 0
    except Exception as e:
        logger.warning(f"Failed to query conversations: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"Error: {e}", file=sys.stderr)
        return 1


# -----------------------------------------------------------------------------
# Subcommand: messages
# -----------------------------------------------------------------------------


def cmd_messages(args: argparse.Namespace) -> int:
    """List messages for a conversation.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_messages_async(args))


async def _cmd_messages_async(args: argparse.Namespace) -> int:
    """Async implementation of messages command."""
    client = await _try_ipc_client()
    if not client:
        print("Daemon not running (messages require a running daemon)", file=sys.stderr)
        return 1

    try:
        messages = await client.query_messages(
            peer_hash=args.peer_hash,
            limit=args.limit,
            status_filter=args.status,
        )
        await client.disconnect()

        if not messages:
            print("No messages")
            return 0

        if args.json:
            import json

            print(json.dumps(messages, indent=2))
        else:
            print(f"\n{len(messages)} message(s) with {args.peer_hash[:16]}...:\n")
            for msg in messages:
                direction = "->" if msg.get("is_outgoing") else "<-"
                status = msg.get("status", "")
                content = msg.get("content", "")
                content_str = content[:80] + "..." if len(content) > 80 else content
                print(f"  {direction} [{status}] {content_str}")

        return 0
    except Exception as e:
        logger.warning(f"Failed to query messages: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"Error: {e}", file=sys.stderr)
        return 1


def cmd_version(args: argparse.Namespace) -> int:
    """Show version information.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    from styrened import __version__

    if args.json:
        import json

        output = {"version": __version__, "name": "styrened"}
        print(json.dumps(output, indent=2))
    else:
        print(f"styrened {__version__}")

    return 0


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser for styrened CLI.

    Returns:
        Configured ArgumentParser.
    """
    from styrened import __version__

    parser = argparse.ArgumentParser(
        prog="styrened",
        description="Styrene headless daemon and mesh network tools",
    )
    parser.add_argument("--version", action="version", version=f"styrened {__version__}")
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

    # shell - interactive terminal session
    shell_parser = subparsers.add_parser(
        "shell", help="Start interactive shell session on remote node"
    )
    shell_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    shell_parser.add_argument(
        "-T",
        "--term-type",
        dest="term_type",
        help="Terminal type (default: $TERM or xterm-256color)",
    )
    shell_parser.add_argument("-r", "--rows", type=int, help="Terminal rows (default: auto-detect)")
    shell_parser.add_argument(
        "-c", "--cols", type=int, help="Terminal columns (default: auto-detect)"
    )
    shell_parser.add_argument(
        "-w", "--wait", type=int, default=15, help="Discovery wait time in seconds (default: 15)"
    )
    shell_parser.set_defaults(func=cmd_shell)

    # announce
    announce_parser = subparsers.add_parser("announce", help="Trigger local announce")
    announce_parser.set_defaults(func=cmd_announce)

    # identity
    identity_parser = subparsers.add_parser("identity", help="Show operator identity")
    identity_parser.add_argument("--create", action="store_true", help="Create identity if missing")
    identity_parser.add_argument("--json", action="store_true", help="Output as JSON")
    identity_parser.set_defaults(func=cmd_identity)

    # identity status - show sharing status with other apps
    identity_status_parser = subparsers.add_parser(
        "identity-status",
        help="Show identity sharing status with LXMF apps",
    )
    identity_status_parser.add_argument("--json", action="store_true", help="Output as JSON")
    identity_status_parser.set_defaults(func=cmd_identity_status)

    # identity share - share identity with other apps
    identity_share_parser = subparsers.add_parser(
        "identity-share",
        help="Share identity with other LXMF applications (NomadNet, Sideband, etc.)",
    )
    identity_share_parser.add_argument(
        "apps",
        nargs="*",
        help="Apps to share with (nomadnet, sideband, meshchat, lxmf). All if omitted.",
    )
    identity_share_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Replace existing identity files",
    )
    identity_share_parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't backup existing identity files",
    )
    identity_share_parser.add_argument("--json", action="store_true", help="Output as JSON")
    identity_share_parser.set_defaults(func=cmd_identity_share)

    # identity unshare - remove identity sharing
    identity_unshare_parser = subparsers.add_parser(
        "identity-unshare",
        help="Remove identity sharing with other LXMF applications",
    )
    identity_unshare_parser.add_argument(
        "apps",
        nargs="*",
        help="Apps to unshare from (nomadnet, sideband, meshchat, lxmf). All if omitted.",
    )
    identity_unshare_parser.add_argument(
        "--no-restore",
        action="store_true",
        help="Don't restore backed-up identity files",
    )
    identity_unshare_parser.add_argument("--json", action="store_true", help="Output as JSON")
    identity_unshare_parser.set_defaults(func=cmd_identity_unshare)

    # conversations
    conversations_parser = subparsers.add_parser(
        "conversations", help="List conversations (requires running daemon)"
    )
    conversations_parser.add_argument("--json", action="store_true", help="Output as JSON")
    conversations_parser.set_defaults(func=cmd_conversations)

    # messages
    messages_parser = subparsers.add_parser(
        "messages", help="List messages for a conversation (requires running daemon)"
    )
    messages_parser.add_argument("peer_hash", help="LXMF destination hash of the peer")
    messages_parser.add_argument(
        "-n", "--limit", type=int, default=50, help="Maximum messages to return (default: 50)"
    )
    messages_parser.add_argument(
        "--status", default=None, help="Filter by message status (e.g., delivered, failed)"
    )
    messages_parser.add_argument("--json", action="store_true", help="Output as JSON")
    messages_parser.set_defaults(func=cmd_messages)

    # version
    version_parser = subparsers.add_parser("version", help="Show version information")
    version_parser.add_argument("--json", action="store_true", help="Output as JSON")
    version_parser.set_defaults(func=cmd_version)

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
