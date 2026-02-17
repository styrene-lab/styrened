"""API routes for the mesh topology explorer."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Query

from styrened.web.events import SSEBroadcaster, create_events_router

if TYPE_CHECKING:
    from styrened.daemon import StyreneDaemon


def create_router(daemon: StyreneDaemon, broadcaster: SSEBroadcaster) -> APIRouter:
    """Create API router with all mesh endpoints."""
    router = APIRouter()

    @router.get("/api/mesh/topology")
    async def topology(include_unnamed: bool = Query(False)):
        """Return graph JSON with nodes and edges for vis-network."""
        node_store = daemon._node_store
        if node_store is None:
            return {"nodes": [], "edges": []}

        devices = node_store.get_all_nodes()
        paths = node_store.get_all_paths()

        # Build node list
        nodes = []
        node_ids = set()
        for d in devices:
            if not include_unnamed and d.name == "binary-data":
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
    async def devices(include_unnamed: bool = Query(False)):
        """Return device list with status information."""
        node_store = daemon._node_store
        if node_store is None:
            return []

        all_devices = node_store.get_all_nodes()
        result = []
        for d in all_devices:
            if not include_unnamed and d.name == "binary-data":
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
            })
        return result

    @router.get("/api/mesh/status")
    async def status():
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
                if d.device_type.value == "styrene_node":
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

    # SSE events
    router.include_router(create_events_router(broadcaster))

    return router
