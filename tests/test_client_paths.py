"""An id goes into a path as one segment, whatever it holds."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from hc_mcp.config import Config
from hc_mcp.homecore_client import HomeCoreClient, seg


def client_seeing(paths: list[str]) -> HomeCoreClient:
    c = HomeCoreClient(Config(base_url="http://hc", api_key="k", timeout_secs=1))

    def answer(req: httpx.Request) -> httpx.Response:
        paths.append(req.url.raw_path.decode())
        return httpx.Response(200, json={})

    c._client = httpx.AsyncClient(
        base_url="http://hc/api/v1", transport=httpx.MockTransport(answer)
    )
    return c


def test_an_id_cant_walk_to_another_device():
    paths: list[str] = []
    c = client_seeing(paths)
    asyncio.run(c.command_device("light.lamp/../lock.front", {"on": True}))
    asyncio.run(c.command_device("lock.front?x=", {"on": True}))
    asyncio.run(c.play_rotation("r#x"))
    assert paths == [
        "/api/v1/devices/light.lamp%2F..%2Flock.front/state",
        "/api/v1/devices/lock.front%3Fx%3D/state",
        "/api/v1/rotations/r%23x/play",
    ]


@pytest.mark.parametrize("bad", ["", ".", ".."])
def test_a_dot_isnt_an_id(bad):
    with pytest.raises(ValueError):
        seg(bad)


def test_an_ordinary_id_is_as_it_was():
    assert seg("light.lamp") == "light.lamp"
    assert seg("plugin.wled") == "plugin.wled"
