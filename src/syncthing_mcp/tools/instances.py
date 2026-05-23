"""Tools for instance management and listing folders (config-level)."""

import time
from typing import Any

from syncthing_mcp.formatters import append_meta, fmt, format_folder, meta_envelope
from syncthing_mcp.models import ReadParams, _resolve_scope_folders
from syncthing_mcp.registry import (
    get_all_instances,
    get_instance,
    handle_error_global,
)
from syncthing_mcp.server import compute_domain_hints_for_records, mcp


@mcp.tool(
    name="syncthing_list_instances",
    annotations={
        "title": "List Configured Instances",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_instances(params: ReadParams) -> str:
    """List all configured Syncthing instances and probe their availability."""
    results = []
    for name, client in get_all_instances().items():
        entry: dict[str, Any] = {"name": name, "url": client.url}
        try:
            status = await client._get("/rest/system/status")
            version = await client._get("/rest/system/version")
            config = await client._get("/rest/config")
            my_id = status.get("myID", "")
            my_name = my_id[:8]
            for dev in config.get("devices", []):
                if dev.get("deviceID") == my_id:
                    my_name = dev.get("name", my_id[:8])
                    break
            entry.update({
                "available": True,
                "deviceName": my_name,
                "version": version.get("version"),
                "folders": len(config.get("folders", [])),
                "devices": len(config.get("devices", [])),
            })
            if not params.concise:
                entry["myID"] = my_id
        except Exception as exc:
            entry.update({"available": False, "error": str(exc)})
        results.append(entry)
    return fmt(results, concise=params.concise)


@mcp.tool(
    name="syncthing_list_folders",
    annotations={
        "title": "List All Folders",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_list_folders(params: ReadParams) -> str:
    """All configured folders with labels, types, and device counts.

    DD-338 A.2 — accepts ``scope=work|personal|family|home|infrastructure``
    mapped to ``SYNCTHING_<SCOPE>_FOLDERS[_<INSTANCE>]`` env var; filters
    ``config.folders`` to the resolved folder-ID set via the A.1
    ``_resolve_scope_folders`` substrate. ``scope=public`` raises.

    DD-338 A.2.dom.c — emits per-record ``domain_hints`` in the ``_meta``
    envelope when the user has configured matching patterns via the
    BladeConfigStore.
    """
    start = time.perf_counter()
    try:
        scope_set, redactions = _resolve_scope_folders(params.scope, params.instance)
        client = get_instance(params.instance)
        config = await client._get("/rest/config")
        all_folders = config.get("folders", [])
        matched_total = len(all_folders)
        filtered_by: list[str] = []
        if scope_set is not None:
            folders = [f for f in all_folders if f.get("id") in scope_set]
            filtered_by.append(f"scope={params.scope}")
        else:
            folders = all_folders
        if params.concise:
            result = [format_folder(f, concise=True) for f in folders]
        else:
            devices_map = {
                d["deviceID"]: d.get("name", d["deviceID"][:8])
                for d in config.get("devices", [])
            }
            result = []
            for f in folders:
                shared = [
                    {"deviceID": d.get("deviceID", ""), "name": devices_map.get(d.get("deviceID", ""), "")}
                    for d in f.get("devices", [])
                ]
                result.append({
                    "id": f["id"],
                    "label": f.get("label", f["id"]),
                    "path": f.get("path", ""),
                    "type": f.get("type", "sendreceive"),
                    "paused": f.get("paused", False),
                    "sharedWith": shared,
                })
        # Project domain hints from raw config records — they carry the
        # full source-of-truth shape (`id`, `label`, `path`, `type`) the
        # projector expects, even when ``concise`` collapses the output.
        domain_hints = compute_domain_hints_for_records(folders) or None
        payload = fmt(result, concise=params.concise)
        latency_ms = int((time.perf_counter() - start) * 1000)
        return append_meta(
            payload,
            meta_envelope(
                matched_total=matched_total,
                returned=len(result),
                filtered_by=filtered_by,
                redactions=redactions,
                latency_ms=latency_ms,
                domain_hints=domain_hints,
            ),
        )
    except Exception as e:
        return handle_error_global(e)
