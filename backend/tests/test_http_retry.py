import httpx
import pytest

from app.connectors.http import request_with_retry


async def _noop_sleep(_delay: float) -> None:
    return None


@pytest.mark.asyncio
async def test_retries_then_succeeds():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "0"})
        return httpx.Response(200, json={"ok": True})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await request_with_retry(client, "GET", "/x", base_delay=0, sleep=_noop_sleep)
    assert resp.status_code == 200
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_passthrough_success_no_retry():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await request_with_retry(client, "GET", "/x", sleep=_noop_sleep)
    assert resp.status_code == 200
    assert calls["n"] == 1


@pytest.mark.asyncio
async def test_raises_after_exhaustion():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await request_with_retry(
                client, "GET", "/x", max_retries=2, base_delay=0, sleep=_noop_sleep
            )


@pytest.mark.asyncio
async def test_non_retryable_4xx_raises_immediately():
    calls = {"n": 0}

    def handler(_request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as client:
        with pytest.raises(httpx.HTTPStatusError):
            await request_with_retry(client, "GET", "/x", sleep=_noop_sleep)
    assert calls["n"] == 1
