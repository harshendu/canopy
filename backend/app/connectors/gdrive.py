"""Google Drive connector (thin).

Reads design docs from Drive on demand: list Google Docs and export them to
markdown. Also uploads export-snapshot artifacts (PDF/CSV) to Drive so a point-in-time
snapshot can be stored outside canopy (a write path used only for generated artifacts —
canopy still does not own the design docs it reads). Auth: user OAuth access token
(scope drive.file/drive for uploads).
"""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import httpx

from app.connectors.base import Connector, SyncResult, register
from app.connectors.http import request_with_retry
from app.models.base import Provider

_API = "https://www.googleapis.com/drive/v3"
_UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3/files"
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

    async def list_design_docs(self, query: str | None = None) -> list[dict[str, Any]]:
        q = f"mimeType='{_DOC_MIME}'"
        if query:
            q += f" and name contains '{query}'"
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client,
                "GET",
                "/files",
                params={"q": q, "fields": "files(id,name,modifiedTime)", "pageSize": 50},
            )
            data: dict[str, Any] = resp.json()
        return list(data.get("files", []))

    async def export_doc(self, file_id: str) -> str:
        """Export a Google Doc to markdown text."""
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client, "GET", f"/files/{file_id}/export", params={"mimeType": "text/markdown"}
            )
            return resp.text

    async def upload_file(self, *, name: str, content: bytes, mime_type: str) -> dict[str, Any]:
        """Upload bytes to Drive as a new file (multipart/related). Returns the created
        file's metadata ({id, name, webViewLink}). Used to store export snapshots."""
        folder_id = self.config.get("folder_id")
        metadata: dict[str, Any] = {"name": name}
        if folder_id:
            metadata["parents"] = [str(folder_id)]
        boundary = f"canopy{uuid4().hex}"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/json; charset=UTF-8\r\n\r\n"
            f"{json.dumps(metadata)}\r\n"
            f"--{boundary}\r\n"
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
        async with await self.open_client() as client:
            resp = await request_with_retry(
                client,
                "POST",
                f"{_UPLOAD_URL}?uploadType=multipart&fields=id,name,webViewLink",
                content=body,
                headers={"Content-Type": f"multipart/related; boundary={boundary}"},
            )
            data: dict[str, Any] = resp.json()
        return data

    async def full_sync(self) -> SyncResult:
        return SyncResult(provider="gdrive")

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        return SyncResult(provider="gdrive")
