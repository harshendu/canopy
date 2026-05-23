---
name: writing-adrs
description: Captures and shepherds architecture decisions as ADRs (Architecture Decision Records) in canopy. Use when the architect makes or revisits a significant technical decision, asks to "write an ADR", proposes a decision for review, runs a decision through its review lifecycle, documents a tradeoff, or supersedes a previous decision.
---

# Writing & shepherding ADRs in canopy

An ADR records one architecturally significant decision: the context/forces, the
decision made, the alternatives weighed, and its consequences. In canopy the decision
(not the task) is the unit of work — an ADR carries an owner, stakeholders who review
it, a discussion thread, and a review lifecycle.

## Recording a decision (architect)

1. Identify the `project_id` (`canopy:list_projects`).
2. Draft the ADR using the template in `reference/adr-template.md`. Keep each section
   tight — context (forces/constraints), decision (what we will do, active voice),
   consequences (what gets easier/harder), and the alternatives considered.
3. Record it with `canopy:create_adr` (project_id, title, context, decision,
   consequences, `alternatives`, `reversibility` = one_way|two_way, `decision_owner_id`,
   `stakeholder_ids`). The number is assigned automatically; status starts `proposed`.
4. If it replaces an earlier decision, say so in the context and move the prior ADR to
   `superseded` via `canopy:transition_adr` (the app tracks the supersession chain).

## Proposing a decision (engineer)

- Use `canopy:propose_adr` (requires `proposed_by_id`) to raise a decision for the owner
  to triage. It lands in `proposed`. Most decisions *should* originate this way.

## Running the review lifecycle

- Lifecycle: `proposed → under_discussion → accepted | rejected → superseded | deprecated`,
  plus `deferred` (a conscious postponement — requires a `decide_by` date). Move between
  states with `canopy:transition_adr`; only legal transitions are accepted.
- Discuss with `canopy:comment_adr`. A `kind` of approve / request_changes / reject is a
  formal review action (attribute it with `engineer_id`); plain `comment` is just a note.
- `canopy:get_adr` shows the thread and a review summary (who approved, what's pending,
  and whether the project's decision rule is satisfied to accept).
- `canopy:decision_queue` is the morning surface: what needs triage, what's stuck in
  discussion, and which deferred decisions are coming due.

## Good ADRs
- One decision per ADR. Title states the decision, not the topic
  ("Use Postgres for the primary store", not "Database").
- Capture the alternatives considered and why they lost — that's the durable value.
- Set reversibility honestly: one-way doors deserve more scrutiny than two-way doors.
- Link the components and PRs the decision affects; tag the stakeholders who must review.
