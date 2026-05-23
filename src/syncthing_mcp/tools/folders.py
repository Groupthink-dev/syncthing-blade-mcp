"""Folder status, completion, replication, operations, and file-level query tools."""

import time
from typing import Any

from syncthing_mcp.formatters import (
    append_meta,
    fmt,
    format_bytes,
    format_completion,
    format_folder_status,
    format_replication_entry,
    truncate,
)
from syncthing_mcp.models import (
    BrowseFolderInput,
    FileInfoInput,
    FolderNeedInput,
    FolderReadParams,
    FolderWriteParams,
    ReadParams,
    RemoteNeedInput,
    _resolve_scope_folders,
)
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import mcp


# =====================================================================
#  Folder Status & Replication
# =====================================================================


@mcp.tool(
    name="syncthing_folder_status",
    annotations={
        "title": "Folder Status",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_status(params: FolderReadParams) -> str:
    """Detailed status for a folder — file counts, bytes, sync state.
    Note: expensive call on the Syncthing side. Use sparingly.

    Accepts DD-278 ``scope=`` filter as a membership precondition. When
    ``scope`` is set and configured, ``folder_id`` must be in the scoped
    folder set; otherwise the call refuses with a single-line error and
    ``_meta.redactions=["folder_outside_scope"]``.
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        filtered_by: list[str] = []
        if params.scope is not None:
            filtered_by.append(f"scope={params.scope}")

        if scope_set is not None and params.folder_id not in scope_set:
            error_payload = fmt(
                {"error": f"folder_id '{params.folder_id}' not in scope={params.scope} folder set"},
                concise=params.concise,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return append_meta(
                error_payload,
                matched_total=0,
                returned=0,
                filtered_by=filtered_by,
                redactions=[*redactions, "folder_outside_scope"],
                latency_ms=latency_ms,
            )

        filtered_by.append(f"folder={params.folder_id}")

        client = get_instance(params.instance)
        status = await client._get("/rest/db/status", params={"folder": params.folder_id})
        stats = await client._get("/rest/stats/folder")
        folder_stats = stats.get(params.folder_id, {})
        data: dict[str, Any] = {
            "folder": params.folder_id,
            "instance": client.name,
            **format_folder_status(status, concise=params.concise),
        }
        if not params.concise:
            data["lastScan"] = folder_stats.get("lastScan", "")
            data["lastFile"] = folder_stats.get("lastFile", {})
        payload = fmt(data, concise=params.concise)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=1,
            returned=1,
            filtered_by=filtered_by,
            redactions=redactions,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_completion",
    annotations={
        "title": "Folder Completion by Device",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_completion(params: FolderReadParams) -> str:
    """Per-device replication completion % for a folder. Key tool for
    determining if a folder is fully replicated before local removal."""
    try:
        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")

        folder_cfg = None
        for f in config.get("folders", []):
            if f["id"] == params.folder_id:
                folder_cfg = f
                break
        if not folder_cfg:
            return fmt({"error": f"Folder '{params.folder_id}' not found in config."})

        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }
        completions = []
        for dev in folder_cfg.get("devices", []):
            did = dev.get("deviceID", "")
            if did == my_id:
                continue
            connected = conn_data.get(did, {}).get("connected", False)
            try:
                comp = await client._get(
                    "/rest/db/completion",
                    params={"folder": params.folder_id, "device": did},
                )
                completions.append(format_completion(
                    comp,
                    devices_map.get(did, did[:8]),
                    connected=connected,
                    concise=params.concise,
                ))
            except Exception:
                completions.append({
                    "device": devices_map.get(did, did[:8]),
                    "connected": False,
                    "completion": None,
                    "error": "unreachable",
                })

        fully = sum(
            1 for c in completions
            if c.get("completion") == 100 and c.get("remoteState") == "valid"
        )
        return fmt({
            "folder": params.folder_id,
            "label": folder_cfg.get("label", params.folder_id),
            "instance": client.name,
            "remoteDevices": len(completions),
            "fullyReplicated": fully,
            "devices": completions,
        }, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_replication_report",
    annotations={
        "title": "Replication Report — Safe to Remove?",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_replication_report(params: ReadParams) -> str:
    """Replication analysis for ALL folders. Shows safe-to-remove flag and
    reclaimable space. Primary tool for disk-space cleanup decisions.

    Accepts DD-278 ``scope=`` filter. Folder set is filtered to ids that
    appear in the scoped folder set; unconfigured scope passes through with
    a redaction.
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        filtered_by: list[str] = []
        if params.scope is not None:
            filtered_by.append(f"scope={params.scope}")

        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        connections = await client._get("/rest/system/connections")
        conn_data = connections.get("connections", {})
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")
        devices_map = {
            d["deviceID"]: d.get("name", d["deviceID"][:8])
            for d in config.get("devices", [])
        }

        all_folders = config.get("folders", [])
        matched_total = len(all_folders)
        if scope_set is not None:
            folders = [f for f in all_folders if f.get("id") in scope_set]
        else:
            folders = list(all_folders)

        report = []
        total_reclaimable = 0

        for folder_cfg in folders:
            fid = folder_cfg["id"]
            try:
                fstatus = await client._get("/rest/db/status", params={"folder": fid})
            except Exception:
                report.append({"id": fid, "label": folder_cfg.get("label", fid), "error": "unreachable"})
                continue

            remote_devices = [
                d for d in folder_cfg.get("devices", []) if d.get("deviceID") != my_id
            ]
            device_completions = []
            for dev in remote_devices:
                did = dev.get("deviceID", "")
                connected = conn_data.get(did, {}).get("connected", False)
                try:
                    comp = await client._get(
                        "/rest/db/completion",
                        params={"folder": fid, "device": did},
                    )
                    device_completions.append(format_completion(
                        comp,
                        devices_map.get(did, did[:8]),
                        connected=connected,
                        concise=params.concise,
                    ))
                except Exception:
                    device_completions.append({
                        "device": devices_map.get(did, did[:8]),
                        "connected": connected,
                        "completion": None,
                        "remoteState": "unknown",
                    })

            entry = format_replication_entry(
                folder_cfg, fstatus, device_completions, concise=params.concise,
            )
            safe = entry.get("safe") if params.concise else entry.get("safeToRemove")
            if safe:
                total_reclaimable += fstatus.get("localBytes", 0)
            report.append(entry)

        # Track 2 — preserve safe-first + bytes-desc ordering; add id tiebreaker
        # so two folders with identical (safe, localBytes) sort deterministically.
        report.sort(key=lambda x: (
            -int(x.get("safe", x.get("safeToRemove", False)) or False),
            -x.get("localBytes", 0) if "localBytes" in x else 0,
            x.get("id", ""),
        ))

        payload = fmt({
            "instance": client.name,
            "summary": {
                "total": len(report),
                "safe": sum(1 for r in report if r.get("safe") or r.get("safeToRemove")),
                "reclaimable": format_bytes(total_reclaimable),
            },
            "folders": report,
        }, concise=params.concise)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=matched_total,
            returned=len(report),
            filtered_by=filtered_by,
            redactions=redactions,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  Folder Operations
# =====================================================================


@mcp.tool(
    name="syncthing_pause_folder",
    annotations={
        "title": "Pause a Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pause_folder(params: FolderWriteParams) -> str:
    """Pause syncing for a folder. Does NOT delete data — only stops sync
    so you can safely remove the local copy without propagating deletions."""
    try:
        client = get_instance(params.instance)
        folder_cfg = await client._get(f"/rest/config/folders/{params.folder_id}")
        folder_cfg["paused"] = True
        await client._patch(f"/rest/config/folders/{params.folder_id}", body=folder_cfg)
        return fmt({
            "status": "paused",
            "folder": params.folder_id,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_resume_folder",
    annotations={
        "title": "Resume a Folder",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_resume_folder(params: FolderWriteParams) -> str:
    """Resume syncing for a paused folder. WARNING: if local data was deleted
    while paused, behaviour depends on folder type (sendreceive may propagate
    deletions; receiveonly will re-download)."""
    try:
        client = get_instance(params.instance)
        folder_cfg = await client._get(f"/rest/config/folders/{params.folder_id}")
        folder_type = folder_cfg.get("type", "sendreceive")
        folder_cfg["paused"] = False
        await client._patch(f"/rest/config/folders/{params.folder_id}", body=folder_cfg)
        return fmt({
            "status": "resumed",
            "folder": params.folder_id,
            "type": folder_type,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_scan_folder",
    annotations={
        "title": "Trigger Folder Scan",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_scan_folder(params: FolderWriteParams) -> str:
    """Trigger an immediate rescan of a folder to refresh its status."""
    try:
        client = get_instance(params.instance)
        await client._post("/rest/db/scan", params={"folder": params.folder_id})
        return fmt({
            "status": "scan_requested",
            "folder": params.folder_id,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_errors",
    annotations={
        "title": "Folder Errors",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_errors(params: FolderReadParams) -> str:
    """Current sync errors for a specific folder.

    Accepts DD-278 ``scope=`` filter as a membership precondition. When
    ``scope`` is set and configured, ``folder_id`` must be in the scoped
    folder set; otherwise the call refuses with a single-line error and
    ``_meta.redactions=["folder_outside_scope"]``.
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        filtered_by: list[str] = []
        if params.scope is not None:
            filtered_by.append(f"scope={params.scope}")

        if scope_set is not None and params.folder_id not in scope_set:
            error_payload = fmt(
                {"error": f"folder_id '{params.folder_id}' not in scope={params.scope} folder set"},
                concise=params.concise,
            )
            latency_ms = int((time.perf_counter() - start) * 1000)
            return append_meta(
                error_payload,
                matched_total=0,
                returned=0,
                filtered_by=filtered_by,
                redactions=[*redactions, "folder_outside_scope"],
                latency_ms=latency_ms,
            )

        filtered_by.append(f"folder={params.folder_id}")

        client = get_instance(params.instance)
        errors = await client._get(
            "/rest/folder/errors", params={"folder": params.folder_id}
        )
        error_list = errors.get("errors", []) or []
        payload = truncate(fmt({
            "folder": params.folder_id,
            "instance": client.name,
            "count": len(error_list),
            "errors": error_list,
        }, concise=params.concise))
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=len(error_list),
            returned=len(error_list),
            filtered_by=filtered_by,
            redactions=redactions,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  File-level queries
# =====================================================================


@mcp.tool(
    name="syncthing_browse_folder",
    annotations={
        "title": "Browse Folder Contents",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_browse_folder(params: BrowseFolderInput) -> str:
    """Browse folder contents at a path prefix (directory listing from DB)."""
    start = time.perf_counter()
    try:
        client = get_instance(params.instance)
        query: dict[str, str] = {"folder": params.folder_id}
        if params.prefix:
            query["prefix"] = params.prefix
        if params.levels is not None:
            query["levels"] = str(params.levels)
        result = await client._get("/rest/db/browse", params=query)
        entries_count = len(result) if isinstance(result, list) else 0
        payload = truncate(fmt({
            "folder": params.folder_id,
            "instance": client.name,
            "prefix": params.prefix or "",
            "entries": result,
        }, concise=params.concise))
        filtered_by: list[str] = [f"folder={params.folder_id}"]
        if params.prefix:
            filtered_by.append(f"prefix={params.prefix}")
        if params.levels is not None:
            filtered_by.append(f"levels={params.levels}")
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=entries_count,
            returned=entries_count,
            filtered_by=filtered_by,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_file_info",
    annotations={
        "title": "File Info",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_file_info(params: FileInfoInput) -> str:
    """Detailed info about a file — versions, availability, modification time."""
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/file",
            params={"folder": params.folder_id, "file": params.file_path},
        )
        if params.concise:
            g = result.get("global", {})
            l = result.get("local", {})
            return fmt({
                "folder": params.folder_id,
                "file": params.file_path,
                "instance": client.name,
                "globalSize": format_bytes(g.get("size", 0)) if g else None,
                "localSize": format_bytes(l.get("size", 0)) if l else None,
                "availability": result.get("availability"),
            })
        # Detailed mode — enrich with human-readable sizes
        for key in ("global", "local"):
            entry = result.get(key)
            if isinstance(entry, dict) and "size" in entry:
                entry["sizeFormatted"] = format_bytes(entry["size"])
        return fmt({
            "folder": params.folder_id,
            "file": params.file_path,
            "instance": client.name,
            "availability": result.get("availability"),
            "global": result.get("global"),
            "local": result.get("local"),
        }, concise=False)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_folder_need",
    annotations={
        "title": "Folder Need (Out-of-Sync Files)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_folder_need(params: FolderNeedInput) -> str:
    """Files this folder still needs — items that are out of sync locally.

    Pagination: caller advances by incrementing ``page`` (1-based) with the
    same ``per_page`` to fetch the next slice; upstream Syncthing exposes no
    cursor token. ``_meta.next_cursor`` is omitted at v1 per DD-338 Phase C
    Wave 2 OQ-4.
    """
    start = time.perf_counter()
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/need",
            params={
                "folder": params.folder_id,
                "page": str(params.page),
                "perpage": str(params.per_page),
            },
        )
        progress = result.get("progress", []) or []
        queued = result.get("queued", []) or []
        rest = result.get("rest", []) or []
        returned_count = len(progress) + len(queued) + len(rest)
        payload = truncate(fmt({
            "folder": params.folder_id,
            "instance": client.name,
            "page": result.get("page", params.page),
            "perpage": result.get("perpage", params.per_page),
            "progress": progress,
            "queued": queued,
            "rest": rest,
        }, concise=params.concise))
        filtered_by: list[str] = [
            f"folder={params.folder_id}",
            f"page={params.page}",
            f"perpage={params.per_page}",
        ]
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=returned_count,
            returned=returned_count,
            filtered_by=filtered_by,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_remote_need",
    annotations={
        "title": "Remote Need (What a Device Needs from Us)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_remote_need(params: RemoteNeedInput) -> str:
    """Files a remote device still needs from us for a specific folder.
    Useful for debugging why sync to a device is incomplete.

    Pagination: caller advances by incrementing ``page`` (1-based) with the
    same ``per_page`` to fetch the next slice; upstream Syncthing exposes no
    cursor token. ``_meta.next_cursor`` is omitted at v1 per DD-338 Phase C
    Wave 2 OQ-4.
    """
    start = time.perf_counter()
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/remoteneed",
            params={
                "folder": params.folder_id,
                "device": params.device_id,
                "page": str(params.page),
                "perpage": str(params.per_page),
            },
        )
        progress = result.get("progress", []) or []
        queued = result.get("queued", []) or []
        rest = result.get("rest", []) or []
        returned_count = len(progress) + len(queued) + len(rest)
        payload = truncate(fmt({
            "folder": params.folder_id,
            "device": params.device_id[:8],
            "instance": client.name,
            "page": result.get("page", params.page),
            "perpage": result.get("perpage", params.per_page),
            "progress": progress,
            "queued": queued,
            "rest": rest,
        }, concise=params.concise))
        filtered_by: list[str] = [
            f"device={params.device_id}",
            f"folder={params.folder_id}",
            f"page={params.page}",
            f"perpage={params.per_page}",
        ]
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            matched_total=returned_count,
            returned=returned_count,
            filtered_by=filtered_by,
            latency_ms=latency_ms,
        )
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  Conflict resolution
# =====================================================================


@mcp.tool(
    name="syncthing_override_folder",
    annotations={
        "title": "Override Remote Changes (Send-Only)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_override_folder(params: FolderWriteParams) -> str:
    """Override remote changes on a send-only folder (make local authoritative)."""
    try:
        client = get_instance(params.instance)
        await client._post("/rest/db/override", params={"folder": params.folder_id})
        return fmt({
            "status": "override_requested",
            "folder": params.folder_id,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_revert_folder",
    annotations={
        "title": "Revert Local Changes (Receive-Only)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_revert_folder(params: FolderWriteParams) -> str:
    """Revert local changes on a receive-only folder (pull remote state)."""
    try:
        client = get_instance(params.instance)
        await client._post("/rest/db/revert", params={"folder": params.folder_id})
        return fmt({
            "status": "revert_requested",
            "folder": params.folder_id,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)
