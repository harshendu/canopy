"""The design-doc URL classifier (pure) and its frozen copy in the design-docs migration."""

import importlib.util
import pathlib

import pytest

from app.models.base import DocFormat, DocProvider
from app.services.doc_kinds import fallback_info, humanize, normalize_slug
from app.services.doc_urls import DocUrlError, classify_doc_url, same_document_key

_ID = "FeJDTrUMxp1SgJzj8o4inL"
_UUID = "5fbea6f3-0b1c-4d2e-8f3a-1b2c3d4e5f6a"


@pytest.mark.parametrize(
    ("url", "external_id", "canonical"),
    [
        (f"https://claude.ai/artifact/{_ID}", _ID, f"https://claude.ai/artifact/{_ID}"),
        # a title-prefixed slug drops the title (it changes when the title does)
        (
            f"https://claude.ai/artifact/checkout-design-v2-{_ID}",
            _ID,
            f"https://claude.ai/artifact/{_ID}",
        ),
        # Claude Code artifacts use a UUID, optionally title-prefixed
        (
            f"https://claude.ai/code/artifact/{_UUID}",
            _UUID,
            f"https://claude.ai/code/artifact/{_UUID}",
        ),
        (
            f"https://claude.ai/code/artifact/funnel-fix-{_UUID.upper()}",
            _UUID,
            f"https://claude.ai/code/artifact/{_UUID}",
        ),
        (
            f"https://preview.claude.ai/artifact/{_ID}",
            _ID,
            f"https://preview.claude.ai/artifact/{_ID}",
        ),
        (
            f"https://claude.ai/public/artifacts/{_UUID}",
            _UUID,
            f"https://claude.ai/public/artifacts/{_UUID}",
        ),
        # an anchor that points at one tab or screen is kept
        (
            f"https://claude.ai/artifact/{_ID}#overview",
            _ID,
            f"https://claude.ai/artifact/{_ID}#overview",
        ),
    ],
)
def test_claude_link_shapes(url: str, external_id: str, canonical: str) -> None:
    info = classify_doc_url(url)
    assert info.provider == DocProvider.claude
    assert info.external_id == external_id
    assert info.url == canonical


def test_one_artifact_one_identity_whatever_the_spelling() -> None:
    keys = {
        same_document_key(classify_doc_url(u))
        for u in (
            f"https://claude.ai/artifact/{_ID}",
            f"https://claude.ai/artifact/old-title-{_ID}",
            f"https://claude.ai/artifact/{_ID}#flows",
        )
    }
    assert keys == {("claude", _ID)}


def test_non_https_is_refused_under_strict_only() -> None:
    with pytest.raises(DocUrlError):
        classify_doc_url(f"http://claude.ai/artifact/{_ID}")
    with pytest.raises(DocUrlError):
        classify_doc_url("javascript:alert(1)")
    with pytest.raises(DocUrlError):
        classify_doc_url("not a url")
    lenient = classify_doc_url("http://intranet/design", strict=False)
    assert lenient.provider == DocProvider.web


@pytest.mark.parametrize(
    "url",
    [
        f"https://claude.ai.example.com/artifact/{_ID}",
        f"https://evilclaude.ai/artifact/{_ID}",
        f"https://example.com/claude.ai/artifact/{_ID}",
        "https://docs.google.com.example.com/document/d/abc/edit",
        "https://github.com.example.com/acme/repo/blob/main/README.md",
    ],
)
def test_lookalike_hosts_are_plain_web_pages(url: str) -> None:
    info = classify_doc_url(url)
    assert info.provider == DocProvider.web
    assert info.external_id is None


def test_other_providers() -> None:
    gdoc = classify_doc_url("https://docs.google.com/document/d/abc123/edit")
    assert (gdoc.provider, gdoc.external_id, gdoc.format_hint) == (
        DocProvider.gdrive, "abc123", DocFormat.document
    )
    sheet = classify_doc_url("https://docs.google.com/spreadsheets/d/s1/edit#gid=0")
    assert sheet.format_hint == DocFormat.sheet
    drive = classify_doc_url("https://drive.google.com/open?id=f42")
    assert (drive.provider, drive.external_id) == (DocProvider.gdrive, "f42")
    blob = classify_doc_url("https://github.com/acme/shop/blob/main/docs/adr/0007.md")
    assert (blob.provider, blob.external_id, blob.format_hint) == (
        DocProvider.github, "acme/shop/docs/adr/0007.md", DocFormat.document
    )
    # the same file on another branch is the same document
    assert same_document_key(blob) == same_document_key(
        classify_doc_url("https://github.com/acme/shop/blob/release-2/docs/adr/0007.md")
    )
    proto = classify_doc_url("https://www.figma.com/proto/KEY9/Checkout?node-id=1")
    assert (proto.provider, proto.external_id, proto.format_hint) == (
        DocProvider.figma, "KEY9", DocFormat.prototype
    )
    page = classify_doc_url("https://acme.atlassian.net/wiki/spaces/ENG/pages/12345/Design")
    assert (page.provider, page.external_id) == (DocProvider.confluence, "acme.atlassian.net/12345")
    issue = classify_doc_url("https://acme.atlassian.net/browse/shop-12")
    assert (issue.provider, issue.external_id) == (DocProvider.jira, "acme.atlassian.net/SHOP-12")
    web = classify_doc_url("https://wiki.example.com/diagrams/flow.svg")
    assert (web.provider, web.format_hint) == (DocProvider.web, DocFormat.diagram)


def test_an_overlong_id_falls_back_to_url_identity() -> None:
    path = "/".join(["deep"] * 40) + "/design.md"
    info = classify_doc_url(f"https://github.com/acme/shop/blob/main/{path}")
    assert info.external_id is None
    assert same_document_key(info)[1].startswith("https://github.com/acme/shop/blob/main/")


def test_kind_slugs_are_open_and_normalized() -> None:
    assert normalize_slug("Threat Model") == "threat_model"
    assert normalize_slug("tech-design") == "tech_design"
    assert normalize_slug("  API / contract!! ") == "api_contract"
    assert normalize_slug("") == "other"
    assert normalize_slug(None) == "other"
    assert len(normalize_slug("x" * 200)) == 48
    assert humanize("threat_model") == "Threat model"
    # a built-in kind keeps its stage; an unknown one lands under `other`
    assert fallback_info("prd").stage == "define"
    assert fallback_info("prd").expected is True
    assert fallback_info("threat_model").stage == "other"


def _migration_classifier():
    path = next(
        pathlib.Path(__file__).resolve().parents[1].joinpath("alembic", "versions").glob(
            "0b1c2d3e4f5a_*.py"
        )
    )
    spec = importlib.util.spec_from_file_location("design_docs_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.classify


@pytest.mark.parametrize(
    "url",
    [
        f"https://claude.ai/artifact/title-{_ID}#tab",
        f"https://claude.ai/code/artifact/{_UUID}",
        "https://docs.google.com/presentation/d/deck1/edit",
        "https://drive.google.com/file/d/f1/view",
        "https://github.com/acme/shop/blob/main/docs/design.md",
        "https://www.figma.com/board/B1/Map",
        "https://acme.atlassian.net/wiki/spaces/X/pages/77/T",
        "https://acme.atlassian.net/browse/ab-1",
        "https://wiki.example.com/page.html",
    ],
)
def test_migration_backfill_classifies_like_the_app(url: str) -> None:
    """The migration carries a frozen copy of the classifier; on the links it backfills it must
    agree with the app, or a later registration would not dedupe against migrated rows."""
    provider, external_id, fmt, canonical = _migration_classifier()(url)
    info = classify_doc_url(url, strict=False)
    assert provider == info.provider.value
    assert external_id == info.external_id
    assert fmt == (info.format_hint.value if info.format_hint else None)
    assert canonical == info.url
