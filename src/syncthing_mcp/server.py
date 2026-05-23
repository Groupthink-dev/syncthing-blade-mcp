"""FastMCP server creation and lifespan."""

import os
from contextlib import asynccontextmanager
from typing import Any

from mcp.server.fastmcp import FastMCP
from starlette.requests import Request
from starlette.responses import JSONResponse

from syncthing_mcp.domain_hint import (
    Pattern,
    compute_domain_hint,
    load_patterns_from_yaml,
)
from syncthing_mcp.registry import get_all_instances


# ---------------------------------------------------------------------------
# DD-338 A.2.dom.c — BladeConfigStore reader + Syncthing field projector
# ---------------------------------------------------------------------------

_BLADE_ID = "syncthing-blade-mcp"


def _state_root() -> str:
    """Resolve Stallari state root.

    Honours ``STALLARI_STATE_ROOT`` env var (used in tests + non-standard
    deployments); falls back to the macOS Application Support default per
    Convention #27 / StallariPaths.
    """
    override = os.environ.get("STALLARI_STATE_ROOT")
    if override:
        return override
    return os.path.expanduser("~/Library/Application Support/Stallari")


def _sanitize_blade_id(blade_id: str) -> str:
    """Mirror the Swift writer's blade-id directory naming.

    Lower-case + ``/`` ⇒ ``_`` — kept in lockstep with BladeConfigStore.swift
    (Convention #23: reader and writer agree on the on-disk shape).
    """
    return blade_id.lower().replace("/", "_")


def _load_blade_config(blade_id: str) -> list[Pattern]:
    """Read this blade's domain_hint patterns from the BladeConfigStore.

    Convention #22 graceful degradation: missing / unreadable / malformed
    config returns ``[]`` — the blade still runs, simply without per-record
    ``domain_hints`` emission.

    Convention #23 reader-side compliance: resolves via state-root +
    ``blade-config/<sanitized-blade>/config.yaml`` in lockstep with the
    Swift writer's path layout.
    """
    config_path = os.path.join(
        _state_root(),
        "blade-config",
        _sanitize_blade_id(blade_id),
        "config.yaml",
    )
    try:
        with open(config_path, encoding="utf-8") as f:
            yaml_str = f.read()
    except OSError:
        return []
    return load_patterns_from_yaml(yaml_str)


# Cached at module load; re-launch the blade to pick up config edits at v1.
_PATTERNS: list[Pattern] = _load_blade_config(_BLADE_ID)


def _syncthing_field_projector(record: dict[str, Any], field: str) -> Any:
    """Project a Syncthing record (folder OR device) onto a logical field name.

    Polymorphic across the two record shapes this blade emits:

    Folder record shape::

        {"id": "...", "label": "...", "path": "...", "type": "sendreceive",
         "devices": [...], "paused": false}

    Device record shape::

        {"deviceID": "ABCD-...", "name": "host", "addresses": [...],
         "paused": false, "introducer": false}

    Field resolution is shape-agnostic: try folder-side keys first, fall
    through to device-side keys. Unknown field ⇒ ``None`` (no match).
    """
    if not isinstance(record, dict):
        return None
    f = field
    # Folder-shape fields
    if f in {"id", "label", "path", "type"}:
        v = record.get(f)
        return v if v is not None else None
    # Device-shape fields
    if f == "deviceID":
        return record.get("deviceID")
    if f == "name":
        return record.get("name")
    if f == "addresses":
        v = record.get("addresses")
        return v if isinstance(v, list) else None
    return None


def _record_id(record: dict[str, Any]) -> str | None:
    """Derive the stable per-record identifier.

    Folders use ``id``; devices use ``deviceID``. The catalog enforces 1:1
    record-id stability via ``deterministic_ordering=stable`` on the
    catalog-mirror tools[] entries.
    """
    if not isinstance(record, dict):
        return None
    rid = record.get("id")
    if isinstance(rid, str):
        return rid
    rid = record.get("deviceID")
    if isinstance(rid, str):
        return rid
    return None


def compute_domain_hints_for_records(
    records: list[dict[str, Any]],
) -> dict[str, str]:
    """Apply ``_PATTERNS`` to each record; return ``{record_id: domain}`` map.

    Records lacking a domain match are omitted. Empty pattern list ⇒ empty
    dict ⇒ caller suppresses the ``domain_hints`` envelope key.
    """
    if not _PATTERNS:
        return {}
    out: dict[str, str] = {}
    for rec in records:
        rid = _record_id(rec)
        if rid is None:
            continue
        hint = compute_domain_hint(rec, _PATTERNS, _syncthing_field_projector)
        if hint is not None:
            out[rid] = hint
    return out


@asynccontextmanager
async def app_lifespan(app):
    import sys

    instances = get_all_instances()
    missing = [n for n, c in instances.items() if not c.api_key]
    if missing:
        print(f"WARNING: API key missing for instance(s): {missing}", file=sys.stderr)
    print(
        f"Syncthing MCP: {len(instances)} instance(s) configured — "
        f"{list(instances.keys())}",
        file=sys.stderr,
    )
    yield {}


mcp = FastMCP(
    "syncthing_mcp",
    lifespan=app_lifespan,
    stateless_http=True,
    json_response=True,
)


@mcp.custom_route("/health", methods=["GET"])
async def health(request: Request) -> JSONResponse:
    """Unauthenticated health-check endpoint for Docker / Traefik probes."""
    return JSONResponse({"status": "ok"})


# Import all tool modules so they register with `mcp` via decorators.
import syncthing_mcp.tools  # noqa: E402, F401
