"""Tests for DD-338 Phase A.2 cat-B scope= promotions.

Covers:
- ``syncthing_list_folders`` — scope filter over ``config.folders`` via the
  A.1 ``_resolve_scope_folders`` substrate.
- ``syncthing_recent_changes`` — scope filter over the event stream's
  ``data.folderID`` key.

Each tool gets ≥6 cases per the spec:
  1. happy-path scope filter
  2. env-unset redaction passthrough
  3. unknown scope passthrough with redaction
  4. scope=None back-compat baseline
  5. scope=public raises through error path
  6. _meta envelope shape check
Plus a determinism harness (N=5 byte-equal) for each.
"""

import json

import pytest
import respx

from syncthing_mcp.models import ReadParams
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    FOLDER_ID,
    make_completion,
    make_connections,
    make_db_status,
    make_stats_device,
    make_stats_folder,
    make_system_status,
    make_version,
    split_meta,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


def _multi_folder_config() -> dict:
    """Config with 5 folders, used for filter assertions."""
    return {
        "folders": [
            {
                "id": f"fld{i}",
                "label": f"f{i}",
                "path": f"/data/f{i}",
                "type": "sendreceive",
                "paused": False,
                "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ],
            }
            for i in range(1, 6)
        ],
        "devices": [
            {"deviceID": DEVICE_ID_LOCAL, "name": "local"},
            {"deviceID": DEVICE_ID_REMOTE, "name": "remote"},
        ],
    }


# ---------------------------------------------------------------------------
# syncthing_list_folders cat-B promotion
# ---------------------------------------------------------------------------


class TestListFoldersScope:
    async def test_scope_work_filters(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1,fld3")

        payload, meta = split_meta(
            await syncthing_list_folders(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        ids = sorted(f["id"] for f in result)
        assert ids == ["fld1", "fld3"]
        assert meta["matched_total"] == 5
        assert meta["returned"] == 2
        assert meta["filtered_by"] == ["scope=work"]
        assert meta["redactions"] == []

    async def test_scope_unconfigured_redacts(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS", raising=False)

        payload, meta = split_meta(
            await syncthing_list_folders(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        # Unconfigured fallthrough — all 5 folders returned
        assert len(result) == 5
        assert meta["matched_total"] == 5
        assert meta["returned"] == 5
        assert meta["filtered_by"] == []
        assert meta["redactions"] == ["scope=work_unconfigured"]

    async def test_unknown_scope_redacts(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        payload, meta = split_meta(
            await syncthing_list_folders(ReadParams(scope="garbage"))
        )
        result = json.loads(payload)
        assert len(result) == 5
        assert meta["redactions"] == ["scope=garbage_unconfigured"]
        assert meta["filtered_by"] == []

    async def test_scope_none_baseline(self, mock_api):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        payload, meta = split_meta(
            await syncthing_list_folders(ReadParams())
        )
        result = json.loads(payload)
        assert len(result) == 5
        assert meta["matched_total"] == 5
        assert meta["returned"] == 5
        assert meta["filtered_by"] == []
        assert meta["redactions"] == []

    async def test_scope_public_raises(self, mock_api):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        out = await syncthing_list_folders(ReadParams(scope="public"))
        assert out.startswith("Error:")
        assert "public" in out

    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        _payload, meta = split_meta(
            await syncthing_list_folders(ReadParams())
        )
        # Required keys per A.1 envelope contract
        assert set(meta.keys()) >= {
            "matched_total",
            "returned",
            "filtered_by",
            "redactions",
            "latency_ms",
        }
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["filtered_by"], list)
        assert isinstance(meta["redactions"], list)
        assert isinstance(meta["latency_ms"], int)

    async def test_deterministic_n5(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.instances import syncthing_list_folders

        mock_api.get("/rest/config").respond(json=_multi_folder_config())
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1,fld3")

        results = []
        for _ in range(5):
            out = await syncthing_list_folders(ReadParams(scope="work"))
            payload, meta = split_meta(out)
            meta.pop("latency_ms")
            results.append((payload, json.dumps(meta, sort_keys=True)))
        first = results[0]
        for r in results[1:]:
            assert r == first


# ---------------------------------------------------------------------------
# syncthing_recent_changes cat-B promotion
# ---------------------------------------------------------------------------


def _events_fixture() -> list[dict]:
    """5 ItemFinished-ish events across 4 folders + 1 with no folderID."""
    return [
        {
            "id": 1,
            "type": "LocalChangeDetected",
            "data": {"folderID": "fld1", "path": "a.txt", "action": "modified"},
        },
        {
            "id": 2,
            "type": "RemoteChangeDetected",
            "data": {"folderID": "fld2", "path": "b.txt", "action": "added"},
        },
        {
            "id": 3,
            "type": "LocalChangeDetected",
            "data": {"folderID": "fld3", "path": "c.txt", "action": "deleted"},
        },
        {
            "id": 4,
            "type": "RemoteChangeDetected",
            "data": {"folderID": "fld4", "path": "d.txt", "action": "modified"},
        },
        {
            "id": 5,
            "type": "LocalChangeDetected",
            "data": {"path": "system.log"},  # no folderID
        },
    ]


class TestRecentChangesScope:
    async def test_scope_work_filters(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1,fld3")

        payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        assert result["count"] == 2
        folder_ids = sorted(e["folder"] for e in result["events"])
        assert folder_ids == ["fld1", "fld3"]
        assert meta["matched_total"] == 5
        assert meta["returned"] == 2
        assert meta["filtered_by"] == ["scope=work"]
        assert meta["redactions"] == []

    async def test_scope_unconfigured_redacts(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS", raising=False)

        payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        # Unconfigured fallthrough — all 5 events returned
        assert result["count"] == 5
        assert meta["matched_total"] == 5
        assert meta["returned"] == 5
        assert meta["filtered_by"] == []
        assert meta["redactions"] == ["scope=work_unconfigured"]

    async def test_unknown_scope_redacts(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams(scope="garbage"))
        )
        result = json.loads(payload)
        assert result["count"] == 5
        assert meta["redactions"] == ["scope=garbage_unconfigured"]
        assert meta["filtered_by"] == []

    async def test_scope_none_baseline(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams())
        )
        result = json.loads(payload)
        assert result["count"] == 5
        assert meta["matched_total"] == 5
        assert meta["returned"] == 5
        assert meta["filtered_by"] == []
        assert meta["redactions"] == []

    async def test_scope_public_raises(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        out = await syncthing_recent_changes(ReadParams(scope="public"))
        assert out.startswith("Error:")
        assert "public" in out

    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        _payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams())
        )
        assert set(meta.keys()) >= {
            "matched_total",
            "returned",
            "filtered_by",
            "redactions",
            "latency_ms",
        }
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["filtered_by"], list)
        assert isinstance(meta["redactions"], list)
        assert isinstance(meta["latency_ms"], int)

    async def test_no_folderid_filtered_out_under_scope(self, mock_api, monkeypatch):
        """Event #5 carries no ``folderID`` — under an active scope filter,
        it MUST drop out (system events do not partition by folder scope)."""
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        monkeypatch.setenv(
            "SYNCTHING_INFRASTRUCTURE_FOLDERS", "fld1,fld2,fld3,fld4"
        )
        payload, meta = split_meta(
            await syncthing_recent_changes(ReadParams(scope="infrastructure"))
        )
        result = json.loads(payload)
        # Event #5 (no folderID) dropped; fld1–fld4 kept = 4
        assert result["count"] == 4
        assert meta["matched_total"] == 5
        assert meta["returned"] == 4

    async def test_deterministic_n5(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=_events_fixture())
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1,fld3")

        results = []
        for _ in range(5):
            out = await syncthing_recent_changes(ReadParams(scope="work"))
            payload, meta = split_meta(out)
            meta.pop("latency_ms")
            results.append((payload, json.dumps(meta, sort_keys=True)))
        first = results[0]
        for r in results[1:]:
            assert r == first
