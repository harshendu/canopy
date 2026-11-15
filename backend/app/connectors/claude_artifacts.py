"""Claude artifacts — the optional organization metadata sync (USER_FLOWS §V11).

An Enterprise organization can give canopy a **Compliance API** key so the server watches the
*metadata* of the Claude docs and artifacts it already tracks — the published version, who can
open them (`read_mode`), and whether they still exist — without a session opening each one.
The connector calls only the **list** endpoint: never a content download, never a delete. The
key is stored Fernet-encrypted like every connector token, and only an admin configures it.

Config: `base_url` (default `https://api.anthropic.com`), `api_version` (the
`anthropic-version` header), optional `organization_ids` (a list). Token: the Compliance API key.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx

from app.connectors.base import Connector, SyncResult, register
from app.connectors.http import request_with_retry
from app.models.base import Provider

API_BASE = "https://api.anthropic.com"
API_VERSION = "2026-10-21"
LIST_PATH = "/v1/compliance/apps/code/artifacts"
_PAGE_SIZE = 100
_MAX_PAGES = 50

_TAGGED_RE = re.compile(r"^[a-z]+_(.+)$")
_BASE58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
_BASE58_INDEX = {c: i for i, c in enumerate(_BASE58)}


@dataclass(frozen=True)
class ArtifactMeta:
    """One artifact as the Compliance API lists it — metadata only, never content."""

    id: str  # a tagged id, e.g. "cart_01…"
    artifact_type: str  # code | claude_docs | claude_slides | claude_design | … | other
    read_mode: str  # owner | users | org | public
    owner_user_id: str | None
    owner_email: str | None
    updated_at: datetime | None  # naive UTC
    published_version_id: str | None  # null for a Claude Doc or Sheet
    latest_version_id: str | None  # the newest listed version (empty list for Docs/Sheets)
    title: str | None  # the newest version's name

    @property
    def version_label(self) -> str | None:
        """The version a non-owner viewer gets — what a session records for a page artifact."""
        return self.published_version_id or self.latest_version_id


@dataclass
class ArtifactListing:
    items: list[ArtifactMeta] = field(default_factory=list)
    # False when the page cap stopped the walk early — "not listed" then proves nothing.
    complete: bool = True


def parse_time(value: Any) -> datetime | None:
    """An RFC 3339 timestamp → naive UTC (how canopy stores every datetime)."""
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(UTC).replace(tzinfo=None)
    return parsed


def parse_artifact(raw: dict[str, Any]) -> ArtifactMeta | None:
    """One list row → `ArtifactMeta` (pure). Rows without an id are skipped."""
    artifact_id = raw.get("id")
    if not isinstance(artifact_id, str) or not artifact_id:
        return None
    user = raw.get("user")
    user = user if isinstance(user, dict) else {}
    versions = [v for v in raw.get("versions") or [] if isinstance(v, dict) and v.get("id")]
    newest = max(versions, key=lambda v: str(v.get("created_at") or ""), default=None)
    published = raw.get("published_version_id")
    owner = raw.get("owner_user_id") or user.get("id")
    email = user.get("email_address")
    return ArtifactMeta(
        id=artifact_id,
        artifact_type=str(raw.get("artifact_type") or "other"),
        read_mode=str(raw.get("read_mode") or "owner"),
        owner_user_id=str(owner) if owner else None,
        owner_email=str(email).strip().lower() if email else None,
        updated_at=parse_time(raw.get("updated_at")),
        published_version_id=str(published) if published else None,
        latest_version_id=str(newest["id"]) if newest else None,
        title=str(newest["name"]) if newest and newest.get("name") else None,
    )


def _base58_uuid(text: str) -> str | None:
    """Decode a base58 string to a 16-byte UUID (hyphenated), or None."""
    value = 0
    for char in text:
        digit = _BASE58_INDEX.get(char)
        if digit is None:
            return None
        value = value * 58 + digit
    if value >= 1 << 128:
        return None
    raw = f"{value:032x}"
    return f"{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"


def candidate_ids(artifact_id: str) -> set[str]:
    """The forms an artifact's tagged id may take inside a claude.ai link (pure).

    The Compliance API returns tagged ids (`cart_01…`); a claude.ai link carries a short id
    (`/artifact/<id>`) or a UUID (`/code/artifact/<uuid>`). Their relation is **not
    documented**, so pairing tries the id as listed, without its tag, without the tag's `01`
    version marker, and that body read as a base58 UUID. A form that matches nothing costs
    nothing; ids are 128-bit, so a wrong pairing is not a practical risk. A pairing found once
    is recorded (`ExternalRef`) and wins from then on, and the sync report counts the tracked
    docs that stayed unmatched so an admin can see whether pairing works for their organization.
    """
    out = {artifact_id}
    tagged = _TAGGED_RE.match(artifact_id)
    if tagged:
        body = tagged.group(1)
        out.add(body)
        if body.startswith("01") and len(body) > 2:
            short = body[2:]
            out.add(short)
            uuid = _base58_uuid(short)
            if uuid:
                out.add(uuid)
    return out


@register(Provider.claude)
class ClaudeArtifactsConnector(Connector):
    def _client(self) -> httpx.AsyncClient:
        token = self.access_token() or ""
        return httpx.AsyncClient(
            base_url=str(self.config.get("base_url") or API_BASE),
            headers={
                "Authorization": f"Bearer {token}",
                "anthropic-version": str(self.config.get("api_version") or API_VERSION),
            },
            timeout=30.0,
        )

    async def list_artifacts(
        self,
        *,
        updated_since: datetime | None = None,
        user_ids: list[str] | None = None,
        max_pages: int = _MAX_PAGES,
    ) -> ArtifactListing:
        """Every artifact the key may read — optionally only those updated since a moment, or
        owned by given users — across pages. Pages may be short or empty while `next_page` is
        set, so the walk continues until it is absent (or the page cap is hit)."""
        params: dict[str, Any] = {"limit": _PAGE_SIZE}
        if updated_since is not None:
            params["updated_at[gte]"] = updated_since.replace(microsecond=0).isoformat() + "Z"
        if user_ids:
            params["user_ids[]"] = list(user_ids)
        org_ids = self.config.get("organization_ids")
        if isinstance(org_ids, list) and org_ids:
            params["organization_ids[]"] = [str(o) for o in org_ids]
        listing = ArtifactListing()
        async with await self.open_client() as client:
            for _ in range(max_pages):
                resp = await request_with_retry(client, "GET", LIST_PATH, params=params)
                data: dict[str, Any] = resp.json()
                for raw in data.get("data") or []:
                    meta = parse_artifact(raw) if isinstance(raw, dict) else None
                    if meta is not None:
                        listing.items.append(meta)
                next_page = data.get("next_page")
                if not next_page:
                    return listing
                params["page"] = str(next_page)
        listing.complete = False
        return listing

    async def full_sync(self) -> SyncResult:
        from app.services import claude_sync

        report = await claude_sync.sync_connection(self, full=True)
        return SyncResult(provider=Provider.claude.value, updated=report.updated)

    async def incremental_sync(self, since: str | None = None) -> SyncResult:
        from app.services import claude_sync

        report = await claude_sync.sync_connection(self, full=False)
        return SyncResult(provider=Provider.claude.value, updated=report.updated)
