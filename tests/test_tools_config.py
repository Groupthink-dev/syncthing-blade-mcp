"""Tests for config mutation tools (pending, accept/reject, ignores)."""

import json

import pytest

from syncthing_mcp.models import (
    AcceptDeviceInput,
    AcceptFolderInput,
    DeviceInput,
    EmptyInput,
    FolderInput,
    RejectFolderInput,
    SetDefaultIgnoresInput,
    SetIgnoresInput,
)
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    DEVICE_ID_REMOTE2,
    FOLDER_ID,
    make_system_status,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestPendingDevices:
    async def test_empty(self, mock_api):
        from syncthing_mcp.tools.config import syncthing_pending_devices

        result = json.loads(await syncthing_pending_devices(EmptyInput()))
        assert result["pendingDevices"] == {}


class TestPendingFolders:
    async def test_empty(self, mock_api):
        from syncthing_mcp.tools.config import syncthing_pending_folders

        result = json.loads(await syncthing_pending_folders(EmptyInput()))
        assert result["pendingFolders"] == {}


class TestAcceptDevice:
    async def test_accept(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_accept_device

        mock_api.get("/rest/cluster/pending/devices").respond(json={
            DEVICE_ID_REMOTE2: {"name": "new-device", "address": "10.0.0.5"}
        })
        mock_api.get("/rest/config/defaults/device").respond(json={
            "addresses": ["dynamic"],
        })
        mock_api.post("/rest/config/devices").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_accept_device(
            AcceptDeviceInput(device_id=DEVICE_ID_REMOTE2, confirm=True)
        ))
        assert result["status"] == "accepted"
        assert result["name"] == "new-device"


class TestRejectDevice:
    async def test_reject(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_reject_device

        mock_api.delete("/rest/cluster/pending/devices").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_reject_device(
            DeviceInput(device_id=DEVICE_ID_REMOTE2)
        ))
        assert result["status"] == "rejected"


class TestAcceptFolder:
    async def test_accept(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_accept_folder

        mock_api.get("/rest/cluster/pending/folders").respond(json={
            "new-folder": {
                "offeredBy": {
                    DEVICE_ID_REMOTE: {"label": "Shared Docs"},
                }
            }
        })
        mock_api.get("/rest/config/defaults/folder").respond(json={
            "path": "/home/user/Sync",
            "type": "sendreceive",
        })
        mock_api.post("/rest/config/folders").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_accept_folder(
            AcceptFolderInput(folder_id="new-folder", confirm=True)
        ))
        assert result["status"] == "accepted"
        assert result["label"] == "Shared Docs"

    async def test_not_pending(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_accept_folder

        result = json.loads(await syncthing_accept_folder(
            AcceptFolderInput(folder_id="nonexistent", confirm=True)
        ))
        assert "error" in result


class TestRejectFolder:
    async def test_reject(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_reject_folder

        mock_api.delete("/rest/cluster/pending/folders").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_reject_folder(
            RejectFolderInput(folder_id="some-folder")
        ))
        assert result["status"] == "rejected"


class TestGetIgnores:
    async def test_get(self, mock_api):
        from syncthing_mcp.tools.config import syncthing_get_ignores

        mock_api.get("/rest/db/ignores").respond(json={
            "ignore": ["*.tmp", ".DS_Store"],
            "expanded": ["*.tmp", ".DS_Store"],
        })
        result = json.loads(await syncthing_get_ignores(FolderInput(folder_id=FOLDER_ID)))
        assert len(result["patterns"]) == 2


class TestSetIgnores:
    async def test_set(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_set_ignores

        mock_api.post("/rest/db/ignores").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_set_ignores(
            SetIgnoresInput(folder_id=FOLDER_ID, patterns=["*.log", "node_modules"], confirm=True)
        ))
        assert result["status"] == "updated"
        assert result["count"] == 2


class TestGetDefaultIgnores:
    async def test_get(self, mock_api):
        from syncthing_mcp.tools.config import syncthing_get_default_ignores

        mock_api.get("/rest/config/defaults/ignores").respond(json={"lines": [".DS_Store"]})
        result = json.loads(await syncthing_get_default_ignores(EmptyInput()))
        assert result["lines"] == [".DS_Store"]


class TestSetDefaultIgnores:
    async def test_set(self, mock_api, write_enabled_env):
        from syncthing_mcp.tools.config import syncthing_set_default_ignores

        mock_api.put("/rest/config/defaults/ignores").respond(
            json={"lines": ["Thumbs.db"]},
            headers={"content-type": "application/json"},
        )
        result = json.loads(await syncthing_set_default_ignores(
            SetDefaultIgnoresInput(lines=["Thumbs.db"])
        ))
        assert result["status"] == "updated"
