"""Classify a document link: where it lives, its id there, and its likely medium (pure).

`classify_doc_url` is the one place canopy decides what a design-doc URL *is* (USER_FLOWS
§V5). It reads the **exact host** (never a substring, so `claude.ai.example.com` is just a web
page), parses the provider's document id, and canonicalizes the link so two spellings of one
document dedupe to one record:

* **Claude** — `https://claude.ai/artifact/[<title>-]<id>`, `…/code/artifact/<uuid>`,
  `…/public/artifacts/<uuid>` (also `preview.claude.ai`). The title prefix is dropped (it
  changes when the title does); an `#anchor` that points at one tab or screen is kept.
* **Google** — Docs / Sheets / Slides / Drawings and Drive files (`/d/<id>`, `?id=<id>`).
* **GitHub** — a blob path (`owner/repo/path`, independent of the branch or commit).
* **Figma** — file / design / proto / board / slides keys.
* **Confluence** and **Jira** — `*.atlassian.net` pages and issues.
* anything else over https is `web`.

Registration accepts only https (`strict=True`); the legacy add-link path stays lenient.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit, urlunsplit

from app.models.base import DocFormat, DocProvider

_CLAUDE_HOSTS = frozenset({"claude.ai", "www.claude.ai", "preview.claude.ai"})
_GOOGLE_DOC_HOSTS = frozenset({"docs.google.com"})
_DRIVE_HOSTS = frozenset({"drive.google.com"})
_GITHUB_HOSTS = frozenset({"github.com", "www.github.com"})
_FIGMA_HOSTS = frozenset({"figma.com", "www.figma.com"})

_UUID_RE = re.compile(
    r"([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$"
)
_SHORT_ID_RE = re.compile(r"^[A-Za-z0-9]{10,64}$")
_EXTERNAL_ID_MAX = 128

_GOOGLE_KINDS: dict[str, DocFormat] = {
    "document": DocFormat.document,
    "spreadsheets": DocFormat.sheet,
    "presentation": DocFormat.deck,
    "drawings": DocFormat.diagram,
    "forms": DocFormat.other,
}
_FIGMA_KINDS: dict[str, DocFormat] = {
    "file": DocFormat.canvas,
    "design": DocFormat.canvas,
    "proto": DocFormat.prototype,
    "board": DocFormat.canvas,
    "slides": DocFormat.deck,
}
_EXTENSION_FORMATS: dict[str, DocFormat] = {
    "md": DocFormat.document,
    "markdown": DocFormat.document,
    "rst": DocFormat.document,
    "txt": DocFormat.document,
    "adoc": DocFormat.document,
    "pdf": DocFormat.document,
    "html": DocFormat.page,
    "htm": DocFormat.page,
    "png": DocFormat.image,
    "jpg": DocFormat.image,
    "jpeg": DocFormat.image,
    "gif": DocFormat.image,
    "svg": DocFormat.diagram,
    "drawio": DocFormat.diagram,
    "mmd": DocFormat.diagram,
    "puml": DocFormat.diagram,
    "csv": DocFormat.sheet,
}


class DocUrlError(ValueError):
    """A link canopy will not register (not a URL, or not https under `strict`)."""


@dataclass(frozen=True)
class DocUrlInfo:
    provider: DocProvider
    external_id: str | None  # the provider's id for the document, when the URL carries one
    format_hint: DocFormat | None  # the medium the URL implies, if any
    url: str  # the canonical link to store (title slug dropped, anchor kept)
    anchor: str | None = None


def _clip(external_id: str | None) -> str | None:
    """An id longer than the column holds is no reliable identity — dedupe by URL instead."""
    if not external_id or len(external_id) > _EXTERNAL_ID_MAX:
        return None
    return external_id


def _claude(host: str, parts: list[str], anchor: str | None) -> DocUrlInfo | None:
    """`/artifact/<slug>`, `/code/artifact/<slug>`, `/public/artifacts/<uuid>`."""
    if len(parts) >= 2 and parts[0] == "artifact":
        prefix, slug = ["artifact"], parts[1]
    elif len(parts) >= 3 and parts[0] == "code" and parts[1] == "artifact":
        prefix, slug = ["code", "artifact"], parts[2]
    elif len(parts) >= 3 and parts[0] == "public" and parts[1] == "artifacts":
        prefix, slug = ["public", "artifacts"], parts[2]
    else:
        return None
    uuid = _UUID_RE.search(slug)
    if uuid:
        artifact_id = uuid.group(1).lower()
    else:
        tail = slug.rsplit("-", 1)[-1]
        if not _SHORT_ID_RE.match(tail):
            return None
        artifact_id = tail
    path = "/" + "/".join([*prefix, artifact_id])
    canonical = urlunsplit(("https", host, path, "", anchor or ""))
    return DocUrlInfo(
        provider=DocProvider.claude,
        external_id=_clip(artifact_id),
        format_hint=None,  # a doc, a page or a prototype — the session says which
        url=canonical,
        anchor=anchor,
    )


def _extension_format(path: str) -> DocFormat | None:
    name = path.rsplit("/", 1)[-1]
    if "." not in name:
        return None
    return _EXTENSION_FORMATS.get(name.rsplit(".", 1)[-1].lower())


def classify_doc_url(raw: str, *, strict: bool = True) -> DocUrlInfo:
    """Classify a document link. Raises `DocUrlError` for something that is not a URL, or —
    under `strict` — not https. Unknown hosts classify as `web` (still linkable)."""
    text = (raw or "").strip()
    try:
        parts = urlsplit(text)
    except ValueError as exc:
        raise DocUrlError(f"Not a URL: {text[:80]}") from exc
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower()
    if not host or scheme not in ("http", "https"):
        if strict:
            raise DocUrlError("A document link must be an https URL")
        return DocUrlInfo(DocProvider.web, None, None, text)
    if strict and scheme != "https":
        raise DocUrlError("A document link must be an https URL")
    anchor = parts.fragment or None
    segments = [s for s in parts.path.split("/") if s]

    if host in _CLAUDE_HOSTS:
        info = _claude(host, segments, anchor)
        if info is not None:
            return info
        return DocUrlInfo(DocProvider.claude, None, None, text, anchor)

    if host in _GOOGLE_DOC_HOSTS and len(segments) >= 3 and segments[1] == "d":
        fmt = _GOOGLE_KINDS.get(segments[0], DocFormat.document)
        return DocUrlInfo(DocProvider.gdrive, _clip(segments[2]), fmt, text, anchor)
    if host in _DRIVE_HOSTS:
        file_id: str | None = None
        if len(segments) >= 3 and segments[0] == "file" and segments[1] == "d":
            file_id = segments[2]
        elif segments[:1] in (["open"], ["uc"]):
            ids = parse_qs(parts.query).get("id") or []
            file_id = ids[0] if ids else None
        elif len(segments) >= 3 and segments[0] == "drive" and segments[1] == "folders":
            file_id = segments[2]
        return DocUrlInfo(DocProvider.gdrive, _clip(file_id), None, text, anchor)

    if host in _GITHUB_HOSTS:
        external_id: str | None = None
        fmt_hint: DocFormat | None = None
        if len(segments) >= 5 and segments[2] in ("blob", "raw"):
            owner, repo, path = segments[0], segments[1], "/".join(segments[4:])
            external_id = f"{owner}/{repo}/{path}"
            fmt_hint = _extension_format(path)
        return DocUrlInfo(DocProvider.github, _clip(external_id), fmt_hint, text, anchor)

    if host in _FIGMA_HOSTS:
        if len(segments) >= 2 and segments[0] in _FIGMA_KINDS:
            return DocUrlInfo(
                DocProvider.figma, _clip(segments[1]), _FIGMA_KINDS[segments[0]], text, anchor
            )
        return DocUrlInfo(DocProvider.figma, None, DocFormat.canvas, text, anchor)

    if host.endswith(".atlassian.net"):
        if segments[:1] == ["wiki"]:
            page_id = None
            if "pages" in segments:
                at = segments.index("pages")
                if at + 1 < len(segments) and segments[at + 1].isdigit():
                    page_id = f"{host}/{segments[at + 1]}"
            return DocUrlInfo(
                DocProvider.confluence, _clip(page_id), DocFormat.document, text, anchor
            )
        if len(segments) >= 2 and segments[0] == "browse":
            return DocUrlInfo(
                DocProvider.jira, _clip(f"{host}/{segments[1].upper()}"), None, text, anchor
            )

    return DocUrlInfo(DocProvider.web, None, _extension_format(parts.path), text, anchor)


def same_document_key(info: DocUrlInfo) -> tuple[str, str]:
    """The identity two registrations of one document share: provider + id when the URL carries
    one, else the canonical URL without its anchor."""
    if info.external_id:
        return (info.provider.value, info.external_id)
    return (info.provider.value, info.url.split("#", 1)[0])
