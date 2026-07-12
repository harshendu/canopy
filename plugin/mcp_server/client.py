"""Thin authenticated HTTP client for the canopy FastAPI backend.

Configuration comes from the environment (set by the plugin's .mcp.json from the
user's plugin config, or exported directly for standalone / cloud Claude sessions):
  CANOPY_API_BASE_URL   e.g. http://localhost:8000  (or your production API URL)
  CANOPY_API_TOKEN      a JWT from POST /api/v1/auth/login
  CANOPY_API_EMAIL      alternative to a static token: a canopy (service) account the
  CANOPY_API_PASSWORD   client logs in as — and re-logs-in when the JWT expires, so a
                        long-lived MCP service never needs manual token rotation

Empty values are treated as unset so a blank plugin config doesn't clobber an env var
provided by the surrounding (e.g. cloud) session. A static CANOPY_API_TOKEN wins over
email/password until it expires; then the login fallback takes over.
"""

from __future__ import annotations

import os

import httpx


class CanopyClient:
    def __init__(self) -> None:
        base = (os.environ.get("CANOPY_API_BASE_URL") or "http://localhost:8000").rstrip("/")
        self.base_url = f"{base}/api/v1"
        self.token = os.environ.get("CANOPY_API_TOKEN") or ""
        self.email = os.environ.get("CANOPY_API_EMAIL") or ""
        self.password = os.environ.get("CANOPY_API_PASSWORD") or ""

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    async def _login(self, client: httpx.AsyncClient) -> bool:
        """Mint a fresh JWT from the configured service account, if one is set."""
        if not (self.email and self.password):
            return False
        resp = await client.post(
            "/auth/login", data={"username": self.email, "password": self.password}
        )
        if resp.status_code != 200:
            return False
        self.token = str(resp.json().get("access_token") or "")
        return bool(self.token)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        timeout: float = 60.0,
    ):
        async with httpx.AsyncClient(base_url=self.base_url, timeout=timeout) as client:
            if not self.token and self.email:
                await self._login(client)
            resp = await client.request(
                method, path, params=params, json=json, headers=self._headers()
            )
            if resp.status_code == 401 and await self._login(client):
                # The stored token expired (or was revoked): one re-login + retry.
                resp = await client.request(
                    method, path, params=params, json=json, headers=self._headers()
                )
            resp.raise_for_status()
            return resp.json() if resp.content else {}

    async def get(self, path: str, params: dict | None = None):
        return await self._request("GET", path, params=params, timeout=30.0)

    async def post(self, path: str, json: dict | None = None):
        return await self._request("POST", path, json=json)

    async def patch(self, path: str, json: dict | None = None):
        return await self._request("PATCH", path, json=json)

    async def delete(self, path: str):
        return await self._request("DELETE", path)
