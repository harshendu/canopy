"""Design-doc health flags (pure): what makes a doc need a look (USER_FLOWS §V8)."""

from datetime import date, datetime, timedelta

from app.services.doc_health import (
    HealthDoc,
    HealthLink,
    doc_health,
    needs_attention,
    needs_check,
)

NOW = datetime(2026, 11, 15, 12, 0)


def _doc(**over) -> HealthDoc:
    base = {
        "id": 1,
        "title": "Checkout design",
        "provider": "claude",
        "visibility": "org",
        "personal": False,
        "review_status": "draft",
        "current_version": "r3",
        "approved_version": None,
        "last_checked_at": NOW - timedelta(days=1),
        "link_health": "ok",
    }
    base.update(over)
    return HealthDoc(**base)


def _flags(doc: HealthDoc, links: list[HealthLink] | None = None) -> list[str]:
    return [
        f.flag
        for f in doc_health(doc, links or [], now=NOW, check_days=14, gate_window_days=14)
    ]


def test_a_healthy_doc_raises_nothing() -> None:
    assert _flags(_doc()) == []


def test_check_flags() -> None:
    assert _flags(_doc(last_checked_at=None)) == ["unverified"]
    # only Claude docs are "unverified"; any tracked doc can be due a check
    assert _flags(_doc(provider="gdrive", last_checked_at=None)) == []
    stale = _doc(provider="gdrive", last_checked_at=NOW - timedelta(days=20))
    assert _flags(stale) == ["check_due"]
    # an untracked plain link is never "due"
    assert _flags(_doc(review_status=None, last_checked_at=NOW - timedelta(days=99))) == []
    flags = doc_health(stale, [], now=NOW, check_days=14, gate_window_days=14)
    assert needs_check(flags) and not needs_attention(flags)


def test_changed_since_approval_and_behind_pin() -> None:
    doc = _doc(review_status="approved", approved_version="r12", current_version="r14")
    pinned = HealthLink("decision", 7, "basis", pinned_version="r12", label="ADR-0007 Bus")
    current = HealthLink("spec", 2, "basis", pinned_version="r14")
    flags = doc_health(doc, [pinned, current], now=NOW, check_days=14, gate_window_days=14)
    assert [f.flag for f in flags] == ["changed_since_approval", "behind_pin"]
    behind = flags[1]
    assert (behind.entity_type, behind.entity_id) == ("decision", 7)
    assert "ADR-0007 Bus" in behind.message and "r12" in behind.message
    assert needs_attention(flags)


def test_gate_open_near_a_milestone_or_on_a_draft_spec() -> None:
    near = HealthLink(
        "milestone", 4, "gate", label="Checkout GA",
        target_date=date(2026, 11, 20), target_status="planned",
    )
    far = HealthLink(
        "milestone", 5, "gate", target_date=date(2027, 3, 1), target_status="planned"
    )
    hit = HealthLink(
        "milestone", 6, "gate", target_date=date(2026, 11, 1), target_status="hit"
    )
    spec = HealthLink("spec", 9, "gate", target_status="draft")
    assert _flags(_doc(), [near, far, hit, spec]) == ["gate_open", "gate_open"]
    # an approved doc opens its gates
    assert _flags(_doc(review_status="approved", approved_version="r3"), [near, spec]) == []


def test_restricted_broken_and_quiet_docs() -> None:
    assert _flags(_doc(visibility="owner")) == ["restricted"]
    assert _flags(_doc(link_health="broken")) == ["broken"]
    # superseded and archived docs raise nothing
    assert _flags(_doc(review_status="superseded", visibility="owner")) == []
    assert _flags(_doc(review_status="archived", link_health="broken")) == []
    # a personal doc raises check flags only — never alerts on shared work
    personal = _doc(personal=True, visibility="owner", last_checked_at=None, review_status=None)
    assert _flags(personal) == ["unverified"]
