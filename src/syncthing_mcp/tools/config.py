"""Config mutation tools: pending devices/folders, ignores, accept/reject."""

from syncthing_mcp.formatters import fmt, truncate
from syncthing_mcp.models import (
    AcceptDeviceInput,
    AcceptFolderInput,
    DeviceWriteParams,
    FolderReadParams,
    ReadParams,
    RejectFolderInput,
    SetDefaultIgnoresInput,
    SetIgnoresInput,
    WriteParams,
    require_write,
)
from syncthing_mcp.registry import get_instance, handle_error_global
from syncthing_mcp.server import mcp


# =====================================================================
#  Pending Devices & Folders
# =====================================================================


@mcp.tool(
    name="syncthing_pending_devices",
    annotations={
        "title": "List Pending Device Requests",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pending_devices(params: ReadParams) -> str:
    """Remote devices that tried to connect but are not yet configured."""
    try:
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/devices")
        return fmt(
            {"instance": client.name, "pendingDevices": pending},
            concise=params.concise,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_pending_folders",
    annotations={
        "title": "List Pending Folder Offers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_pending_folders(params: ReadParams) -> str:
    """Folders that remote devices have offered to share but are not yet accepted."""
    try:
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/folders")
        return fmt(
            {"instance": client.name, "pendingFolders": pending},
            concise=params.concise,
        )
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_accept_device",
    annotations={
        "title": "Accept Pending Device",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def syncthing_accept_device(params: AcceptDeviceInput) -> str:
    """Accept a pending device by adding it to the Syncthing configuration.
    Requires SYNCTHING_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    if not params.confirm:
        return fmt({"error": (
            "Accepting a pending device admits it into the Syncthing cluster, "
            "allowing it to connect and be offered folder shares. "
            "Set confirm=true to proceed."
        )})
    try:
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/devices")
        pending_info = pending.get(params.device_id, {})
        name = params.name
        if not name:
            name = pending_info.get("name", params.device_id[:8])
        defaults = await client._get("/rest/config/defaults/device")
        new_device = defaults.copy()
        new_device["deviceID"] = params.device_id
        new_device["name"] = name
        await client._post("/rest/config/devices", body=new_device)
        return fmt({
            "status": "accepted",
            "deviceID": params.device_id[:8],
            "name": name,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_reject_device",
    annotations={
        "title": "Reject Pending Device",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_reject_device(params: DeviceWriteParams) -> str:
    """Dismiss a pending device connection request.
    Requires SYNCTHING_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    try:
        client = get_instance(params.instance)
        await client._delete(
            "/rest/cluster/pending/devices",
            params={"device": params.device_id},
        )
        return fmt({
            "status": "rejected",
            "deviceID": params.device_id[:8],
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_accept_folder",
    annotations={
        "title": "Accept Pending Folder Offer",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def syncthing_accept_folder(params: AcceptFolderInput) -> str:
    """Accept a pending folder share offer. Uses default folder config as template.
    Requires SYNCTHING_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    if not params.confirm:
        return fmt({"error": (
            "Accepting a pending folder adds it to the configuration and "
            "starts syncing its contents to local disk from the offering "
            "device(s). Set confirm=true to proceed."
        )})
    try:
        client = get_instance(params.instance)
        pending = await client._get("/rest/cluster/pending/folders")
        folder_pending = pending.get(params.folder_id, {})
        if not folder_pending:
            return fmt({"error": f"Folder '{params.folder_id}' not found in pending offers."})
        offering_devices = list(folder_pending.get("offeredBy", {}).keys())
        first_offer = next(iter(folder_pending.get("offeredBy", {}).values()), {})
        label = first_offer.get("label", params.folder_id)
        status = await client._get("/rest/system/status")
        my_id = status.get("myID", "")
        defaults = await client._get("/rest/config/defaults/folder")
        new_folder = defaults.copy()
        new_folder["id"] = params.folder_id
        new_folder["label"] = label
        if params.path:
            new_folder["path"] = params.path
        device_list = [{"deviceID": my_id}]
        for did in offering_devices:
            device_list.append({"deviceID": did})
        new_folder["devices"] = device_list
        await client._post("/rest/config/folders", body=new_folder)
        return fmt({
            "status": "accepted",
            "folder": params.folder_id,
            "label": label,
            "path": new_folder.get("path", "(default)"),
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_reject_folder",
    annotations={
        "title": "Reject Pending Folder Offer",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_reject_folder(params: RejectFolderInput) -> str:
    """Dismiss a pending folder share offer.
    Requires SYNCTHING_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    try:
        client = get_instance(params.instance)
        delete_params: dict[str, str] = {"folder": params.folder_id}
        if params.device_id:
            delete_params["device"] = params.device_id
        await client._delete("/rest/cluster/pending/folders", params=delete_params)
        return fmt({
            "status": "rejected",
            "folder": params.folder_id,
            "instance": client.name,
        })
    except Exception as e:
        return handle_error_global(e)


# =====================================================================
#  Ignore Patterns
# =====================================================================


@mcp.tool(
    name="syncthing_get_ignores",
    annotations={
        "title": "Get Folder Ignore Patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_get_ignores(params: FolderReadParams) -> str:
    """Get the .stignore patterns for a folder."""
    try:
        client = get_instance(params.instance)
        result = await client._get(
            "/rest/db/ignores", params={"folder": params.folder_id}
        )
        data = {
            "folder": params.folder_id,
            "instance": client.name,
            "patterns": result.get("ignore", []) or [],
        }
        if not params.concise:
            data["expanded"] = result.get("expanded", []) or []
        return fmt(data, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_set_ignores",
    annotations={
        "title": "Set Folder Ignore Patterns",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_set_ignores(params: SetIgnoresInput) -> str:
    """Set .stignore patterns for a folder. Replaces all existing patterns.
    Requires SYNCTHING_WRITE_ENABLED=true and confirm=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    if not params.confirm:
        return fmt({"error": (
            "This REPLACES the folder's entire .stignore pattern set — "
            "existing patterns are lost and the change alters which files "
            "sync. Set confirm=true to proceed."
        )})
    try:
        client = get_instance(params.instance)
        await client._post(
            "/rest/db/ignores",
            params={"folder": params.folder_id},
            body={"ignore": params.patterns},
        )
        return fmt({
            "status": "updated",
            "folder": params.folder_id,
            "instance": client.name,
            "count": len(params.patterns),
        })
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_get_default_ignores",
    annotations={
        "title": "Get Default Ignore Patterns",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_get_default_ignores(params: ReadParams) -> str:
    """Default ignore patterns applied to newly created folders."""
    try:
        client = get_instance(params.instance)
        result = await client._get("/rest/config/defaults/ignores")
        return fmt({
            "instance": client.name,
            "lines": result.get("lines", []) or [],
        }, concise=params.concise)
    except Exception as e:
        return handle_error_global(e)


@mcp.tool(
    name="syncthing_set_default_ignores",
    annotations={
        "title": "Set Default Ignore Patterns",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def syncthing_set_default_ignores(params: SetDefaultIgnoresInput) -> str:
    """Set the default ignore patterns for newly created folders.
    Requires SYNCTHING_WRITE_ENABLED=true."""
    gate = require_write()
    if gate:
        return fmt({"error": gate})
    try:
        client = get_instance(params.instance)
        await client._put(
            "/rest/config/defaults/ignores",
            body={"lines": params.lines},
        )
        return fmt({
            "status": "updated",
            "instance": client.name,
            "count": len(params.lines),
        })
    except Exception as e:
        return handle_error_global(e)
