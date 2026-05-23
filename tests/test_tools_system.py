"""Tests for system tools (status, health, errors, log, restart, upgrade)."""

import json

import pytest
import respx
from httpx import Response

from syncthing_mcp.models import EmptyInput
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    FOLDER_ID,
    make_completion,
    make_config,
    make_connections,
    make_db_status,
    make_system_status,
    make_version,
    split_meta,
)


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


class TestSystemStatus:
    async def test_returns_status(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_system_status

        result = json.loads(await syncthing_system_status(EmptyInput()))
        # Concise mode truncates device ID to 8 chars
        assert result["myID"] == DEVICE_ID_LOCAL[:8]
        assert result["deviceName"] == "local-dev"
        assert result["version"] == "v1.28.0"
        assert result["instance"] == "default"


class TestSystemErrors:
    async def test_no_errors(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_system_errors

        result = json.loads(await syncthing_system_errors(EmptyInput()))
        assert result["count"] == 0

    async def test_with_errors(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_system_errors

        mock_api.get("/rest/system/error").respond(
            json={"errors": [{"when": "2025-01-01", "message": "disk full"}]}
        )
        result = json.loads(await syncthing_system_errors(EmptyInput()))
        assert result["count"] == 1


class TestClearErrors:
    async def test_clear(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_clear_errors

        mock_api.post("/rest/system/error/clear").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_clear_errors(EmptyInput()))
        assert result["status"] == "cleared"


class TestSystemLog:
    async def test_returns_log(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_system_log

        result = json.loads(await syncthing_system_log(EmptyInput()))
        assert result["count"] == 0


class TestRecentChanges:
    async def test_returns_events(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_recent_changes

        mock_api.get("/rest/events").respond(json=[
            {"id": 1, "type": "LocalChangeDetected", "data": {"path": "file.txt"}}
        ])
        payload, meta = split_meta(await syncthing_recent_changes(EmptyInput()))
        result = json.loads(payload)
        assert result["count"] == 1
        assert meta["matched_total"] == 1
        assert meta["returned"] == 1
        assert meta["filtered_by"] == []
        assert meta["redactions"] == []


class TestRestartRequired:
    async def test_not_required(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_restart_required

        result = json.loads(await syncthing_restart_required(EmptyInput()))
        assert result["restartRequired"] is False


class TestRestart:
    async def test_restart(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_restart

        mock_api.post("/rest/system/restart").respond(status_code=200, content=b"")
        result = json.loads(await syncthing_restart(EmptyInput()))
        assert result["status"] == "restart_initiated"


class TestCheckUpgrade:
    async def test_upgrade_available(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_check_upgrade

        mock_api.get("/rest/system/upgrade").respond(json={
            "latest": "v1.29.0", "newer": True, "majorNewer": False
        })
        result = json.loads(await syncthing_check_upgrade(EmptyInput()))
        assert result["newer"] is True
        assert result["latest"] == "v1.29.0"
        assert result["running"] == "v1.28.0"

    async def test_upgrade_disabled(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_check_upgrade

        mock_api.get("/rest/system/upgrade").respond(status_code=501)
        result = json.loads(await syncthing_check_upgrade(EmptyInput()))
        assert result["upgradeCheck"] == "unavailable"


class TestHealthSummary:
    async def test_all_good(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_health_summary

        mock_api.get("/rest/db/status").respond(json=make_db_status())
        result = json.loads(await syncthing_health_summary(EmptyInput()))
        assert result["status"] == "good"
        assert result["summary"]["idle"] == 1

    async def test_error_state(self, mock_api):
        from syncthing_mcp.tools.system import syncthing_health_summary

        mock_api.get("/rest/system/error").respond(
            json={"errors": [{"when": "now", "message": "bad"}]}
        )
        mock_api.get("/rest/db/status").respond(json=make_db_status())
        result = json.loads(await syncthing_health_summary(EmptyInput()))
        assert result["status"] == "error"
        assert any("system error" in a for a in result["alerts"])
