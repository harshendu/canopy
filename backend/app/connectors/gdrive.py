"""Google Drive connector (thin).

Reads design docs from Drive on demand: list Google Docs and export them to
markdown. Auth: user OAuth access token (scope drive.readonly). For the slice the
architect supplies an access token; a full OAuth dance is the production path.
"""

from __future__ import annotations

import httpx

from app.connectors.base import Connector, SyncResult, register
from app.models.base import Provider

_API = "https://www.googleapis.com/drive/v3"
_DOC_MIME = "application/vnd.google-apps.document"


@register(Provider.gdrive)
class GoogleDriveConnector(Connector):
    def _client(self) -> httpx.AsyncClient:
        token = self.access_token() or ""
        return httpx.AsyncClient(
            base_url=_API,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def list_design_docs(self, query: str | None = None) -> list[dict]:
        q = f"mimeType='{_DOC_MIME}'"
        if query:
            q += f" and name contains '{query}'"
        async with self._client() as client:
            resp = await client.get(
                "/files",
                params={"q": q, "fields": "files(id,name,modifiedTime)", "pageSize": 50},
            )
            resp.raise_for_status()
            data = resp.json()
        return list(data.get("files", []))

    async def export_doc(self, file_id: str) -> str:
        """Export a Google Doc to markdown text."""
        async with self._client() as client:
            resp = await client.get(
                f"/files/{file_id}/export", params={"mimeType": "text/markdown"}
            )
            resp.raise_for_status()
            return resp.text

    async def full_sync(self) -> SyncResult:
        return SyncResult(provider="gdrive")

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        return SyncResult(provider="gdrive")
