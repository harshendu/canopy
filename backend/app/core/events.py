"""Pub/sub for Server-Sent Events — live UI refresh (USER_FLOWS §K).

Actions publish a small event (`{"type": "board", "project_id": 3, ...}`) and every connected SSE
client receives it, so open pages refetch. Two backends (`EVENTS_BACKEND`):

* `memory` (the default) — delivery within this process only. Fine for one API process with no
  worker activity worth showing live.
* `redis` — every event is also published on the Redis channel `canopy:events`, and each web
  process runs a listener (`start()`, from the app lifespan) that fans events from the *other*
  processes out to its own subscribers: other API workers, and the arq worker (tracker syncs,
  webhook processing, the work queue's claim reaper). An event never reaches a process twice —
  each carries its origin and a process skips its own.

Redis trouble never fails the action that published: delivery degrades to in-process (logged at
most once a minute) and the listener reconnects with backoff.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)

CHANNEL = "canopy:events"
# This process. Its own events come back from Redis too; the listener skips them.
ORIGIN = uuid.uuid4().hex

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
_client: Redis | None = None
_listener: asyncio.Task[None] | None = None
_last_failure_log = 0.0


def remote_enabled() -> bool:
    return settings.EVENTS_BACKEND.strip().lower() == "redis"


def _deliver(event: dict[str, Any]) -> None:
    for queue in list(_subscribers):
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)


def _log_failure(what: str, exc: BaseException) -> None:
    global _last_failure_log
    now = time.monotonic()
    if now - _last_failure_log > 60:
        _last_failure_log = now
        logger.warning("Live-refresh events over Redis: %s failed (%s); delivering in-process",
                       what, exc)


async def _redis() -> Redis:
    global _client
    if _client is None:
        _client = Redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2
        )
    return _client


async def publish(event: dict[str, Any]) -> None:
    """Deliver to this process's subscribers and, with the Redis backend, to every other
    process's. Never raises for a Redis problem."""
    _deliver(event)
    if not remote_enabled():
        return
    try:
        client = await _redis()
        await client.publish(CHANNEL, json.dumps({"origin": ORIGIN, "event": event},
                                                 default=str))
    except Exception as exc:  # any Redis/network trouble: in-process delivery still happened
        _log_failure("publish", exc)


def handle_message(raw: bytes | str) -> bool:
    """Fan one message from the channel out to this process's subscribers. False (nothing
    delivered) for this process's own events and for anything malformed."""
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        return False
    if not isinstance(payload, dict) or payload.get("origin") == ORIGIN:
        return False
    event = payload.get("event")
    if not isinstance(event, dict):
        return False
    _deliver(event)
    return True


async def _listen() -> None:
    """Subscribe to the channel and fan messages out, reconnecting with backoff. A dedicated
    connection without a read timeout: a quiet channel is not an error."""
    delay = 1.0
    while True:
        client: Redis | None = None
        try:
            client = Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
            pubsub = client.pubsub(ignore_subscribe_messages=True)
            await pubsub.subscribe(CHANNEL)
            delay = 1.0
            async for message in pubsub.listen():
                if message.get("type") == "message":
                    handle_message(message.get("data"))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # connection refused / dropped: retry
            _log_failure("listening", exc)
        finally:
            if client is not None:
                with contextlib.suppress(Exception):
                    await client.aclose()
        await asyncio.sleep(delay)
        delay = min(delay * 2, 30.0)


async def start() -> None:
    """Start this web process's cross-process listener (a no-op on the memory backend)."""
    global _listener
    if remote_enabled() and (_listener is None or _listener.done()):
        _listener = asyncio.create_task(_listen(), name="canopy-events-listener")


async def stop() -> None:
    """Stop the listener and close the publishing connection."""
    global _listener, _client
    if _listener is not None:
        _listener.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await _listener
        _listener = None
    if _client is not None:
        with contextlib.suppress(Exception):
            await _client.aclose()
        _client = None


async def subscribe() -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    try:
        while True:
            yield await queue.get()
    finally:
        _subscribers.discard(queue)
