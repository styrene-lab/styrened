"""CLI for styrened - interactive tooling for mesh network operations.

Provides subcommands for:
- daemon: Run the headless daemon (default)
- devices: List discovered mesh devices
- status: Show local daemon health or query remote node status
- send: Send a message to a node
- exec: Execute a command on a remote node
- announce: Trigger an announce
- identity: Show local operator identity
- conversations: List conversations
- messages: List messages for a conversation
- doctor: Installation diagnostics and setup wizard

Usage:
    styrened                      # Run daemon (default)
    styrened daemon               # Run daemon explicitly
    styrened devices              # List discovered devices
    styrened status               # Show local daemon health
    styrened status <dest>        # Query remote node status
    styrened send <dest> <msg>    # Send chat message
    styrened exec <dest> <cmd>    # Execute command on remote
    styrened announce             # Trigger local announce
    styrened identity             # Show local identity info
    styrened conversations        # List conversations
    styrened messages <peer>      # List messages with peer
    styrened doctor               # Run diagnostics
    styrened doctor --setup       # Interactive setup wizard
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

    # No destination: show local daemon health
    if destination is None:
        return await _cmd_local_status(args)

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


async def _cmd_local_status(args: argparse.Namespace) -> int:
    """Display local daemon health via IPC QUERY_STATUS."""
    client = await _try_ipc_client()
    if not client:
        print("Daemon not running (local status requires a running daemon)", file=sys.stderr)
        print("Start with: styrened daemon", file=sys.stderr)
        return 1

    try:
        status = await client.query_status()
        await client.disconnect()

        if args.json:
            import json

            print(json.dumps(status.to_dict(), indent=2))
        else:
            # Uptime formatting
            hours, remainder = divmod(int(status.uptime), 3600)
            minutes, seconds = divmod(remainder, 60)
            uptime_str = f"{hours}h {minutes}m {seconds}s"

            rns_str = "initialized" if status.rns_initialized else "not initialized"
            lxmf_str = "initialized" if status.lxmf_initialized else "not initialized"

            print("\nstyrened status\n")
            print("  Daemon")
            print(f"    Version:    {status.daemon_version}")
            print(f"    Uptime:     {uptime_str}")
            print(f"    RNS:        {rns_str}")
            print(f"    LXMF:       {lxmf_str}")

            # Transport mode
            transport_str = "enabled" if status.transport_enabled else "disabled"
            print(f"    Transport:  {transport_str}")

            # Hub section
            hub_status = status.hub_status
            if hub_status != "disabled":
                print()
                print("  Hub")
                print(f"    Status:     {hub_status}")
                if status.hub_address:
                    print(f"    Address:    {status.hub_address}")

            # Interfaces section
            if status.interfaces:
                print()
                print(f"  Interfaces ({len(status.interfaces)})")
                for iface in status.interfaces:
                    name = iface.get("name", "unnamed")
                    itype = iface.get("type", "unknown")
                    online = iface.get("online", True)
                    marker = "[UP]  " if online else "[DOWN]"
                    print(f"    {marker} {name} ({itype})")
            elif status.interface_count > 0:
                print()
                print(f"  Interfaces: {status.interface_count}")

            # Mesh section
            print()
            print("  Mesh")
            print(
                f"    Devices:    {status.device_count} total, {status.styrene_node_count} styrene nodes"
            )
            print(f"    Pending:    {status.pending_rpc_count} RPC requests")
            print(f"    Links:      {status.active_links} active")
            print()

        return 0
    except Exception as e:
        logger.warning(f"Failed to query local status: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"Error querying daemon status: {e}", file=sys.stderr)
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

    # --- Path resolution ---
    # RNS.Transport.request_path() asks transport nodes for a route.
    # We must wait for has_path() == True before DIRECT delivery.
    # Identity recall alone is NOT sufficient — send_message needs a path
    # to select DIRECT mode, otherwise it falls back to PROPAGATED.
    import RNS

    from styrened.services.lxmf_service import DeliveryMethod

    dest_bytes = bytes.fromhex(destination)
    print(f"Requesting path to {destination[:16]}...")
    RNS.Transport.request_path(dest_bytes)

    path_resolved = False
    identity_known = False
    start_time = time.time()
    path_wait = min(discovery_wait, 15)
    while time.time() - start_time < path_wait:
        if RNS.Transport.has_path(dest_bytes):
            path_resolved = True
            break
        if not identity_known:
            if RNS.Identity.recall(dest_bytes) or RNS.Identity.recall(
                dest_bytes, from_identity_hash=True
            ):
                identity_known = True
                print("Identity known, waiting for path...")
        await asyncio.sleep(0.5)

    payload = {"type": "chat", "protocol": "chat", "content": message}

    # --- Helper: send and wait for delivery ---
    # LXMF delivery is async — handle_outbound() just queues work.
    # We must wait for the delivery/failure callback before shutting down,
    # otherwise the RNS Link handshake gets torn down mid-flight.
    async def _send_and_wait(
        dest_hash: str,
        method: str = DeliveryMethod.DIRECT,
        delivery_timeout: float = 30.0,
    ) -> bool:
        loop = asyncio.get_event_loop()
        delivery_event = asyncio.Event()
        delivery_result: dict[str, bool] = {"success": False}

        def on_delivery(msg: object) -> None:
            delivery_result["success"] = True
            loop.call_soon_threadsafe(delivery_event.set)

        def on_failed(msg: object) -> None:
            delivery_result["success"] = False
            loop.call_soon_threadsafe(delivery_event.set)

        result = lxmf_service.send_message(
            dest_hash,
            payload,
            on_delivery=on_delivery,
            on_failed=on_failed,
            delivery_method=method,
        )
        if result is None:
            return False

        print(f"Waiting for delivery ({int(delivery_timeout)}s timeout)...")
        try:
            await asyncio.wait_for(delivery_event.wait(), timeout=delivery_timeout)
        except TimeoutError:
            print("Delivery timed out (Link handshake may have failed)")
            return False

        return delivery_result["success"]

    if path_resolved:
        print(f"Path resolved, sending direct to {destination[:16]}...")
        success = await _send_and_wait(destination, DeliveryMethod.DIRECT)
        if success:
            print("Message delivered successfully")
            lifecycle.shutdown()
            return 0
        else:
            print("Direct delivery failed, trying discovery fallback...")

    # Fallback: discover via announces (needed if path request failed)
    node_store = get_node_store()
    remaining_wait = max(discovery_wait - (time.time() - start_time), 5)
    if identity_known and not path_resolved:
        print(f"Identity known but no direct path after {int(time.time() - start_time)}s")
    print(f"Listening for announces ({int(remaining_wait)}s)...")
    start_discovery(node_store=node_store)

    target_device = None
    disc_start = time.time()
    prefix = destination[:16]
    while time.time() - disc_start < remaining_wait:
        devices = discover_devices()
        for device in devices:
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
            await asyncio.sleep(1.0)
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

    stop_discovery()
    await asyncio.sleep(0.5)

    if not target_device:
        print(f"Device {destination[:16]}... not found after {discovery_wait}s", file=sys.stderr)
        lifecycle.shutdown()
        return 1

    lxmf_dest = target_device.lxmf_destination_hash or destination
    print(f"Found {target_device.name or 'device'}, sending to LXMF dest {lxmf_dest[:16]}...")

    success = await _send_and_wait(lxmf_dest, DeliveryMethod.DIRECT)
    if success:
        print("Message delivered successfully")
        lifecycle.shutdown()
        return 0
    else:
        print("Failed to deliver message", file=sys.stderr)
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
# Subcommand: update
# -----------------------------------------------------------------------------


def cmd_update(args: argparse.Namespace) -> int:
    """Trigger self-update on a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_update_async(args))


async def _cmd_update_async(args: argparse.Namespace) -> int:
    """Async implementation of update command."""
    destination = args.destination
    version = args.version if hasattr(args, "version") else None
    timeout = args.timeout if hasattr(args, "timeout") else 120.0

    # Try IPC first (uses daemon's mesh stack)
    client = await _try_ipc_client()
    if client:
        try:
            version_str = version or "latest"
            print(f"Sending self-update ({version_str}) via daemon...")
            result = await client.self_update_device(
                destination, version=version, timeout=timeout,
            )
            await client.disconnect()

            if args.json:
                import json

                output = result.to_dict()
                print(json.dumps(output, indent=2))
            else:
                if result.success:
                    print(f"Update successful: {result.old_version} -> {result.new_version}")
                    print(f"  {result.message}")
                else:
                    print(f"Update failed: {result.message}", file=sys.stderr)

            return 0 if result.success else 1
        except Exception as e:
            logger.warning(f"IPC update failed, falling back to standalone: {e}")
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
            await asyncio.sleep(1.0)
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

    version_str = version or "latest"
    print(f"Sending self-update ({version_str}) to {lxmf_dest[:16]}... (timeout: {timeout}s)")

    try:
        result = await rpc_client.call_self_update(lxmf_dest, version=version, timeout=timeout)

        if args.json:
            import json

            output = {
                "success": result.success,
                "message": result.message,
                "old_version": result.old_version,
                "new_version": result.new_version,
            }
            print(json.dumps(output, indent=2))
        else:
            if result.success:
                print(f"Update successful: {result.old_version} -> {result.new_version}")
                print(f"  {result.message}")
            else:
                print(f"Update failed: {result.message}", file=sys.stderr)

        lifecycle.shutdown()
        return 0 if result.success else 1

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
# Subcommand: restart
# -----------------------------------------------------------------------------


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart the daemon process (preserves identity and config).

    Sends SIGTERM to the running daemon. If managed by launchd (macOS)
    or systemd, it will be restarted automatically with the currently
    installed version.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    import subprocess
    import time

    from styrened import __version__

    print(f"styrened v{__version__}")
    print("Stopping daemon...")

    result = subprocess.run(
        ["pkill", "-f", r"^.*/styrened daemon"],
        capture_output=True,
    )

    if result.returncode != 0:
        print("No running daemon found.", file=sys.stderr)
        return 1

    # Wait for restart (launchd KeepAlive / systemd Restart=always)
    print("Waiting for daemon to restart...")
    time.sleep(2)

    # Check if it came back
    check = subprocess.run(
        ["pgrep", "-f", r"^.*/styrened daemon"],
        capture_output=True,
    )
    if check.returncode == 0:
        print("✅ Daemon restarted successfully.")
    else:
        print("⚠️  Daemon stopped but did not auto-restart.")
        print("   Start manually: styrened daemon")

    return 0


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

    from styrened import __version__
    from styrened.services.system_info import get_system_fingerprint

    hostname = socket.gethostname()
    fingerprint = get_system_fingerprint()
    app_data = f"styrene:{hostname}:{__version__}:cli:::{fingerprint}".encode()
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


def cmd_identity_yubikey_setup(args: argparse.Namespace) -> int:
    """Create a FIDO2 credential on a YubiKey for identity derivation.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    try:
        from styrened.services.yubikey import require_fido2, setup_credential

        require_fido2()
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    rp_id = args.rp_id

    if not args.json:
        print(f"Creating FIDO2 credential on YubiKey (rp_id: {rp_id})...")
        print("You may be prompted for your YubiKey PIN and/or touch.")
        print()

    try:
        credential_id = setup_credential(rp_id=rp_id)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        import json

        output = {
            "credential_id": credential_id,
            "rp_id": rp_id,
        }
        print(json.dumps(output, indent=2))
    else:
        print("Credential created successfully.")
        print()
        print("Add the following to your styrened config:")
        print()
        print("identity:")
        print('  provider: "yubikey"')
        print("  yubikey:")
        print(f'    credential_id: "{credential_id}"')
        print(f'    rp_id: "{rp_id}"')
        print("    require_touch: false")

    return 0


def cmd_identity_yubikey_derive(args: argparse.Namespace) -> int:
    """Derive identity from YubiKey and display the hash for verification.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    try:
        from styrened.services.yubikey import derive_identity_bytes, require_fido2

        require_fido2()
    except ImportError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Read config for defaults
    from styrened.services.config import load_core_config

    try:
        config = load_core_config()
    except Exception:
        config = None

    credential_id = args.credential_id
    rp_id = args.rp_id

    # Fall back to config values
    if not credential_id and config and config.identity.provider == "yubikey":
        credential_id = config.identity.yubikey.credential_id
        if not rp_id:
            rp_id = config.identity.yubikey.rp_id

    if not credential_id:
        print("Error: No credential_id specified and none found in config.", file=sys.stderr)
        print("Run 'styrened identity-yubikey-setup' first.", file=sys.stderr)
        return 1

    rp_id = rp_id or "styrene.mesh"

    if not args.json:
        print(f"Deriving identity from YubiKey (rp_id: {rp_id})...")

    try:
        identity_bytes = derive_identity_bytes(
            credential_id_b64=credential_id,
            rp_id=rp_id,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    # Compute identity hash using RNS
    try:
        import RNS

        identity = RNS.Identity.from_bytes(identity_bytes)
        if identity is None:
            print("Error: RNS could not load derived identity bytes", file=sys.stderr)
            return 1
        identity_hash = identity.hash.hex()
    except ImportError:
        print("Error: RNS library not available. Install with: pip install rns", file=sys.stderr)
        return 1

    if args.json:
        import json

        output = {
            "identity_hash": identity_hash,
            "rp_id": rp_id,
            "provider": "yubikey",
        }
        print(json.dumps(output, indent=2))
    else:
        print(f"\nIdentity Hash: {identity_hash}")
        print("Provider:      yubikey")
        print(f"RP ID:         {rp_id}")

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
# Subcommand: inbox (remote)
# -----------------------------------------------------------------------------


def cmd_inbox(args: argparse.Namespace) -> int:
    """Query inbox on a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_inbox_async(args))


async def _cmd_inbox_async(args: argparse.Namespace) -> int:
    """Async implementation of inbox command."""
    destination = args.destination
    limit = args.limit
    timeout = args.timeout if hasattr(args, "timeout") else 30.0

    client = await _try_ipc_client()
    if not client:
        print("Daemon not running (remote inbox query requires a running daemon)", file=sys.stderr)
        print("Start with: styrened daemon", file=sys.stderr)
        return 1

    try:
        print(f"Querying remote inbox on {destination[:16]}... (timeout: {timeout}s)")

        conversations = await client.remote_inbox(
            destination=destination,
            limit=limit,
            timeout=timeout,
        )
        await client.disconnect()

        if not conversations:
            print("No conversations on remote node")
            return 0

        if args.json:
            import json

            print(json.dumps(conversations, indent=2))
        else:
            print(f"\n{len(conversations)} conversation(s) on remote node:\n")
            for conv in conversations:
                peer = conv.get("peer_hash", "unknown")
                unread = conv.get("unread_count", 0)
                count = conv.get("message_count", 0)
                preview = conv.get("last_message_preview", "")
                display_name = conv.get("display_name", "")
                name_str = f" ({display_name})" if display_name else ""
                unread_str = f" ({unread} unread)" if unread else ""
                preview_str = (
                    f" - {preview[:60]}..."
                    if len(preview) > 60
                    else f" - {preview}"
                    if preview
                    else ""
                )
                print(f"  {peer[:16]}...{name_str}{unread_str} [{count} msgs]{preview_str}")

        return 0
    except Exception as e:
        logger.warning(f"Failed to query remote inbox: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"Error: {e}", file=sys.stderr)
        return 1


# -----------------------------------------------------------------------------
# Subcommand: remote-messages
# -----------------------------------------------------------------------------


def cmd_remote_messages(args: argparse.Namespace) -> int:
    """Query messages for a peer on a remote node.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code.
    """
    return asyncio.run(_cmd_remote_messages_async(args))


async def _cmd_remote_messages_async(args: argparse.Namespace) -> int:
    """Async implementation of remote-messages command."""
    destination = args.destination
    peer_hash = args.peer_hash
    limit = args.limit
    timeout = args.timeout if hasattr(args, "timeout") else 30.0

    client = await _try_ipc_client()
    if not client:
        print(
            "Daemon not running (remote messages query requires a running daemon)",
            file=sys.stderr,
        )
        print("Start with: styrened daemon", file=sys.stderr)
        return 1

    try:
        print(
            f"Querying messages for {peer_hash[:16]}... on {destination[:16]}... "
            f"(timeout: {timeout}s)"
        )

        messages = await client.remote_messages(
            destination=destination,
            peer_hash=peer_hash,
            limit=limit,
            timeout=timeout,
        )
        await client.disconnect()

        if not messages:
            print("No messages")
            return 0

        if args.json:
            import json

            print(json.dumps(messages, indent=2))
        else:
            print(f"\n{len(messages)} message(s):\n")
            for msg in messages:
                direction = "->" if msg.get("is_outgoing") else "<-"
                status = msg.get("status", "")
                content = msg.get("content", "")
                content_str = content[:80] + "..." if len(content) > 80 else content
                print(f"  {direction} [{status}] {content_str}")

        return 0
    except Exception as e:
        logger.warning(f"Failed to query remote messages: {e}")
        try:
            await client.disconnect()
        except Exception:
            pass
        print(f"Error: {e}", file=sys.stderr)
        return 1


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


# -----------------------------------------------------------------------------
# Subcommand: doctor
# -----------------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    """Run installation diagnostics.

    Args:
        args: Parsed arguments.

    Returns:
        Exit code (0=ok, 1=warnings, 2=errors).
    """
    return asyncio.run(_cmd_doctor_async(args))


async def _cmd_doctor_async(args: argparse.Namespace) -> int:
    """Async implementation of doctor command."""
    from styrened.services.doctor import apply_fixes, run_doctor, run_setup_wizard

    # Setup wizard mode
    if args.setup:
        results = run_setup_wizard()
        print()
        for finding in results:
            _print_finding(finding)
        return 0

    # Run diagnostics
    report = await run_doctor(offline=args.offline)

    # Apply fixes if requested
    if args.fix:
        fixed = apply_fixes(report)
        report.findings.extend(fixed)

    # Output
    if args.json:
        import json

        print(json.dumps(report.to_dict(), indent=2))
    else:
        _print_report(report)

    return report.exit_code


def _print_finding(finding) -> None:
    """Print a single finding with severity prefix."""
    from styrened.services.doctor import Severity

    prefix_map = {
        Severity.OK: "[OK] ",
        Severity.WARN: "[WARN]",
        Severity.ERROR: "[ERR] ",
    }
    prefix = prefix_map.get(finding.severity, "[???]")
    print(f"  {prefix} {finding.message}")
    if finding.fix_hint and finding.severity != Severity.OK:
        print(f"         -> {finding.fix_hint}")


def _print_report(report) -> None:
    """Print a formatted doctor report grouped by category."""
    from styrened.services.doctor import CheckCategory

    category_labels = {
        CheckCategory.VERSION: "Version",
        CheckCategory.IDENTITY: "Identity",
        CheckCategory.CONFIG: "Configuration",
        CheckCategory.RETICULUM: "Reticulum",
        CheckCategory.DAEMON: "Daemon",
        CheckCategory.PATHS: "Paths",
    }

    print("\nstyrened doctor\n")

    # Group findings by category
    by_category: dict = {}
    for finding in report.findings:
        by_category.setdefault(finding.category, []).append(finding)

    # Print in defined order
    for category in CheckCategory:
        findings = by_category.get(category, [])
        if not findings:
            continue
        label = category_labels.get(category, category.value)
        print(f"  {label}")
        for finding in findings:
            _print_finding(finding)
        print()

    # Summary
    errors = sum(1 for f in report.findings if f.severity.value == "ERR")
    warnings = sum(1 for f in report.findings if f.severity.value == "WARN")
    oks = sum(1 for f in report.findings if f.severity.value == "OK")
    print(f"  {oks} passed, {warnings} warnings, {errors} errors")


# -----------------------------------------------------------------------------
# Subcommand: api-auth
# -----------------------------------------------------------------------------


def cmd_api_auth(args: argparse.Namespace) -> int:
    """Manage web API authentication configuration.

    Operates directly on config file (no running daemon needed).

    Args:
        args: Parsed arguments with api_auth_action and optional identity_hash.

    Returns:
        Exit code.
    """
    import json as json_mod

    from styrened.services.config import load_core_config, save_core_config

    config = load_core_config()
    action = args.api_auth_action

    if action == "list":
        auth = config.api.auth
        if args.json:
            # Show RBAC roster entries with WEB_READ capability
            from styrened.models.rbac import Capability
            web_identities = [
                entry.identity_hash
                for entry in config.rbac.roster.values()
                if config.rbac.has_capability(entry.identity_hash, Capability.WEB_READ)
            ]
            output = {
                "enabled": auth.enabled,
                "exempt_localhost": auth.exempt_localhost,
                "session_ttl": auth.session_ttl,
                "rbac_default_role": config.rbac.default_role.name,
                "web_authorized_identities": sorted(web_identities),
            }
            print(json_mod.dumps(output, indent=2))
        else:
            from styrened.models.rbac import Capability
            print(f"Auth enabled:           {auth.enabled}")
            print(f"Exempt localhost:       {auth.exempt_localhost}")
            print(f"Session TTL:            {auth.session_ttl}s")
            print(f"RBAC default role:      {config.rbac.default_role.name}")
            web_identities = [
                entry
                for entry in config.rbac.roster.values()
                if config.rbac.has_capability(entry.identity_hash, Capability.WEB_READ)
            ]
            if web_identities:
                print(f"Web-authorized (RBAC):  ({len(web_identities)})")
                for entry in sorted(web_identities, key=lambda e: e.identity_hash):
                    label = f" ({entry.label})" if entry.label else ""
                    print(f"  {entry.identity_hash} [{entry.role.name}]{label}")
            else:
                default_has_web = config.rbac.has_capability("0" * 32, Capability.WEB_READ)
                if default_has_web:
                    print("Web-authorized:         (all — default role grants WEB_READ)")
                else:
                    print("Web-authorized:         (none — add identities to RBAC roster)")
        return 0

    elif action == "add":
        identity_hash = args.identity_hash.lower()
        if len(identity_hash) != 32:
            print(f"Error: identity hash must be 32 hex characters, got {len(identity_hash)}", file=sys.stderr)
            return 1
        try:
            int(identity_hash, 16)
        except ValueError:
            print("Error: identity hash must be valid hexadecimal", file=sys.stderr)
            return 1

        from styrened.models.rbac import Role, RosterEntry
        if identity_hash not in config.rbac.roster:
            config.rbac.add_entry(RosterEntry(
                identity_hash=identity_hash,
                role=Role.MONITOR,
                label="(added via web-auth CLI)",
            ))
        if not config.api.auth.enabled:
            config.api.auth.enabled = True
            print("Auth auto-enabled (was disabled)")
        save_core_config(config)
        print(f"Added {identity_hash} to RBAC roster as MONITOR (grants WEB_READ)")
        return 0

    elif action == "remove":
        identity_hash = args.identity_hash.lower()
        if identity_hash in config.rbac.roster:
            config.rbac.remove_entry(identity_hash)
            save_core_config(config)
            print(f"Removed {identity_hash} from RBAC roster")
        else:
            print(f"Identity {identity_hash} not found in RBAC roster", file=sys.stderr)
            return 1
        return 0

    return 1


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
    status_parser = subparsers.add_parser(
        "status", help="Show local daemon health or query remote node status"
    )
    status_parser.add_argument(
        "destination",
        nargs="?",
        default=None,
        help="Destination hash (hex) of remote node. Omit for local daemon status.",
    )
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

    # update
    update_parser = subparsers.add_parser(
        "update", help="Trigger self-update on a remote node"
    )
    update_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    update_parser.add_argument(
        "--version", default=None, help="Target version (default: latest from PyPI)"
    )
    update_parser.add_argument(
        "-t", "--timeout", type=float, default=120.0, help="Timeout in seconds (default: 120)"
    )
    update_parser.add_argument(
        "-w", "--wait", type=int, default=10, help="Discovery wait time in seconds (default: 10)"
    )
    update_parser.add_argument("--json", action="store_true", help="Output as JSON")
    update_parser.set_defaults(func=cmd_update)

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

    # restart
    restart_parser = subparsers.add_parser("restart", help="Restart the daemon (preserves identity and config)")
    restart_parser.set_defaults(func=cmd_restart)

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

    # identity-yubikey-setup
    yk_setup_parser = subparsers.add_parser(
        "identity-yubikey-setup",
        help="Create a FIDO2 credential on YubiKey for identity derivation",
    )
    yk_setup_parser.add_argument(
        "--rp-id",
        default="styrene.mesh",
        help="Relying party ID (default: styrene.mesh)",
    )
    yk_setup_parser.add_argument("--json", action="store_true", help="Output as JSON")
    yk_setup_parser.set_defaults(func=cmd_identity_yubikey_setup)

    # identity-yubikey-derive
    yk_derive_parser = subparsers.add_parser(
        "identity-yubikey-derive",
        help="Derive identity from YubiKey and display hash for verification",
    )
    yk_derive_parser.add_argument(
        "--credential-id",
        default=None,
        help="Base64-encoded credential ID (reads from config if omitted)",
    )
    yk_derive_parser.add_argument(
        "--rp-id",
        default=None,
        help="Relying party ID (reads from config if omitted)",
    )
    yk_derive_parser.add_argument("--json", action="store_true", help="Output as JSON")
    yk_derive_parser.set_defaults(func=cmd_identity_yubikey_derive)

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

    # inbox (remote via RPC)
    inbox_parser = subparsers.add_parser(
        "inbox", help="Query inbox on a remote node (via RPC over LXMF)"
    )
    inbox_parser.add_argument("destination", help="Destination hash (hex) of remote node")
    inbox_parser.add_argument(
        "-n", "--limit", type=int, default=50, help="Maximum conversations (default: 50)"
    )
    inbox_parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, help="RPC timeout in seconds (default: 30)"
    )
    inbox_parser.add_argument("--json", action="store_true", help="Output as JSON")
    inbox_parser.set_defaults(func=cmd_inbox)

    # remote-messages (remote via RPC)
    remote_messages_parser = subparsers.add_parser(
        "remote-messages", help="Query messages on a remote node (via RPC over LXMF)"
    )
    remote_messages_parser.add_argument(
        "destination", help="Destination hash (hex) of remote node"
    )
    remote_messages_parser.add_argument("peer_hash", help="Peer hash to query messages for")
    remote_messages_parser.add_argument(
        "-n", "--limit", type=int, default=50, help="Maximum messages (default: 50)"
    )
    remote_messages_parser.add_argument(
        "-t", "--timeout", type=float, default=30.0, help="RPC timeout in seconds (default: 30)"
    )
    remote_messages_parser.add_argument("--json", action="store_true", help="Output as JSON")
    remote_messages_parser.set_defaults(func=cmd_remote_messages)

    # version
    version_parser = subparsers.add_parser("version", help="Show version information")
    version_parser.add_argument("--json", action="store_true", help="Output as JSON")
    version_parser.set_defaults(func=cmd_version)

    # doctor
    doctor_parser = subparsers.add_parser(
        "doctor", help="Run installation diagnostics and health checks"
    )
    doctor_parser.add_argument("--json", action="store_true", help="Output as JSON")
    doctor_parser.add_argument(
        "--offline", action="store_true", help="Skip network checks (PyPI version)"
    )
    doctor_parser.add_argument(
        "--fix", action="store_true", help="Auto-fix issues (create missing dirs)"
    )
    doctor_parser.add_argument(
        "--setup", action="store_true", help="Run interactive setup wizard"
    )
    doctor_parser.set_defaults(func=cmd_doctor)

    # api-auth
    api_auth_parser = subparsers.add_parser(
        "api-auth", help="Manage web API authentication"
    )
    api_auth_sub = api_auth_parser.add_subparsers(
        dest="api_auth_action", help="Auth management action"
    )

    api_auth_list = api_auth_sub.add_parser("list", help="Show auth config and authorized identities")
    api_auth_list.add_argument("--json", action="store_true", help="Output as JSON")

    api_auth_add = api_auth_sub.add_parser("add", help="Add an identity to the authorized set")
    api_auth_add.add_argument("identity_hash", help="32-character hex identity hash")

    api_auth_remove = api_auth_sub.add_parser("remove", help="Remove an identity from the authorized set")
    api_auth_remove.add_argument("identity_hash", help="32-character hex identity hash")

    api_auth_parser.set_defaults(func=cmd_api_auth)

    # menubar (macOS menu bar agent)
    menubar_parser = subparsers.add_parser(
        "menubar", help="Launch macOS menu bar agent (shows unread count, notifications)"
    )
    menubar_parser.set_defaults(func=cmd_menubar)

    # Block/unblock commands
    block_parser = subparsers.add_parser(
        "block", help="Block a peer (silently drop all future messages)"
    )
    block_parser.add_argument("peer_hash", help="LXMF destination hash of peer to block")
    block_parser.set_defaults(func=cmd_block)

    unblock_parser = subparsers.add_parser(
        "unblock", help="Unblock a previously blocked peer"
    )
    unblock_parser.add_argument("peer_hash", help="LXMF destination hash of peer to unblock")
    unblock_parser.set_defaults(func=cmd_unblock)

    blocked_parser = subparsers.add_parser(
        "blocked", help="List all blocked peers"
    )
    blocked_parser.set_defaults(func=cmd_blocked)

    return parser


def cmd_block(args: argparse.Namespace) -> int:
    """Block a peer."""
    import asyncio

    from styrened.ipc.client import ControlClient

    async def _run() -> int:
        client = ControlClient()
        await client.connect()
        try:
            await client.block_peer(args.peer_hash)
            print(f"Blocked {args.peer_hash[:16]}...")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            await client.disconnect()

    return asyncio.run(_run())


def cmd_unblock(args: argparse.Namespace) -> int:
    """Unblock a peer."""
    import asyncio

    from styrened.ipc.client import ControlClient

    async def _run() -> int:
        client = ControlClient()
        await client.connect()
        try:
            await client.unblock_peer(args.peer_hash)
            print(f"Unblocked {args.peer_hash[:16]}...")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            await client.disconnect()

    return asyncio.run(_run())


def cmd_blocked(args: argparse.Namespace) -> int:
    """List blocked peers."""
    import asyncio

    from styrened.ipc.client import ControlClient

    async def _run() -> int:
        client = ControlClient()
        await client.connect()
        try:
            result = await client.get_blocked_peers()
            peers = result.get("blocked_peers", [])
            if not peers:
                print("No blocked peers")
                return 0
            for p in peers:
                alias = p.get("alias", "")
                blocked_at = p.get("blocked_at", "")
                print(f"  {p['peer_hash'][:16]}...  {alias}  (blocked: {blocked_at})")
            return 0
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        finally:
            await client.disconnect()

    return asyncio.run(_run())


def cmd_menubar(args: argparse.Namespace) -> int:
    """Launch the macOS menu bar agent."""
    from styrened.tui.menubar.agent import run

    run()
    return 0


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
