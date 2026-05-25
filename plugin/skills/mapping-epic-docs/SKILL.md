---
name: mapping-epic-docs
description: One-time, AI-driven setup that teaches canopy where each kind of document (PRD, design/Figma, tech-design, architecture, release, QA) lives on a team's Jira epics, then harvests those links into canopy's document graph so they're discoverable for everyone. Use when an admin is setting up a Jira connection's document discovery, when docs on epics aren't showing up in canopy, or when the team's Jira fields for docs have changed.
---

# Mapping epic documents into the canopy doc graph

Canopy is a document **graph**, not a document store. It never copies a PRD, Figma file, or
design doc — it **links** to where they already live (most often attached to a Jira **epic**,
plus Confluence/Drive/Figma URLs) and makes them discoverable in context. Jira epics are the
canonical attachment point; canopy reflects them.

This skill runs the **one-time setup**: discover which Jira fields hold which kind of doc,
confirm the mapping with the admin, save it, and harvest.

## Workflow

1. **Find the Jira connection.** `canopy:list_connections` → the one with provider `jira`.
   Note its `connection_id`.

2. **Sample the epics.** Call `canopy:sample_epic_doc_fields(connection_id, limit=5)`. It
   returns, per sampled epic, the URL-bearing fields (`field_candidates`, each with a
   `field_id`, human `field_name`, and sample `urls`), any `description_urls`, and Jira
   `remote_links`; plus `distinct_fields` (the union across the sample).

3. **Infer a mapping.** For each candidate field, decide its `doc_kind` from the field name
   and the URL domain. Heuristics:
   - `figma.com`, `zeplin`, `abstract` → **design**
   - a field named "PRD" / "Product Requirements" / a `docs.google.com` doc named like a PRD → **prd**
   - "Tech Design" / "RFC" / "Design Doc" (engineering) → **tech_design**
   - `ARCHITECTURE.md` / an arch wiki / a field named "Architecture" → **architecture**
   - "Release" / release-notes pages → **release**
   - `testrail`, "QA", "Test Plan" → **qa**
   - runbooks / on-call docs → **runbook**
   - anything ambiguous → leave it out or mark **other**
   Confluence (`/wiki/`) URLs depend on the field name — use it to disambiguate prd vs
   tech_design vs release.

4. **Confirm with the admin.** Present the proposed mapping as a short table
   (jira_field → field_name → doc_kind) and ask the admin to confirm or correct it. Also ask
   whether to harvest Jira **remote links** (usually yes — they're deliberate) and
   **description links** (usually no — noisy). **Do not save without confirmation.**

5. **Save it.** `canopy:set_epic_doc_field_mapping(connection_id, mappings, parse_remote_links,
   parse_description_links)` where `mappings` is a list of
   `{"jira_field", "field_name", "doc_kind"}`.

6. **Harvest.** `canopy:harvest_epic_docs(connection_id)`. It attaches a reference to whatever
   canopy entity each epic maps to (a summary **task** for a whole-project sync, a **project**
   for an initiative-linked epic). Idempotent — re-running updates, never duplicates. Report
   the created/updated/skipped counts.

7. **Check coverage.** `canopy:get_doc_coverage(scope_level, scope_id)` for a project or
   initiative shows which expected kinds (prd / design / tech_design / architecture) are
   **present vs missing**. A missing kind is a signal worth flagging — absence of a doc is not
   neutral.

## Notes
- Epics must already be synced into canopy (run the `syncing-jira` skill first) — harvest
  attaches to the epic's existing canopy entity and **skips** epics that aren't mapped yet.
- Re-run this skill (steps 2–6) whenever the team adds a new doc field or changes conventions.
- canopy reads only; it never writes the links back to Jira and never stores the documents.
- Individual one-off links can be added with `canopy:add_doc_reference` without a mapping.
