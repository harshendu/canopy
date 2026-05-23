---
name: writing-adrs
description: Captures architecture decisions as ADRs (Architecture Decision Records) in canopy using a consistent template. Use when the architect makes or revisits a significant technical decision, asks to "write an ADR", documents a tradeoff, or supersedes a previous decision.
---

# Writing ADRs in canopy

An ADR records one architecturally significant decision: the context/forces, the
decision made, and its consequences. Use this whenever a choice will be expensive to
reverse or future engineers will ask "why did we do it this way?".

## Workflow

1. Identify the `project_id` (`canopy:list_projects`).
2. Draft the ADR using the template in `reference/adr-template.md`. Keep each section
   tight — context (the forces and constraints), decision (what we will do, in active
   voice), consequences (what becomes easier and harder, including risks).
3. Record it with `canopy:create_adr` (project_id, title, context, decision,
   consequences). The ADR number is assigned automatically; status starts as
   `proposed`.
4. If this decision replaces an earlier one, say so explicitly in the context and note
   that the prior ADR should move to `superseded` (the app tracks the supersession
   chain).

## Good ADRs
- One decision per ADR. Title states the decision, not the topic
  ("Use Postgres for the primary store", not "Database").
- Capture the alternatives considered and why they lost — that's the durable value.
- Link the components and PRs the decision affects.
- Status lifecycle: proposed → accepted → (later) superseded / deprecated.
