"""Tests for device tools (list, completion, connections, stats)."""

import json

import pytest

from syncthing_mcp.models import DeviceInput, EmptyInput, ReadParams
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    DEVICE_ID_REMOTE2,
    FOLDER_ID,
    make_completion,
    make_config,
    make_connections,
    make_stats_device,
    split_meta,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestListDevices:
    async def test_returns_devices(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        payload, _meta = split_meta(await syncthing_list_devices(EmptyInput()))
        result = json.loads(payload)
        assert len(result) == 2
        names = {d["name"] for d in result}
        assert "local-dev" in names
        assert "remote-dev" in names

    # DD-338 Phase A.1 — Track 3 — _meta envelope baseline
    async def test_meta_envelope_no_scope_baseline(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        _payload, meta = split_meta(await syncthing_list_devices(EmptyInput()))
        assert meta["matched_total"] == 2
        assert meta["returned"] == 2
        assert meta["filtered_by"] == []
        assert meta["redactions"] == []
        assert isinstance(meta["latency_ms"], int)

    # DD-338 Phase A.1 — Track 1 — scope=work filters by folder membership
    async def test_scope_work_filters_by_folder_membership(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        # Devices A/B/C in folder fld1; A in fld2; only B in fld3
        cfg = {
            "folders": [
                {"id": "fld1", "label": "f1", "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ]},
                {"id": "fld2", "label": "f2", "devices": [
                    {"deviceID": DEVICE_ID_REMOTE2},
                ]},
            ],
            "devices": [
                {"deviceID": DEVICE_ID_LOCAL, "name": "alpha"},
                {"deviceID": DEVICE_ID_REMOTE, "name": "beta"},
                {"deviceID": DEVICE_ID_REMOTE2, "name": "gamma"},
            ],
        }
        mock_api.get("/rest/config").respond(json=cfg)
        monkeypatch.setenv("SYNCTHING_WORK_FOLDERS", "fld1")

        payload, meta = split_meta(await syncthing_list_devices(ReadParams(scope="work")))
        result = json.loads(payload)
        # Devices in fld1 = LOCAL + REMOTE
        names = {d["name"] for d in result}
        assert names == {"alpha", "beta"}
        assert meta["matched_total"] == 3
        assert meta["returned"] == 2
        assert meta["filtered_by"] == ["scope=work"]
        assert meta["redactions"] == []

    # DD-338 Phase A.1 — Track 1 — unconfigured scope passes through w/ redaction
    async def test_scope_work_unconfigured_redacts(self, mock_api, monkeypatch):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        monkeypatch.delenv("SYNCTHING_WORK_FOLDERS", raising=False)
        payload, meta = split_meta(await syncthing_list_devices(ReadParams(scope="work")))
        result = json.loads(payload)
        assert len(result) == 2  # unfiltered fallthrough
        assert meta["redactions"] == ["scope=work_unconfigured"]

    # DD-338 Phase A.1 — Track 1 — scope=public raises through error path
    async def test_scope_public_raises(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        # ValueError surfaces via handle_error_global as a plain string
        out = await syncthing_list_devices(ReadParams(scope="public"))
        assert out.startswith("Error:")
        assert "public" in out

    # DD-338 Phase A.1 — Track 2 — sort-before-return deterministic across N=5
    async def test_deterministic_n5(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_list_devices

        # Strip the latency_ms from _meta because it varies per call.
        results = []
        for _ in range(5):
            out = await syncthing_list_devices(EmptyInput())
            payload, meta = split_meta(out)
            meta.pop("latency_ms")
            results.append((payload, json.dumps(meta, sort_keys=True)))
        first = results[0]
        for r in results[1:]:
            assert r == first, "byte-equality (modulo latency_ms) broken"


class TestDeviceCompletion:
    async def test_fully_synced(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_device_completion

        mock_api.get("/rest/db/completion").respond(json=make_completion(100.0))
        result = json.loads(await syncthing_device_completion(
            DeviceInput(device_id=DEVICE_ID_REMOTE)
        ))
        assert result["completion"] == 100.0
        assert result["needSize"] == "0.0 B"


class TestConnections:
    async def test_returns_connections(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_connections

        result = json.loads(await syncthing_connections(EmptyInput()))
        assert len(result) == 2
        assert any(c["connected"] for c in result)


class TestDeviceStats:
    async def test_returns_stats(self, mock_api):
        from syncthing_mcp.tools.devices import syncthing_device_stats

        result = json.loads(await syncthing_device_stats(EmptyInput()))
        assert len(result) >= 1
        assert "lastSeen" in result[0]
