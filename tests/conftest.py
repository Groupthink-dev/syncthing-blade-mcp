"""Shared fixtures for Syncthing MCP tests."""

import json
import os
import re
from unittest.mock import patch

import pytest
import respx
from httpx import Response

from syncthing_mcp.client import SyncthingClient


# ---------------------------------------------------------------------------
# DD-338 _meta envelope test helper (Phase A.1 — Track 3)
# ---------------------------------------------------------------------------

_META_REGEX = re.compile(r"\n\n_meta: (\{.*\})$", re.DOTALL)


def split_meta(text: str) -> tuple[str, dict]:
    """Split a tool's return string into (payload, _meta dict).

    Matches the assembler regex documented in the DD-338 spec amendment:
        \\n\\n_meta: (\\{.*\\})$
    """
    m = _META_REGEX.search(text)
    if not m:
        raise AssertionError(f"_meta envelope not found in:\n{text!r}")
    payload = text[: m.start()]
    meta = json.loads(m.group(1))
    return payload, meta


# ---------------------------------------------------------------------------
# Common Syncthing API response fixtures
# ---------------------------------------------------------------------------

DEVICE_ID_LOCAL = "AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA-AAAAAAA"
DEVICE_ID_REMOTE = "BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB-BBBBBBB"
DEVICE_ID_REMOTE2 = "CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC-CCCCCCC"

FOLDER_ID = "test-folder"
API_KEY = "test-api-key-12345"
BASE_URL = "http://localhost:8384"


def make_config(
    *,
    folders: list | None = None,
    devices: list | None = None,
) -> dict:
    """Build a minimal Syncthing config response."""
    if devices is None:
        devices = [
            {"deviceID": DEVICE_ID_LOCAL, "name": "local-dev"},
            {"deviceID": DEVICE_ID_REMOTE, "name": "remote-dev"},
        ]
    if folders is None:
        folders = [
            {
                "id": FOLDER_ID,
                "label": "Test Folder",
                "path": "/data/test",
                "type": "sendreceive",
                "paused": False,
                "devices": [
                    {"deviceID": DEVICE_ID_LOCAL},
                    {"deviceID": DEVICE_ID_REMOTE},
                ],
            }
        ]
    return {"folders": folders, "devices": devices}


def make_system_status(my_id: str = DEVICE_ID_LOCAL) -> dict:
    return {"myID": my_id, "uptime": 3600}


def make_version() -> dict:
    return {"version": "v1.28.0", "os": "linux", "arch": "amd64"}


def make_connections(connected: dict | None = None) -> dict:
    if connected is None:
        connected = {
            DEVICE_ID_LOCAL: {"connected": True, "paused": False, "address": "127.0.0.1:22000",
                              "type": "tcp-client", "crypto": "TLS1.3", "inBytesTotal": 1024, "outBytesTotal": 2048},
            DEVICE_ID_REMOTE: {"connected": True, "paused": False, "address": "192.168.1.2:22000",
                               "type": "tcp-client", "crypto": "TLS1.3", "inBytesTotal": 4096, "outBytesTotal": 8192},
        }
    return {"connections": connected}


def make_db_status(*, state: str = "idle", local_bytes: int = 1000000, global_bytes: int = 1000000) -> dict:
    return {
        "state": state,
        "stateChanged": "2025-01-01T00:00:00Z",
        "globalFiles": 100,
        "globalBytes": global_bytes,
        "localFiles": 100,
        "localBytes": local_bytes,
        "needFiles": 0,
        "needBytes": 0,
        "inSyncFiles": 100,
        "inSyncBytes": local_bytes,
        "globalDeleted": 5,
        "localDeleted": 5,
        "ignorePatterns": True,
    }


def make_completion(pct: float = 100.0, remote_state: str = "valid") -> dict:
    return {
        "completion": pct,
        "globalBytes": 1000000,
        "needBytes": int(1000000 * (1 - pct / 100)),
        "needItems": 0 if pct == 100 else 5,
        "needDeletes": 0,
        "remoteState": remote_state,
    }


def make_stats_device() -> dict:
    return {
        DEVICE_ID_LOCAL: {"lastSeen": "2025-01-01T12:00:00Z"},
        DEVICE_ID_REMOTE: {"lastSeen": "2025-01-01T12:00:00Z"},
    }


def make_stats_folder() -> dict:
    return {
        FOLDER_ID: {
            "lastScan": "2025-01-01T12:00:00Z",
            "lastFile": {"filename": "test.txt", "at": "2025-01-01T11:00:00Z"},
        }
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def client():
    """A SyncthingClient for testing."""
    return SyncthingClient("test", BASE_URL, API_KEY)


@pytest.fixture
def single_instance_env(monkeypatch):
    """Set env vars for single-instance mode."""
    monkeypatch.setenv("SYNCTHING_API_KEY", API_KEY)
    monkeypatch.setenv("SYNCTHING_URL", BASE_URL)
    monkeypatch.delenv("SYNCTHING_INSTANCES", raising=False)


@pytest.fixture
def write_enabled_env(monkeypatch):
    """Enable the AUD-04-02 write gate for tests exercising mutating tools."""
    monkeypatch.setenv("SYNCTHING_WRITE_ENABLED", "true")


@pytest.fixture
def multi_instance_env(monkeypatch):
    """Set env vars for multi-instance mode."""
    instances = {
        "alpha": {"url": "http://alpha.local:8384", "api_key": "key-alpha"},
        "beta": {"url": "http://beta.local:8384", "api_key": "key-beta"},
    }
    monkeypatch.setenv("SYNCTHING_INSTANCES", json.dumps(instances))
    monkeypatch.delenv("SYNCTHING_API_KEY", raising=False)
    monkeypatch.delenv("SYNCTHING_URL", raising=False)


@pytest.fixture
def mock_api():
    """Activate respx mock for the default Syncthing base URL.

    Pre-configures common routes so tools can call multiple endpoints.
    Returns the respx mock router for further customisation.
    """
    with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
        # Pre-configure common endpoints
        router.get("/rest/system/status").respond(json=make_system_status())
        router.get("/rest/system/version").respond(json=make_version())
        router.get("/rest/config").respond(json=make_config())
        router.get("/rest/system/connections").respond(json=make_connections())
        router.get("/rest/stats/device").respond(json=make_stats_device())
        router.get("/rest/stats/folder").respond(json=make_stats_folder())
        router.get("/rest/system/error").respond(json={"errors": []})
        router.get("/rest/system/log").respond(json={"messages": []})
        router.get("/rest/config/restart-required").respond(json={"requiresRestart": False})
        router.get("/rest/cluster/pending/devices").respond(json={})
        router.get("/rest/cluster/pending/folders").respond(json={})
        yield router


@pytest.fixture
def _setup_single_instance(single_instance_env):
    """Reload the registry with single-instance env, then restore after test."""
    from syncthing_mcp import registry
    registry.reload_instances()
    yield
    registry.reload_instances()
