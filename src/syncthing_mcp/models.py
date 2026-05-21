"""Pydantic input models for Syncthing MCP tools."""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
#  DD-278 scope-tag vocabulary (Phase A.1 — Track 1)
# ---------------------------------------------------------------------------

_VALID_SCOPES = frozenset({"work", "personal", "family", "home", "infrastructure"})

_log = logging.getLogger(__name__)


def _resolve_scope_folders(
    scope: str | None,
    instance: str | None,
) -> tuple[set[str] | None, list[str]]:
    """Resolve a DD-278 scope value to a Syncthing folder-ID set.

    Returns ``(folder_id_set, redactions)``. ``folder_id_set is None`` means
    no scope filter applies (caller iterates the full set). An empty set
    means filter matches no folders (caller returns empty result). The
    ``redactions`` list documents degradations for the ``_meta`` envelope.

    Env-var lookup order (per-instance variant takes precedence):

    1. ``SYNCTHING_<SCOPE>_FOLDERS_<INSTANCE>`` (when ``instance`` is set)
    2. ``SYNCTHING_<SCOPE>_FOLDERS``

    ``scope=public`` raises ``ValueError`` (folders cannot be public in
    Syncthing's model). ``scope=None`` returns ``(None, [])`` — back-compat.
    """
    if scope is None:
        return None, []
    if scope == "public":
        raise ValueError("scope=public is not applicable to Syncthing folders")
    if scope not in _VALID_SCOPES:
        _log.warning("scope=%r not in DD-278 vocabulary; treating as unconfigured", scope)
        return None, [f"scope={scope}_unconfigured"]

    scope_upper = scope.upper()
    raw: str | None = None
    if instance:
        raw = os.environ.get(f"SYNCTHING_{scope_upper}_FOLDERS_{instance.upper()}")
    if raw is None:
        raw = os.environ.get(f"SYNCTHING_{scope_upper}_FOLDERS")
    if raw is None:
        return None, [f"scope={scope}_unconfigured"]

    folder_ids = {fid.strip() for fid in raw.split(",") if fid.strip()}
    return folder_ids, []


# ---------------------------------------------------------------------------
#  Read-oriented base models (include concise toggle for token efficiency)
# ---------------------------------------------------------------------------


class ReadParams(BaseModel):
    """Base for read-only tools — includes output-format flag."""

    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )
    concise: bool = Field(
        True,
        description="Compact output (default). Set false for full details.",
    )
    scope: str | None = Field(
        None,
        description=(
            "DD-278 scope filter — work|personal|family|home|infrastructure. "
            "Resolved to a Syncthing folder-ID set via env var "
            "SYNCTHING_<SCOPE>_FOLDERS (comma-separated) with per-instance "
            "override SYNCTHING_<SCOPE>_FOLDERS_<INSTANCE>. Omit for no filter."
        ),
    )


class FolderReadParams(ReadParams):
    """Read tool that targets a single folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID (e.g. 'abcd-1234')", min_length=1
    )


class DeviceReadParams(ReadParams):
    """Read tool that targets a single device."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ...,
        description="Syncthing device ID (long alphanumeric string with dashes)",
        min_length=1,
    )


class FolderDeviceReadParams(ReadParams):
    """Read tool targeting a folder + device pair."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Syncthing device ID", min_length=1)


# ---------------------------------------------------------------------------
#  Write-oriented models (no concise flag — output is always minimal)
# ---------------------------------------------------------------------------


class WriteParams(BaseModel):
    """Base for write/mutating tools."""

    model_config = ConfigDict(extra="forbid")
    instance: str | None = Field(
        None, description="Instance name. Omit if only one instance is configured."
    )


class FolderWriteParams(WriteParams):
    """Write tool that targets a single folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Syncthing folder ID", min_length=1
    )


class DeviceWriteParams(WriteParams):
    """Write tool that targets a single device."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Syncthing device ID", min_length=1
    )


# ---------------------------------------------------------------------------
#  Specialised input models
# ---------------------------------------------------------------------------


class AcceptDeviceInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    device_id: str = Field(
        ..., description="Device ID to accept (from pending list)", min_length=1
    )
    name: str | None = Field(
        None,
        description="Friendly name to assign. If omitted, uses the name from the pending request.",
    )


class AcceptFolderInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to accept (from pending list)", min_length=1
    )
    path: str | None = Field(
        None,
        description="Local path for the folder. If omitted, uses Syncthing's default path.",
    )


class RejectFolderInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(
        ..., description="Folder ID to reject", min_length=1
    )
    device_id: str | None = Field(
        None,
        description="Device ID that offered the folder. If omitted, rejects from all devices.",
    )


class SetIgnoresInput(WriteParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Folder ID", min_length=1)
    patterns: list[str] = Field(
        ...,
        description="List of ignore patterns (e.g. ['*.tmp', '.DS_Store', '// #include'])",
    )


class SetDefaultIgnoresInput(WriteParams):
    model_config = ConfigDict(extra="forbid")
    lines: list[str] = Field(
        ...,
        description="Default ignore patterns for new folders (e.g. ['.DS_Store', 'Thumbs.db'])",
    )


# ---------------------------------------------------------------------------
#  File-level query models
# ---------------------------------------------------------------------------


class BrowseFolderInput(ReadParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    prefix: str | None = Field(
        None,
        description="Path prefix to browse (e.g. 'Documents/reports'). Omit for root.",
    )
    levels: int | None = Field(
        None,
        description="How many directory levels deep to return (default: 1).",
        ge=0,
    )


class FileInfoInput(ReadParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    file_path: str = Field(
        ..., description="Relative path of the file within the folder", min_length=1
    )


class FolderNeedInput(ReadParams):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    page: int = Field(1, description="Page number (1-based)", ge=1)
    per_page: int = Field(50, description="Items per page", ge=1, le=500)


class RemoteNeedInput(ReadParams):
    """Query files a remote device still needs for a folder."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    folder_id: str = Field(..., description="Syncthing folder ID", min_length=1)
    device_id: str = Field(..., description="Remote device ID", min_length=1)
    page: int = Field(1, description="Page number (1-based)", ge=1)
    per_page: int = Field(50, description="Items per page", ge=1, le=500)


# ---------------------------------------------------------------------------
#  Backward-compatible aliases (referenced by existing tests)
# ---------------------------------------------------------------------------

EmptyInput = ReadParams
FolderInput = FolderReadParams
DeviceInput = DeviceReadParams
PauseFolderInput = FolderWriteParams
FolderDeviceInput = FolderDeviceReadParams
