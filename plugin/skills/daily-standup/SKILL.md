---
name: daily-standup
description: Synthesizes a manage-by-exception standup / health digest for an initiative (or across initiatives) — what moved, what's blocked, what's awaiting a decision, what drifted, and what's most likely to slip the date. Use for a morning briefing, a weekly leadership update, or whenever someone asks "where do things stand?" / "what needs my attention?".
---

# Daily standup / health digest

The architect's highest-leverage recurring surface: one proactive briefing that watches the
breadth so a human can spend attention on the depth. **Manage by exception** — lead with what's
off-track and what needs a decision; green is silent (but a project *flying blind*, with no
signal, is flagged, not assumed green). See `docs/AI_NATIVE_EXECUTION.md` §5.

## Workflow

1. **Pick the scope.** `canopy:list_initiatives` → the initiative(s) to brief on (or the one the
   user named).

2. **Get the digest.** `canopy:get_initiative_digest(initiative_id)` returns the spine:
   - `headline` + `attention` — the exception list (behind target, P85 past target, elevated
     risk/drift, open blockers, decisions awaiting, at-risk sub-projects).
   - status (progress, forecast P85 vs target, risk/drift, open blockers/decisions), `outcomes`,
     and a ready-to-send `markdown` rendering.

3. **Drill where it matters.** For each attention item, pull the detail so the briefing is
   actionable (don't just restate the count):
   - blocked work → `canopy:list_blockers(project_id, open_only=true)` (who owns the unblock).
   - decisions awaiting → `canopy:decision_queue(project_id)` (which are stuck / past decide-by).
   - drift opened → `canopy:get_drift(project_id)`.
   - most likely to slip → `canopy:get_forecast(initiative_id=…)` (P50/P85) and the cross-project
     critical path `canopy:get_initiative_critical_path(initiative_id)` (the hand-offs).
   - outcomes off-track → `canopy:list_outcomes(scope_level="initiative", scope_id=…)`.

4. **Write the briefing.** Lead with the **headline** and a tight **"needs attention / needs a
   decision"** list (each with the owner and the one next action), then a one-line status, then
   the outcomes. Keep it scannable — this is read every day. The digest's `markdown` is a good
   starting point; enrich it with the drill-down detail.

## Notes
- **Altitude:** keep it exception-first and short. Don't dump every task — surface the few things
  that need a human.
- **Delivery** to Slack/email isn't built in canopy yet — post the briefing wherever the team
  reads (the digest content is the deliverable; delivery is a hook over it).
- This composes existing read tools and writes nothing; safe to run on any cadence (see `/loop`).
