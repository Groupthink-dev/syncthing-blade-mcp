"""Regression tests for the write gate + confirm discipline (AUD-04-02 / DD-385 Phase W).

Every mutating tool must refuse when ``SYNCTHING_WRITE_ENABLED`` is not
``true``; destructive/disruptive tools must additionally refuse without
``confirm=true`` even when the gate is open.
"""

import json

import pytest

from syncthing_mcp.models import (
    AcceptDeviceInput,
    AcceptFolderInput,
    ConfirmFolderWriteParams,
    ConfirmWriteParams,
    DeviceInput,
    PauseFolderInput,
    RejectFolderInput,
    SetDefaultIgnoresInput,
    SetIgnoresInput,
    WriteParams,
)
from syncthing_mcp.registry import reload_instances
from syncthing_mcp.tools.config import (
    syncthing_accept_device,
    syncthing_accept_folder,
    syncthing_reject_device,
    syncthing_reject_folder,
    syncthing_set_default_ignores,
    syncthing_set_ignores,
)
from syncthing_mcp.tools.folders import (
    syncthing_override_folder,
    syncthing_pause_folder,
    syncthing_resume_folder,
    syncthing_revert_folder,
    syncthing_scan_folder,
)
from syncthing_mcp.tools.system import syncthing_clear_errors, syncthing_restart
from tests.conftest import DEVICE_ID_REMOTE2, FOLDER_ID

WRITE_DISABLED_MSG = (
    "Write operations are disabled. Set SYNCTHING_WRITE_ENABLED=true to enable."
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env, monkeypatch):
    monkeypatch.delenv("SYNCTHING_WRITE_ENABLED", raising=False)
    reload_instances()
    yield
    reload_instances()


# Every mutating tool, with valid params. confirm=True so the gated-off test
# proves the env gate refuses even a fully-confirmed call.
ALL_MUTATING = [
    pytest.param(syncthing_pause_folder, PauseFolderInput(folder_id=FOLDER_ID), id="pause_folder"),
    pytest.param(syncthing_resume_folder, PauseFolderInput(folder_id=FOLDER_ID), id="resume_folder"),
    pytest.param(syncthing_scan_folder, PauseFolderInput(folder_id=FOLDER_ID), id="scan_folder"),
    pytest.param(syncthing_override_folder, ConfirmFolderWriteParams(folder_id=FOLDER_ID, confirm=True), id="override_folder"),
    pytest.param(syncthing_revert_folder, ConfirmFolderWriteParams(folder_id=FOLDER_ID, confirm=True), id="revert_folder"),
    pytest.param(syncthing_clear_errors, WriteParams(), id="clear_errors"),
    pytest.param(syncthing_restart, ConfirmWriteParams(confirm=True), id="restart"),
    pytest.param(syncthing_accept_device, AcceptDeviceInput(device_id=DEVICE_ID_REMOTE2, confirm=True), id="accept_device"),
    pytest.param(syncthing_reject_device, DeviceInput(device_id=DEVICE_ID_REMOTE2), id="reject_device"),
    pytest.param(syncthing_accept_folder, AcceptFolderInput(folder_id=FOLDER_ID, confirm=True), id="accept_folder"),
    pytest.param(syncthing_reject_folder, RejectFolderInput(folder_id=FOLDER_ID), id="reject_folder"),
    pytest.param(syncthing_set_ignores, SetIgnoresInput(folder_id=FOLDER_ID, patterns=["*.tmp"], confirm=True), id="set_ignores"),
    pytest.param(syncthing_set_default_ignores, SetDefaultIgnoresInput(lines=[".DS_Store"]), id="set_default_ignores"),
]

# Destructive/disruptive tools requiring confirm=true, with confirm left False.
DESTRUCTIVE_NO_CONFIRM = [
    pytest.param(syncthing_override_folder, ConfirmFolderWriteParams(folder_id=FOLDER_ID), id="override_folder"),
    pytest.param(syncthing_revert_folder, ConfirmFolderWriteParams(folder_id=FOLDER_ID), id="revert_folder"),
    pytest.param(syncthing_restart, ConfirmWriteParams(), id="restart"),
    pytest.param(syncthing_accept_device, AcceptDeviceInput(device_id=DEVICE_ID_REMOTE2), id="accept_device"),
    pytest.param(syncthing_accept_folder, AcceptFolderInput(folder_id=FOLDER_ID), id="accept_folder"),
    pytest.param(syncthing_set_ignores, SetIgnoresInput(folder_id=FOLDER_ID, patterns=["*.tmp"]), id="set_ignores"),
]


class TestWriteGateOff:
    @pytest.mark.parametrize("tool, params", ALL_MUTATING)
    async def test_refuses_when_gate_unset(self, mock_api, tool, params):
        result = json.loads(await tool(params))
        assert result == {"error": WRITE_DISABLED_MSG}

    @pytest.mark.parametrize("tool, params", ALL_MUTATING)
    async def test_refuses_when_gate_not_true(self, mock_api, monkeypatch, tool, params):
        monkeypatch.setenv("SYNCTHING_WRITE_ENABLED", "1")
        result = json.loads(await tool(params))
        assert result == {"error": WRITE_DISABLED_MSG}


class TestConfirmRequired:
    @pytest.mark.parametrize("tool, params", DESTRUCTIVE_NO_CONFIRM)
    async def test_refuses_without_confirm(self, mock_api, write_enabled_env, tool, params):
        result = json.loads(await tool(params))
        assert "error" in result
        assert "confirm=true" in result["error"]
        # Refusal must not be the gate message — the gate is open.
        assert result["error"] != WRITE_DISABLED_MSG


class TestGatedOnProceeds:
    async def test_restart_with_confirm(self, mock_api, write_enabled_env):
        mock_api.post("/rest/system/restart").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_restart(ConfirmWriteParams(confirm=True)))
        assert result["status"] == "restart_initiated"

    async def test_override_with_confirm(self, mock_api, write_enabled_env):
        mock_api.post("/rest/db/override").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_override_folder(
            ConfirmFolderWriteParams(folder_id=FOLDER_ID, confirm=True)
        ))
        assert result["status"] == "override_requested"

    async def test_set_ignores_with_confirm(self, mock_api, write_enabled_env):
        mock_api.post("/rest/db/ignores").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_set_ignores(
            SetIgnoresInput(folder_id=FOLDER_ID, patterns=["*.tmp"], confirm=True)
        ))
        assert result["status"] == "updated"

    async def test_non_destructive_needs_no_confirm(self, mock_api, write_enabled_env):
        mock_api.post("/rest/db/scan").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_scan_folder(
            PauseFolderInput(folder_id=FOLDER_ID)
        ))
        assert result["status"] == "scan_requested"
