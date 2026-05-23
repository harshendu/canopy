"""In-process pub/sub for Server-Sent Events.

A minimal broker for live UI refresh: web-process actions (e.g. replan) publish a
small event and connected SSE clients receive it. Single-process only — events from
the arq worker won't propagate here; Redis pub/sub is the multi-process upgrade path.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from typing import Any

_subscribers: set[asyncio.Queue[dict[str, Any]]] = set()


async def publish(event: dict[str, Any]) -> None:
    for queue in list(_subscribers):
        with contextlib.suppress(asyncio.QueueFull):
            queue.put_nowait(event)


async def subscribe() -> AsyncIterator[dict[str, Any]]:
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=100)
    _subscribers.add(queue)
    try:
        while True:
            yield await queue.get()
    finally:
        _subscribers.discard(queue)
