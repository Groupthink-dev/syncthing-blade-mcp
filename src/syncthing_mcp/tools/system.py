"""System status, health, errors, log, restart, and upgrade tools."""

import time
from typing import Any

import httpx

from syncthing_mcp.formatters import append_meta, fmt, format_bytes, meta_envelope, truncate
from syncthing_mcp.models import ReadParams, WriteParams, _resolve_scope_folders
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import mcp


@mcp.tool(
    name="syncthing_system_status",
    annotations={
        "title": "System Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_status(params: ReadParams) -> str:
    """Device ID, name, uptime, version, and folder/device counts."""
    try:
        client = get_instance(params.instance)
        status = await client._get("/rest/system/status")
        version = await client._get("/rest/system/version")
        config = await client._get("/rest/config")
        my_id = status.get("myID", "")
        my_name = my_id[:8]
        for dev in config.get("devices", []):
            if dev.get("deviceID") == my_id:
                my_name = dev.get("name", my_id[:8])
                break
        data: dict[str, Any] = {
            "instance": client.name,
            "myID": my_id[:8] if params.concise else my_id,
            "deviceName": my_name,
            "uptime": status.get("uptime"),
            "version": version.get("version"),
            "folders": len(config.get("folders", [])),
            "devices": len(config.get("devices", [])),
        }
        if not params.concise:
            data["os"] = version.get("os")
            data["arch"] = version.get("arch")
        return fmt(data, concise=params.concise)
    except Exception as e:
        if isinstance(e, ValueError):
            return handle_error_global(e)
        try:
            return get_instance(None).handle_error(e)
        except Exception:
            return handle_error_global(e)


@mcp.tool(
    name="syncthing_system_errors",
    annotations={
        "title": "System Errors & Warnings",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_errors(params: ReadParams) -> str:
    """Recent system errors and warnings."""
    try:
        client = get_instance(params.instance)
        result = await client._get("/rest/system/error")
        errors = result.get("errors", []) or []
        data: dict[str, Any] = {
            "instance": client.name,
            "count": len(errors),
            "errors": errors,
        }
        return truncate(fmt(data, concise=params.concise))
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_clear_errors",
    annotations={
        "title": "Clear System Errors",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_clear_errors(params: WriteParams) -> str:
    """Clear the system error log."""
    try:
        client = get_instance(params.instance)
        await client._post("/rest/system/error/clear")
        return fmt({"status": "cleared", "instance": client.name})
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_system_log",
    annotations={
        "title": "System Log",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_system_log(params: ReadParams) -> str:
    """Recent system log entries."""
    try:
        client = get_instance(params.instance)
        result = await client._get("/rest/system/log")
        messages = result.get("messages", []) or []
        data: dict[str, Any] = {
            "instance": client.name,
            "count": len(messages),
            "messages": messages,
        }
        return truncate(fmt(data, concise=params.concise))
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_recent_changes",
    annotations={
        "title": "Recent File Changes",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_recent_changes(params: ReadParams) -> str:
    """Recent file change events (local and remote) across all folders.

    DD-338 A.2 — accepts ``scope=work|personal|family|home|infrastructure``
    mapped to ``SYNCTHING_<SCOPE>_FOLDERS[_<INSTANCE>]`` env var; filters the
    event stream to events whose ``data.folderID`` is in the scoped folder
    set via the A.1 ``_resolve_scope_folders`` substrate. ``scope=public``
    raises. Events with missing/empty ``folderID`` are filtered out when
    a scope filter is active (system-level events do not partition by
    folder scope).
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        client = get_instance(params.instance)
        events_raw = await client._get(
            "/rest/events",
            params={
                "events": "LocalChangeDetected,RemoteChangeDetected",
                "limit": "50",
                "timeout": "0",
            },
        )
        if not isinstance(events_raw, list):
            events_raw = []
        matched_total = len(events_raw)
        filtered_by: list[str] = []
        if scope_set is not None:
            events_raw = [
                e for e in events_raw
                if (e.get("data", {}).get("folderID") or "") in scope_set
            ]
            filtered_by.append(f"scope={params.scope}")
        if params.concise:
            events = [
                {
                    "type": e.get("type", "")[:6],  # "Local" or "Remote"
                    "folder": e.get("data", {}).get("folderID", ""),
                    "path": e.get("data", {}).get("path", ""),
                    "action": e.get("data", {}).get("action", ""),
                }
                for e in events_raw
            ]
        else:
            events = events_raw
        data: dict[str, Any] = {
            "instance": client.name,
            "count": len(events),
            "events": events,
        }
        payload = truncate(fmt(data, concise=params.concise))
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            meta_envelope(
                matched_total=matched_total,
                returned=len(events),
                filtered_by=filtered_by,
                redactions=redactions,
                latency_ms=latency_ms,
            ),
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_restart_required",
    annotations={
        "title": "Check if Restart Required",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_restart_required(params: ReadParams) -> str:
    """Check if Syncthing requires a restart for config changes to take effect."""
    try:
        client = get_instance(params.instance)
        result = await client._get("/rest/config/restart-required")
        return fmt({
            "instance": client.name,
            "restartRequired": result.get("requiresRestart", False),
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_restart",
    annotations={
        "title": "Restart Syncthing",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_restart(params: WriteParams) -> str:
    """Restart the Syncthing service. Temporarily stops all sync activity."""
    try:
        client = get_instance(params.instance)
        try:
            await client._post("/rest/system/restart")
        except (httpx.ConnectError, httpx.RemoteProtocolError):
            pass  # Expected — Syncthing closes the connection as it restarts
        return fmt({
            "status": "restart_initiated",
            "instance": client.name,
            "message": f"Syncthing '{client.name}' is restarting.",
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_check_upgrade",
    annotations={
        "title": "Check for Upgrade",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_check_upgrade(params: ReadParams) -> str:
    """Check if a newer version of Syncthing is available."""
    try:
        client = get_instance(params.instance)
        version = await client._get("/rest/system/version")
        try:
            upgrade = await client._get("/rest/system/upgrade")
            return fmt({
                "instance": client.name,
                "running": version.get("version"),
                "latest": upgrade.get("latest"),
                "newer": upgrade.get("newer", False),
            }, concise=params.concise)
        except httpx.HTTPStatusError as ue:
            if ue.response.status_code == 501:
                return fmt({
                    "instance": client.name,
                    "running": version.get("version"),
                    "upgradeCheck": "unavailable",
                })
            raise
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_health_summary",
    annotations={
        "title": "Health Summary",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_health_summary(params: ReadParams) -> str:
    """Single-call health overview: system status, folder states, device
    connectivity, errors, and pending items. Start here for quick triage."""
    try:
        client = get_instance(params.instance)

        sys_status = await client._get("/rest/system/status")
        config = await client._get("/rest/config")
        sys_errors = await client._get("/rest/system/error")
        connections = await client._get("/rest/system/connections")

        try:
            pending_devices = await client._get("/rest/cluster/pending/devices")
        except Exception:
            pending_devices = {}
        try:
            pending_folders = await client._get("/rest/cluster/pending/folders")
        except Exception:
            pending_folders = {}

        folders = config.get("folders", [])
        conn_data = connections.get("connections", {})

        online_count = sum(1 for c in conn_data.values() if c.get("connected"))
        total_remote = len(conn_data)

        folder_health = []
        paused_count = 0
        syncing_count = 0
        error_folders = 0

        for f_cfg in folders:
            fid = f_cfg["id"]
            if f_cfg.get("paused", False):
                paused_count += 1
                folder_health.append({"id": fid, "state": "paused"})
            else:
                try:
                    fstatus = await client._get(
                        "/rest/db/status", params={"folder": fid}
                    )
                    state = fstatus.get("state", "unknown")
                    entry: dict[str, Any] = {"id": fid, "state": state}
                    if state in ("syncing", "sync-preparing"):
                        syncing_count += 1
                        entry["needSize"] = format_bytes(fstatus.get("needBytes", 0))
                    elif state == "error":
                        error_folders += 1
                    folder_health.append(entry)
                except Exception:
                    error_folders += 1
                    folder_health.append({"id": fid, "state": "unreachable"})

        alerts: list[str] = []
        error_list = sys_errors.get("errors", []) or []
        if error_list:
            alerts.append(f"{len(error_list)} system error(s)")
        if error_folders > 0:
            alerts.append(f"{error_folders} folder(s) in error state")
        offline_count = total_remote - online_count
        if offline_count > 0:
            alerts.append(f"{offline_count} device(s) offline")
        if paused_count > 0:
            alerts.append(f"{paused_count} folder(s) paused")
        if syncing_count > 0:
            alerts.append(f"{syncing_count} folder(s) syncing")
        num_pending_dev = len(pending_devices) if isinstance(pending_devices, dict) else 0
        num_pending_fld = len(pending_folders) if isinstance(pending_folders, dict) else 0
        if num_pending_dev > 0:
            alerts.append(f"{num_pending_dev} pending device(s)")
        if num_pending_fld > 0:
            alerts.append(f"{num_pending_fld} pending folder(s)")

        if error_folders > 0 or len(error_list) > 0:
            overall = "error"
        elif alerts:
            overall = "warning"
        else:
            overall = "good"

        data: dict[str, Any] = {
            "instance": client.name,
            "status": overall,
            "uptime": sys_status.get("uptime"),
            "summary": {
                "folders": len(folders),
                "idle": sum(1 for f in folder_health if f.get("state") == "idle"),
                "syncing": syncing_count,
                "paused": paused_count,
                "errors": error_folders,
                "devicesOnline": online_count,
                "devicesOffline": offline_count,
                "pendingDevices": num_pending_dev,
                "pendingFolders": num_pending_fld,
            },
            "alerts": alerts,
        }
        if not params.concise:
            data["folders"] = folder_health
        return fmt(data, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)
