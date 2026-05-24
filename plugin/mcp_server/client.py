"""Thin authenticated HTTP client for the canopy FastAPI backend.

Configuration comes from the environment (set by the plugin's .mcp.json from the
user's plugin config, or exported directly when running standalone):
  CANOPY_API_BASE_URL  e.g. http://localhost:8000
  CANOPY_API_TOKEN     a JWT from POST /api/v1/auth/login
"""

from __future__ import annotations

import os

import httpx


class CanopyClient:
    def __init__(self) -> None:
        base = os.environ.get("CANOPY_API_BASE_URL", "http://localhost:8000").rstrip("/")
        self.base_url = f"{base}/api/v1"
        self.token = os.environ.get("CANOPY_API_TOKEN", "")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def get(self, path: str, params: dict | None = None):
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=30.0
        ) as client:
            resp = await client.get(path, params=params)
            resp.raise_for_status()
            return resp.json()

    async def post(self, path: str, json: dict | None = None):
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=60.0
        ) as client:
            resp = await client.post(path, json=json)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def patch(self, path: str, json: dict | None = None):
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=60.0
        ) as client:
            resp = await client.patch(path, json=json)
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def delete(self, path: str):
        async with httpx.AsyncClient(
            base_url=self.base_url, headers=self._headers(), timeout=60.0
        ) as client:
            resp = await client.delete(path)
            resp.raise_for_status()
            return resp.json() if resp.content else {}
