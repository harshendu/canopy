"""Pull-request review and check signals (pure, unit-tested) — docs/AGENT_EXECUTION.md §11.3.

GitHub reports a PR's state in pieces: the PR itself (`pull_request`), each review
(`pull_request_review`), and each check suite / check run / commit status. canopy keeps the
latest review per reviewer and every check seen at the PR's current head, and rolls them up
here into the three facts stage checks and gates read:

* `checks_state` — `failing` if any check failed, `pending` if any is still running, `passing`
  when at least one succeeded and none is failing or pending. A `neutral` or `skipped` check is
  neither a pass nor a failure (Bugbot reports `neutral` by default); with nothing but neutral
  checks the state stays None.
* `approved_by` — logins whose latest review approves the **current head**. An approval of an
  older commit is stale and does not count, the way "Require approval of the most recent
  reviewable push" treats it.
* `review_decision` — `changes_requested` while any reviewer's latest review requests changes
  (until they re-review or it is dismissed, as on GitHub), else `approved` when someone approved
  the current head, else `review_required` once any review exists; None before the first review.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

# Normalised check states.
SUCCESS = "success"
FAILURE = "failure"
PENDING = "pending"
NEUTRAL = "neutral"

_FAILED_CONCLUSIONS = frozenset(
    {"failure", "timed_out", "cancelled", "action_required", "startup_failure", "stale", "error"}
)
_NEUTRAL_CONCLUSIONS = frozenset({"neutral", "skipped"})
_BODY_LIMIT = 2000


def normalize_check(status: str | None, conclusion: str | None) -> str:
    """One check run / suite / commit status as success | failure | pending | neutral.

    `status` is a check's lifecycle (queued | in_progress | completed, or a commit status's
    pending | success | failure | error); `conclusion` is set once a check completes."""
    value = (conclusion or "").strip().lower()
    state = (status or "").strip().lower()
    if not value and state in ("success", "failure", "error", "pending"):
        value = state  # a commit status carries its outcome in `state`
    if value == "success":
        return SUCCESS
    if value in _FAILED_CONCLUSIONS:
        return FAILURE
    if value in _NEUTRAL_CONCLUSIONS:
        return NEUTRAL
    return PENDING


def roll_up_checks(checks: Mapping[str, str]) -> str | None:
    """`failing` | `pending` | `passing` | None (no check that counts)."""
    states = set(checks.values())
    if FAILURE in states:
        return "failing"
    if PENDING in states:
        return "pending"
    if SUCCESS in states:
        return "passing"
    return None


def record_review(
    reviews: Iterable[Mapping[str, Any]], review: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """The latest-review-per-reviewer list after `review` (a webhook `review` object or the
    same shape from ingest). A dismissed review removes that reviewer's verdict; a plain comment
    does not replace an earlier approval or change request (GitHub keeps the verdict)."""
    user = review.get("user")
    nested = user.get("login") if isinstance(user, Mapping) else None
    login = str(nested or review.get("login") or "").strip()
    if not login:
        return [dict(r) for r in reviews]
    state = str(review.get("state") or "").strip().lower()
    kept = [dict(r) for r in reviews if str(r.get("login")) != login]
    previous = next((dict(r) for r in reviews if str(r.get("login")) == login), None)
    if state == "dismissed":
        return kept
    if state == "commented" and previous is not None and previous.get("state") in (
        "approved",
        "changes_requested",
    ):
        return [*kept, previous]
    body = str(review.get("body") or "")[:_BODY_LIMIT]
    kept.append(
        {
            "login": login,
            "state": state or "commented",
            "commit_id": review.get("commit_id"),
            "submitted_at": review.get("submitted_at"),
            "body": body,
        }
    )
    return kept


def approvals_at_head(reviews: Iterable[Mapping[str, Any]], head_sha: str | None) -> list[str]:
    """Logins whose latest review approves `head_sha` (any approval when the head is unknown)."""
    out: list[str] = []
    for review in reviews:
        if review.get("state") != "approved":
            continue
        if head_sha and review.get("commit_id") and review.get("commit_id") != head_sha:
            continue
        login = str(review.get("login") or "")
        if login and login not in out:
            out.append(login)
    return out


def review_decision(reviews: Iterable[Mapping[str, Any]], head_sha: str | None) -> str | None:
    rows = list(reviews)
    if not rows:
        return None
    if any(r.get("state") == "changes_requested" for r in rows):
        return "changes_requested"
    if approvals_at_head(rows, head_sha):
        return "approved"
    return "review_required"


def latest_change_request(reviews: Iterable[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    """The most recent review that requests changes (its body is the note a gate routes with)."""
    pending = [r for r in reviews if r.get("state") == "changes_requested"]
    if not pending:
        return None
    return max(pending, key=lambda r: str(r.get("submitted_at") or ""))
