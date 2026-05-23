"""Device listing, completion, connection, and stats tools."""

import time
from typing import Any

from syncthing_mcp.formatters import (
    append_meta,
    fmt,
    format_bytes,
    format_connection,
    format_device,
    truncate,
)
from syncthing_mcp.models import DeviceReadParams, ReadParams, _resolve_scope_folders
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import compute_domain_hints_for_records, mcp


@mcp.tool(
    name="syncthing_list_devices",
    annotations={
        "title": "List All Devices",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_devices(params: ReadParams) -> str:
    """All configured devices with connection status and last seen time.

    Accepts DD-278 ``scope=`` filter. Device set is filtered to devices that
    share at least one folder with the scoped folder set (devices have no
    intrinsic scope tag in Syncthing's model).
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        stats = await client._get("/rest/stats/device")
        conn_data = connections.get("connections", {})

        all_devices = config.get("devices", [])
        matched_total = len(all_devices)
        filtered_by: list[str] = []

        if scope_set is not None:
            # Devices in any folder whose id ∈ scope_set
            scoped_device_ids: set[str] = set()
            for f in config.get("folders", []):
                if f.get("id") in scope_set:
                    for d in f.get("devices", []):
                        did = d.get("deviceID")
                        if did:
                            scoped_device_ids.add(did)
            devices = [d for d in all_devices if d.get("deviceID") in scoped_device_ids]
            filtered_by.append(f"scope={params.scope}")
        else:
            devices = list(all_devices)

        # Track 2 — canonical sort by deviceID ascending (stable key).
        devices.sort(key=lambda d: d.get("deviceID", ""))

        result = [
            format_device(
                dev,
                conn_data.get(dev["deviceID"]),
                stats.get(dev["deviceID"]),
                concise=params.concise,
            )
            for dev in devices
        ]
        # DD-338 A.2.dom.c — apply domain_hint patterns to raw device records
        # (the formatter truncates deviceID in concise mode; use the source
        # records so projector sees full deviceID + name + addresses).
        domain_hints = compute_domain_hints_for_records(devices) or None
        payload = fmt(result, concise=params.concise)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=matched_total,
            returned=len(result),
            filtered_by=filtered_by,
            redactions=redactions,
            latency_ms=latency_ms,
            domain_hints=domain_hints,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_device_completion",
    annotations={
        "title": "Device Completion (All Folders)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_device_completion(params: DeviceReadParams) -> str:
    """Aggregated sync completion for a remote device across all shared folders."""
    try:
        client = get_instance(params.instance)
        comp = await client._get(
            "/rest/db/completion", params={"device": params.device_id}
        )
        data: dict[str, Any] = {
            "device": params.device_id[:8] if params.concise else params.device_id,
            "instance": client.name,
            "completion": round(comp.get("completion", 0), 2),
            "needSize": format_bytes(comp.get("needBytes", 0)),
            "remoteState": comp.get("remoteState", "unknown"),
        }
        if not params.concise:
            data["globalBytes"] = comp.get("globalBytes", 0)
            data["globalSize"] = format_bytes(comp.get("globalBytes", 0))
            data["needBytes"] = comp.get("needBytes", 0)
            data["needItems"] = comp.get("needItems", 0)
        return fmt(data, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_connections",
    annotations={
        "title": "Active Connections",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_connections(params: ReadParams) -> str:
    """Current connection details for all devices. Sorted by deviceID ascending."""
    try:
        client = get_instance(params.instance)
        connections = await client._get("/rest/system/connections")
        config = await client._get("/rest/config")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        # DD-338 B.1.b: canonical sort-before-return on deviceID (dict key) ascending.
        # Syncthing REST API returns `connections.connections` as a dict keyed by
        # canonical deviceID (hex string per Syncthing protocol convention).
        result = [
            format_connection(
                did, conn, devices_map.get(did, did[:8]), concise=params.concise,
            )
            for did, conn in sorted(
                connections.get("connections", {}).items(),
                key=lambda kv: kv[0],
            )
        ]
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_device_stats",
    annotations={
        "title": "Device Statistics",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_device_stats(params: ReadParams) -> str:
    """Per-device statistics: last seen time and connection duration."""
    try:
        client = get_instance(params.instance)
        stats = await client._get("/rest/stats/device")
        config = await client._get("/rest/config")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        result = []
        for did, stat in stats.items():
            entry: dict[str, Any] = {
                "device": devices_map.get(did, did[:8]),
                "lastSeen": stat.get("lastSeen", ""),
            }
            if not params.concise:
                entry["deviceID"] = did
                entry["lastConnectionDurationS"] = stat.get("lastConnectionDurationS", 0)
            result.append(entry)
        return fmt(result, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)
