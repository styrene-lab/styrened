"""API routes for the styrened web UI."""

from __future__ import annotations

import logging
import re
import threading
import time
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, HTTPException, Query

from styrened.web.events import SSEBroadcaster, create_events_router
from styrened.web.models import (
    AutoReplyToggleRequest,
    ConfigUpdateRequest,
    ExecCommandRequest,
    FleetConfigUpdateRequest,
    RebootRequest,
    SendChatRequest,
    SetContactRequest,
)

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon

logger = logging.getLogger(__name__)

# Validation constants (shared with ipc/handlers.py)
HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{16,32}$")
LXMF_HASH_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
MAX_MESSAGE_LIMIT = 1000
VALID_DELIVERY_METHODS = {"auto", "direct", "propagated"}


def _validate_peer_hash(peer_hash: str) -> None:
    """Validate a peer hash path parameter."""
    if not HASH_PATTERN.match(peer_hash):
        raise HTTPException(400, detail="peer_hash must be 16-32 hex characters")


def create_router(daemon: StyreneDaemon, broadcaster: SSEBroadcaster) -> APIRouter:
    """Create API router with all endpoints."""
    router = APIRouter()

    # -------------------------------------------------------------------------
    # Identity & Config
    # -------------------------------------------------------------------------

    @router.get("/api/identity")
    async def identity():
        """Return local identity information."""
        from styrened.services.lxmf_service import get_lxmf_service
        from styrened.services.reticulum import get_operator_identity

        identity_hash = get_operator_identity()
        if not identity_hash:
            raise HTTPException(503, detail="No operator identity configured")

        destination_hash = ""
        lxmf_destination_hash = ""

        if daemon._operator_destination:
            destination_hash = daemon._operator_destination.hexhash

        lxmf_service = get_lxmf_service()
        if lxmf_service and lxmf_service._destination:
            lxmf_destination_hash = lxmf_service._destination.hexhash

        display_name = daemon.config.identity.display_name

        return {
            "identity_hash": identity_hash,
            "destination_hash": destination_hash,
            "lxmf_destination_hash": lxmf_destination_hash,
            "display_name": display_name,
        }

    @router.get("/api/config")
    async def config():
        """Return sanitized configuration (all 10 sections, no secrets)."""
        from styrened.services.config import _serialize_config

        cfg = daemon.config
        config_dict = _serialize_config(cfg)

        # Sanitize sensitive fields
        if "identity" in config_dict:
            yk = config_dict["identity"].get("yubikey")
            if yk and yk.get("credential_id"):
                yk["credential_id"] = "***"

        if "terminal" in config_dict:
            auth_ids = config_dict["terminal"].get("authorized_identities")
            if auth_ids:
                config_dict["terminal"]["authorized_identities_count"] = len(auth_ids)
                del config_dict["terminal"]["authorized_identities"]

        # Redact API auth authorized_identities (show count only)
        if "api" in config_dict:
            api_auth = config_dict["api"].get("auth")
            if api_auth and isinstance(api_auth, dict):
                auth_ids = api_auth.get("authorized_identities")
                if auth_ids:
                    api_auth["authorized_identities_count"] = len(auth_ids)
                    del api_auth["authorized_identities"]

        # Redact infrastructure details in public mode
        if cfg.api.public_mode:
            if "reticulum" in config_dict:
                ret = config_dict["reticulum"]
                if "interfaces" in ret:
                    ifaces = ret["interfaces"]
                    ret["interfaces"] = {
                        "auto": ifaces.get("auto", True),
                        "server": {"enabled": bool(ifaces.get("server", {}).get("enabled"))},
                    }
                # Strip filesystem paths
                for key in ("config_path_override", "operator_identity_path"):
                    ret.pop(key, None)
            if "terminal" in config_dict:
                config_dict["terminal"] = {
                    "enabled": config_dict["terminal"].get("enabled", False),
                }
            if "ipc" in config_dict:
                for key in ("socket_path", "socket_mode"):
                    config_dict["ipc"].pop(key, None)

        return {"config": config_dict}

    @router.put("/api/config")
    async def update_config(body: ConfigUpdateRequest):
        """Update configuration (partial merge). Protected fields are rejected."""
        from styrened.models.config import ConfigValidationError
        from styrened.services.config import (
            _serialize_config,
            load_core_config,
            save_core_config,
            validate_core_config,
        )

        protected_fields = {
            ("identity", "yubikey", "credential_id"),
            ("terminal", "authorized_identities"),
            ("api", "auth"),  # entire auth subtree — manage via CLI only
        }

        # Check for protected fields
        updates = body.model_dump(exclude_none=True)
        for section_key, section_val in updates.items():
            if isinstance(section_val, dict):
                for field_key, field_val in section_val.items():
                    for protected in protected_fields:
                        if len(protected) == 2 and protected == (section_key, field_key):
                            raise HTTPException(
                                403,
                                detail=f"Field '{section_key}.{field_key}' cannot be set via API",
                            )
                        if (
                            len(protected) == 3
                            and protected[0] == section_key
                            and protected[1] == field_key
                            and isinstance(field_val, dict)
                            and protected[2] in field_val
                        ):
                            raise HTTPException(
                                403,
                                detail=f"Field '{'.'.join(protected)}' cannot be set via API",
                            )

        # Load current → deep-merge → validate → save
        current = load_core_config()
        current_dict = _serialize_config(current)

        for section_key, section_val in updates.items():
            if isinstance(section_val, dict):
                if section_key in current_dict and isinstance(current_dict[section_key], dict):
                    current_dict[section_key].update(section_val)
                else:
                    current_dict[section_key] = section_val
            else:
                # Top-level scalar fields (e.g., profile)
                current_dict[section_key] = section_val

        # Re-load from merged dict by saving temp and loading
        import tempfile
        from pathlib import Path

        import yaml

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(current_dict, f, default_flow_style=False, sort_keys=False)
            temp_path = Path(f.name)

        try:
            merged_config = load_core_config(temp_path)
        finally:
            temp_path.unlink(missing_ok=True)

        # Validate
        try:
            validate_core_config(merged_config, raise_on_error=True)
        except ConfigValidationError as e:
            raise HTTPException(
                422,
                detail={
                    "message": "Validation failed",
                    "errors": [{"field": err.field, "message": err.message, "value": err.value} for err in e.errors],
                },
            ) from None

        # Save and reload
        save_core_config(merged_config)
        daemon.config = load_core_config()

        # Re-announce if chat section was updated (capability changes)
        if "chat" in updates:
            daemon._announce()

        # Broadcast change
        broadcaster.broadcast_config_event()

        # Return sanitized config
        result = _serialize_config(daemon.config)
        if "identity" in result:
            yk = result["identity"].get("yubikey")
            if yk and yk.get("credential_id"):
                yk["credential_id"] = "***"
        if "terminal" in result:
            auth_ids = result["terminal"].get("authorized_identities")
            if auth_ids:
                result["terminal"]["authorized_identities_count"] = len(auth_ids)
                del result["terminal"]["authorized_identities"]
        if "api" in result:
            api_auth = result["api"].get("auth")
            if api_auth and isinstance(api_auth, dict):
                auth_ids = api_auth.get("authorized_identities")
                if auth_ids:
                    api_auth["authorized_identities_count"] = len(auth_ids)
                    del api_auth["authorized_identities"]

        return {"config": result}

    # -------------------------------------------------------------------------
    # Auto-reply (out-of-office)
    # -------------------------------------------------------------------------

    @router.get("/api/auto-reply")
    async def get_auto_reply():
        """Return current auto-reply state."""
        return {
            "mode": daemon.config.chat.auto_reply_mode.value,
            "message": daemon.config.chat.auto_reply_message,
            "cooldown": daemon.config.chat.auto_reply_cooldown,
        }

    @router.post("/api/auto-reply")
    async def toggle_auto_reply(body: AutoReplyToggleRequest):
        """Set auto-reply mode and optionally update the message."""
        from styrened.models.config import AutoReplyMode
        from styrened.services.config import save_core_config

        daemon.config.chat.auto_reply_mode = AutoReplyMode(body.mode)
        if body.message is not None:
            daemon.config.chat.auto_reply_message = body.message

        # Persist to disk
        save_core_config(daemon.config)

        # Re-announce to propagate capability change
        daemon._announce()

        # Broadcast SSE event
        broadcaster.broadcast_auto_reply_event(
            daemon.config.chat.auto_reply_mode.value,
            daemon.config.chat.auto_reply_message,
        )

        return {
            "mode": daemon.config.chat.auto_reply_mode.value,
            "message": daemon.config.chat.auto_reply_message,
            "cooldown": daemon.config.chat.auto_reply_cooldown,
        }

    # -------------------------------------------------------------------------
    # Mesh topology (existing)
    # -------------------------------------------------------------------------

    @router.get("/api/mesh/topology")
    async def topology(
        include_unnamed: bool = Query(False),
        exclude_status: str | None = Query(None),
    ):
        """Return graph JSON with nodes and edges for vis-network."""
        node_store = daemon._node_store
        if node_store is None:
            return {"nodes": [], "edges": []}

        excluded = {s.strip() for s in exclude_status.split(",")} if exclude_status else set()

        devices = node_store.get_all_nodes()
        paths = node_store.get_all_paths()

        # Build node list
        nodes = []
        node_ids = set()
        for d in devices:
            if not include_unnamed and d.name == "binary-data":
                continue
            if d.status.value in excluded:
                continue
            node_ids.add(d.destination_hash)
            nodes.append({
                "id": d.destination_hash,
                "label": d.name,
                "type": d.device_type.value,
                "status": d.status.value,
                "last_seen": d.last_announce,
                "announce_count": d.announce_count,
                "capabilities": d.capabilities,
                "version": d.version,
                "short_name": d.short_name,
                "system_fingerprint": d.system_fingerprint,
            })

        # Determine self node (hub) — highest announce count
        self_node_id = ""
        if devices:
            best = max(devices, key=lambda d: d.announce_count)
            self_node_id = best.destination_hash

        # Build edge list from paths
        edges = []
        for p in paths:
            dest = p.get("destination_hash", "")
            next_hop = p.get("next_hop")
            from_id = next_hop if next_hop else self_node_id

            # Skip self-referential or empty edges
            if not from_id or from_id == dest:
                continue

            # Skip edges to filtered-out nodes
            if not include_unnamed and dest not in node_ids:
                continue

            edges.append({
                "from": from_id,
                "to": dest,
                "hops": p.get("hops", 0),
                "interface_type": p.get("interface_type"),
                "interface_name": p.get("interface_name"),
                "bitrate": p.get("bitrate"),
            })

        return {"nodes": nodes, "edges": edges}

    @router.get("/api/mesh/devices")
    async def devices(
        include_unnamed: bool = Query(False),
        exclude_status: str | None = Query(None),
    ):
        """Return device list with status information."""
        node_store = daemon._node_store
        if node_store is None:
            return []

        excluded = {s.strip() for s in exclude_status.split(",")} if exclude_status else set()

        all_devices = node_store.get_all_nodes()
        result = []
        for d in all_devices:
            if not include_unnamed and d.name == "binary-data":
                continue
            if d.status.value in excluded:
                continue
            result.append({
                "destination_hash": d.destination_hash,
                "identity_hash": d.identity_hash,
                "name": d.name,
                "device_type": d.device_type.value,
                "status": d.status.value,
                "last_seen": d.last_announce,
                "last_seen_display": d.last_seen_display,
                "announce_count": d.announce_count,
                "capabilities": d.capabilities,
                "version": d.version,
                "lxmf_destination_hash": d.lxmf_destination_hash,
                "short_name": d.short_name,
                "system_fingerprint": d.system_fingerprint,
            })
        return result

    @router.get("/api/mesh/status")
    async def mesh_status():
        """Return daemon and mesh status summary."""
        node_store = daemon._node_store
        device_count = 0
        styrene_count = 0
        active_count = 0
        stale_count = 0
        lost_count = 0

        if node_store is not None:
            all_devices = node_store.get_all_nodes()
            device_count = len(all_devices)
            for d in all_devices:
                if d.device_type.value == "styrene":
                    styrene_count += 1
                s = d.status.value
                if s == "active":
                    active_count += 1
                elif s == "stale":
                    stale_count += 1
                else:
                    lost_count += 1

        uptime = int(time.time() - daemon._start_time)

        return {
            "uptime": uptime,
            "version": daemon.config.version if hasattr(daemon.config, "version") else None,
            "device_count": device_count,
            "styrene_count": styrene_count,
            "active": active_count,
            "stale": stale_count,
            "lost": lost_count,
            "path_snapshot_running": (
                daemon._path_snapshot.is_running if daemon._path_snapshot else False
            ),
        }

    # -------------------------------------------------------------------------
    # Conversations
    # -------------------------------------------------------------------------

    def _require_conversation_service():
        if daemon._conversation_service is None:
            raise HTTPException(503, detail="Conversation service not available")
        return daemon._conversation_service

    @router.get("/api/conversations")
    async def list_conversations():
        """Return all conversations."""
        conv_service = _require_conversation_service()
        conversations = conv_service.list_conversations()
        return {"conversations": [c.to_dict() for c in conversations]}

    @router.get("/api/conversations/{peer_hash}/messages")
    async def get_messages(
        peer_hash: str,
        limit: int = Query(50, ge=1, le=MAX_MESSAGE_LIMIT),
        before: float | None = Query(None),
        status: str | None = Query(None),
    ):
        """Return messages for a conversation."""
        _validate_peer_hash(peer_hash)
        conv_service = _require_conversation_service()
        messages = conv_service.get_messages(
            peer_hash=peer_hash,
            limit=limit,
            before_timestamp=before,
            status_filter=status,
        )
        return {"messages": [m.to_dict() for m in messages]}

    @router.post("/api/conversations/{peer_hash}/messages")
    async def send_chat(peer_hash: str, body: SendChatRequest):
        """Send a chat message to a peer."""
        from styrened.services.lxmf_service import get_lxmf_service

        _validate_peer_hash(peer_hash)
        conv_service = _require_conversation_service()

        # Validate reply_to_hash format if provided
        if body.reply_to_hash and not LXMF_HASH_PATTERN.match(body.reply_to_hash):
            raise HTTPException(400, detail="reply_to_hash must be a 64-character hex string")

        lxmf_service = get_lxmf_service()
        if not lxmf_service:
            raise HTTPException(503, detail="LXMF service not initialized")

        # Build fields and payload
        fields: dict[str, object] = {"protocol": "chat"}
        if body.title:
            fields["title"] = body.title

        payload: dict[str, object] = {
            "type": "chat",
            "protocol": "chat",
            "content": body.content,
        }
        if body.title:
            payload["title"] = body.title

        # Step 1: Save message first (avoids race with fast delivery callbacks)
        msg_id = conv_service.save_outgoing_message(
            destination_hash=peer_hash,
            content=body.content,
            title=body.title,
            fields=fields,
            reply_to_hash=body.reply_to_hash,
        )

        # Step 2: Thread-safe tracking for delivery callbacks
        tracking_lock = threading.Lock()
        tracking_registered: dict[str, bytes | None] = {"hash": None}

        def on_delivery(lxmf_message: Any) -> None:
            try:
                if not conv_service._initialized:
                    return
                msg_hash = lxmf_message.hash
                needs_reg = False
                with tracking_lock:
                    if tracking_registered["hash"] is None:
                        tracking_registered["hash"] = msg_hash
                        needs_reg = True
                if needs_reg:
                    conv_service.register_delivery_tracking(msg_id, msg_hash)
                conv_service.on_delivery_callback(msg_hash)
                daemon._broadcast_delivery_status_event(msg_id, peer_hash, "delivered")
            except Exception as e:
                logger.warning(f"Error in delivery callback: {e}")

        def on_failed(lxmf_message: Any) -> None:
            try:
                if not conv_service._initialized:
                    return
                msg_hash = lxmf_message.hash
                needs_reg = False
                with tracking_lock:
                    if tracking_registered["hash"] is None:
                        tracking_registered["hash"] = msg_hash
                        needs_reg = True
                if needs_reg:
                    conv_service.register_delivery_tracking(msg_id, msg_hash)
                conv_service.on_failed_callback(msg_hash)
                daemon._broadcast_delivery_status_event(msg_id, peer_hash, "failed")
            except Exception as e:
                logger.warning(f"Error in failed callback: {e}")

        # Step 3: Build LXMF fields
        lxmf_fields: dict[int, Any] = {}
        try:
            import LXMF
            lxmf_fields[LXMF.FIELD_RENDERER] = LXMF.RENDERER_PLAIN
            if body.reply_to_hash:
                lxmf_fields[LXMF.FIELD_THREAD] = {"reply_to": body.reply_to_hash}
        except ImportError:
            pass

        # Step 4: Send via LXMF
        result = lxmf_service.send_message(
            peer_hash,
            payload,
            on_delivery=on_delivery,
            on_failed=on_failed,
            delivery_method=body.delivery_method,
            lxmf_fields=lxmf_fields if lxmf_fields else None,
        )

        if result is None:
            conv_service.update_message_status(msg_id, "failed")
            raise HTTPException(502, detail=f"Failed to send message to {peer_hash[:16]}...")

        lxmf_hash: bytes = result["hash"]
        delivery_method_used: str = result.get("method", body.delivery_method)
        actual_dest_hash: str = result.get("destination_hash", peer_hash)

        # Normalize truncated peer_hash to full resolved hash
        if actual_dest_hash != peer_hash:
            conv_service.update_destination_hash(msg_id, actual_dest_hash)

        # Register delivery tracking
        needs_reg = False
        with tracking_lock:
            if tracking_registered["hash"] is None:
                tracking_registered["hash"] = lxmf_hash
                needs_reg = True
        if needs_reg:
            conv_service.register_delivery_tracking(msg_id, lxmf_hash)

        conv_service.mark_sent(msg_id)

        return {
            "message_id": msg_id,
            "sent": True,
            "lxmf_hash": lxmf_hash.hex(),
            "delivery_method": delivery_method_used,
        }

    @router.post("/api/conversations/{peer_hash}/read")
    async def mark_read(peer_hash: str):
        """Mark all messages in a conversation as read."""
        _validate_peer_hash(peer_hash)
        conv_service = _require_conversation_service()
        count = conv_service.mark_read(peer_hash)

        # Send read receipts (fire-and-forget)
        try:
            await daemon.send_read_receipts(peer_hash)
        except Exception:
            pass

        return {"marked_read": count}

    @router.delete("/api/conversations/{peer_hash}")
    async def delete_conversation(peer_hash: str):
        """Delete all messages in a conversation."""
        _validate_peer_hash(peer_hash)
        conv_service = _require_conversation_service()
        count = conv_service.delete_conversation(peer_hash)
        return {"deleted": count}

    # -------------------------------------------------------------------------
    # Messages (cross-conversation)
    # -------------------------------------------------------------------------

    @router.get("/api/messages/search")
    async def search_messages(
        q: str = Query(..., min_length=2),
        peer_hash: str | None = Query(None),
        limit: int = Query(50, ge=1, le=MAX_MESSAGE_LIMIT),
    ):
        """Search messages across conversations."""
        conv_service = _require_conversation_service()
        if peer_hash:
            _validate_peer_hash(peer_hash)
        messages = conv_service.search_messages(
            query=q,
            peer_hash=peer_hash,
            limit=limit,
        )
        return {"messages": [m.to_dict() for m in messages]}

    @router.delete("/api/messages/{message_id}")
    async def delete_message(message_id: int):
        """Delete a specific message."""
        if message_id <= 0:
            raise HTTPException(400, detail="message_id must be a positive integer")
        conv_service = _require_conversation_service()
        deleted = conv_service.delete_message(message_id)
        if not deleted:
            raise HTTPException(404, detail=f"Message {message_id} not found")
        return {"deleted": True}

    @router.post("/api/messages/{message_id}/retry")
    async def retry_message(message_id: int):
        """Retry sending a failed message."""
        from styrened.services.lxmf_service import get_lxmf_service

        if message_id <= 0:
            raise HTTPException(400, detail="message_id must be a positive integer")

        conv_service = _require_conversation_service()

        lxmf_service = get_lxmf_service()
        if not lxmf_service:
            raise HTTPException(503, detail="LXMF service not initialized")

        retry_data = conv_service.prepare_retry(message_id)
        if retry_data is None:
            raise HTTPException(404, detail=f"Message {message_id} not found or not in FAILED state")

        dest_hash, content, retry_fields = retry_data

        payload: dict[str, object] = {
            "type": "chat",
            "protocol": "chat",
            "content": content,
        }
        if retry_fields.get("title"):
            payload["title"] = retry_fields["title"]

        def on_delivery(lxmf_message: Any) -> None:
            try:
                msg_hash = lxmf_message.hash
                conv_service.on_delivery_callback(msg_hash)
                daemon._broadcast_delivery_status_event(message_id, dest_hash, "delivered")
            except Exception as e:
                logger.warning(f"Error in delivery callback: {e}")

        def on_failed(lxmf_message: Any) -> None:
            try:
                msg_hash = lxmf_message.hash
                conv_service.on_failed_callback(msg_hash)
                daemon._broadcast_delivery_status_event(message_id, dest_hash, "failed")
            except Exception as e:
                logger.warning(f"Error in failed callback: {e}")

        result = lxmf_service.send_message(
            dest_hash,
            payload,
            on_delivery=on_delivery,
            on_failed=on_failed,
        )

        if result is None:
            conv_service.update_message_status(message_id, "failed")
            raise HTTPException(502, detail=f"Failed to retry message to {dest_hash[:16]}...")

        lxmf_hash = result["hash"]
        delivery_method_used = result.get("method", "direct")

        conv_service.register_delivery_tracking(message_id, lxmf_hash)
        conv_service.mark_sent(message_id)

        return {
            "message_id": message_id,
            "retried": True,
            "lxmf_hash": lxmf_hash.hex(),
            "delivery_method": delivery_method_used,
        }

    # -------------------------------------------------------------------------
    # Contacts
    # -------------------------------------------------------------------------

    def _require_contact_service():
        if not getattr(daemon, "_contact_service", None):
            raise HTTPException(503, detail="Contact service not available")
        return daemon._contact_service

    @router.get("/api/contacts")
    async def list_contacts():
        """Return all contacts."""
        contact_service = _require_contact_service()
        contacts = contact_service.list_contacts()
        return {"contacts": [c.to_dict() for c in contacts]}

    @router.get("/api/contacts/resolve")
    async def resolve_contact(
        name: str = Query(..., min_length=1),
        prefix_match: bool = Query(True),
    ):
        """Resolve a name to a peer hash."""
        contact_service = _require_contact_service()
        peer_hash = contact_service.resolve_name(name, prefix_match=prefix_match)
        return {"peer_hash": peer_hash}

    @router.put("/api/contacts/{peer_hash}")
    async def set_contact(peer_hash: str, body: SetContactRequest):
        """Set or update a contact."""
        _validate_peer_hash(peer_hash)
        contact_service = _require_contact_service()
        contact = contact_service.set_alias(peer_hash, body.alias.strip(), notes=body.notes)
        broadcaster.broadcast_contact_event(peer_hash, "set")
        return contact.to_dict()

    @router.delete("/api/contacts/{peer_hash}")
    async def remove_contact(peer_hash: str):
        """Remove a contact."""
        _validate_peer_hash(peer_hash)
        contact_service = _require_contact_service()
        removed = contact_service.remove_alias(peer_hash)
        if not removed:
            raise HTTPException(404, detail=f"Contact not found: {peer_hash[:16]}...")
        broadcaster.broadcast_contact_event(peer_hash, "removed")
        return {"removed": True}

    # -------------------------------------------------------------------------
    # Fleet
    # -------------------------------------------------------------------------

    @router.post("/api/fleet/{destination}/exec")
    async def fleet_exec(destination: str, body: ExecCommandRequest):
        """Execute a command on a remote device."""
        _validate_peer_hash(destination)
        if not daemon._rpc_client:
            raise HTTPException(503, detail="RPC client not initialized")

        try:
            result = await daemon._rpc_client.call_exec(
                destination=destination,
                command=body.command,
                args=body.args,
                timeout=body.timeout,
            )
            return {
                "exit_code": result.exit_code,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        except TimeoutError as err:
            raise HTTPException(504, detail=f"Exec timed out after {body.timeout}s") from err

    @router.get("/api/fleet/{destination}/status")
    async def fleet_status(destination: str):
        """Query status of a remote device."""
        _validate_peer_hash(destination)
        if not daemon._rpc_client:
            raise HTTPException(503, detail="RPC client not initialized")

        try:
            result = await daemon._rpc_client.call_status(destination=destination)
            return {
                "uptime": result.uptime,
                "ip": result.ip,
                "services": result.services,
                "disk_used": result.disk_used,
                "disk_total": result.disk_total,
                "styrened_version": result.styrened_version,
                "hostname": result.hostname,
                "arch": result.arch,
                "os_id": result.os_id,
                "os_version": result.os_version,
                "nixos_generation": result.nixos_generation,
            }
        except TimeoutError as err:
            raise HTTPException(504, detail="Status request timed out") from err

    @router.post("/api/fleet/{destination}/reboot")
    async def fleet_reboot(destination: str, body: RebootRequest):
        """Reboot a remote device."""
        _validate_peer_hash(destination)
        if not daemon._rpc_client:
            raise HTTPException(503, detail="RPC client not initialized")

        try:
            result = await daemon._rpc_client.call_reboot(
                destination=destination,
                delay=body.delay,
            )
            return {
                "success": result.success,
                "message": result.message,
                "scheduled_time": result.scheduled_time,
            }
        except TimeoutError:
            raise HTTPException(504, detail="Reboot request timed out") from None

    @router.put("/api/fleet/{destination}/config")
    async def fleet_config_update(destination: str, body: FleetConfigUpdateRequest):
        """Update configuration on a remote device."""
        _validate_peer_hash(destination)
        if not daemon._rpc_client:
            raise HTTPException(503, detail="RPC client not initialized")

        try:
            result = await daemon._rpc_client.call_update_config(
                destination=destination,
                config_updates=body.config_updates,
                timeout=body.timeout,
            )
            return {
                "success": result.success,
                "message": result.message,
                "updated_keys": result.updated_keys,
            }
        except TimeoutError:
            raise HTTPException(504, detail=f"Config update timed out after {body.timeout}s") from None

    @router.post("/api/announce")
    async def announce():
        """Trigger a network announce."""
        if not daemon._operator_destination:
            raise HTTPException(503, detail="Operator destination not initialized")
        daemon._announce()
        return {
            "announced": True,
            "destination_hash": daemon._operator_destination.hexhash,
        }

    # -------------------------------------------------------------------------
    # System status
    # -------------------------------------------------------------------------

    @router.get("/api/system/status")
    async def system_status():
        """Return local system hardware information."""
        import platform as plat

        from styrened import __version__
        from styrened.services.hardware import get_system_info

        is_public = daemon.config.api.public_mode
        hostname = daemon.config.identity.display_name or "styrened" if is_public else plat.node()

        try:
            info = get_system_info()
            return {
                "hostname": hostname,
                "platform": plat.system().lower(),
                "cpu_model": info.cpu_model,
                "cpu_cores": info.cpu_cores,
                "ram_total_bytes": info.ram_total_bytes,
                "ram_total_gb": round(info.ram_total_gb, 1),
                "version": __version__,
                "uptime": round(time.time() - daemon._start_time, 1),
            }
        except Exception as e:
            logger.warning(f"Failed to get system info: {e}")
            return {
                "hostname": hostname,
                "platform": plat.system().lower(),
                "cpu_model": "unknown",
                "cpu_cores": 0,
                "ram_total_bytes": 0,
                "ram_total_gb": 0,
                "version": __version__,
                "uptime": round(time.time() - daemon._start_time, 1),
            }

    @router.get("/api/system/reticulum")
    async def reticulum_status():
        """Return Reticulum network status."""
        from styrened.services.reticulum import get_operator_identity

        identity_hash = get_operator_identity()
        destination_hash = ""
        if daemon._operator_destination:
            destination_hash = daemon._operator_destination.hexhash

        # Interface info from node store
        interfaces: list[dict[str, Any]] = []
        path_count = 0
        announce_count = 0

        if daemon._node_store:
            paths = daemon._node_store.get_all_paths()
            path_count = len(paths)
            devices = daemon._node_store.get_all_nodes()
            announce_count = sum(d.announce_count for d in devices)

        transport_enabled = daemon.config.reticulum.resolve_transport_enabled()

        return {
            "initialized": identity_hash is not None,
            "transport_enabled": transport_enabled,
            "identity_hash": identity_hash or "",
            "destination_hash": destination_hash,
            "interfaces": interfaces,
            "path_count": path_count,
            "announce_count": announce_count,
        }

    @router.get("/api/system/disks")
    async def system_disks():
        """Return disk information."""
        from styrened.services.hardware import get_disks

        try:
            disks = get_disks()
            return [
                {
                    "name": d.name,
                    "size_bytes": d.size_bytes,
                    "size_gb": round(d.size_gb, 1),
                    "disk_type": d.disk_type.value,
                    "mount_point": d.mount_point,
                    "filesystem": d.filesystem,
                }
                for d in disks
            ]
        except Exception as e:
            logger.warning(f"Failed to get disk info: {e}")
            return []

    @router.get("/api/system/network")
    async def system_network():
        """Return network interface information."""
        from styrened.services.hardware import get_network_interfaces

        is_public = daemon.config.api.public_mode

        try:
            interfaces = get_network_interfaces()
            result = []
            for iface in interfaces:
                entry: dict[str, Any] = {
                    "name": iface.name,
                    "interface_type": iface.interface_type.value,
                    "category": iface.category.value,
                }
                if not is_public:
                    entry["mac_address"] = iface.mac_address
                    entry["ip_address"] = iface.ip_address
                result.append(entry)
            return result
        except Exception as e:
            logger.warning(f"Failed to get network info: {e}")
            return []

    @router.get("/api/system/setup-status")
    async def setup_status():
        """Return first-run setup status."""
        from styrened.services.setup import get_setup_status

        status = get_setup_status()
        return {
            "identity_configured": status.identity_configured,
            "config_file_exists": status.config_file_exists,
            "display_name_set": status.display_name_set,
            "rns_initialized": status.rns_initialized,
            "is_complete": status.is_complete,
        }

    # SSE events
    router.include_router(create_events_router(broadcaster))

    return router
