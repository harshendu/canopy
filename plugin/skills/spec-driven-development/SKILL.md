---
name: spec-driven-development
description: Turns intent into a reviewable spec with explicit, checkable acceptance criteria before work begins, links the implementing work, and self-audits each criterion against the implementation afterward. Use when starting a new slice of work, when an architect/PM wants to capture "what done looks like", when converting a PRD/design doc into engineering intent, or when verifying that completed work actually met its acceptance criteria.
---

# Spec-driven development

**Intent is the source of truth.** In the age of AI, the spec — not the code — is the
bottleneck and the artifact that aligns everyone: the agent that struggles is almost always
working from a weak spec. A canopy `Spec` captures the *problem* and explicit, checkable
*acceptance criteria* up front; tasks implement it (`Task.spec_id`); and afterward each criterion
is **self-audited** (met / unmet / waived) against the implementation. See
`docs/AI_NATIVE_EXECUTION.md`.

## Workflow

### 1. Draft the spec from intent
Gather the inputs: the PRD / design doc (via the document graph — `list_doc_references` for the
project, or a `source_url`), the governing decision (`list_adrs` → an `adr_id`), and the codebase
context (`read_repo_file`). Then `create_spec(project_id, title, problem, context, out_of_scope,
source_url, adr_id)`. Write `problem` as *what + why*, and use `out_of_scope` to bound it — a
spec that doesn't say what it is *not* invites scope creep.

### 2. Write checkable acceptance criteria
For each thing that must be true for "done", `add_spec_criterion(spec_id, text, verification)`.
Good criteria are **observable and singular** — "P85 forecast renders within 300ms for a 200-task
project", not "it's fast". Put *how it will be checked* in `verification` (a test name, a fitness
function, a demo step). These criteria are the contract the agent self-audits against.

### 3. Review and approve
Refine with the architect/PM. When the spec is ready to build, `set_spec_status(spec_id,
"approved")`.

### 4. Plan and link the work
Generate the tickets from the spec using the **`drafting-jira-tickets`** skill (create a draft
plan whose `source` references this spec, push to Jira, sync back), then link the resulting tasks
to the spec with `link_task_to_spec(task_id, spec_id)`. Move the spec to `in_progress`. Keep
batches small — a criterion that needs a 2,000-line change is a criterion that needs splitting.

### 5. Self-audit when the work lands
Call `get_spec(spec_id)` — it returns the criteria, the linked tasks (with status / percent
complete), and the computed `acceptance_ratio`. For **each** criterion, judge it against the
actual implementation (read the code/PR, check the test or fitness function named in
`verification`) and record the verdict with `update_spec_criterion(criterion_id, status=...,
verification="how I checked")`:
- `met` — verified true.
- `unmet` — not satisfied yet (mint follow-up work).
- `waived` — consciously dropped (note why); excluded from readiness.
When every effective criterion is `met`, `set_spec_status(spec_id, "verified")`.

## Notes
- The self-audit is a **judgment** step — actually verify against the implementation; don't mark
  `met` from the spec text alone (that's how "cognitive debt" accumulates).
- Pair criteria with **fitness functions** (`add_adr_fitness`, §G7) where the criterion is a
  machine-checkable architecture rule — then the criterion defends itself continuously.
- canopy stores the spec, criteria, and links; Jira still owns ticket status (never written back).
