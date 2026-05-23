---
name: pr-to-adr-linker
description: Given a pull request, finds the components it touches (via code bindings) and the ADRs covering those components, then judges whether the PR implements, contradicts, or is unrelated to each decision. Use when reviewing a PR for architectural traceability, or when asked "does this PR follow our decisions?". Builds the implementation traceability v1 lacked.
---

# PR-to-ADR linker

Connects code changes back to the decisions that govern them.

## Workflow

1. Identify the PR and the GitHub connection. List open PRs with `canopy:list_open_prs` if you need
   to pick one; read changed files with `canopy:read_repo_file` as needed.
2. Pull the project's component **code bindings** (`canopy:list_code_bindings`). Match the PR's
   changed paths against each binding's `path_glob` / `module_prefix` to find the **components the
   PR touches**.
3. For those components, find the ADRs that cover them: list ADRs (`canopy:list_adrs` if available,
   else the components' decisions) and use `canopy:adr_impact` to see which decisions name those
   components in their blast radius.
4. For each relevant ADR, judge the PR against it: **implements** (advances the decision),
   **contradicts** (violates it — e.g. introduces a dependency an ADR forbade), or **unrelated**.
   Quote the specific code and ADR clause behind your call.
5. Post the summary to the most relevant ADR thread with `canopy:comment_adr`, and prompt the
   author/architect to confirm: "This PR appears to implement / contradict / be unrelated to ADR-NNNN
   — confirm?". If it contradicts a decision with no superseding ADR, suggest opening one
   (`canopy:propose_adr`).

## Notes
- Be conservative about "contradicts" — only when the code clearly breaks a stated decision. A weak
  signal is better surfaced as a question than asserted.
- If the PR touches a component with **no** governing ADR but makes an architectural change, that's
  an implicit decision — flag it (it's exactly what the Drift Sentinel would catch).
