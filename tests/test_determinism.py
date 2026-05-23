"""DD-338 Phase B.1.b — determinism harness for syncthing_connections.

The single multi-record tool in this blade. Sort key is canonical deviceID
(dict key from the Syncthing REST API response). N=5 byte-equal verification.
"""

from __future__ import annotations

import json

import pytest
import respx
from httpx import Response

from syncthing_mcp.models import EmptyInput
from syncthing_mcp.registry import reload_instances
from tests.conftest import (
    BASE_URL,
    DEVICE_ID_LOCAL,
    DEVICE_ID_REMOTE,
    DEVICE_ID_REMOTE2,
    make_config,
    make_connections,
)


N_RUNS = 5


@pytest.fixture(autouse=True)
def _setup(single_instance_env):
    reload_instances()
    yield
    reload_instances()


def _byte_equal(outputs: list[str]) -> None:
    first = outputs[0]
    for i, o in enumerate(outputs[1:], start=1):
        assert o == first, f"Non-deterministic on run {i}: {o!r} vs {first!r}"


class TestSyncthingConnectionsDeterministic:
    async def test_byte_equal_n5(self):
        """N=5 byte-equal harness against fixed mocked upstream."""
        from syncthing_mcp.tools.devices import syncthing_connections

        # Non-pre-sorted connection dict — IDs in reverse-canonical order.
        # The 3 device IDs ALL = A < B < C; supply in reverse to verify sort.
        conn = {
            DEVICE_ID_REMOTE2: {
                "connected": True, "paused": False, "address": "192.168.1.3:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 1, "outBytesTotal": 2,
            },
            DEVICE_ID_REMOTE: {
                "connected": True, "paused": False, "address": "192.168.1.2:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 3, "outBytesTotal": 4,
            },
            DEVICE_ID_LOCAL: {
                "connected": True, "paused": False, "address": "127.0.0.1:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 5, "outBytesTotal": 6,
            },
        }
        cfg = make_config(devices=[
            {"deviceID": DEVICE_ID_LOCAL, "name": "local-dev"},
            {"deviceID": DEVICE_ID_REMOTE, "name": "remote-dev"},
            {"deviceID": DEVICE_ID_REMOTE2, "name": "remote-dev2"},
        ])

        outputs: list[str] = []
        for _ in range(N_RUNS):
            with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
                router.get("/rest/system/status").respond(json={"myID": DEVICE_ID_LOCAL})
                router.get("/rest/config").respond(json=cfg)
                router.get("/rest/system/connections").respond(json={"connections": dict(conn)})
                outputs.append(await syncthing_connections(EmptyInput()))
        _byte_equal(outputs)

    async def test_sorts_by_device_id_ascending(self):
        """Output ordering must reflect canonical deviceID-ascending sort."""
        from syncthing_mcp.tools.devices import syncthing_connections

        # AAA, BBB, CCC — supply in reverse order; expect AAA appears first in output.
        conn = {
            DEVICE_ID_REMOTE2: {
                "connected": True, "paused": False, "address": "192.168.1.3:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 1, "outBytesTotal": 2,
            },
            DEVICE_ID_REMOTE: {
                "connected": True, "paused": False, "address": "192.168.1.2:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 3, "outBytesTotal": 4,
            },
            DEVICE_ID_LOCAL: {
                "connected": True, "paused": False, "address": "127.0.0.1:22000",
                "type": "tcp-client", "crypto": "TLS1.3",
                "inBytesTotal": 5, "outBytesTotal": 6,
            },
        }
        cfg = make_config(devices=[
            {"deviceID": DEVICE_ID_LOCAL, "name": "local-dev"},
            {"deviceID": DEVICE_ID_REMOTE, "name": "remote-dev"},
            {"deviceID": DEVICE_ID_REMOTE2, "name": "remote-dev2"},
        ])
        with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
            router.get("/rest/system/status").respond(json={"myID": DEVICE_ID_LOCAL})
            router.get("/rest/config").respond(json=cfg)
            router.get("/rest/system/connections").respond(json={"connections": dict(conn)})
            result = await syncthing_connections(EmptyInput())

        # AAA prefix appears before BBB prefix appears before CCC prefix.
        idx_a = result.find(DEVICE_ID_LOCAL[:8])
        idx_b = result.find(DEVICE_ID_REMOTE[:8])
        idx_c = result.find(DEVICE_ID_REMOTE2[:8])
        # We use name lookup since formatter renders by name first; check
        # alternative ordering signals:
        idx_local = result.find("local-dev")
        idx_remote = result.find("remote-dev")
        idx_remote2 = result.find("remote-dev2")
        # local-dev (AAA-keyed) must appear before remote-dev (BBB-keyed)
        # before remote-dev2 (CCC-keyed).
        assert idx_local != -1 and idx_remote != -1 and idx_remote2 != -1
        assert idx_local < idx_remote < idx_remote2

    async def test_handles_empty_connections(self):
        """Empty connections dict must not crash."""
        from syncthing_mcp.tools.devices import syncthing_connections

        with respx.mock(base_url=BASE_URL, assert_all_called=False) as router:
            router.get("/rest/system/status").respond(json={"myID": DEVICE_ID_LOCAL})
            router.get("/rest/config").respond(json=make_config())
            router.get("/rest/system/connections").respond(json={"connections": {}})
            result = await syncthing_connections(EmptyInput())
        # Result is JSON-formatted empty list (fmt is JSON dumper here).
        parsed = json.loads(result)
        assert parsed == []
