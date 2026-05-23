"""Tests for folder tools (status, completion, replication, operations, new tools)."""

import json

import pytest
import respx

from syncthing_mcp.models import (
    BrowseFolderInput,
    EmptyInput,
    FileInfoInput,
    FolderInput,
    FolderNeedInput,
    FolderReadParams,
    PauseFolderInput,
    ReadParams,
    RemoteNeedInput,
)
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    FOLDER_ID,
    make_completion,
    make_config,
    make_connections,
    make_db_status,
    make_stats_folder,
    make_system_status,
    split_meta,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestFolderStatus:
    async def test_returns_status(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        payload, _meta = split_meta(
            await syncthing_folder_status(FolderInput(folder_id=FOLDER_ID))
        )
        result = json.loads(payload)
        assert result["folder"] == FOLDER_ID
        assert result["state"] == "idle"
        assert result["globalSize"] is not None

    # DD-338 Phase A.1 — Track 3 — _meta baseline
    async def test_meta_envelope_no_scope_baseline(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        _payload, meta = split_meta(
            await syncthing_folder_status(FolderInput(folder_id=FOLDER_ID))
        )
        assert meta["matched_total"] == 1
        assert meta["returned"] == 1
        assert meta["filtered_by"] == [f"folder={FOLDER_ID}"]
        assert meta["redactions"] == []

    # DD-338 Phase A.1 — Track 1 — scope membership match
    async def test_scope_membership_match(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", FOLDER_ID)
        payload, meta = split_meta(
            await syncthing_folder_status(
                FolderReadParams(folder_id=FOLDER_ID, scope="work")
            )
        )
        result = json.loads(payload)
        assert result["folder"] == FOLDER_ID
        # filtered_by is sorted alphabetically by meta_envelope
        assert sorted(meta["filtered_by"]) == [f"folder={FOLDER_ID}", "scope=work"]
        assert meta["matched_total"] == 1
        assert meta["returned"] == 1

    # DD-338 Phase A.1 — Track 1 — scope membership mismatch refuses
    async def test_scope_membership_mismatch_refuses(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "some-other-folder")
        payload, meta = split_meta(
            await syncthing_folder_status(
                FolderReadParams(folder_id=FOLDER_ID, scope="work")
            )
        )
        result = json.loads(payload)
        assert "error" in result
        assert "folder_outside_scope" in meta["redactions"]
        assert meta["matched_total"] == 0
        assert meta["returned"] == 0

    # DD-338 Phase A.1 — Track 1 — unconfigured scope passes through
    async def test_scope_unconfigured_passthrough(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS", raising=False)
        payload, meta = split_meta(
            await syncthing_folder_status(
                FolderReadParams(folder_id=FOLDER_ID, scope="work")
            )
        )
        result = json.loads(payload)
        assert result["folder"] == FOLDER_ID  # pass-through, not refused
        assert "scope=work_unconfigured" in meta["redactions"]

    # DD-338 Phase A.1 — Track 2 — deterministic N=5
    async def test_deterministic_n5(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_status

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        results = []
        for _ in range(5):
            out = await syncthing_folder_status(FolderInput(folder_id=FOLDER_ID))
            payload, meta = split_meta(out)
            meta.pop("latency_ms")
            results.append((payload, json.dumps(meta, sort_keys=True)))
        first = results[0]
        for r in results[1:]:
            assert r == first


class TestFolderCompletion:
    async def test_fully_replicated(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id=FOLDER_ID)))
        assert result["fullyReplicated"] == 1
        assert result["devices"][0]["completion"] == 100.0

    async def test_partially_replicated(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(75.0, "unknown"))
        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id=FOLDER_ID)))
        assert result["fullyReplicated"] == 0

    async def test_folder_not_found(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_completion

        result = json.loads(await syncthing_folder_completion(FolderInput(folder_id="nonexistent")))
        assert "error" in result


class TestReplicationReport:
    async def test_safe_to_remove(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        payload, _meta = split_meta(await syncthing_replication_report(EmptyInput()))
        result = json.loads(payload)
        assert result["summary"]["safe"] == 1
        assert result["folders"][0]["safe"] is True

    async def test_not_safe_when_incomplete(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(50.0))
        payload, _meta = split_meta(await syncthing_replication_report(EmptyInput()))
        result = json.loads(payload)
        assert result["summary"]["safe"] == 0

    # DD-338 Phase A.1 — Track 3 — _meta baseline
    async def test_meta_envelope_no_scope_baseline(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        _payload, meta = split_meta(await syncthing_replication_report(EmptyInput()))
        assert meta["matched_total"] == 1
        assert meta["returned"] == 1
        assert meta["filtered_by"] == []
        assert meta["redactions"] == []

    # DD-338 Phase A.1 — Track 1 — scope filters folder set
    async def test_scope_work_filters_folder_set(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        # 5 folders; SYNCTHING_WORK_FOLDERS=fld1,fld3 → expect 2 returned.
        cfg = {
            "folders": [
                {"id": f"fld{i}", "label": f"f{i}", "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ]}
                for i in range(1, 6)
            ],
            "devices": [
                {"deviceID": DEVICE_ID_LOCAL, "name": "local"},
                {"deviceID": DEVICE_ID_REMOTE, "name": "remote"},
            ],
        }
        mock_api.get("/rest/config").respond(json=cfg)
        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1,fld3")

        payload, meta = split_meta(
            await syncthing_replication_report(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        ids = sorted(f["id"] for f in result["folders"])
        assert ids == ["fld1", "fld3"]
        assert meta["matched_total"] == 5
        assert meta["returned"] == 2
        assert meta["filtered_by"] == ["scope=work"]

    # DD-338 Phase A.1 — Track 1 — unconfigured scope redacts but passes through
    async def test_scope_unconfigured_redacts(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS", raising=False)
        payload, meta = split_meta(
            await syncthing_replication_report(ReadParams(scope="work"))
        )
        result = json.loads(payload)
        assert len(result["folders"]) == 1  # unfiltered fallthrough
        assert meta["redactions"] == ["scope=work_unconfigured"]

    # DD-338 Phase A.1 — Track 1 — scope=public raises through error path
    async def test_scope_public_raises(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        out = await syncthing_replication_report(ReadParams(scope="public"))
        assert out.startswith("Error:")
        assert "public" in out

    # DD-338 Phase A.1 — Track 2 — deterministic N=5 with tie-breaker fixture
    async def test_deterministic_n5_with_tiebreaker(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_replication_report

        # Two folders with identical localBytes → id tie-breaker must apply.
        cfg = {
            "folders": [
                {"id": "z-folder", "label": "z", "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ]},
                {"id": "a-folder", "label": "a", "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ]},
            ],
            "devices": [
                {"deviceID": DEVICE_ID_LOCAL, "name": "local"},
                {"deviceID": DEVICE_ID_REMOTE, "name": "remote"},
            ],
        }
        mock_api.get("/rest/config").respond(json=cfg)
        mock_api.get("/rest/db/status").respond(json=make_db_status())
        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))

        results = []
        for _ in range(5):
            out = await syncthing_replication_report(EmptyInput())
            payload, meta = split_meta(out)
            meta.pop("latency_ms")
            results.append((payload, json.dumps(meta, sort_keys=True)))
        first = results[0]
        for r in results[1:]:
            assert r == first
        # Tie-breaker by id ascending; a-folder before z-folder
        result = json.loads(first[0])
        ids = [f["id"] for f in result["folders"]]
        assert ids == ["a-folder", "z-folder"]


class TestPauseFolder:
    async def test_pause(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_pause_folder

        mock_api.get(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": False}
        )
        mock_api.patch(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": True},
            headers={"content-type": "application/json"},
        )
        result = json.loads(await syncthing_pause_folder(PauseFolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "paused"


class TestResumeFolder:
    async def test_resume(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_resume_folder

        mock_api.get(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "type": "sendreceive", "paused": True}
        )
        mock_api.patch(f"/rest/config/folders/{FOLDER_ID}").respond(
            json={"id": FOLDER_ID, "paused": False},
            headers={"content-type": "application/json"},
        )
        result = json.loads(await syncthing_resume_folder(PauseFolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "resumed"
        assert result["type"] == "sendreceive"


class TestScanFolder:
    async def test_scan(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_scan_folder

        mock_api.post("/rest/db/scan").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_scan_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "scan_requested"


class TestFolderErrors:
    async def test_no_errors(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_errors

        mock_api.get("/rest/folder/errors").respond(json={"errors": None, "page": 1})
        payload, _meta = split_meta(
            await syncthing_folder_errors(FolderInput(folder_id=FOLDER_ID))
        )
        result = json.loads(payload)
        assert result["count"] == 0

    # DD-338 Phase C Wave 2 — _meta shape
    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_errors

        mock_api.get("/rest/folder/errors").respond(json={"errors": None, "page": 1})
        _payload, meta = split_meta(
            await syncthing_folder_errors(FolderInput(folder_id=FOLDER_ID))
        )
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["filtered_by"], list)
        assert isinstance(meta["latency_ms"], int)
        assert meta["filtered_by"] == [f"folder={FOLDER_ID}"]

    # DD-338 Phase C Wave 2 — scope membership match
    async def test_scope_membership_match(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_folder_errors

        mock_api.get("/rest/folder/errors").respond(json={"errors": [], "page": 1})
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", FOLDER_ID)
        payload, meta = split_meta(
            await syncthing_folder_errors(
                FolderReadParams(folder_id=FOLDER_ID, scope="work")
            )
        )
        result = json.loads(payload)
        assert result["count"] == 0
        assert sorted(meta["filtered_by"]) == [f"folder={FOLDER_ID}", "scope=work"]

    # DD-338 Phase C Wave 2 — scope membership mismatch refuses
    async def test_scope_membership_mismatch_refuses(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.folders import syncthing_folder_errors

        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "some-other-folder")
        payload, meta = split_meta(
            await syncthing_folder_errors(
                FolderReadParams(folder_id=FOLDER_ID, scope="work")
            )
        )
        result = json.loads(payload)
        assert "error" in result
        assert "folder_outside_scope" in meta["redactions"]
        assert meta["matched_total"] == 0
        assert meta["returned"] == 0


class TestBrowseFolder:
    async def test_browse_root(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        mock_api.get("/rest/db/browse").respond(json=[
            {"name": "docs", "type": "directory"},
            {"name": "readme.txt", "type": "file"},
        ])
        payload, _meta = split_meta(
            await syncthing_browse_folder(BrowseFolderInput(folder_id=FOLDER_ID))
        )
        result = json.loads(payload)
        assert result["folder"] == FOLDER_ID
        assert len(result["entries"]) == 2

    async def test_browse_with_prefix(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        mock_api.get("/rest/db/browse").respond(json=[])
        payload, _meta = split_meta(
            await syncthing_browse_folder(
                BrowseFolderInput(folder_id=FOLDER_ID, prefix="docs", levels=2)
            )
        )
        result = json.loads(payload)
        assert result["prefix"] == "docs"

    # DD-338 Phase C Wave 2 — _meta shape
    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        mock_api.get("/rest/db/browse").respond(json=[
            {"name": "docs", "type": "directory"},
            {"name": "readme.txt", "type": "file"},
            {"name": "notes.md", "type": "file"},
        ])
        _payload, meta = split_meta(
            await syncthing_browse_folder(BrowseFolderInput(folder_id=FOLDER_ID))
        )
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["filtered_by"], list)
        assert isinstance(meta["latency_ms"], int)
        assert meta["returned"] == 3

    # DD-338 Phase C Wave 2 — filtered_by content with prefix + levels
    async def test_filtered_by_includes_prefix_and_levels(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_browse_folder

        mock_api.get("/rest/db/browse").respond(json=[])
        _payload, meta = split_meta(
            await syncthing_browse_folder(
                BrowseFolderInput(folder_id=FOLDER_ID, prefix="docs", levels=2)
            )
        )
        # filtered_by is sorted alphabetically by meta_envelope
        assert sorted(meta["filtered_by"]) == [
            f"folder={FOLDER_ID}",
            "levels=2",
            "prefix=docs",
        ]


class TestFileInfo:
    async def test_file_info(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_file_info

        mock_api.get("/rest/db/file").respond(json={
            "availability": [{"id": DEVICE_ID_REMOTE}],
            "global": {"name": "test.txt", "size": 1024, "modified": "2025-01-01T00:00:00Z"},
            "local": {"name": "test.txt", "size": 1024},
        })
        result = json.loads(await syncthing_file_info(
            FileInfoInput(folder_id=FOLDER_ID, file_path="test.txt")
        ))
        assert result["file"] == "test.txt"
        # Concise mode returns globalSize at top level
        assert result["globalSize"] == "1.0 KB"


class TestFolderNeed:
    async def test_need_empty(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_need

        mock_api.get("/rest/db/need").respond(json={
            "page": 1, "perpage": 50,
            "progress": [], "queued": [], "rest": [],
        })
        payload, _meta = split_meta(
            await syncthing_folder_need(FolderNeedInput(folder_id=FOLDER_ID))
        )
        result = json.loads(payload)
        assert result["progress"] == []
        assert result["queued"] == []

    # DD-338 Phase C Wave 2 — _meta shape
    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_need

        mock_api.get("/rest/db/need").respond(json={
            "page": 2, "perpage": 25,
            "progress": [{"name": "a"}],
            "queued": [{"name": "b"}, {"name": "c"}],
            "rest": [],
        })
        _payload, meta = split_meta(
            await syncthing_folder_need(
                FolderNeedInput(folder_id=FOLDER_ID, page=2, per_page=25)
            )
        )
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["latency_ms"], int)
        assert meta["returned"] == 3
        # next_cursor must NOT be present per OQ-4 (v1)
        assert "next_cursor" not in meta

    # DD-338 Phase C Wave 2 — filtered_by content
    async def test_filtered_by_contains_pagination(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_folder_need

        mock_api.get("/rest/db/need").respond(json={
            "page": 3, "perpage": 100,
            "progress": [], "queued": [], "rest": [],
        })
        _payload, meta = split_meta(
            await syncthing_folder_need(
                FolderNeedInput(folder_id=FOLDER_ID, page=3, per_page=100)
            )
        )
        assert sorted(meta["filtered_by"]) == [
            f"folder={FOLDER_ID}",
            "page=3",
            "perpage=100",
        ]


class TestRemoteNeed:
    async def test_remote_need_empty(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_remote_need

        mock_api.get("/rest/db/remoteneed").respond(json={
            "page": 1, "perpage": 50,
            "progress": [], "queued": [], "rest": [],
        })
        payload, _meta = split_meta(
            await syncthing_remote_need(
                RemoteNeedInput(folder_id=FOLDER_ID, device_id=DEVICE_ID_REMOTE)
            )
        )
        result = json.loads(payload)
        assert result["progress"] == []

    # DD-338 Phase C Wave 2 — _meta shape
    async def test_meta_envelope_shape(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_remote_need

        mock_api.get("/rest/db/remoteneed").respond(json={
            "page": 1, "perpage": 50,
            "progress": [{"n": 1}],
            "queued": [],
            "rest": [{"n": 2}, {"n": 3}],
        })
        _payload, meta = split_meta(
            await syncthing_remote_need(
                RemoteNeedInput(folder_id=FOLDER_ID, device_id=DEVICE_ID_REMOTE)
            )
        )
        assert isinstance(meta["matched_total"], int)
        assert isinstance(meta["returned"], int)
        assert isinstance(meta["latency_ms"], int)
        assert meta["returned"] == 3
        assert "next_cursor" not in meta

    # DD-338 Phase C Wave 2 — filtered_by content
    async def test_filtered_by_contains_device_and_pagination(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_remote_need

        mock_api.get("/rest/db/remoteneed").respond(json={
            "page": 1, "perpage": 50,
            "progress": [], "queued": [], "rest": [],
        })
        _payload, meta = split_meta(
            await syncthing_remote_need(
                RemoteNeedInput(folder_id=FOLDER_ID, device_id=DEVICE_ID_REMOTE)
            )
        )
        assert sorted(meta["filtered_by"]) == [
            f"device={DEVICE_ID_REMOTE}",
            f"folder={FOLDER_ID}",
            "page=1",
            "perpage=50",
        ]


class TestOverrideFolder:
    async def test_override(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_override_folder

        mock_api.post("/rest/db/override").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_override_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "override_requested"


class TestRevertFolder:
    async def test_revert(self, mock_api):
        from syncthing_mcp.tools.folders import syncthing_revert_folder

        mock_api.post("/rest/db/revert").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_revert_folder(FolderInput(folder_id=FOLDER_ID)))
        assert result["status"] == "revert_requested"
