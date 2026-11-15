"""Live-refresh events (app/core/events.py, USER_FLOWS §K): in-process delivery, and the Redis
fan-out that carries the worker's and other API processes' events to every open page.

The last test talks to a real Redis — CI runs it with `CANOPY_TEST_REDIS_URL`; it is skipped
without one."""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

import pytest

from app.core import events
from app.core.config import settings


async def _subscribed() -> Any:
    """A live subscription (the generator registers its queue on first iteration)."""
    stream = events.subscribe()
    waiter = asyncio.ensure_future(stream.__anext__())
    await asyncio.sleep(0)  # let it register before anything is published
    return stream, waiter


class FakeRedis:
    def __init__(self, fail: bool = False) -> None:
        self.published: list[tuple[str, str]] = []
        self.fail = fail

    async def publish(self, channel: str, message: str) -> int:
        if self.fail:
            raise ConnectionError("redis is down")
        self.published.append((channel, message))
        return 1


@pytest.mark.asyncio
async def test_memory_backend_delivers_in_process_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EVENTS_BACKEND", "memory")
    fake = FakeRedis()
    monkeypatch.setattr(events, "_client", fake)
    stream, waiter = await _subscribed()
    await events.publish({"type": "board", "project_id": 1})
    assert await asyncio.wait_for(waiter, 2) == {"type": "board", "project_id": 1}
    assert fake.published == []
    await stream.aclose()


@pytest.mark.asyncio
async def test_redis_backend_publishes_with_its_origin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EVENTS_BACKEND", "redis")
    fake = FakeRedis()
    monkeypatch.setattr(events, "_client", fake)
    stream, waiter = await _subscribed()
    await events.publish({"type": "work", "project_id": 2})
    # Delivered here at once, and published for the other processes.
    assert await asyncio.wait_for(waiter, 2) == {"type": "work", "project_id": 2}
    [(channel, message)] = fake.published
    assert channel == events.CHANNEL
    assert json.loads(message) == {"origin": events.ORIGIN,
                                   "event": {"type": "work", "project_id": 2}}
    await stream.aclose()


@pytest.mark.asyncio
async def test_a_redis_failure_never_fails_the_publisher(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EVENTS_BACKEND", "redis")
    monkeypatch.setattr(events, "_client", FakeRedis(fail=True))
    stream, waiter = await _subscribed()
    await events.publish({"type": "replan", "project_id": 3})  # does not raise
    assert await asyncio.wait_for(waiter, 2) == {"type": "replan", "project_id": 3}
    await stream.aclose()


@pytest.mark.asyncio
async def test_messages_from_other_processes_fan_out_and_our_own_are_skipped() -> None:
    stream, waiter = await _subscribed()
    own = json.dumps({"origin": events.ORIGIN, "event": {"type": "board"}})
    assert events.handle_message(own) is False  # already delivered when we published it
    assert events.handle_message(b"not json") is False
    assert events.handle_message(json.dumps({"origin": "other", "event": "nope"})) is False
    other = json.dumps({"origin": "worker-1", "event": {"type": "work", "task_id": 9}})
    assert events.handle_message(other.encode()) is True
    assert await asyncio.wait_for(waiter, 2) == {"type": "work", "task_id": 9}
    await stream.aclose()


@pytest.mark.asyncio
async def test_start_is_a_noop_on_the_memory_backend(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "EVENTS_BACKEND", "memory")
    await events.start()
    assert events._listener is None
    await events.stop()


REDIS_URL = os.environ.get("CANOPY_TEST_REDIS_URL")


@pytest.mark.asyncio
@pytest.mark.skipif(not REDIS_URL, reason="needs CANOPY_TEST_REDIS_URL (a real Redis)")
async def test_events_cross_processes_over_a_real_redis(monkeypatch: pytest.MonkeyPatch) -> None:
    from redis.asyncio import Redis

    assert REDIS_URL is not None
    monkeypatch.setattr(settings, "EVENTS_BACKEND", "redis")
    monkeypatch.setattr(settings, "REDIS_URL", REDIS_URL)
    monkeypatch.setattr(events, "_client", None)
    monkeypatch.setattr(events, "_listener", None)
    # Read a subscriber's queue directly: timing out a read must not end the subscription.
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    events._subscribers.add(queue)
    await events.start()
    try:
        # Another process (here: a raw client with another origin) publishes...
        other = Redis.from_url(REDIS_URL)
        payload = json.dumps({"origin": "the-worker", "event": {"type": "work", "task_id": 1}})
        received: dict[str, Any] | None = None
        for _ in range(30):  # until the listener has subscribed
            await other.publish(events.CHANNEL, payload)
            try:
                received = await asyncio.wait_for(queue.get(), 0.3)
                break
            except TimeoutError:
                continue
        await other.aclose()
        assert received == {"type": "work", "task_id": 1}
        while not queue.empty():  # retries that landed after the first delivery
            queue.get_nowait()
        # ...and our own event arrives once, not a second time through Redis.
        await events.publish({"type": "board", "project_id": 7})
        assert await asyncio.wait_for(queue.get(), 2) == {"type": "board", "project_id": 7}
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.get(), 0.5)
    finally:
        events._subscribers.discard(queue)
        await events.stop()
