"""Shared HTTP helper with rate-limit-aware retries.

Honors `Retry-After` and falls back to exponential backoff with jitter on 429 and
transient 5xx responses. Injectable `sleep` keeps it unit-testable.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})


def _retry_delay(response: httpx.Response, attempt: int, base_delay: float) -> float:
    """Seconds to wait before the next attempt: Retry-After if present, else backoff+jitter."""
    retry_after = response.headers.get("Retry-After")
    if retry_after and retry_after.isdigit():
        return float(retry_after)
    return float(base_delay * (2**attempt) + random.uniform(0, base_delay))


async def request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    max_retries: int = 4,
    base_delay: float = 1.0,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    **kwargs: Any,
) -> httpx.Response:
    """Issue a request, retrying retryable statuses. Raises on non-retryable or exhausted errors."""
    attempt = 0
    while True:
        response = await client.request(method, url, **kwargs)
        if response.status_code not in RETRYABLE_STATUSES or attempt >= max_retries:
            response.raise_for_status()
            return response
        await sleep(_retry_delay(response, attempt, base_delay))
        attempt += 1
