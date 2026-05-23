"""Token-efficient formatters for Syncthing API responses.

Design principles (following best-in-class MCP patterns):
  - Default output is compact JSON (no indentation, no spaces after separators)
  - Device IDs are truncated to short form unless full detail is requested
  - Redundant fields (both raw bytes AND human-readable size) are collapsed
  - Large responses are truncated with guidance to use pagination/filters
  - Summary modes return counts only, skipping per-item detail
"""

import json
import random
from typing import Any

# ---------------------------------------------------------------------------
#  Constants
# ---------------------------------------------------------------------------

CHARACTER_LIMIT = 25_000
SHORT_ID_LEN = 7


# ---------------------------------------------------------------------------
#  Core helpers
# ---------------------------------------------------------------------------


def fmt(data: Any, *, concise: bool = True) -> str:
    """Serialize to JSON.  Compact by default for token efficiency."""
    if concise:
        return json.dumps(data, separators=(",", ":"))
    return json.dumps(data, indent=2)


# ---------------------------------------------------------------------------
#  DD-338 Phase A.1 — Track 3 — _meta envelope (JSON tail block)
# ---------------------------------------------------------------------------
#
#  Architect amendment 2026-05-21 — canonical wire shape is JSON tail block,
#  not pipe-delimited. Single line appended after \n\n. Assembler regex:
#      \n\n_meta: (\{.*\})$
#  Required fields: matched_total, returned, filtered_by, latency_ms.
#  Optional: redactions, next_cursor, error_notes.
#  filtered_by is sorted alphabetically for hash reproducibility.
# ---------------------------------------------------------------------------


def meta_envelope(
    *,
    matched_total: int,
    returned: int,
    filtered_by: list[str] | None = None,
    redactions: list[str] | None = None,
    latency_ms: int,
    domain_hints: dict[str, str] | None = None,
) -> str:
    """Render the canonical JSON-tail _meta envelope line.

    Returns the literal line ``_meta: {"matched_total": ..., ...}`` — caller
    is responsible for joining it to the payload with ``\\n\\n``.

    DD-338 A.2.dom.c — when ``domain_hints`` is non-empty, an additional
    ``domain_hints: {record_id: domain}`` entry is emitted. Empty / None ⇒
    key omitted entirely (Convention #22 graceful degradation).
    """
    fb = sorted(filtered_by) if filtered_by else []
    rd = list(redactions) if redactions else []
    payload: dict[str, Any] = {
        "matched_total": matched_total,
        "returned": returned,
        "filtered_by": fb,
        "redactions": rd,
        "latency_ms": latency_ms,
    }
    if domain_hints:
        payload["domain_hints"] = domain_hints
    return "_meta: " + json.dumps(payload, separators=(",", ":"))


def append_meta(
    payload: str,
    *,
    matched_total: int,
    returned: int,
    filtered_by: list[str] | None = None,
    redactions: list[str] | None = None,
    latency_ms: int,
    domain_hints: dict[str, str] | None = None,
) -> str:
    """Append the _meta envelope tail line to a serialized payload."""
    return payload + "\n\n" + meta_envelope(
        matched_total=matched_total,
        returned=returned,
        filtered_by=filtered_by,
        redactions=redactions,
        latency_ms=latency_ms,
        domain_hints=domain_hints,
    )


def short_id(device_id: str) -> str:
    """Truncate a Syncthing device ID to its first block."""
    return device_id[:SHORT_ID_LEN] if device_id else ""


def format_bytes(n: int | float) -> str:
    """Human-readable byte size."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(n) < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


def truncate(text: str, limit: int = CHARACTER_LIMIT) -> str:
    """Truncate text that exceeds the character limit, with guidance."""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_nl = cut.rfind("\n")
    if last_nl > limit * 0.8:
        cut = cut[:last_nl]
    return (
        cut
        + f"\n... truncated ({len(text):,} chars, limit {limit:,})."
        " Use pagination or filters to narrow results."
    )


def sample(items: list, size: int = 5) -> list:
    """Return a random sample from a list without replacement."""
    if len(items) <= size:
        return items
    return random.sample(items, size)


# ---------------------------------------------------------------------------
#  Entity formatters — concise mode strips to essential fields only
# ---------------------------------------------------------------------------


def format_folder(cfg: dict, *, concise: bool = True) -> dict:
    """Format a folder config entry."""
    if concise:
        return {
            "id": cfg["id"],
            "label": cfg.get("label", cfg["id"]),
            "type": cfg.get("type", "sendreceive"),
            "paused": cfg.get("paused", False),
            "devices": len(cfg.get("devices", [])),
        }
    devices = []
    for d in cfg.get("devices", []):
        did = d.get("deviceID", "")
        devices.append(did)
    return {
        "id": cfg["id"],
        "label": cfg.get("label", cfg["id"]),
        "path": cfg.get("path", ""),
        "type": cfg.get("type", "sendreceive"),
        "paused": cfg.get("paused", False),
        "devices": devices,
    }


def format_device(
    dev: dict,
    conn: dict | None = None,
    stat: dict | None = None,
    *,
    concise: bool = True,
) -> dict:
    """Format a device config + connection entry."""
    did = dev["deviceID"]
    conn = conn or {}
    stat = stat or {}
    if concise:
        return {
            "id": short_id(did),
            "name": dev.get("name", short_id(did)),
            "connected": conn.get("connected", False),
            "address": conn.get("address", ""),
        }
    return {
        "deviceID": did,
        "name": dev.get("name", short_id(did)),
        "connected": conn.get("connected", False),
        "paused": conn.get("paused", False),
        "address": conn.get("address", ""),
        "type": conn.get("type", ""),
        "crypto": conn.get("crypto", ""),
        "inBytesTotal": conn.get("inBytesTotal", 0),
        "outBytesTotal": conn.get("outBytesTotal", 0),
        "lastSeen": stat.get("lastSeen", ""),
    }


def format_folder_status(status: dict, *, concise: bool = True) -> dict:
    """Format a /rest/db/status response."""
    if concise:
        return {
            "state": status.get("state"),
            "globalFiles": status.get("globalFiles"),
            "globalSize": format_bytes(status.get("globalBytes", 0)),
            "localFiles": status.get("localFiles"),
            "localSize": format_bytes(status.get("localBytes", 0)),
            "needFiles": status.get("needFiles"),
            "needSize": format_bytes(status.get("needBytes", 0)),
        }
    return {
        "state": status.get("state"),
        "stateChanged": status.get("stateChanged"),
        "globalFiles": status.get("globalFiles"),
        "globalBytes": status.get("globalBytes"),
        "globalSize": format_bytes(status.get("globalBytes", 0)),
        "localFiles": status.get("localFiles"),
        "localBytes": status.get("localBytes"),
        "localSize": format_bytes(status.get("localBytes", 0)),
        "needFiles": status.get("needFiles"),
        "needBytes": status.get("needBytes"),
        "needSize": format_bytes(status.get("needBytes", 0)),
        "inSyncFiles": status.get("inSyncFiles"),
        "inSyncBytes": status.get("inSyncBytes"),
        "globalDeleted": status.get("globalDeleted"),
        "localDeleted": status.get("localDeleted"),
        "ignorePatterns": status.get("ignorePatterns"),
    }


def format_completion(
    comp: dict,
    device_name: str = "",
    *,
    connected: bool = False,
    concise: bool = True,
) -> dict:
    """Format a /rest/db/completion response for a single device."""
    if concise:
        return {
            "device": device_name or short_id(comp.get("deviceID", "")),
            "connected": connected,
            "completion": round(comp.get("completion", 0), 2),
            "needSize": format_bytes(comp.get("needBytes", 0)),
            "remoteState": comp.get("remoteState", "unknown"),
        }
    return {
        "device": device_name,
        "connected": connected,
        "completion": round(comp.get("completion", 0), 2),
        "globalBytes": comp.get("globalBytes", 0),
        "globalSize": format_bytes(comp.get("globalBytes", 0)),
        "needBytes": comp.get("needBytes", 0),
        "needSize": format_bytes(comp.get("needBytes", 0)),
        "needItems": comp.get("needItems", 0),
        "needDeletes": comp.get("needDeletes", 0),
        "remoteState": comp.get("remoteState", "unknown"),
    }


def format_connection(did: str, conn: dict, name: str = "", *, concise: bool = True) -> dict:
    """Format a single connection entry."""
    if concise:
        return {
            "device": name or short_id(did),
            "connected": conn.get("connected", False),
            "address": conn.get("address", ""),
            "type": conn.get("type", ""),
        }
    return {
        "deviceID": did,
        "deviceName": name or short_id(did),
        "connected": conn.get("connected", False),
        "paused": conn.get("paused", False),
        "address": conn.get("address", ""),
        "type": conn.get("type", ""),
        "crypto": conn.get("crypto", ""),
        "inBytesTotal": conn.get("inBytesTotal", 0),
        "outBytesTotal": conn.get("outBytesTotal", 0),
    }


# ---------------------------------------------------------------------------
#  Replication helpers
# ---------------------------------------------------------------------------


def format_replication_entry(
    folder_cfg: dict,
    status: dict,
    device_completions: list[dict],
    *,
    concise: bool = True,
) -> dict:
    """Format a single folder's replication data for the replication report."""
    fid = folder_cfg["id"]
    label = folder_cfg.get("label", fid)
    local_bytes = status.get("localBytes", 0)
    state = status.get("state", "unknown")
    paused = folder_cfg.get("paused", False)

    fully_replicated = [
        d for d in device_completions
        if d.get("completion") == 100 and d.get("remoteState") == "valid"
    ]
    safe = len(fully_replicated) >= 1 and state == "idle" and not paused

    if concise:
        return {
            "id": fid,
            "label": label,
            "safe": safe,
            "local": format_bytes(local_bytes),
            "state": state,
            "replicated": len(fully_replicated),
            "totalDevices": len(device_completions),
        }
    return {
        "id": fid,
        "label": label,
        "path": folder_cfg.get("path", ""),
        "type": folder_cfg.get("type", "sendreceive"),
        "paused": paused,
        "state": state,
        "localBytes": local_bytes,
        "localSize": format_bytes(local_bytes),
        "globalSize": format_bytes(status.get("globalBytes", 0)),
        "safeToRemove": safe,
        "fullyReplicatedOn": len(fully_replicated),
        "totalRemoteDevices": len(device_completions),
        "devices": device_completions,
    }
