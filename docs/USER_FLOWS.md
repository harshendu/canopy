# Canopy — User Flows

> **This document is the source of truth for user-facing flows and must be kept in sync with the
> code.** When a flow is added, changed, or removed, update this file in the same change. If a flow
> exists only via the API or the Claude plugin (no UI yet), it is still documented here and flagged.

Canopy is a tool for a **software/technical architect** to manage the architecture and delivery of a
codebase. It has two front doors over one FastAPI backend:

- **React dashboard** (`frontend/`) — the visual cockpit the architect clicks through.
- **Claude plugin** (`plugin/`) — an MCP server + skills + subagents that let the architect drive
  canopy conversationally, and let Claude run multi-step work.

Both call the same REST API (`/api/v1/...`). Throughout, **API** = REST endpoint and
**MCP** = the equivalent Claude plugin tool.

> **Looking ahead:** a critique of these flows and a proposed revision/extension live in
> [`PROPOSED_FLOWS.md`](./PROPOSED_FLOWS.md); the delivery philosophy behind those proposals is in
> [`EXECUTION_PHILOSOPHY.md`](./EXECUTION_PHILOSOPHY.md). The design for agent sessions that pull
> delegated tasks from canopy and move them through gated stages is in
> [`AGENT_EXECUTION.md`](./AGENT_EXECUTION.md). This file remains the source of truth for
> what is *built*; those are the source of intent for what *should change*.

## Actors
- **Architect** (primary) — plans, schedules, manages the team, records decisions.
- **Admin** — an architect with `admin` role; the only one who can create new users.
- **Claude** — acts on the architect's behalf through the plugin's MCP tools / skills / subagents.

## Source-of-truth boundaries (affect every sync flow)
- **Every task's status has exactly one owner** (`Task.status_owner`): **canopy** for a task only
  canopy knows (every task of a **native** project, plus canopy-only work — milestones, spikes —
  in a **mirrored** one), or the **external tracker** (Jira today) for a task mirrored from it.
  canopy moves only canopy-owned tasks (§C9) and **never writes status to a tracker** — a
  mirrored task's status is read-only in canopy and changes only when its tracker says so.
  Every status change, native or synced, goes through one write path that records history.
- **Jira** owns the epics/stories it mirrors into canopy and their **status**. Canopy syncs
  *from* Jira and **never writes status back**. **Scoped exception (§C10):** from an
  architect-reviewed **draft plan**, canopy can **create** new tickets and **update ticket
  content** (summary / description / story points + the epic→story parent link) — but **status is
  still never written**; the new issues flow back in via the normal Jira sync.
- **GitHub** owns code + some architecture docs. **Google Drive** holds design docs. Canopy reads
  these on demand and caches lightly. **Scoped write (§S):** canopy can *upload an export snapshot*
  (a generated PDF/CSV) into a connected Drive — it stores its own artifacts there but still does
  not own the design docs it reads.
- **Claude** (claude.ai) owns the **Claude Docs and artifacts** a session publishes — design docs,
  pages, prototypes, diagrams. Canopy keeps one record per document (link, identity, kind,
  version, a short summary, review state, links to the work) and **never receives the content**;
  a Claude session registers and re-checks them (§V5). A Claude doc joins shared work only once
  it is **shared in Claude** (§V6).

---

## UI. App shell & navigation conventions (apply to every screen)

The authenticated dashboard renders one **persistent layout route** (`ProtectedLayout` in
`frontend/src/App.tsx`, an `<Outlet/>` shell) so the nav rail and the preview drawer survive
navigation instead of remounting per page. These conventions are shared by every flow below; a page
that navigates must follow them.

- **Collapsible left nav rail** (`components/Sidebar.tsx`, config `lib/nav.ts`): every primary +
  admin destination is a link with an **SVG icon** (`components/icons.tsx`). A chevron toggles the
  rail between the full `w-56` (icon + label) and a `w-16` **icon-only rail** (label becomes a
  hover tooltip); the choice is persisted in `localStorage` (`canopy_sidebar_collapsed`). The
  Reviews entry keeps its live open-count badge (a dot when collapsed). Admin links sit under an
  "Admin" divider. The current-user switcher + sign-out live at the foot of the rail (avatar-only
  when collapsed). Which links appear is still role/feature-gated (`visibleNavItems`, §A10).
- **Right-side preview drawer** (`components/PreviewPanel.tsx`, `lib/preview.tsx`): a plain click on
  a link to a **project / initiative / scenario** opens a peek in a right drawer (key facts + status
  + "Jump to" deep-links) **before** navigating — the user commits with **"Open full view →"** (or a
  Jump-to chip). Backdrop-click, the ✕, and **Esc** dismiss it. The trigger is `PreviewLink`
  (`components/PreviewLink.tsx`), which renders a real `<a href>`: **⌘/Ctrl/middle-click still opens
  the full page directly** (and in a new tab), so the preview never traps a power user. Preview
  targets + their routes are the pure `lib/previewTarget.ts`.
  - **What previews vs. navigates directly:** entity records (project / initiative / scenario) preview.
    **Wayfinding** links do not — sidebar items, breadcrumb crumbs, the back arrow, section links
    (e.g. Initiative → Scenarios, My work → Today), and the Reviews alert banner navigate straight
    through, because a "peek" of a list/section or a back-step is noise.
- **Standard page header** (`components/PageHeader.tsx`): every page renders its title, optional
  subtitle, and right-aligned actions through one header. Nested/detail pages also carry
  **breadcrumbs** + a **back arrow** to the logical parent (derived from the breadcrumb trail):
  Projects → *Project*; Initiatives → *Initiative* (→ Scenarios → *Scenario*); My work → Today;
  Reviews → *Review*. Top-level list pages show title + subtitle only (no back/breadcrumbs).
- **Iconized tabs:** both the project cockpit (`ProjectView`, §B3) and the scenario workspace
  (`ScenarioWorkspace`, §T3) use a **two-level** icon nav — domain workspaces (primary) over the
  active group's views (secondary), replacing the old single-level strips (a 17-tab
  horizontal-scroll / a 10-tab wrapping row). The pure nav models are `lib/projectNav.ts` /
  `lib/scenarioNav.ts`.
- **First-run guide:** on a brand-new, **empty install** (no projects *and* no engineers) the `/`
  landing shows a **Get started** checklist (`components/GetStarted.tsx`) — create a project → add
  the team → connect Jira/GitHub/Drive → break down + schedule — instead of routing the installing
  admin (whose `function` defaults to `engineering`) to an empty `/me` that tells them to "ask an
  admin" (themselves). Once any project/engineer exists, persona landing (§A7) resumes.
- **Resilient states:** an app-level **error boundary** (`components/ErrorBoundary.tsx`) keeps one
  bad view from blanking the whole SPA, and async panels distinguish an **error** from an empty
  state (`components/QueryError.tsx`) — a failed `/alerts` reads "couldn't load", never a false
  "On track"; a failed `/portfolio` never reads "No projects yet". The SSE live-refresh (§K)
  reconnects after a transient drop instead of closing permanently.

---

## A. Authentication & access

### A1. Log in
- **Actor:** any user · **UI:** `/login`
- **Steps:** enter email + password → submit. On success a JWT is stored in the browser
  (`localStorage`) and the app routes to `/portfolio`. On failure an "Invalid email or password"
  message is shown.
- **API:** `POST /api/v1/auth/login` (form-encoded `username`/`password`) → `{access_token}`.
- **Notes:** the first admin is seeded at backend startup from `FIRST_SUPERUSER_EMAIL` /
  `FIRST_SUPERUSER_PASSWORD` when that account doesn't exist yet; startup refuses to create it with
  a password under 8 characters or a published placeholder (`changeme`, …), and the backend won't
  start at all without a strong `SECRET_KEY` (`app/core/startup_checks.py`). The token is sent as
  `Authorization: Bearer <jwt>` on every request.

### A2. Sign out
- **UI:** sidebar "Sign out" clears the stored token and returns to `/login`.

### A3. User & role management *(admin)*
- **Roles:** `admin`, `architect`, `engineering_manager`, `engineer`, `viewer` (plus a legacy
  `member` ≈ architect, kept for back-compat and not offered in the UI).
- **UI:** `/admin/users` (admin only, shown in the sidebar only for admins) — provision by email
  (email + temp password + role + **function** + name), change a user's role or function,
  **reset a password** (inline per-row form), and deactivate / reactivate. Closes v1's API-only
  registration gap.
- **API:** `POST /api/v1/auth/register` (admin), `GET /api/v1/auth/users` (admin),
  `PATCH /api/v1/auth/users/{id}` (admin; role / function / is_active / full_name — you can't
  deactivate yourself, and the **last active admin** can't be demoted or deactivated, so an
  install can't lock itself out), `POST /api/v1/auth/users/{id}/password` (admin resets;
  **human-only** — an agent token (§A6) can't rotate credentials).
- **Self-service password:** every user can rotate their own password from the sidebar
  ("Change password", current password required) — `POST /api/v1/auth/me/password` (human-only).
  Passwords are min 8 chars (enforced on register/reset/change).
### A3a. Role enforcement (Roles × flows) **[new]**
Write access is now enforced server-side per the v2 matrix; **reads stay open to any
authenticated user** (viewers included). Enforced via role-group dependencies in
`app/api/deps.py` (`ArchitectWriter` / `PlannerWriter` / `ContributorWriter`; admin always
allowed; legacy `member` ≈ architect):

|Domain                                   |admin|architect|eng-manager|engineer|viewer|
|-----------------------------------------|-----|---------|-----------|--------|------|
|Users (register / role / active)         |rw   |r        |r          |r       |r     |
|Project create / settings / holidays (B) |rw   |rw       |r          |r       |r     |
|Plan: tasks / deps / milestones / replan |rw   |rw       |rw         |own task|r     |
|Capacity: engineers / roles / alloc (F)  |rw   |rw       |rw         |r       |r     |
|ADR propose / comment (G2/G6)            |rw   |rw       |rw         |rw      |r     |
|ADR status transition / components       |rw   |rw       |rw         |r       |r     |
|Risk mitigations (Q)                     |rw   |rw       |rw         |r       |r     |
|Connectors: create / authorize / delete connection (J)|rw|rw    |–          |–       |–     |
|Connectors: sync / ingest / push-to-Jira / harvest / links (J)|rw|rw|rw      |–       |–     |
|Connectors: connect my own account — per-user SSO (J2a)|rw|rw   |rw         |rw      |–     |
|Connectors: list + read external / export download (J6/S)|r|r   |r          |r       |r     |

- **Engineer "own task":** an engineer (linked via `Engineer.user_id`) may `PATCH` only a task
  whose `assignee_engineer_id` is theirs (e.g. update progress); creating/deleting tasks, editing
  the dependency graph, and replanning stay planner-only.
- **Connectors (J):** connection lifecycle + the shared/service OAuth authorize is `ArchitectWriter`
  (admin/architect); sync, ingest, draft finalise, doc harvest, tracker links, and status-history
  are `PlannerWriter` (+ eng-manager). Per-user SSO connect (J2a) is open to any contributor (non-viewer)
  when the admin's `allow_user_connect` permits it. **External writes are also human-only** —
  push-to-Jira (§C10) and export-to-Drive (§S) reject `agent`-scope tokens (§A6); ingest, the draft
  record-push, and sync stay open to agents (internal, idempotent two-way-door). Enforced in
  `connectors.py` / `drafts.py` / `exports.py`; the `oauth/callback` is intentionally unauthenticated
  (trust via signed `state`).
- **The web app hides** write controls the current role can't use (a pure `src/lib/permissions.ts`
  mirrors the matrix); the server is the real gate and returns `403` regardless.
- **Not enforced yet:** the engineer "own-allocation / availability" carve-out (that self-service
  flow is §F4, not built) — capacity writes are planner-only for now. Decision **rules/approval
  gates** (G3) remain advisory.

### A4. Get current user
- **API:** `GET /api/v1/auth/me`. The web app caches this to gate admin-only nav.
- **API:** `GET /api/v1/auth/session` returns the active session — the effective (possibly
  impersonated) user plus the real admin behind it when impersonating (§A9). Backs the bottom-of-
  sidebar account display and the impersonation banner.

### A5. Engineer ↔ login link & workspace **[new]**
- A team **Engineer** record can be linked to a login via `Engineer.user_id` (set on the **Team**
  page's per-engineer "link to a login" select, or `PATCH /api/v1/team/engineers/{id}`). That link
  powers the engineer **workspace** (§M): a logged-in user sees the tasks and decisions tied to
  their engineer record.
- **Not built (v2 §A5):** self-service `/onboarding` (engineers confirming their own
  timezone/skills/hours) — an admin sets these on the Team page for now. **OIDC/SSO** and the
  `HttpOnly`-cookie token model (v2 §A1) are also not built; auth remains a `Bearer` JWT.

### A6. Bounded agency — scoped agent tokens **[new]**
As agents do more of the writing, their authority should be **intentionally constrained** (Team
Topologies / "bounded agency"; the reversibility distinction *is* the human-in-the-loop policy —
see [`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §3/§8, roadmap gap #4). An access token
carries a **scope** claim: `full` (a human login — does anything its role allows) or `agent` (a
bounded token an architect hands to Claude). An `agent` token acts **as its issuer** but is
forbidden from **one-way-door / external-write** actions; **two-way-door** actions run freely
(bias to action on reversible work).
- **Mint:** `POST /api/v1/auth/agent-token` (**any signed-in user** — the token only carries the
  issuer's own permissions, so this is safe; `HumanOnly` stops an agent token from minting another)
  → an `agent`-scoped JWT for the current user (`{label?, expires_minutes?}`, default 7 days, max
  30; gated by the `ai.agent_tokens` feature). Configure the plugin's `CANOPY_API_TOKEN` with this
  instead of a full login token. Minted tokens are **persisted as metadata** (`AgentTokenRecord` —
  never the secret, which is shown once) so they can be listed and revoked; the JWT carries a `jti`
  and `get_current_user` rejects it once revoked. **List/revoke:** `GET /auth/agent-tokens` (your
  tokens + expiry + status) and `DELETE /auth/agent-tokens/{id}` (revoke, `HumanOnly`). UI: the
  **Agent Setup** tab (§A11).
- **Scope (narrowing):** a token can be minted for given agent **roles** (`roles`, e.g.
  `["reviewer"]`) and **projects** (`project_ids`), with a limit on how many tasks it may hold at
  once (`max_active_claims`, default 1, max 10) — empty lists mean "whatever the issuer may do",
  so existing tokens are unchanged. The work queue enforces them (§AE): a claim for a role the
  token lacks is `403 role_not_allowed`, other projects' tasks are never offered, and a token at
  its limit gets back the claim it holds. `GET /auth/session` reports an agent token's
  scope (`agent_token`), and each token records **when it was last used** (`last_used_at`,
  refreshed at most once a minute) — shown on the Agent Setup list.
- **What an agent token is blocked from (403):** delegating a task, switching a project's agent
  intake, taking work back, and deciding or reassigning a gate (§AE — and `409 use_work_claim`
  on moving a delegated card); accepting a decision that is **not explicitly
  two-way** (`PATCH /architecture/adrs/{id}` → `accepted` unless `reversibility=two_way` — an
  *unclassified* decision fails closed too, §G2); **finalising a draft plan**
  (`POST /draft-plans/{id}/finalize`, §C10 — real work, and an external write when the project
  mirrors a tracker); **applying a scenario** to the
  live plan (`POST /scenarios/{id}/apply`, §T5); **reviewing/applying/rejecting a change proposal**
  (§AA — the agent stages, the human commits); and **credential / role / admin-config mutations**
  — registering or updating a user (`POST /auth/register`, `PATCH /auth/users/{id}`, which set an
  initial credential or grant a role) and toggling feature gates / integration strategy
  (`PATCH /admin/features/{key}`, `/admin/integrations/{provider}`). This keeps an admin's agent
  token from escalating to a fresh full-scope admin account (the credential rule `reset_password`
  already honored, now consistent across every credential/authority path). Everything else
  (creating/updating tasks, proposing/refining decisions, accepting *two-way* doors, specs,
  blockers, risks, draft authoring, **staging + withdrawing proposals**) stays open. Enforced in `app/api/deps.py`
  (`require_human` / `HumanOnly`); the scope rides in the JWT (`app/core/security.py`), and
  `GET /auth/session` reports it so a session can see its own limits.
- **Not built:** auto-running the coherence guardrails (drift + PR-to-ADR + fitness) on an
  agent-authored PR via webhook — the server can't crawl code itself (§N4), so that scan stays
  agent-driven; the webhook→agent trigger is the remaining piece of roadmap gap #4.

### A7. Cross-functional persona (`function`) + per-persona landing **[updated]**
A user carries a **`function`** — `engineering | product | design | architecture | management |
leadership` — **orthogonal to their access `role`** (roadmap gap #6; the stakeholder model in
[`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §5). It makes PM/UX/staff/director/exec
first-class identities (not all "viewer") and drives the **default landing surface**, *not* CRUD —
reads stay open everywhere; writes are still gated by `role`. Personas are a **lens, not a wall**.
- **API:** `function` is set on `POST /api/v1/auth/register` and `PATCH /api/v1/auth/users/{id}`
  (admin) and returned on `GET /api/v1/auth/me` (defaults to `engineering`).
- **UI:** on login (and the `/` root) the app routes to the persona's home (`src/lib/persona.ts`):
  **leadership / product / design → `/portfolio`** (the cross-project Home + "needs attention"
  band, §B1 — read-first, and always on, unlike `/initiatives`), **management → `/team`** (which
  now leads with its own "needs attention" band — open blockers + over-allocated engineer-weeks,
  ahead of the engineer/role admin forms), **architecture → `/decisions`**, **engineering → `/me`**.
  The current-user row at the sidebar foot (`UserSwitcher`) shows the persona label next to the
  role, so the "lens" is legible at a glance, not just implied by the landing route. Any user can
  still navigate anywhere — it only sets where you land.
- **Not built:** bespoke per-persona *dashboards* (each persona sees the shared surfaces — now with
  a persona-relevant attention band on the ones that needed it — not a fully custom-built page);
  admin **UI** to edit a user's function (API-only).

### A8. Integration strategy — per-provider read/write policy *(admin)* **[new]**
Setting up connectors is heavy and a single shared token can't always fit, so the **admin chooses,
per provider** (Jira / GitHub / Drive), *how* canopy reads and writes — independently on a **read
axis** and a **write axis**. The policy is the control plane every connector path consults; the
absence of a setting reads back as the default (**direct/direct**), so existing installs are
unaffected until an admin opts in. (Phase 1 of a larger plan — per-user SSO, MCP-orchestrated
ingest, and file-drop ingest are later phases.)
- **Read strategy** — `direct` (canopy polls / accepts webhooks using its **own credentials** when
  available, degrading silently when not), or `mcp` / `file` (canopy does **not** call the provider
  API — data arrives via Claude over MCP or a file drop). *Phase 1 wires `direct` only; `mcp`/`file`
  are shown but not yet selectable.*
- **Write strategy** — `direct` (canopy writes with its own credentials), `mcp` (the write is
  **routed through Claude**; canopy's direct write paths refuse with `403`), or `disabled`
  (read-only — writes blocked).
- **UI:** `/admin/integrations` (admin only, in the sidebar for admins) — one row per provider with
  a Reads and a Writes select (`frontend/src/pages/AdminIntegrations.tsx`).
- **API:** `GET /api/v1/admin/integrations` (all providers, defaults synthesized) and
  `PATCH /api/v1/admin/integrations/{provider}` — both admin-gated (`AdminUser`).
- **Enforcement** (`app/services/integration_policy.py`): the reconciliation poll
  (`app/workers/worker.py`) and webhook intake (`app/webhooks/trackers.py`, `github.py`) stand down
  when reads ≠ `direct`; the direct write paths — **finalising a draft into a tracker** (§C10) and
  **export-to-Drive** (§S) — return `403` when writes ≠ `direct`. Orthogonal to the bounded-agency gate (§A6).
- **Built in Phase 2:** per-user SSO connections (`allow_user_connect` + per-user OAuth, §J2a).
- **Built in Phase 3:** MCP-orchestrated ingest (Claude pushes external data in idempotently) +
  the draft push write-back + the scheduled-Claude-job pattern (§J3a) — so the `mcp` read strategy
  and `mcp` write strategy are now functional, not inert.
- **Built in Phase 4:** file-drop ingest (§J3b) — an upload endpoint + a watched local/S3 drop
  folder — so the `file` read strategy is now functional too. The full integration-strategy matrix
  is in place.

### A9. Admin user impersonation (act as another user) **[new]**
An admin can **switch into any other account** to see canopy exactly as that user does (debug a
persona's landing/permissions, reproduce a report). It is a **session-identity switch, not a data
write** — Jira/ticket status is never touched (§Source-of-truth) and nothing is created on the
user's behalf.
- **UI — current user + switcher:** the bottom of the left panel always shows the **current user**
  (avatar + name + role; `frontend/src/components/UserSwitcher.tsx`). For an admin — including the
  *real* admin behind an active impersonation — it expands into a switcher over **every account**:
  pick anyone to act as them, or pick **your own account** to step back. Non-admins just see their
  own identity (no switcher).
- **UI — impersonation banner:** while impersonating, a thin amber **strip across the top of every
  page** (`ImpersonationBanner.tsx`, rendered in `App.tsx`'s `ProtectedLayout`) reads "Viewing as
  <user> — impersonated by <admin>" with a one-click **Back to <admin>** exit.
- **API:** `POST /api/v1/auth/impersonate/{user_id}` mints a token that acts **as** `user_id`
  (404 unknown / 400 deactivated target); `POST /api/v1/auth/impersonate/stop` returns to the
  admin's own account. Selecting your own id via `…/impersonate/{id}` also drops impersonation.
- **How it's bounded:** the minted JWT keeps `sub`=target but carries an **`act`=admin** claim
  (RFC 8693-style delegation, `app/core/security.py`). Switching is gated on the *acting admin*
  (`AdminActor` in `app/api/deps.py`) — **not** the impersonated user — so the admin keeps the
  power to switch again or back even while acting as a non-admin (`GET /auth/users` is likewise
  actor-readable for the switcher; user **writes** stay on the impersonated identity). The action
  is **human-only** (`HumanOnly`): a bounded **agent** token (§A6) is rejected (403) — no MCP tool.
  The web app drops its entire query cache on a switch so all data refetches as the new principal.
- **Not built:** a server-side impersonation **audit log** (who acted as whom, when) — the `act`
  claim makes the session attributable in the moment, but events aren't persisted yet; and a
  configurable **short expiry** for impersonation tokens (they currently inherit the normal login
  TTL).

### A10. Feature gates — admin on/off switches per surface **[new]**
An admin can turn whole product surfaces (a **group**) or single **features** on and off for the
entire install — e.g. run canopy as "plan + Jira sync + Gantt only" by disabling `architecture`,
`governance`, and `portfolio`.
- **UI:** `/admin/features` (admin only) — grouped toggles with descriptions. A child whose own
  toggle is on but whose **group** is off shows an "off via group" badge (its own choice is
  remembered). Gated surfaces vanish **live** everywhere: sidebar items (Initiatives / Decisions /
  Connectors), ProjectView workspaces + their sub-views (a whole group collapses when all its
  features are off, §B3), header buttons (Set baseline, Export), and
  panels (outcomes, blockers, task risk register) — every toggle publishes an SSE event (§K) that
  refetches the map, no reload or restart.
- **Catalog (two levels, defaults all-on):** `planning` (whatif · baselines · scenarios ·
  draft_plans) · `tracking` (board · burndown · forecast · alerts · blockers · delivery ·
  capacity) · `architecture` (drift) · `portfolio` (initiatives · outcomes) · `governance` (risk ·
  retros · specs · docs) · `integrations` (webhooks · **outbound** — notifications and push
  starts, §AE10) · `reporting` (exports) · `ai`
  (agent_tokens · proposals · **work_queue** — the agent work queue, its Decisions inbox and the
  Agents view, §AE · **stage_policy** — per-column stage policy, rules and the agent-flow
  measures, §AE6–§AE8).
  **Core flows are not gateable** (auth, projects, tasks/deps/milestones, Gantt + CPM replan, team,
  /me, activity, live events). A feature is effectively on iff its toggle **and** its group's are on.
- **API:** `GET /api/v1/features` (any authenticated user — the effective map every client reads),
  `GET /api/v1/admin/features`, `PATCH /api/v1/admin/features/{key}` `{enabled}` · **MCP:**
  `get_enabled_features`.
- **Enforcement is server-side:** gated routers/endpoints return **403** with a machine-readable
  detail `{code:"feature_disabled", feature:"…"}` (`require_feature`/`FeatureGate` in
  `app/api/deps.py`; catalog + resolution in `app/services/features.py`; stored as `FeatureFlag`
  rows — a missing row means enabled, so existing installs are unaffected). Webhook intake ACKs
  but ignores deliveries while `integrations.webhooks` is off (so GitHub/Jira don't disable the
  hook). The UI mirror is `useFeatures`/`featureOn` (`src/lib/useFeatures.ts`).
- **Not built:** per-user / per-project gates (gates are install-wide), and a "who toggled what
  when" audit trail.

### A11. Agent Setup tab — self-service MCP token + connection instructions **[new]**
Every user needs a way to point their own Claude Code at canopy. The **Agent Setup** tab lets any
signed-in user mint a bounded agent token (§A6), see their live tokens, revoke one, and copy the
exact steps to connect — as a full plugin or a bare MCP server.
- **Actor:** any authenticated user (the token carries only the issuer's own permissions).
- **UI:** `/agent-setup` (sidebar **Agent Setup**, shown to everyone). Three parts: (1) a
  **generate** form (name + 7/14/30-day expiry + an optional **agent role** and **project**
  scope — one token per runner, scoped to the role it runs, is the recommended practice) that
  reveals the secret **once** in a copy block with a "copy it now" warning; (2) a **token list** —
  label, status chip (active/expired/revoked), its scope ("Reviewer · PAYMENTS"), expiry phrase,
  when it was last used, and a two-click **Revoke**; (3) **Connect Claude Code** with a *Full plugin* /
  *MCP only* toggle whose copy-paste snippets auto-fill the just-minted token. When the
  `ai.agent_tokens` gate is off, the generate form is replaced by an explainer but list/revoke stay.
- **API:** `POST /auth/agent-token` (mint, `ai.agent_tokens`-gated), `GET /auth/agent-tokens`
  (list), `DELETE /auth/agent-tokens/{id}` (revoke) — see §A6. The token is consumed by the MCP
  server as `CANOPY_API_TOKEN` (plugin `api_token`), so the instructions mirror §L1.
- **Notes:** the *Full plugin* path is `/plugin marketplace add … → /plugin install canopy@canopy →`
  fill the enable-time **config dialog** with `api_base_url` + `api_token` (the other fields are
  optional). Those two `userConfig` fields are `required:true` in `plugin/.claude-plugin/plugin.json`
  so Claude Code actually prompts for them; the optional ones (`dashboard_url`/`api_email`/
  `api_password`) carry a `default:""` so their `${user_config.*}` substitution in `.mcp.json` is
  never undefined (was the "undefined parameters" install failure). The *MCP only* path clones the repo, `pip install`s
  `mcp_server/requirements.txt`, and drops a stdio `.mcp.json` (`CANOPY_API_BASE_URL` +
  `CANOPY_API_TOKEN`). The API URL defaults to the dashboard origin (with a local-dev
  `:8000` note); a shared always-on HTTP MCP server points at `docs/PRODUCTION.md` instead.
- **Config-driven snippets:** the repo/marketplace refs in the snippets come from the deployment
  (`GET /api/v1/meta` ← `PLUGIN_MARKETPLACE_REF` / `PLUGIN_REPO_URL` / `PLUGIN_MCP_SERVER_PATH`), so a
  **fork or self-hosted install** shows *its own* repo — no hardcoded upstream. The clone dir + server
  path are derived from the configured URL (pure `frontend/src/lib/agentSetup.ts`, unit-tested).
- **Honest copy button:** copy reflects the *real* result — "Copied" only on success, and a
  "Copy failed — select & ⌘C" hint when the clipboard write is refused (insecure origin / denied
  permission), with a hidden-textarea `execCommand` fallback. The one-time token is never lost to a
  false "Copied" (was BUG-13).
- **Cross-link:** pairs with **Connectors** (§J1) — Agent Setup connects *Claude*, Connectors connect
  *data sources*; each links to the other.
- **Not built:** a guided shared-server (HTTP transport) setup on this tab — the snippets are for a
  per-user stdio server; a shared HTTP server in per-caller mode (§L1) takes the same token as an
  `Authorization: Bearer` header.

---

## R. Initiatives (the program layer above projects) **[new — v2 §R / C1]**

The architect's unit of work is usually an **initiative** (a.k.a. program) spanning several
projects executed concurrently and decentrally — not a single project. An `Initiative` groups
projects and rolls up their health.

### R1. List / create initiatives
- **UI:** `/initiatives` (sidebar) — list initiatives and (architect) create one (KEY + name +
  optional outcome statement + target date). Each row opens its cockpit.
- **API:** `GET /api/v1/initiatives`, `POST /api/v1/initiatives` (architect, also accepts `tags`),
  `GET/PATCH/DELETE /api/v1/initiatives/{id}` (PATCH also accepts `tags`, `health`, `status_note` —
  stamping `status_updated_at`; delete **unlinks** sub-projects, never deletes them) · **MCP:**
  `list_initiatives`, `create_initiative`, `set_initiative_health`, `set_tags`/`add_tags`/`remove_tags`.

### R2. Link a project to an initiative
- **UI:** `/projects` → per-project **initiative** select (architect). A project carries
  `initiative_id`.
- **API:** `PATCH /api/v1/projects/{id}` (`initiative_id`; `null` unlinks); `POST /api/v1/projects`
  also accepts `initiative_id` · **MCP:** `set_project_initiative`, `create_project(initiative_id=)`.

### R3. Initiative cockpit (rolled-up health)
- **UI:** `/initiatives/:id` — outcome statement, a **delivery meta bar** (manual health + status
  note + tags, editable by architects — §B4), an **on track / behind target** badge, aggregate
  cards (progress, **worst** sub-project risk, **worst** drift, open-decision backlog, latest end
  vs target, **P85 forecast** §C8), the **cross-project critical path** (§R4), an initiative-scoped
  **risk register** (RAID, §Q3a), the sub-project cards (each with its own risk/drift, linking
  into the project), and a **Linked tracker items** panel (link tracker items — Jira, Linear… —
  into the initiative, §J9; shown when `integrations` is on). An **Export ▾** control exports the initiative as a PDF/CSV snapshot (§S).
- **API:** `GET /api/v1/initiatives/{id}/rollup` (per-project summaries + aggregates: total/completed
  tasks, avg %, latest `project_end`, max `risk_score`/`drift_score` with the owning level,
  `open_decisions` = ADRs proposed/under-discussion, `on_track`) · **MCP:** `get_initiative_rollup`.
  The per-project summary is the same `summarize_project` the portfolio (§B1) uses.

### R4. Cross-project dependencies & critical path **[new]**
- **Cross-project hand-offs:** a dependency may link tasks in **different projects of the same
  initiative** (a between-team hand-off). `POST /api/v1/dependencies` now validates this: a
  cross-project edge is rejected (400) unless both projects share one initiative. Per-project Gantt
  / replan stay project-local (they ignore cross-project edges); the hand-offs surface at the
  initiative level.
- **Cross-project critical path:** the **initiative cockpit** shows the longest chain of dependent
  work across sub-projects, in working days, with cross-project hand-offs highlighted (amber). Built
  over the union of the initiative's tasks + dependencies with the same CPM as per-project
  scheduling (structural, calendar-independent).
- **API:** `GET /api/v1/initiatives/{id}/critical-path` (ordered critical chain with each task's
  project, total working days, `spans_projects`, and the `handoffs`; cyclic cross-project deps →
  409) · **MCP:** `get_initiative_critical_path`.

### R6. Teams, pods & ownership-scoped editing **[new]**
The org model above initiatives (`app/models/org.py`, `app/models/leadership.py`):
- A **team** owns a product or a platform and holds several **pods**. Its **directors** and
  **managers** sit in `TeamMember` seats.
- An **initiative** belongs to a team (`Initiative.team_id`) and has **one or more owners**
  (`InitiativeLead` seats: a pod's technical / product / design lead, or a `manager`). One person
  may own several initiatives at the same time.
- Every **project** has exactly **one owner** (`Project.owner_engineer_id`) and is run by one pod
  (`Project.pod_id`). An initiative **spans the pods of its projects** (derived, never stored).

The role matrix (§A3a) still says *what kind* of write a role may make; ownership says *where*.
For a planner-role user (architect / engineering manager / legacy member):
- an **initiative owner** plans the whole initiative and every project in it;
- a **team director** plans every initiative in their team;
- a **project owner** plans their own project, even inside an initiative they do not own;
- everyone else has **read-only visibility** — complete lateral visibility, no cross-team edits.

Admins are exempt. An initiative with **no owners and no team** keeps the plain role rules
(back-compat for data created before teams and owners existed). Contributor writes by engineers (own-task progress,
blockers, criterion verdicts, decision comments) are **not** scoped — they stay role-governed.
Enforced centrally in `app/services/access.py` (`ensure_initiative_editable` for initiative-level
writes, `ensure_project_editable` for project-level ones) and called from: initiative
edit/delete, project create-into/edit/delete, replan, task / milestone / dependency
create-edit-delete, ADR create/edit, draft plans (incl. push), scenario
create/edit/delete/apply. A denied write is `403 {code:"not_initiative_lead", initiative_id,
message}`.
- **UI:** `/initiatives` shows **Initiatives I own** first (for planners who own any), then every
  initiative **grouped by team** (director, manager, pods in the heading), each row with its pods
  ("spans pods" when more than one), its owners and an `owner` / `editable` / `read-only` chip.
  The initiative cockpit shows team · pods · owners and a **read-only banner** when the user
  cannot plan it; sub-project cards show each project's pod and owner. The project cockpit's
  header shows team · pod · initiative · project owner, with a read-only banner naming the project
  owner and the initiative's owners. Planning controls are hidden when `can_edit` is false
  (deeper controls that are still rendered are rejected by the server).
- **API:** `GET /api/v1/teams` (teams with pods + director/manager seats; open to all) · admin:
  `POST /teams`, `POST /teams/{id}/pods`, `PUT /teams/{id}/members` · `GET /initiatives/access`
  → `{led_initiative_ids, editable_initiative_ids, owned_project_ids, leads[]}` ·
  `GET|PUT /initiatives/{id}/leads` (replace the owner seats; admin or a current owner) ·
  `GET /initiatives/{id}/rollup` carries `can_edit`, `leads`, `team_id`, `team_name`, `pods` ·
  `GET /projects/{id}/access` → `{can_edit, initiative_id, initiative_name, leads, owner_name,
  pod_name, team_name}` · `team_id` on initiative create/update; `pod_id` + `owner_engineer_id`
  on project create/update; the portfolio / rollup project summaries carry `pod_name` +
  `owner_name`.
- **Not built:** UI editors for teams, pods, team seats, initiative owners and project
  owner/pod (set via the API / the seed); validation that a project's pod belongs to its
  initiative's team; scoping of the row-level edits inside a scenario workspace (the scenario's
  create/edit/delete/apply are scoped, its task/milestone/allocation rows are not yet).

### R5. Initiative digest — manage-by-exception weekly roll-up **[updated — now in the UI]**
- A synthesized health digest that **leads with what needs attention** (roadmap gap #6 / `PF L-R2`;
  37signals/Cagan: green is silent, surface exceptions). Reuses the **rollup** (§R3) + **forecast**
  (§C8) and adds **open blockers** (across the initiative's projects) + **outcomes** (§Y). Returns
  a `headline`, an `attention` exception list (behind target, P85 past target, elevated risk/drift,
  open blockers, decisions awaiting, at-risk sub-projects, and — with `ai.work_queue` on — agent
  decisions waiting on a person past their reminder and parked agent tasks), the status numbers,
  the outcomes, and a
  ready-to-send **`markdown`** rendering. Pure synthesis in `app/services/digest.py`.
- **UI:** the initiative cockpit (§R3) now renders the digest at the top — the headline + the
  `attention` list — with a **Copy digest** action that copies the `markdown` rendering to the
  clipboard (falls back to a no-op, never a false "Copied", if the clipboard API is unavailable).
- **API:** `GET /api/v1/initiatives/{id}/digest` · **MCP:** `get_initiative_digest` (the spine of
  the `daily-standup` skill §L16).
- **Delivery** to Slack/email is a **hook over this output**, not built (same posture as the alerts
  digest §I).

---

## BR. Leadership review & feedback (business review) **[new]**
The leadership layer's surface. Leadership — the heads of engineering and product
(`function = leadership`, any role — typically `viewer`) — and **team directors** (§R6) read
everything and **write one thing: leadership notes** on a specific view —
something to **watch**, a **priority** call (P1–P3), or free-form **feedback** — optionally pinned
to a decision / risk / outcome / milestone inside an initiative or project. The initiative's lead
team **acknowledges / resolves** each note with a response, so the loop closes where the work is.
`GET /leadership/review` rolls every initiative up for the **monthly business review**, grouped
by team (directors, managers, pods): owners, pods spanned,
headline health (progress, on-track, worst risk/drift, open decisions, open blockers), outcomes,
and the notes still open — plus an `attention` list. Gate: `portfolio.leadership`.
- **UI:** sidebar **Business review** (`/review`, the leadership persona's landing page) — the
  attention list, then a section per team (director · manager · pods) with one card per
  initiative showing its pods, owners, health, outcomes and open notes; the **Leadership notes** panel on the initiative cockpit and the project overview lists
  notes and (for the leadership persona / admin) adds one with an optional target picker; leads
  acknowledge / resolve inline with a response. The portfolio/initiative **Export** (§S) remains
  the PDF hand-out for the meeting.
- **API:** `GET /api/v1/leadership/notes?scope_level&scope_id&status` · `POST /leadership/notes`
  (leadership persona, a team director, or admin; `target_kind` + `target_id` resolve to a captured
  `target_label`) · `PATCH /leadership/notes/{id}` (author edits body/priority; the scope's lead
  team, the author or an admin sets `status`/`response`) · `DELETE /leadership/notes/{id}`
  (author/admin) · `GET /leadership/review`.
- **Not built:** Slack/email delivery of a new note (a hook over this data, like §I); notes on
  tasks; a decision-level "flagged by leadership" chip in the ADR list (the panel shows the
  target label instead); the seed is the only way to pre-populate notes.

## B. Projects & portfolio

### B1. View the portfolio dashboard — the cross-project Home **[updated]**
- **UI:** `/portfolio` — the cross-project "what needs me" entry (leadership/product/design land
  here, §A7), leading with a **"Needs attention"** exception band (green is silent) derived purely
  from the portfolio summaries — off-track health, CPM end past target, elevated (high/critical)
  risk or drift — each row a deep-link into the owning project's workspace (`lib/attention.ts`,
  pure + unit-tested, no extra fetches). Deliberately **not** triggered by any open RAID risk
  count: the register is a maintained ledger, not an alarm, so flagging every tracked risk would
  show nearly every project and defeat "green is silent." Below it: a completion bar chart and a
  card per project (avg %
  complete, completed/total tasks, critical-task count, end date, and **risk + drift score
  badges** — see §Q / §N). Clicking a card opens it. An **Export ▾** control exports the whole
  portfolio as a PDF/CSV snapshot (§S).
- **API:** `GET /api/v1/projects/portfolio` (each `ProjectSummary` includes `risk_score`/`risk_level`
  and `drift_score`/`drift_level`, computed by the same scorers as the Risk/Drift tabs) · **MCP:**
  `list_projects`. The attention band is a pure client-side derivation over this same response.
- **Not built (v2 §B1):** last-decision recency and sortable columns.

### B2. Create a project
- **UI:** `/projects` → enter KEY + name → "Add".
- **API:** `POST /api/v1/projects` (`key`, `name`, optional `initiative_id`, `start_date`,
  `target_date`) · **MCP:** `create_project`.
- **Notes:** `key` is a unique slug (e.g. `PLATFORM`). A project can belong to an **initiative**
  (§R) via `initiative_id`.

### B3. Open a project (the cockpit)
- **UI:** `/projects/:id` — a **two-level workspace** (the pure nav model is `lib/projectNav.ts`).
  The default landing is the **Overview** (§B3a); the detail views are grouped into **six
  top-level workspaces** that mirror the backend feature domains, each with a secondary sub-nav:
  - **Overview** — at-a-glance health + "needs attention" (§B3a)
  - **Schedule** *(planning)* — **Gantt** · **Dependencies** · **Roadmap** (the add-task /
    dependency forms live under Gantt, §C1/§C2)
  - **Execution** *(tracking)* — **Board** · **Agents** (§AE5, gate `ai.work_queue`) ·
    **Capacity** · **Delivery** (§X) · **Burndown** · **Activity**
  - **Architecture** *(architecture)* — **Decisions** · **Architecture** (map) · **Drift**
  - **Governance** *(governance)* — **Risk score** (§Q1, the computed dashboard) · **Risk
    register** (§Q3a, the human RAID ledger — a separate sub-view) · **Specs** (§W) · **Rules**
    (§AE7, gate `ai.stage_policy`) · **Docs** (§V) · **Retros**
  - **Integrations** — **Tracking** (§C12, core — so the workspace always shows) · **Draft
    plans** (§C10) · **Tracker links** (§J9) · **Notifications** (§AE10, gate
    `integrations.outbound`)

  A whole workspace disappears when *every* one of its features is gated off (§A10); a group that
  still has a core child (Schedule, Execution) always shows. The header has an **Export ▾** menu
  (PDF/CSV snapshot, §S), a **5-day week** toggle, **Set baseline**, and **Schedule (CPM)** (the
  planning controls are hidden for roles that can't use them — §A3a).
- **Deep-linking / URL state:** the active view lives in the URL as `?tab=<leaf>` (leaf keys are
  unchanged from the old flat tab bar, e.g. `/projects/:id?tab=drift`) and is **written on every
  switch**, so a view is shareable and back/forward works. The parent workspace is derived from the
  leaf, so every existing deep link (the preview drawer, the Drift Sentinel) keeps working and lands
  in the right group; an absent / unknown / gated-off tab lands on the Overview.

### B3a. Project Overview — the at-a-glance entry **[new]**
- **UI:** the default project landing (`components/ProjectOverview.tsx`). It answers "is this
  project on track, and what needs me?" in one screen, surfacing signals that used to be buried:
  - a **"Needs attention"** exception list (green is silent) from `GET /projects/{id}/alerts` —
    blocked tasks, deadline misses, overdue milestones, over-allocations, unscheduled work — each
    row drilling into the workspace that owns it;
  - a **stat grid** (progress, latest CPM end vs target, **forecast** P50/P85, computed **risk** and
    **drift** score+level, open RAID risks) from `GET /projects/{id}/summary`, which reuses the same
    `summarize_project` as the portfolio (§B1) so the numbers match everywhere — each tile drills
    into its workspace;
  - the **Outcomes** panel (§Y), relocated here so the measurable bet leads the entry rather than
    sitting above every workspace.
- **API:** `GET /api/v1/projects/{id}/summary` (per-project `ProjectSummary`, reuses the portfolio
  rollup), `GET …/alerts`, `GET …/forecast`.

### B4. Edit / archive a project · toggle working week · status & tags
- **UI:** the "5-day week" checkbox in the project header toggles weekend-aware scheduling. A
  **delivery meta bar** under the title shows the manual **health** (on_track / at_risk / off_track,
  RAG badge) + a weekly **status note** headline + **tags**, all inline-editable ("edit status").
- **API:** `PATCH /api/v1/projects/{id}` (`name`, `description`, dates, `archived`, `skip_weekends`,
  `tags`, `health`, `status_note` — setting health/status_note stamps `status_updated_at`),
  `DELETE /api/v1/projects/{id}` · **MCP:** `set_project_health`, `set_tags`/`add_tags`/`remove_tags`.
- **Notes:** `health` is the architect's narrative status that sits **alongside** the computed risk
  score (it doesn't override the score); `health=null` means "use the computed on-track signal".
  The portfolio card (§B1) shows the health badge, status note, tags, and open-risk count.
- **UI gap:** renaming/archiving/date edits are API-only today (the header has the weekend toggle +
  the health/status/tags meta bar).

---

## C. Work breakdown & scheduling (Gantt tab)

### C1. Add a task / milestone / phase
- **UI:** Gantt tab → "Add task" form: name, duration (working days), type
  (**task** / **milestone** / **summary**), a **parent (phase)** picker (any summary task in the
  project — nests the new task into the WBS tree directly from the form), optional deadline →
  "Add".
- **API:** `POST /api/v1/tasks` (optional `status`) · **MCP:** `create_task` (optional `status`).
- **Notes:** a **summary** task is a phase/workstream; the WBS is built by setting `parent_id`,
  now exposed in the UI form (previously API/MCP-only) alongside the API/MCP.
- **Key + first status:** every new task gets a human **key** (`<project key>-<n>`, e.g. `CHK-12`;
  a project's `task_key_prefix` overrides the prefix, keys already in use are skipped) and — unless
  it is a summary task — a **first status**: the `status` asked for (must be a column of the
  project's workflow, else 422 `unknown_status`), or the default for its progress (first done
  column at 100%, first in-progress column when started, else the first to-do column). The first
  status is recorded as a transition in the task's history. With **`tracking.native`** off canopy
  owns no status: new tasks start without one (an explicit `status` is a 403).
- **Edit / assign / delete:** `PATCH /api/v1/tasks/{id}` (a planner edits any task; an engineer
  only one assigned to them — §A3a) · **MCP:** `update_task` (planning fields: name/duration/
  start/end/deadline/percent_complete/parent). **`status` is not a PATCH field**: a status change
  is a board **move** (§C9 — `POST /api/v1/tasks/{id}/move`, MCP `move_task`), which records the
  transition and is refused for a task whose status a tracker owns. `assign_task` sets/clears
  `assignee_engineer_id`. **Delete** is a planner-only **Delete**
  button in the task detail panel (§C1a, `window.confirm`'d) → `DELETE /api/v1/tasks/{id}`, which
  cascades its dependencies/status-history/blockers server-side (`app/services/cascade.py`) and
  promotes any child tasks to the deleted task's parent rather than orphaning them.
- **Auto-replan (UI):** adding a task, adding a dependency, or changing a task's duration in the
  dashboard now **re-runs CPM automatically** (planner sessions) and shows the delta banner —
  scheduled-task count, the critical path **by task name**, project end, and any deadline
  violations — so the schedule + critical path never silently go stale between edits. A cyclic
  dependency surfaces the 409 inline instead of failing quietly. The manual **Schedule (CPM)**
  button stays for an explicit re-run. (Agent/API callers still call `replan_schedule` themselves.)

### C1a. Task detail panel — owner, estimates, tags, progress, blockers, risks, external links **[updated]**
- **UI:** click a task bar in the **Gantt** (or a card on the **Board**) to open a right-side
  **detail panel**. A planner-only **Delete** button sits next to the panel's close (✕) — deletes
  the task after a confirm, cascading its dependencies/history/blockers (see §C1). Its **status**
  is a select over the workflow's columns for a canopy-owned task (a board move, §C9.3 — recorded
  in the history), or a locked "Status owned by <tracker>" chip with a link for a mirrored one. It
  edits the task's **owner** (an "Owner" select over the team's engineers —
  the click-through home of individual ownership), **progress** + **duration**, a **3-point
  estimate** (aggressive / practical / buffered, with the computed PERT mean + spread + a
  confidence badge), **tags**, the task's **blockers** (raise/resolve with category + severity +
  needed-by; hidden when `tracking.blockers` is gated off §A10), and the task-scoped
  **risk register** (RAID; hidden when `governance.risk` is off). An **External links** section shows the task's links out to
  the systems that own the work: its **tracker item** (Jira, Linear… — named by the tracker's
  label and clickable when the tracker exposes a browsable site), the **GitHub PRs** implementing it (with open/closed state), and its
  pull requests. A **Design docs** section lists the docs filed under the task or linked to it
  (provider · format · review status · relation), with **Link a doc** for contributors on
  their own tasks (§V7); personal docs show only to their owner. Doc CRUD lives on the project
  **Docs** tab (§V). With `ai.work_queue` on, an **Agent work** section delegates the task to
  agents or takes it back, and shows why it is or isn't moving (§AE2).
- **API:** `PATCH /api/v1/tasks/{id}` (`tags`, `estimate_optimistic`/`estimate_likely`/
  `estimate_pessimistic`; `TaskRead` returns computed `pert_mean` + `estimate_spread`) ·
  `GET/POST /api/v1/tasks/{id}/blockers` · `GET/POST /api/v1/risks?scope_level=task&scope_id=…` ·
  `GET /api/v1/tasks/{id}/links` (the external-links bundle: `tracker` = `{provider, label,
  key, url}` from the task's live `ExternalRef` (null for canopy-only work), PRs from
  `PullRequest.task_id`, task-scoped `DocReference`s; the URL comes from the
  tracker's `browse_url` over the connection the ref came from, `app/services/links.py`) · **MCP:** `set_task_estimates`, `set_tags`/`add_tags`/`remove_tags`,
  `raise_blocker`, `add_risk`.
- **Notes:** the 3-point estimate is **advisory** — it never moves the scheduling `duration`; a wide
  optimistic→pessimistic spread instead raises the schedule-risk "estimate uncertainty" indicator
  (§Q1). There is deliberately **no** "apply estimate to duration" action. The Jira **browse URL**
  is built from the connection's `base_url`; OAuth connections store the non-browsable API base
  (`api.atlassian.com/ex/jira/{cloudId}`), so the key is shown without a link there. A PR↔task link
  comes from `PullRequest.task_id`, matched on ingest by the issue key in the PR's title or branch
  (§J6); the demo seed wires it directly. Gantt/Board still show no per-row link badge (a possible follow-up).

### C2. Add / remove a dependency **[updated]**
- **UI:** Gantt tab → "Add dependency" form: pick predecessor + successor, a **type** select
  (finish→start / start→start / finish→finish / start→finish, default FS) + a **lag (days)**
  input → "Link". Below the form, an **existing-dependencies list** (source → target, type, lag)
  with a **remove** action per row.
- **API:** `POST /api/v1/dependencies` (`type` FS/SS/FF/SF and `lag`), `DELETE
  /api/v1/dependencies/{id}` · **MCP:** `link_dependency`.
- **Notes:** all four types + lag are now in the UI form (previously API/MCP-only for non-FS/lag).
  A **cross-project** dependency (a hand-off between teams) is allowed only when both tasks'
  projects share an **initiative** (§R4); it appears on the initiative critical path, not the
  per-project Gantt.

### C3. Schedule (Critical Path Method)
- **UI:** project header → **Schedule (CPM)**. A banner reports scheduled task count, the critical
  path, the project end date, and any **deadline violations** (also flagged red on the Gantt).
- **API:** `POST /api/v1/projects/{id}/replan` · **MCP:** `replan_schedule`.
- **Result:** computes start/end dates, `is_critical`, and float for every task, honoring the
  project's working calendar (weekends + holidays) and a task's **`constraint_start`** — an
  explicit "start no earlier than" (SNET) pin, set via `PATCH /tasks/{id}`. `constraint_start` is
  kept **separate from the computed `start`** so a replan never reuses last run's *output* as this
  run's *pin*; without that separation the schedule ratcheted forward-only and what-if (§C5) was
  inert (removing a dependency or cutting a duration couldn't pull successors earlier). Repeated
  replans are now idempotent, and cutting scope pulls the end in. Cycles return a 409 error.

### C4. Set / view a baseline (schedule variance)
- **UI:** project header → **Set baseline** opens a note field ("Why re-baseline?") and snapshots
  current start/end as the plan-of-record. The Gantt draws a faint gray "planned" strip under each
  bar so **schedule variance** (current-vs-baseline) is visible. Re-baselining is a deliberate,
  *reasoned* reset — re-planning is a feature, not a failure — so each one is logged and shown in a
  **Baseline history** panel under the Gantt (date · reason · task count · planned end). The word
  **"drift" is reserved for architecture drift** (§N); the schedule's plan-vs-actual is *variance*.
- **API:** `POST /api/v1/projects/{id}/baseline` (optional `{note}`, returns the logged
  `Baseline`), `GET /api/v1/projects/{id}/baselines` (the history, newest first) · **MCP:**
  `set_baseline` (accepts a `note`). Capturing a baseline also **pins** the design docs the plan
  was based on (basis links on the project and its tasks) to their current versions (§V9).

### C5. What-if scheduling **[updated — now has a UI panel]**
- **UI:** Gantt tab → a **What-if** card under the chart (shown when `planning.whatif` is on and the
  plan has tasks). Pick a leaf task, enter a hypothetical duration, **Add override** (accumulates
  removable chips showing `old → new`), then **Project**. The result shows **Projected end**, **Δ vs
  current** (green earlier / red later), **critical-task count**, and **deadline misses** — all
  computed, nothing persisted. Editing the override set clears the stale projection. Component:
  `frontend/src/components/WhatIfPanel.tsx`.
- **Actor:** architect via Claude (or API) · **MCP:** `whatif_schedule` · **API:**
  `POST /api/v1/projects/{id}/whatif` with `duration_overrides` (`{task_id: working_days}`).
- **Result:** returns a *projected* end date / critical path / deadline violations **without
  persisting** — for "what if we add an engineer / cut scope" analysis. Now **actually responsive**:
  cutting a duration pulls dependent work (and the project end) earlier, because the scheduler no
  longer pins tasks at their last-computed start (see §C3 `constraint_start`). Previously a scope
  cut showed no improvement.

### C6. Read the Gantt — zoom, legend, today, variance, collapse **[updated]**
- **UI:** Gantt tab.
  - **Zoom:** the `−` / `+` controls change the day-width.
  - **Legend:** a row under the chart decodes the marks — **red** = critical path, **canopy** =
    task, **slate** = phase/summary, gray strip = **baseline**, amber dashed = **deadline**, sky
    dashed = **today**, and the `+d`/`−d` chip = schedule variance.
  - **Today marker:** a sky dashed vertical line (labeled "today") when the current date falls in the
    charted window, so "where are we now" reads at a glance.
  - **Schedule variance chips:** a leaf whose finish moved off its baseline shows a `+Nd` (red, late)
    or `−Nd` (canopy, early) chip past its bar — the numeric twin of the gray baseline strip (§C4).
  - **Collapse WBS:** summary rows with children carry a `▾`/`▸` chevron; clicking it hides that
    phase's descendants so a large tree stays navigable (client-side, not persisted).

### C6a. Ownership on the Gantt — owner chips + filter **[new]**
- **UI:** each assigned row shows the owner's **initials chip** in the label column (full name in
  the bar tooltip, next to dates/float). An **owner** dropdown in the Gantt toolbar filters the
  chart to one person's work — **Everyone · Unassigned · each engineer with work here** — keeping
  the WBS readable by retaining a matching task's phase ancestors. The **Board** (§C9) shows the
  same chips on cards plus its own owner filter, so ownership reads consistently across both views.
- **API:** `GET /api/v1/projects/{id}/gantt` now returns `assignee_engineer_id` +
  server-resolved `assignee_name` per task; assignment itself is §C1/C1a (`PATCH /tasks/{id}`,
  MCP `assign_task`). Jira-synced tasks arrive with ownership already mapped (§J3).

### C7. Working calendar (weekends + holidays) **[updated — holidays now in the UI]**
- **UI:** "5-day week" toggle (weekends). **Holidays**: a `HolidaysEditor` panel under the Gantt
  tab (list + add-by-date + remove), gated on the same **`ArchitectWriter`** role as other project
  settings (admin/architect — not the broader planner set that can edit tasks/deps). Adding or
  removing a holiday re-runs CPM automatically (it shifts the working calendar).
- **API:** `GET/POST/DELETE /api/v1/projects/{id}/holidays`. Both feed the CPM scheduler.

### C8. Probabilistic forecast (Monte-Carlo) **[new — v2 §C-R1]**
- **UI:** Gantt tab → a **Probabilistic forecast** card shows **P50 (likely)** and **P85 (safe)**
  completion dates next to the deterministic CPM date — the honest "when will it ship?" for
  knowledge work. If there isn't enough completed-work history yet, it says so (no fake precision).
  The initiative cockpit (§R) shows the same P50/P85 for the whole program.
- **API:** `GET /api/v1/projects/{id}/forecast`, `GET /api/v1/initiatives/{id}/forecast` · **MCP:**
  `get_forecast` (pass `project_id` *or* `initiative_id`).
- **How:** `app/services/forecast.py` (pure) runs a Monte-Carlo simulation — repeatedly burning down
  the remaining items by sampling the team's **historical weekly throughput** (completed items/week,
  including stall weeks, from `TaskStatusHistory` — the same source as burndown §H). Needs no
  per-task estimates; reports a distribution, not a single date. Insufficient until ~3 weeks of
  throughput exist. A task completes when it enters a status whose **category** is `done`
  (counted once, at its last such transition); `remaining` counts leaves not in a done or
  cancelled category.

---

## C9. Kanban board & native tracking (workflow, moves, WIP, aging) **[updated]**
Projects are tracked **natively** (canopy owns every task's status — `Project.tracking_mode =
native`, the default) or **mirrored** from a tracker (the tracker — Jira today, any `WorkTracker`
§J0 — owns the tasks it knows; canopy-only tasks in the project stay canopy-owned). The board
works the same in both; only who may move a card's status — and, for a mirrored project whose
tracker sent its statuses, where the columns come from — differs.

### C9.1 Workflow (the board's columns)
- **What:** an ordered list of **columns** — a status name, a **category** (`todo` |
  `in_progress` | `done` | `cancelled`) and an optional **WIP limit** — plus a **WIP
  enforcement** (`off` | `warn` | `block`). The default is Backlog · To Do · In Progress · In Review
  · Done · Cancelled, enforcement `warn`.
- **Where it is defined:** a **team** workflow is shared by every project the team runs (a
  project's team = its pod's team, else its initiative's team); a project may **override** it; a
  team-less project uses the **workspace template**; with nothing saved, the built-in default
  applies (nothing is written on read). A **mirrored** project whose binding holds the tracker's
  **status map** (refreshed on each full sync, §J0) shows **the tracker's statuses** instead —
  `scope: "tracker"`, e.g. "Jira workflow", in the tracker's order and categories, enforcement
  `off`; editing it is refused (`409 workflow_externally_owned` — change it in the tracker), and
  team/template edits skip such projects.
- **API:** `GET/PUT /api/v1/teams/{id}/workflow` (the team's directors/managers or an admin),
  `GET/PUT/DELETE /api/v1/projects/{id}/workflow` (an override; planners who may edit the
  project), `GET/PUT /api/v1/workflows/template` (admin) · **MCP:** `get_workflow`, `set_workflow`.
  A PUT replaces the columns: a column carrying `previous_name` is a **rename** (its tasks follow,
  no transition); removing a column that still holds canopy-owned tasks needs `move_tasks_to`
  (`{"Old": "New"}` — those tasks move with a recorded transition), else 422 `column_in_use`. A
  workflow needs at least one `todo` and one `done` column. Core (ungated).
- **Categories, not names, drive every metric** (§C8, §H, §X): `done` is throughput, `cancelled`
  leaves WIP but is never throughput, `in_progress` is started work. A status's category is
  resolved from what the tracker sent, else the workflow's column, else a name heuristic, and is
  **stamped on each history row** so a later rename or remap never rewrites the past.

### C9.2 Read the board
- **UI:** project → **Execution → Board** → the workflow's columns **in order, empty ones
  included** (a status found on a card that the workflow doesn't name — e.g. a mirrored status —
  shows as an extra column after its category's columns; Cancelled starts collapsed). Cards are
  **ranked** within a column; each shows its key, name, **age in status** (amber "aging" beyond
  the team's **cycle-time P85**), blocked / critical-path flags, deadline, tags, the owner's
  initials chip and, for a mirrored card, a lock + its tracker with a link out. A card
  **delegated to agents** carries a badge (§AE): `agent` while it waits, the **role** of the
  session working it (amber when that session stopped checking in), or the **gate** holding it
  for a person (`question · 5 h`, red `parked`) — a link to decide it. A column worked by an agent
  role names the role in its header. Column headers
  show WIP vs the limit (red when over) — counted over the **WIP scope**: every project
  sharing these columns (the team's projects on the team's or template's columns; just this
  project when it has its own override or its tracker's statuses), so a project's board shows
  the same count the move check enforces even when the team's other projects hold cards
  (`scope_wip`). **Toolbar:** owner / tag / blocked / aging filters,
  **swimlanes** (none · owner · parent), the cycle-time P85, and — for planners — **Edit
  columns**. A mirrored project says so above the board.
- **API:** `GET /api/v1/projects/{id}/board` — lanes (`status`, `category`, `position`, `wip`
  (cards on this board), `scope_wip` (open cards across the WIP scope), `wip_limit`,
  `over_limit` (against `scope_wip`), `in_workflow`, `worked_by`) with cards (`key`,
  `status_owner`, `movable`, `external_url`, `rank`, `blocked`, `is_critical`, `deadline`,
  `tags`, `age_days`, `aging`, and agent work: `delegation`, `claim` {role, label, since,
  heartbeat_age_s}, `gate` {kind, origin, parked, title, age_hours}, `parked`), plus
  `mode`, `wip_enforcement`, `cycle_time_p85_days`, `aging_count` and a `viewer` block (may plan?
  which engineer? is native tracking on?) · **MCP:** `get_board`. Pure logic in
  `app/services/flow.py` (columns, WIP, P85, aging, ranks); assembly in `app/services/board.py`.
- **Cycle time** is now *started → done* (first transition into `in_progress` → last into `done`;
  falls back to created when a task never passed through a started status); **lead time** is
  created → done (§X).

### C9.3 Move a card
- **UI:** **drag** a card (mouse/pen after a few pixels; touch with press-and-hold; keyboard:
  focus the grip, Space/Enter to lift, arrows to move between and within columns, Space to drop,
  Escape to cancel — announced to screen readers) within its column (reorder) or to another
  column (status change); or use the card's **Move to…** menu, or the **status select** in the
  task panel (§C1a — a mirrored task shows a locked "Status owned by <tracker>" chip with a link
  instead). Moves are **optimistic** (the card moves at once, rolls back with the server's message
  on a refusal; a WIP warning shows a non-blocking notice). A mirrored card can be reordered but
  not dropped into another column. **Add card** at a column's foot (planners) creates a task with
  that status. Move affordances follow who may move what (below) and hide when
  `tracking.native` is off.
- **API:** `POST /api/v1/tasks/{id}/move` `{to_status?, after_task_id?, before_task_id?,
  position: top|bottom, expected_status?}` · **MCP:** `move_task`. Omitting `to_status` only
  reorders (allowed for mirrored cards too — rank is canopy's). Every status change goes through
  the one write path (`workflow.record_transition`): it stamps the category, appends a
  `TaskStatusHistory` row (author = the mover, `source = canopy`, and `actor_kind` — `human`
  for a person's own session, `agent` for an agent token acting for them) and reconciles progress
  (entering done → 100%; leaving done → 0; other manual progress kept).
- **Who:** a planner moves any card in projects they may edit (§R6); anyone else who contributes
  — an **engineer**, or a planner outside the project — moves their own cards, or **pulls** an
  unassigned one by moving it to another column (which assigns it to them; reordering it alone
  is `403`); viewers read. The board's `viewer` block reports exactly these rules (`can_plan`,
  and `engineer_id` — null for a viewer). An agent
  token acts as its issuer — a move is a two-way door; a status an agent merely *inferred* goes
  through a proposal (§AA).
- **Delegated cards** (§AE, with `ai.work_queue` on): an **agent token** changing a delegated
  card's status gets `409 use_work_claim` — the queue moves it (claim, then hand off). A
  **person** may move one — the board follows reality: the target column's entry checks come
  back as `warnings` (a check marked for everyone that blocks refuses the move, `409
  checks_failed`, unless a planner passes `override_reason`, recorded as an `override` event),
  the running claim ends (its session is told to stop) and gates holding the card in its old
  column close.
- **Refusals:** `409 status_externally_owned` (a mirrored task — the body names the `provider`
  and the item's `url`), `409 wip_limit_reached` (enforcement `block` and the column is full;
  `warn` succeeds with `warnings: ["wip_limit_exceeded"]`), `409 stale` (`expected_status` no
  longer matches; the board's "(no status)" label counts as an empty status), `422 unknown_status`, `403 native_tracking_disabled` (feature
  **`tracking.native`** off — every status must then come from a tracker).
- **Ranks:** integers with gaps of 1024; a drop takes the midpoint of its neighbours, and when no
  gap is left the team's cards are renumbered once (relative order everywhere is kept). A card
  never placed sorts by creation order.
- **Live refresh:** creating or moving a task publishes a `board` event (§K).

### C9.4 Edit the columns (workflow editor)
- **UI:** Board → **Edit columns** (planners) → a panel showing where the columns come from
  ("inherited from the team / workspace", or this project's own), with each column's name,
  category and WIP limit, reorder, add/remove (removing a column that still holds cards asks
  where they go → `move_tasks_to`), the WIP enforcement, **Save** (`PUT
  /projects/{id}/workflow`) and **Use team/workspace columns** (`DELETE`, when the project has
  its own). Server validation messages (e.g. a missing done column) show inline.
- **Columns carry their stage policies** (§AE6): renaming a column keeps its policy, removing
  one drops it, and going back to the team/workspace columns deletes the project's policies.
  Once a workflow has policies, changing its columns is **human-only** (`403 human_only` for an
  agent token) — an agent can't loosen its own guardrails by editing the board.
- Built with `@dnd-kit` (lazy-loaded with the board); pure helpers (optimistic move, `canMove`,
  swimlanes, filters, drop placement, editor validation) in `frontend/src/lib/board.ts` /
  `lib/workflow.ts`, unit-tested with Vitest.

---

## C11. Delivery method — Kanban, sprints or both (per team) **[new]**
A **team** chooses how it runs work **once, for all of its projects**: continuous **Kanban**
flow, time-boxed **sprints**, or **both**. The method switches surfaces and metrics on; the data
underneath (tasks, statuses, history) is the same.

### C11.1 Choose a team's delivery method
- **What:** `Team.delivery_method` = `kanban` | `sprint` | `both`, plus `sprint_length_days`
  (default 14) and `estimate_unit` (`points` → `Task.story_points`, `days` → `Task.duration`,
  `count` → every task 1; points with no estimates fall back to count, and responses say which
  `unit` they used).
- **Which team:** a project's team is its pod's team, else its initiative's team. A project in no
  team is **Kanban-only** (there is no team to hold a sprint) — a tracker's sprints aren't
  mirrored for it either; `Task.sprint_id` is the only membership (the old `sprint` name field
  is gone).
- **API:** `GET/PUT /api/v1/teams/{id}/delivery` (PUT: the team's directors/managers or an
  admin — `can_manage` in the GET) · **MCP:** `get_team_delivery`, `set_team_delivery`. New teams
  start on `DELIVERY_DEFAULT_METHOD` (env, default `kanban`). Switching to `kanban` needs the
  active sprint completed (409 `active_sprint`); nothing is deleted — past sprints stay history.
- **UI:** team page (`/teams/:teamId` — linked from the project header's team name, the
  Initiatives team headings, the initiative cockpit and the **Teams** list on `/team`) →
  **Settings**: the method (with a one-line explanation of each), sprint length and estimate
  unit; read-only without `can_manage`; the `409 active_sprint` refusal shows inline.
- **Gate:** **`tracking.sprints`** — off means every team works as Kanban
  (`effective_method = kanban`) and the sprint endpoints 403. The delivery settings are core.
- **Upgrade:** teams whose projects synced Jira sprints start on `both`; every other team on
  `kanban`.

### C11.2 The team board
- **UI:** team page → **Board** — the Kanban board (§C9) over every project the team runs: cards
  carry a project chip (and story points); extra **project** / **pod** filters and **By
  project** swimlanes; quick-add asks which project. **Edit columns** edits the team's workflow
  (shown to the team's directors/managers). When the team runs sprints a **sprint selector**
  (active sprint · backlog · all work · any sprint) sits in the toolbar — on project boards of
  sprint teams too — showing the selected sprint's dates, time left and goal; it opens on the
  active sprint when there is one. A move validates against the card's own project workflow, so
  a team column its project's override lacks is refused (`422`, rolled back with the message).
- **API:** `GET /api/v1/teams/{id}/board?pod_id=&project_id=&sprint=` (gate `tracking.board`) —
  the project board's shape (§C9.2) over **every project the team runs**, on the **team's
  workflow** (one set of columns and WIP limits: the team's work in progress). A card whose status
  the team's columns don't name (a mirrored status, a project override) sits in the **first
  column of its category** and keeps showing its own status. Cards carry their `project_id`; the
  response carries `team_id`, `sprint_id`, `delivery_method`. `sprint` = `active` | `backlog`
  (open work in no live sprint) | `all` | a sprint id; the project board takes the same filter
  (`GET /projects/{id}/board?sprint=`) · **MCP:** `get_board(team_id=…, sprint=…)`.

### C11.3 Plan and run a sprint
- **Model:** a `Sprint` belongs to a team (optionally a pod), has `name`, `goal`, dates, `state`
  (`planned` → `active` → `completed`) and an `owner` (`canopy`, or the tracker it is mirrored
  from — then read-only). `Task.sprint_id` puts a task in at most one sprint; every membership
  move is a `TaskSprintHistory` row (commitment, scope change and carry-over come from it).
- **API** (gate `tracking.sprints`): `GET/POST /api/v1/teams/{id}/sprints` (create: dates default
  to the day after the last sprint, for the team's length; name "Sprint n"; the team must run
  sprints, else 409 `team_is_kanban`), `GET/PATCH/DELETE /api/v1/sprints/{id}` (delete: planned
  canopy sprints only), `POST /api/v1/sprints/{id}/tasks {task_ids}` and
  `DELETE /api/v1/sprints/{id}/tasks/{task_id}` (membership — tasks of the team's projects,
  each leaves its previous sprint), `POST .../start` (captures the commitment; one active sprint
  per team, or per pod for pod-scoped sprints), `POST .../complete {carry_over: next|backlog,
  next_sprint_id?}` (captures what was completed; each unfinished task moves on, recorded),
  `POST .../reopen` · **MCP:** `list_sprints`, `get_sprint`, `plan_sprint`, `start_sprint`,
  `complete_sprint`; skill **`planning-sprints`**.
- **UI:** team page → **Sprints** (sprint or both): the sprint list and **New sprint**, then a
  **planning view** with the backlog beside the sprint — move tasks by mouse, touch, keyboard
  (left/right jumps lists) or Add/Remove, optimistically; a capacity bar (over capacity warns)
  with person-days per engineer; **Start**, **Complete** (asks where unfinished work goes: a
  planned sprint or the backlog), **Reopen**, **Edit**, **Delete** (planned only). A mirrored
  sprint shows its owner and hides lifecycle actions. The **task drawer** has a **Sprint** field
  (live sprints + Backlog; hidden for Kanban teams or with the gate off) and a **Story points**
  input; `/me` shows **My sprint** (dates, time left, done/total, your tasks).
- **Planning view:** `GET /sprints/{id}` returns the tasks plus `capacity` — the open estimate vs
  the team's **person-days** over the sprint (allocations to the team's projects × working days ×
  availability/PTO) and its **mean velocity**; `over_capacity` **warns, never blocks**.
- **Who:** sprints — the team's directors/managers and the planners who may edit one of its
  projects (or an admin); reads are open. An agent token acts as its issuer; a sprint change an
  agent *inferred* goes through a proposal (§AA — task `sprint_id`).
- **Ownership:** a sprint mirrored from a tracker (Jira's active sprints, synced when the
  connection has a `board_id` and the project has a team) is read-only (409
  `sprint_externally_owned`); a mirrored task whose tracker syncs sprints can't be re-planned in
  canopy (409 `membership_externally_owned`). **canopy never writes sprints to a tracker.** A
  mirrored sprint may hold canopy-owned tasks (one team sprint over a Jira-bound and a native
  project).
- **Schedule:** sprints never pin the CPM schedule; the alerts digest (§I) raises
  **`sprint_overrun`** for an open task whose computed end falls after its active sprint ends.

### C11.4 Measure sprints (team-level only)
- **UI:** team page → **Sprint report**: the burndown (remaining, the ideal line to the sprint
  end, scope added), six stats, velocity bars (committed vs completed, with the mean) and the
  P50/P85 sprint forecast (or the server's reason when data is thin), each chart with a **Show
  the numbers** table. While a sprint runs its unfinished work reads "Not done yet".
- **Report:** `GET /api/v1/sprints/{id}/report` — daily **burndown** (remaining estimate vs an
  ideal line from the captured commitment; work added after the start shown separately as
  `scope_added`), `committed`, `completed`, `reliability` (completed ÷ committed),
  `scope_added`, `scope_removed`, `carried_over` (work that left at completion counts as carried,
  not removed) · **MCP:** `get_sprint(include_report=True)`.
- **Velocity:** `GET /api/v1/teams/{id}/velocity` — completed estimate per completed sprint, mean
  and range over the last six, mean reliability, and a **sprint forecast** (P50/P85 sprints to
  finish the team's open work — the Monte-Carlo of §C8 run per sprint). `sufficient=false` until
  3 sprints have completed · **MCP:** `get_velocity`.
- Pure maths in `app/services/sprints.py`; the DB side (membership — the only writer of
  `Task.sprint_id` — lifecycle, capacity, items) in `app/services/sprint_service.py`.
  **Never per engineer** (the §X Goodhart rule).

### C11.5 Not built yet
- **Reopen** doesn't bring back the work a completion carried over, so a reopened sprint's report
  counts it as scope removed.
- Trackers' planned/completed sprints are mirrored by the tracker engine (§J0) when a binding
  syncs iterations; canopy still never writes sprints to a tracker.

---

## C12. Project tracking — native, mirrored, and switching **[new]**
A project is tracked **natively** (canopy owns every status; the board is the source of truth)
or **mirrored** from a bound tracker (§J0) — and can move between the two, or to another
tracker, without losing work or history.

### C12.1 Read and adjust a project's tracking
- **UI:** project → **Integrations → Tracking**: the mode ("Native — canopy owns every status" /
  "Mirrored from {tracker}"), who owns how many statuses ("canopy owns N · Jira owns M"), the
  binding card (connection, scope and mapping chips labelled from the tracker's `scope_schema`,
  the tracker's statuses as category-coloured column chips, last synced, sprint mirroring), past
  trackers with their bound/detached dates. With planning rights and `integrations` on: **Sync now** / **Full
  re-sync**, **Edit binding** (scope form from the `scope_schema`, sprint toggle, advanced mapping
  JSON — sends only what changed), **Publish open tasks…** (confirm) and **Switch tracking…**
  (§C12.2). An action the tracker can't do says why ("canopy doesn't read Generic tracker
  directly…").
- **API:** `GET /api/v1/projects/{id}/tracking` — `mode`, the active **binding** (connection,
  provider + label, `scope`, `mapping`, the tracker's `status_map`, `sync_iterations`,
  `last_synced_at`), `history` (trackers it used before, detached), the bound tracker's
  `capabilities`, how many tasks canopy vs the tracker owns, `can_edit`, `trackers_enabled`.
  Core (ungated). `PUT .../tracking` adjusts the active binding **in place** (scope — validated
  against the tracker's `scope_schema`; a new scope resets the watermark and status map so the
  next sync is a full one — the type/field mapping, sprint mirroring); `409 not_bound` without
  one. `POST .../tracking/sync?full=` pulls the project's binding now (the caller's own
  credential when connected, §J2a); `409 not_directly_readable` when its reads come by MCP/file.
- **New projects** start in `TRACKING_DEFAULT_MODE` (`native` unless set; `POST /projects`
  takes an explicit `tracking_mode`).

### C12.2 Switch (native ⇄ mirrored, or to another tracker)
- **API:** `POST /api/v1/projects/{id}/tracking/switch` `{to_mode, connection_id?, scope?,
  mapping?, sync_iterations?, strategy, dry_run}` — **previews by default** (`dry_run: true`,
  open to agent tokens): the plan lists what happens to **every task** — `keep`, `adopt`
  (matched to a tracker item), `publish` (created in the tracker), `release` (leaves the old
  tracker; canopy owns its status) or `remap` (released, and its status moved to the native
  column of the same category because the native columns lack it) — with counts and warnings.
  With `dry_run: false` (**human-only**, planner who may edit the project) it applies **exactly
  that plan**: the old binding is detached and its refs kept (`detached_at` — the task still
  links "formerly SHOP-101"), released tasks become canopy-owned (remaps recorded through the
  one status writer, author "tracking switch"), the new binding is created, matched tasks
  adopted, the mode flipped — one transaction — then open tasks are published (strategy
  `publish`) and a first full sync runs. `tests/test_tracking_switch.py` pins preview == apply.
- **Strategies** (for the work the project already has): `keep_separate` (it stays canopy-only
  work in the mirrored project), `match` (a task whose key — else unique title — matches a
  tracker item is adopted by it), `publish` (open tasks are created as tracker items — content
  only; they start in the tracker's first status, so started work is warned about —
  done/cancelled work stays canopy-owned history). `POST .../tracking/publish` re-runs
  publishing (idempotent; human-only).
- **Refusals (400):** already tracked this way; the same connection with another scope (use
  `PUT`); a scope that already feeds another project (one tracker selection — e.g. a Jira
  project key or JQL; a board only adds sprints — feeds one project); not a tracker / not
  enabled; `match` without direct reads; `publish` without item creation or write access.
- **UI:** Tracking → **Switch tracking…** — a wizard: the target (Native, or one of the enabled
  tracker connections; the current one is disabled) → scope + strategy (scope prefilled from the
  connection's config the way the server reads it; `match` / `publish` disabled with the reason —
  capabilities, the read/write policy, a missing credential) → **Preview** (the plan grouped by
  action, with counts and warnings) → **Apply** (confirm) → the result (published / first-sync
  counts, warnings); tracking, the project, tasks, Gantt, boards, workflow and draft plans refresh.
- **MCP:** `get_project_tracking`, `set_project_tracking`, `switch_project_tracking` (previews
  by default; applying 403s on an agent token), `sync_project_tracking`, `publish_project_tasks`
  (skill: `syncing-trackers`).

---

## C10. Draft plans → tickets or tasks **[updated]**

The architect's "plan first, then make the work" flow. A **draft plan** is a staging area
(its own tables — kept out of the live Gantt/CPM/board) where the architect proposes phases,
tasks, estimates, and story points, reviews them, then **finalises** the draft — into canopy
tasks for a **native** project, or into **tickets in the project's tracker** for a mirrored one.
Writing to a tracker is **content only** — status stays the tracker's (§Source-of-truth
boundaries).

### C10.1 Create & review a draft plan
- **UI:** project → **Integrations → Draft plans** → "New draft plan" (title + optional **source** note, e.g.
  the design-doc/PRD url). Select a plan to expand it: add proposed tasks (name, **type** —
  story/task · epic/phase · milestone, **estimate (days)**, **story points**, and a **parent**
  epic to nest under), and remove tasks. Drafts carry a status: **draft → synced → archived**.
- **API:** `GET/POST /api/v1/projects/{id}/draft-plans`, `GET/PATCH/DELETE
  /api/v1/draft-plans/{plan_id}`, `POST /api/v1/draft-plans/{plan_id}/tasks`,
  `PATCH/DELETE /api/v1/draft-tasks/{task_id}` (writes are planner-gated) · **MCP:**
  `list_draft_plans`, `create_draft_plan`, `get_draft_plan`, `add_draft_task`,
  `update_draft_task`, `delete_draft_task`.
- **From a design doc (§V9):** `source_doc_id` + `source_doc_version` name the tracked (shared)
  doc the plan was drafted from (422 `invalid_source_doc` for a personal or unknown doc). On
  finalise, a **native** plan links the doc as a **reference** to every task it creates; a
  **mirrored** plan cites it at the end of each ticket's description ("Design doc: <title> —
  <url>", idempotent — a content write, never status). Only a doc shared at its source is cited.
  The plan card shows "drafted from a tracked design doc".

### C10.2 Finalise the draft (canopy tasks, or create / update tickets)
- **Finalise (any tracking mode):** `POST /api/v1/draft-plans/{plan_id}/finalize`
  (`{connection_id?}`; planner + **human-only**) follows the project's mode: **native** → canopy
  tasks (keys, first statuses, parents, then a replan; each draft task is stamped with its
  `task_id`, so a re-finalise updates rather than duplicates); **mirrored** → the plan's items
  are created/updated in the bound tracker via `WorkTracker.create_item`/`update_item` (epics
  first; each stamped with `external_provider/_id/_key`), then the next sync pulls them back. The
  result says `mode` (native | tracker) with per-task created/updated/failed · **MCP:**
  `finalize_draft_plan` (skill `drafting-tickets`).
- **UI:** expand a draft → **Create tasks** (native project; **Update tasks** once finalised) or
  **Create {tracker} tickets** (mirrored; **Update {tracker} tickets**) — `/finalize`. A
  **pre-flight confirm** states the split before the write — "create N new, update M existing"
  (M = draft tasks already created: a `task_id` natively, an `external_id` in a tracker) — since a tracker write is outbound and irreversible. Reports the mode and per-task
  created/updated/failed with the new keys; a partial failure doesn't abort the rest.
- **How the tracker write goes:** logic in `app/services/draft_sync.py`, through the bound
  tracker's `WorkTracker.create_item` / `update_item` — for Jira `POST/PUT /rest/api/3/issue`
  (description as ADF). Epics (summary tasks) are created before their stories so the parent link
  resolves; each pushed draft task is stamped with the item's `external_provider/_id/_key`, so a
  **re-push updates** rather than duplicates. When the admin's integration policy routes the
  tracker's writes via MCP (or disables them), finalise answers **`403`** with the reason; Claude
  then creates the items with its own tools and records them (`record-push`, §J8).
- **Then sync back (mirrored):** canopy does **not** create local tasks on a tracker push — run a
  sync (§J3, `sync_project_tracking`) to pull the new items in as canopy tasks (then
  `replan_schedule`). This keeps the tracker the source of truth for the materialized tickets.
- **Field and type mapping:** the binding's `mapping` (§C12, `PUT /projects/{id}/tracking`) —
  `estimate_field` (e.g. `customfield_10016`; without one, points are skipped), `epic_types`
  (the first is what epics are created as) and `item_type`. For Jira the connection's
  `story_point_field` / `epic_issue_type` / `story_issue_type` (§J1) are the fallbacks
  (default `Epic` / `Story`).

### C10.3 Not built (deliberate limits)
- **No status writes** (by design — the source-of-truth rule holds).
- **Draft dependencies** aren't modeled — the draft captures the WBS (epic→story via `parent_id`)
  and estimates; sequencing/dependencies are added on the live tasks after sync-back.
- No **diff/preview** of "what will change in Jira" before a push, and no automatic
  `replan_schedule` after sync-back (run it from the project header).

---

## D0. Blockers (flagged impediments) **[new — v2 §D-R2]**

The leading signal that work has stalled: an engineer flags an impediment on a task, and it
surfaces where decisions get made — the engineer workspace and the project alerts digest.

### D0.1 Raise / resolve a blocker
- **UI:** `/me` → **Blockers** section → "Flag a blocker on…" (pick one of your tasks + a reason);
  open blockers list with a **resolve** action. Also raisable from the **task detail panel** (§C1a)
  with the enrichment fields below.
- **API:** `POST /api/v1/tasks/{task_id}/blockers` (`reason`, optional `blocking_task_id`,
  `category` [dependency|resource|decision|external|technical], `severity`
  [low|medium|high|critical], `owner_engineer_id`, `needed_by`; `raised_by_engineer_id` defaults to
  the caller's engineer), `GET /api/v1/tasks/{task_id}/blockers`,
  `GET /api/v1/blockers?project_id=&open_only=`, `PATCH /api/v1/blockers/{id}` (`resolved` + the
  enrichment fields), `DELETE /api/v1/blockers/{id}` (planner) · **MCP:** `raise_blocker` (now takes
  category/severity/owner/needed_by), `list_blockers`, `resolve_blocker`. Raise/resolve = any
  contributor; delete = planner.

### D0.2 Where blockers surface
- **`/me` workspace (§M):** open blockers on your tasks or raised by you (`MyWorkspaceResponse.blockers`).
- **Alerts digest (§I/Q):** each open blocker is a `blocked` alert in the project's alerts list
  (shown in the Risk tab). **high/critical** `severity` escalates it from a warning to an **error**,
  and a `needed_by` date is appended to the message.
- **Not yet:** blocked-time folded into the composite **risk score** (Q-R2) and a red marker on the
  Gantt/dependency-graph nodes — follow-ups.

---

## D. Dependencies tab
- **UI:** Dependencies tab → a graph (React Flow) of tasks as nodes and dependencies as arrows,
  laid out left-to-right by topological level; critical-path nodes/edges are red.
- **Data:** same `GET /api/v1/projects/{id}/gantt` payload as the Gantt.

---

## E. Milestones & roadmap

### E1. Define a milestone
- **UI:** Roadmap tab → "Add milestone" form (name, target date) → "Add milestone".
- **API:** `POST /api/v1/milestones` · **MCP:** `create_milestone`.

### E2. Roadmap (now / next / later)
- **UI:** Roadmap tab groups the project's milestones into **Now** (≤30 days / overdue),
  **Next** (31–90 days), **Later** (90+ days / undated).
- **API:** `GET /api/v1/milestones?project_id=`.

---

## F. Team & capacity

### F1. Manage engineers and roles
- **UI:** `/team` (the management persona's landing, §A7) — leads with an **"Open blockers"**
  queue (`components/BlockerQueue.tsx`): every open blocker across the team (from `GET /blockers`
  with no `project_id` filter), sorted worst-severity then soonest-`needed_by`, each showing
  severity/category/owner/needed-by with an inline **resolve** — plus an over-allocation summary
  line (from the org-wide capacity grid below, §F3). All before the roster admin forms. Then: add
  engineers (name, title, **GitHub login**, **timezone**, **committed
  hours/week**, **skill tags**), link an engineer to a **login** (per-row select, admins only),
  add functional roles, and remove engineers. Engineer rows show skills / GitHub / committed hours.
- **API:** `GET/POST /api/v1/team/engineers`, `PATCH/DELETE /api/v1/team/engineers/{id}`
  (engineer payload now includes `user_id`, `skill_tags`, `github_login`, `timezone`,
  `committed_hours_per_week`; an engineer's tracker accounts are `EngineerIdentity` rows the
  sync records, §J3 ownership), `GET/POST /api/v1/team/roles` · **MCP:** `list_engineers`,
  `add_engineer` (extended).
- **Not built (v2 §F1):** on-call schedule (needs the PagerDuty connector §J7).
- **Not built (v2 §F2–F5):** committed-hours/interrupt-budget *allocation*, planned-vs-realized
  capacity, and skill-task fit scores — allocation is still percent-based. **Engineer availability
  now exists (§F4)** but informs the capacity/over-allocation views only, **not** CPM dates.

### F2. Allocate engineers (capacity)
- **UI:** project → Capacity tab → "Allocate" form (engineer, percent, date range) → "Add".
- **API:** `GET/POST /api/v1/team/allocations`, `DELETE /api/v1/team/allocations/{id}`
  (engineer, project, percent allocation, capacity hours, date range) · **MCP:** `allocate_engineer`.

### F3. Capacity heatmap (per-project **and** org-wide)
- **UI:** project → Capacity tab → an engineer × ISO-week grid shaded by total allocation %;
  over-allocation (>100%) is red. The **Team** page (`/team`) shows the same grid **summed across
  every project** ("Capacity across all projects") — so cross-project overload (someone at 50% on
  three projects = 150%) is visible where per-project views hide it; rows split across >1 project
  are flagged with their contributing project keys.
- **API:** `GET /api/v1/team/capacity?project_id=` (omit `project_id` for the org-wide grid;
  `project_id` is `null` in the response and each row carries `projects` = contributing keys, and
  `availability` = week→factor for any week below full capacity) ·
  **MCP:** `get_capacity` (`project_id` now optional). Closes the v2 §F cross-project blind spot.

### F4. Engineer availability (PTO / leave / ramp-up) **[new]**
- **UI:** `/team` → an engineer's **availability** editor — add date ranges with a **capacity
  factor** (0 = fully out, 0.5 = half). Reduced-capacity weeks are shaded on the capacity heatmap.
- **API:** `GET /api/v1/team/availability?engineer_id=`, `POST /api/v1/team/availability`,
  `PATCH/DELETE /api/v1/team/availability/{id}` (`EngineerAvailability`: engineer, date range,
  `capacity_factor`, note). Reads are open; writes are planner-gated.
- **Effect:** the capacity heatmap, the **risk** over-allocation indicator, and the **alerts**
  digest now flag a week as over-allocated when summed allocation exceeds **100% × the worst
  availability factor that week** (so 60% allocation during half-time PTO is already "over").
- **Deliberately not built:** availability does **not** push CPM/schedule dates (that is
  resource-constrained scheduling/leveling — a separate, harder problem); it adjusts the
  capacity/over-allocation *views* only. Per-person time-off does not yet sync from any calendar.

---

## G. Architecture & decisions (Architecture + Decisions tabs)

Components and the system map live on the **Architecture** tab (G1). ADRs are now first-class
**decisions** on their own **Decisions** tab (G2–G6) plus a team-wide **`/decisions`** page — the
architect's unit of work is the decision, so it carries a lifecycle, an owner, stakeholders who
review it, alternatives, reversibility, and a discussion thread.

> **Identity note:** decision **owner**, **proposer**, **stakeholders**, and **comment authors**
> reference **Engineer** records (the team model). An Engineer can now be **linked to a login**
> (`Engineer.user_id`, §A5), which powers the `/me` workspace (§M). Role enforcement now applies
> (§A3a): **engineers can propose and comment** on decisions and edit ADR fields, but **only
> planners (admin / architect / engineering-manager) can change a decision's status** (e.g. accept);
> viewers are read-only.

### G1. Map components (Architecture tab)
- **UI:** Architecture tab → add components (name + kind: service/module/datastore/external/ui) and
  relationships (source → target, kind: depends_on/calls/publishes_to/reads_from). The system map
  (React Flow) shows components colored by kind with relationship edges.
- **API:** `GET/POST /api/v1/architecture/components`, `GET/POST/DELETE
  /api/v1/architecture/component-links` · **MCP:** `list_components`, `create_component`,
  `link_components`.
- **Code bindings** (drift linchpin): the Architecture tab has a **Code bindings** section to tie a
  component to where it lives (`path_glob` + Python `module_prefix`, optional connection/repo) —
  `GET /api/v1/architecture/code-bindings?project_id=`, `POST/DELETE
  /api/v1/architecture/code-bindings[/{id}]` (planner-gated) · **MCP:** `list_code_bindings`,
  `add_code_binding`. These feed drift detection (§N).
- **Component metadata (v2 §G1):** components carry an **owner** (engineer), **criticality**
  (low/med/high), **tier** (presentation/business/data/infra), and an **observability URL** — set on
  the Add-component form (criticality also shown on the map node label).

### G2. Record / propose a decision (ADR) — Decisions tab
- **UI:** Decisions tab → "Propose / record a decision": title, context, decision, consequences,
  **alternatives** (one per line), **reversibility** (one-way / two-way door), **decision owner**,
  **proposed by**, **stakeholders** (must review), supersedes, affected components → "Save". The
  team-wide `/decisions` page has a lighter "Propose a decision" form (engineer flow).
- **API:** `POST /api/v1/architecture/adrs` (now also accepts `alternatives`, `reversibility`,
  `decision_owner_id`, `proposed_by_id`, `decide_by`, `rfc_url`, `stakeholder_ids`) · **MCP:**
  `create_adr` (architect records) / `propose_adr` (engineer proposes — sets `proposed_by_id`,
  status `proposed`).
- **List:** `GET /api/v1/architecture/adrs?project_id=` backs the Decisions-tab list (omit
  `project_id` for org-wide) · **MCP:** `list_adrs`.
- **Lifecycle:** `proposed → under_discussion → accepted | rejected → superseded | deprecated`,
  plus **`deferred`** (a conscious postponement — **requires a `decide_by` date**, enforced 400).
  Illegal jumps (e.g. `deprecated → proposed`) are rejected 409. The legal map is in
  `app/services/decisions.py:valid_transition` (mirrored client-side in `src/lib/decisions.ts`).

### G3. Discuss & review a decision
- **UI:** Decisions tab → click an ADR to expand: full context/decision/consequences/alternatives,
  a **status control** (only legal transitions; a `decide_by` date appears when deferring), a
  **review summary** (approved / changes-requested / rejected / pending + whether the project's
  decision rule is met to accept — plus an advisory **"N design doc(s) not approved yet"** chip
  when a doc it rests on or waits for is not approved, §V9), a **Design docs behind this
  decision** panel (§V7), a **blast-radius** button (G5), and the **discussion thread**.
  Post a comment with a **kind**: `comment` | `approve` | `request_changes` | `reject` (a
  non-comment kind is a formal review action, attributable to an engineer).
- **API:** `GET /api/v1/architecture/adrs/{id}` (detail: fields + comments + review summary),
  `POST /api/v1/architecture/adrs/{id}/comments`, `PATCH /api/v1/architecture/adrs/{id}`
  (status transitions, stakeholders, all fields) · **MCP:** `get_adr`, `comment_adr`,
  `transition_adr`.
- **Decision rule** (per project, `PATCH /api/v1/projects/{id}` → `decision_rule` =
  `owner_decides` | `consensus` | `lazy_consensus`, `decision_sla_hours`): drives the advisory
  `can_accept` in the review summary. It is surfaced, **not hard-enforced** — the owner can still
  decide. Per-stakeholder approval *gates* and SLA *notifications* are **not built** yet.
  The summary also carries `docs_ready` / `docs_pending` (advisory, §V9); **accepting** an ADR
  pins every basis design doc to its current version.

### G4. Decision queue
- **UI:** the **`/decisions`** page (team-wide, also in the sidebar) and the top of each project's
  Decisions tab show the queue, grouped by bucket: **needs_triage** (proposed, with the owner's
  SLA), **stuck** (under discussion > 14 days), **deferred_soon** (`decide_by` within 14 days /
  past), **discussing**. Overdue items sort first; rows link into the owning project's Decisions tab.
- **API:** `GET /api/v1/decisions/queue?project_id=` (omit `project_id` for org-wide) · **MCP:**
  `decision_queue`. Logic is pure in `app/services/decisions.py:build_decision_queue`.
- **Not built:** **implicit decisions** (architectural choices made in code without an ADR) require
  drift detection (v2 §N) and are not surfaced here yet.

### G5. Decision-impact analysis (blast radius)
- **UI:** Decisions tab → expand an ADR → **Blast radius**: the components it directly affects plus
  everything that transitively depends on them. (v2 §G4: now in the UI, no longer Claude/API-only.)
- **API:** `GET /api/v1/architecture/adrs/{id}/impact` · **MCP:** `adr_impact`.
- **Not built:** `whatif_supersede` preview (v2 §G4).

### G6. Import an ADR from a doc
- **UI:** Decisions tab → "Import an ADR from a doc" (planner): pick a GitHub/Drive connection + a
  path/file id → the markdown is parsed (title + context/decision/consequences) into an ADR.
- **API:** `POST /api/v1/architecture/adrs/import` · **MCP:** `import_adr`.
- **From a design doc's text (§V9):** `POST /api/v1/architecture/adrs/import-text`
  `{project_id, markdown, doc_id?, doc_version?, fallback_title?}` (planner, project owner) — a
  session exports a Claude doc or artifact as markdown; the ADR's fields become canopy's own
  record and, with `doc_id`, the doc is linked as the ADR's **basis** pinned to the version read
  · **MCP:** `import_adr_from_markdown`.

### G7. Fitness functions (machine-checkable decisions) **[new — v2 §G-R1]**
- **What:** a decision can carry **fitness functions** — dependency rules over the component graph
  the drift scan enforces. `forbid`: source must NOT depend on target; `require`: it MUST. When the
  ADR is **accepted**, a violation appears in the drift queue as a `fitness_violation` (the heaviest
  drift signal — an accepted decision isn't being honored), and **auto-resolves** when the code is
  fixed. This is the decision→verification spine: a decision that defends itself.
- **UI:** Decisions tab → expand an ADR → **Fitness functions** (list + add `forbid`/`require` rule
  picking source/target components). Violations show on the **Drift** tab (§N).
- **API:** `GET/POST /api/v1/architecture/adrs/{id}/fitness`, `DELETE /api/v1/architecture/fitness/{id}`
  (components must be in the ADR's project) · **MCP:** `add_adr_fitness`. The ADR detail
  (`GET .../adrs/{id}`) includes `fitness_functions`.
- **Traceability:** whether a decision is honored, from its rules and the work behind it, is the
  ledger (§G8).

### G8. Traceability ledger — what implemented a decision, and is it still honored **[new — v2 §T]**
- **What:** each decision joined to the work that **implements** it (`Task.implements_adr_id`)
  or **touches what it governs** (tasks tied to its components — a session's plan resolves the
  components its paths touch, §AE3), the **pull requests** behind that work, the **reviews** that
  checked the work against it (a review whose `checked` list names it, e.g. `ADR-0001`), its
  **fitness rules** (§G7) and the **open drift** on what it governs (§N). A **verdict** is computed
  from those facts, never stored — the first that holds, worst first: **violated** (a fitness rule
  is broken in the code), **unimplemented** (the scan finds no code implementing it), **at risk**
  (open drift on its components, or the reviews that checked it failed), **in progress** (its
  implementing work is still open), **no linked work**, **not binding yet** (not accepted),
  **honored**, **retired** (superseded, deprecated or rejected).
- **UI:** project → **Architecture → Decisions** → the **Traceability ledger** panel: one row per
  decision, worst first, with the reason and the counts (tasks done, PRs merged, rules broken,
  reviews that checked it, open drift); a row opens the decision. Expand a decision →
  **Traceability**: the verdict and why, what it governs, the tasks that implement it and those
  that touch what it governs, their PRs (merged / open / closed, checks), the reviews that checked
  it, each fitness rule (**Broken** / **No open violation**) and the open drift. Planners **link**
  the task that implements it, or **unlink** one.
- **API:** `GET /api/v1/architecture/adrs/{id}/traceability` (one decision, with its facts) ·
  `GET /api/v1/architecture/traceability?project_id=` (the ledger) · the link is
  `PATCH /api/v1/tasks/{id}` `{implements_adr_id}` — a decision of the task's own project
  (`422 adr_not_in_project`; `null` unlinks). Reads are open. **MCP:**
  `get_decision_traceability(adr_id | project_id)` (read), `link_task_to_decision`.
- **Honest limits:** canopy doesn't read code — *violated* and *unimplemented* come from the drift
  scan's findings (§N, run by the Drift Sentinel), so a stale scan means a stale verdict; a
  decision's components decide what work it governs, so a decision without components traces only
  the tasks linked to it. Decision latency (how long decisions take) is not on the ledger.
- **Where:** pure `app/services/traceability.py` (facts → verdict, ledger row) +
  `traceability_service.py` (loads the facts; the ledger reads the project's plans and open drift
  once); `tests/test_traceability.py`. The demo links implementing tasks and seeds drift with the
  scan's own keys, so the decisions show each verdict (`tests/test_demo_seed.py`).

---

## H. Progress: burndown
- **UI:** project → Burndown tab → a line chart of remaining vs completed work per week. (v2 §H
  folds burndown into Risk and adds cumulative flow / cycle time / throughput / PR latency — those
  extra charts are **not built**, and burndown stays its own tab for now.)
- **API:** `GET /api/v1/projects/{id}/burndown` · **MCP:** `get_burndown`.
- **Notes:** burndown is driven by task **status history**, recorded on every status change —
  a board move (§C9) for canopy-owned tasks, every sync/webhook/ingest that changes a mirrored
  task's status (§J3), and the changelog backfill (§J5). A task counts as completed when it enters
  a `done`-category status. Without any transitions the chart is flat at the total.

---

## I. Alerts / digest
- **UI:** the old standalone **Alerts** tab is **gone** — alerts now live as the *lagging-indicator*
  section inside the **Risk** tab (§Q). Same content: deadline misses (error), overdue milestones /
  over-allocations / **open blockers** / **`sprint_overrun`** — an open task in an active sprint
  whose computed end falls after the sprint ends (§C11) (warning), unscheduled work (info) —
  and, with `ai.work_queue` on, agent work that needs a person (§AE): **`task_parked`** (error —
  sessions used up their attempts), **`gate_waiting`** (warning past the gate's reminder, error
  past its escalation threshold), **`claim_stale`** (warning — the session hasn't checked in for
  half its lease) and **`claim_overrun`** (warning — held longer than `WORK_CLAIM_OVERRUN_HOURS`).
  With `ai.stage_policy` also on, where the flow is stuck (§AE8): **`work_unclaimed`** (ready for
  a role longer than `WORK_UNCLAIMED_HOURS` — nothing is running that role's sessions),
  **`rework_loop`** (a task has gone back for rework as often as its column allows — one more
  escalates it), **`review_saturated`** (a review/QA/decision column is at its WIP limit while
  work waits upstream), **`merged_ahead_of_stage`** (a PR merged before its review/QA/sign-off
  ran, last 14 days) and **`rule_stale`** (a rule follows a decision that was superseded or
  deprecated, §AE7). On mirrored projects (§AE9): **`moved_without_clearance`** (a ticket moved in
  its tracker without canopy clearing it) and **`clearance_waiting`** (a cleared move the tracker
  still doesn't show after `WORK_CLEARANCE_HOURS`).
  **Design-doc alerts** (§V8) for the docs that bear on the project: `doc_changed_since_approval`
  and `doc_behind_pin` / `doc_gate_open` (warning), `doc_restricted` (a shared Claude doc made
  private) and `doc_broken` (error) — `entity_type: "doc"`; on the project **Overview** they drill
  to the **Docs** tab.
- **API:** `GET /api/v1/projects/{id}/alerts` (unchanged) · **MCP:** `list_alerts`.
- **Notes:** delivery to Slack/email is **not built** — alerts are computed and shown/queried; a
  delivery integration is a future hook over this output.

---

## Q. Risk dashboard (Risk tab) — leading indicators

Replaces Alerts as the primary risk surface (v2 §Q). A per-project, opinionated **risk score**
(0–100, higher = riskier) with a drillable breakdown, plus a mitigation log; the lagging Alerts
digest (§I) sits underneath.

### Q1. Risk score & breakdown
- **UI:** project → **Risk** tab → the overall score + level (low/moderate/high/critical) and four
  **families**, each with a score bar and drillable **indicators**:
  - **Schedule** — deadline misses, schedule variance vs baseline (drifted tasks), critical-path
    float consumption, **estimate uncertainty** (count of tasks whose 3-point estimate spread is
    wide — see §C1a; stays inside the schedule weight, no new family).
  - **Capacity** — engineer-week over-allocation (from the capacity grid).
  - **Architecture** — deferred decisions past `decide_by` + decisions stuck in `under_discussion`
    > 14 days (both from §G) **+ the drift score (§N)** as a third indicator.
  - **Quality** — **build failures + open incidents** from §J8 activity events. When a project has
    **no** observability events the family doesn't drop out; it scores an explicit **observability
    coverage** gap and the response carries `confidence: "low"` with a note — so a blind project is
    flagged ("flying blind"), never silently scored as *safer* (the old behaviour excluded the
    family and renormalised). (PR-latency / churn metrics, v2 §J6, would enrich it further.)
- Each indicator carries a 0–100 sub-score and drill-down **details** (the offending tasks /
  decisions / engineer-weeks). Scoring weights/thresholds live in `app/services/risk.py` (pure).
- **API:** `GET /api/v1/projects/{id}/risk` · **MCP:** `get_risk`. The same scorer feeds the
  portfolio card's `risk_score` (§B1).

### Q2. Risk timeline
- **UI:** Risk tab → a sparkline of recent risk **snapshots** next to the score; planners can also
  **Capture snapshot** on demand.
- **API:** `GET /api/v1/projects/{id}/risk/timeline`, `POST /api/v1/projects/{id}/risk/snapshot`.
  Snapshots persist score + level; the trend matters more than any single value.
- **Auto-capture (v2 §Q-R3):** the arq **worker** runs a nightly cron (`capture_risk_snapshots`,
  03:00) that snapshots **every** project, so the trend is real without anyone clicking. The job is
  `run_risk_snapshots` in `app/api/v1/risk.py`.

### Q3. Indicator acknowledgements **[renamed from "Mitigation log"]**
- **UI:** **Risk score** tab → **Acknowledge** any indicator with a note, an owner, and a check-in
  date; open acknowledgements show inline under their indicator and in the **Indicator
  acknowledgements** panel (resolve / reopen / delete).
- **API:** `GET` (embedded in the risk response), `POST/PATCH/DELETE
  /api/v1/projects/{id}/risk/mitigations[/{mid}]` · **MCP:** `log_risk_mitigation`.
- **Note:** an acknowledgement **acknowledges a computed indicator**. It was renamed from
  "Mitigation log" because the RAID register (Q3a) has its own **mitigation** field — two different
  "mitigation" concepts on one screen was the confusion. It is distinct from the **risk register**
  (Q3a), which tracks human-identified qualitative risks.

### Q3a. Risk register (RAID) **[new]**
- A **human-tracked** risk register, kept **separate from the computed risk score** (it does not feed
  the 0–100 score). Each entry hangs off a **task / project / initiative**, graded by **probability ×
  impact** (low/medium/high each → an exposure of 1–9, banded to low/moderate/high/critical), with an
  owner, a **mitigation** (lower the probability), a **contingency** (if it occurs anyway), and a
  target resolution date. Status: open | mitigating | accepted | resolved | occurred (terminal
  statuses stamp `resolved_at`).
- **UI:** its **own "Risk register" sub-view** under the project Governance group (`?tab=raid`),
  separate from the computed Risk score (§Q1) — a ledger, not a dashboard — plus on the
  **initiative** cockpit and in the **task detail panel** (§C1a). List with exposure/status badges +
  add / status / delete. Writes are planner-gated.
- **API:** `GET /api/v1/risks?scope_level=&scope_id=&status=`, `POST /api/v1/risks`,
  `GET/PATCH/DELETE /api/v1/risks/{id}`, `POST /api/v1/risks/{id}/close` · **MCP:** `list_risks`,
  `add_risk`, `update_risk`, `close_risk`.
- **Where it surfaces:** the portfolio card shows a project's **open-risk count** (§B1/B4); an open
  register risk **past its target_resolution_date** appears in the alerts digest (§I) as a
  `risk_overdue` alert (error when high-exposure) — reporting only, the **computed score is
  unchanged**.

### Q4. Not built (v2 §Q)
- Automated **check-in follow-ups** / notifications on mitigations past their date.
- PR-latency / churn **quality** metrics (need GitHub PR-metrics, §J6). *(The nightly risk-snapshot
  schedule is now built — the arq worker captures it; see Q2.)*
- Folding the **risk register** into the computed score (deliberately kept separate for now), and the
  full RAID set (assumptions / issues) — the register is risks-only today.

---

## N. Architecture drift detection (Drift tab)

The central value prop: catch where the code has diverged from the declared architecture. Detection
is **pure** (`app/services/drift.py` + `app/services/code_analysis.py`); the **Drift Sentinel**
subagent (§L7) reads code and reports observations, and the server compares them to the declared
component map + ADRs and maintains the queue.

### N1. Drift score
- A per-project 0–100 score (higher = more drift), derived from the currently **open** drift events
  by kind, shown on the **Drift** tab and on every portfolio card (§B1). Computed by the same scorer
  in both places.
- Signals: **declared-vs-actual dependencies** (unexpected edges in code / declared edges absent
  from code = dead architecture), **unimplemented ADRs** (accepted ADRs whose affected components
  show no activity), and **implicit decisions** (new package / dependency / service / datastore with
  no ADR).
- **Code analysis:** Python imports are parsed with the stdlib `ast` and mapped back to components
  via their code-binding `module_prefix` (`app/services/code_analysis.py`, pure + unit-tested). Other
  languages can plug in later; the edge-mapping is language-agnostic.

### N2. Drift queue & scan
- **UI:** Drift tab → the score + the **drift queue** (open events first, then triaged): each event
  shows its kind, summary, affected components, and suspected cause.
- **API:** `GET /api/v1/projects/{id}/drift` (score + events + **`last_scanned_at`** and
  **`scan_due`**) · `POST /api/v1/projects/{id}/drift/scan`
  (architect-gated) accepts the Sentinel's observations (`actual_edges`, `inactive_component_ids`,
  `implicit_signals`), runs detection (applying learned suppressions), and upserts events — new
  findings open, resolved ones disappear, triaged ones persist. **MCP:** `get_drift`, `scan_drift`.
- **Scan staleness (v2 §N-R1):** every scan is logged (`DriftScan`), so the Drift tab shows
  **last scanned** and a **scan due** badge when code bindings exist but the scan is missing or
  older than ~7 days — prompting a Sentinel re-scan. (The server can't crawl code itself, so the
  loop is: staleness surfaced here → the Drift Sentinel re-scans. A push-webhook that *enqueues* the
  Sentinel is the remaining piece — N4.)

### N3. Reconciliation
- **UI:** Drift tab → per open event (architect): **Accept → ADR** (auto-proposes an ADR for the
  change, linking the affected components), **Reject → task** (opens a "Revert drift: …" task), or
  **False positive** (records a per-project suppression so the rule won't re-fire). The detector
  "learns" from false positives.
- **API:** `POST /api/v1/projects/{id}/drift/{event_id}/reconcile` (`accepted|rejected|false_positive`)
  · **MCP:** `reconcile_drift`.

### N4. Not built / honest limits
- **No server-side code crawl:** the server doesn't fetch + parse a whole repo itself — the **Drift
  Sentinel** subagent does the reading (via its tools) and posts observations to the scan endpoint.
  So the Drift tab is populated by the Sentinel (or the API/plugin), not by a UI button.
- Only **Python** import analysis is implemented. Per-project **suppression UI** (events are kept as
  `false_positive`); folding drift into **Risk** (§Q1) — both follow-ups.

---

## P. Retrospectives & postmortems (Retros tab)

### P1. Project retrospective
- **UI:** project → **Retros** tab → **New retrospective** (planner) opens a retro whose body is
  **auto-seeded** from project state: completed milestones, schedule variance (tasks ended off
  baseline), open drift (§N), ADR churn (superseded/total), and the **design docs that changed
  after approval** (approved vs current version, §V9). It's editable markdown; engineers
  **comment**; planners can **close** it.
- **Agent work** (with `ai.work_queue` on, once sessions have worked the project): the seed adds
  an **Agent work** section from the last 8 weeks of the project's agent flow (§AE8) — sessions
  finished and agent-worked tasks done (with the share that needed no person but the sign-off),
  the median time people took to decide per gate kind, first-pass acceptance, rework, parked
  tasks, tracker moves made without canopy's clearance (§AE9), cost per task when sessions report
  it, and the gates approved nearly every time — candidates to relax through graduated autonomy
  (§AE6). Team-level numbers only, never per person.
- **Follow-ups:** from a retro, mint a **task** or **propose an ADR** (linked to the retro's
  affected components) — turning lessons into tracked work.
- **API:** `GET/POST /api/v1/projects/{id}/retrospectives`, `GET/PATCH
  /api/v1/projects/{id}/retrospectives/{rid}`, `POST .../comments`, `POST .../follow-up`
  (`task|adr`) · **MCP:** `list_retrospectives`, `create_retrospective`, `comment_retrospective`,
  `retrospective_follow_up`. The seeder is pure (`app/services/retro.py`).
- **Roles (§A3a):** create / edit / close / follow-up = planners (admin/architect/eng-manager);
  comment = any non-viewer; read = anyone.

### P2. Incident postmortem
- **UI:** **New postmortem** opens a templated postmortem (timeline / impact / root cause / action
  items) that can record affected components and mint the same follow-ups.
- **Not built (v2 §P2):** **auto-open from an incident webhook** — that needs the CI/observability
  connector (§J8); for now a postmortem is opened manually.

---

## J. Connectors & integrations (Connectors page)

### J0. Work trackers — the pluggable layer **[new]**
Execution works **with or without** a tracker, and Jira is one tracker among several.
- **Three layers:** a `Connector` (credentials, HTTP, OAuth refresh, the demo mock) → a
  **`WorkTracker`** (`app/connectors/tracker.py`: declares `capabilities`, a connection
  `config_schema` and a binding `scope_schema`; only **fetches and normalizes** into
  `app/services/tracker_types.py` and writes item **content** — there is deliberately no status
  write, so canopy cannot transition an item back) → the **sync engine**
  (`app/services/tracker_sync.py`, the only caller: upsert, parents, epic → project, watermarks,
  status history, sprint/cycle mirroring, auto-replan — written once for every tracker). A new
  tracker is one module + `@register_tracker`; no migration, engine or UI change (provider
  columns are VARCHAR).
- **Bindings (`TrackerBinding`):** what a connection feeds — a canopy project (or initiative)
  bound to a scope in the tracker: a whole tracker project (`scope_kind=project`, e.g. a Jira
  project key / board / JQL), one item and its descendants (`subtree` — a tracker link, §J9) or
  a query. A binding owns its watermark, type/field mapping (epic types, estimate field), the
  tracker's **status map** (statuses + categories + order: a mirrored project's columns, §C9.1)
  and the nightly backfill cursor. Only a binding row feeds a project: the pre-binding
  `config.project_id` is no longer read (migrations a9b0c1d2e3f4 + b0c1d2e3f4a5 turned every
  one into a binding and removed it), and creating a tracker connection with it is refused —
  `project_id` goes beside the config (§J1). **Identities (`EngineerIdentity`)** map an
  account in any tracker onto one engineer (matched by account id, then email, then exact name;
  else auto-created).
- **Trackers shipped:**
  - **Jira** (`app/connectors/jira.py`) — everything: JQL reads, project statuses with their
    categories, changelog history, board sprints, webhooks (`/webhooks/jira`), OAuth, content
    writes.
  - **Linear** (`app/connectors/linear.py`) — GraphQL reads of a team's issues (scope
    `team_key`, optionally a `linear_project_id` or `label`), workflow states (their type gives
    the category: triage/backlog/unstarted → todo, started → in progress, completed → done,
    canceled → cancelled), issue history, **cycles → tracker-owned sprints** (the active and
    upcoming ones plus the last three completed), signed webhooks at `/webhooks/linear`
    (`Linear-Signature`, `LINEAR_WEBHOOK_SECRET`), OAuth (`LINEAR_OAUTH_CLIENT_ID/SECRET`) or a
    personal API key, content writes (issue create/update — never a state change). An issue
    with sub-issues (or a label named in the binding's `epic_labels`, default "Epic") is an
    epic. Browse links need the connection's `workspace_url_key`.
  - **Generic** (`app/connectors/generic.py`) — any tracker canopy has no connector for
    (Shortcut, Asana, an in-house tool, a spreadsheet). canopy never calls it (`direct_read:
    false`): items arrive through MCP ingest (`ingest_work_items`), a JSON/CSV file drop, or its
    signed webhook (`/webhooks/generic`, `X-Canopy-Signature: sha256=<hex>`,
    `GENERIC_WEBHOOK_SECRET`, body `{"item": {<an ingest item>}, "scope": {"project_key": "…"},
    "action": "upsert"|"remove"}`). Bindings, the board, switching and history work as for any
    tracker; browse links come from the connection's `item_url_template`
    (`https://…/{key}`).
  Linear and generic are opt-in (`TRACKERS_ENABLED=jira,linear,generic`); the demo mock serves
  a Linear workspace too (an unbound "Linear — example workspace" connection is seeded when
  Linear is enabled).
- **Config:** `TRACKERS_ENABLED` (comma-separated provider keys, default `jira`; empty = native
  only), `TRACKING_DEFAULT_MODE` (`native`, reported for new projects),
  `TRACKER_POLL_MINUTES` (default 10), `<PROVIDER>_WEBHOOK_SECRET`.
- **Discover:** `GET /api/v1/meta/trackers` (**MCP:** `list_trackers`; `get_workspace_context`
  lists the enabled ones and each project's `tracking_mode`) — each registered tracker with its
  label, whether it is `enabled`, its `capabilities`, the JSON Schemas of its connection and scope forms, and
  its webhook path + secret setting; plus `default_tracking_mode`. (Rendering the Connectors form
  and a project Tracking panel from it is Phase 4 — see Known UI gaps.)
- **Contract:** `tests/test_tracker_layer.py` runs the same checks over every registered tracker
  (implements what it declares, no status write, webhook verification fails closed) and pins the
  import boundary (the engine never imports a concrete tracker).

### J1. Add a connection **[updated — tracker catalog + binding]**
- **UI:** `/connectors` → choose a provider — the **enabled work trackers** from
  `GET /meta/trackers` (directly-read ones first; Jira, Linear, Generic tracker…), then GitHub and
  Google Drive — name it, optionally paste an API token, then fill **typed config fields** instead
  of hand-writing JSON — Jira: **Site URL**, **Account email**, **Jira project key**, **Mirror into
  canopy project (optional)** (picking one **binds** that project, §C12); other trackers: fields
  rendered from their `config_schema`; GitHub: **Owner / org**, **Repository**, **canopy
  project**. A tracker row that takes webhooks shows its **webhook URL** and the env var holding
  its secret; **Remove** says whether the connection was deleted or only deactivated, and the
  `project_already_bound` / `connection_in_use` refusals link to the projects' Tracking tabs. The **canopy project** field is a **picker** (choose a project
  by `key — name`; stored as a numeric `project_id`) so nobody has to look up an internal id.
  Switching provider swaps the field set. An **Advanced (extra config as JSON)** disclosure remains
  for uncommon keys — e.g. Jira ticket-creation keys used by §C10 (`story_point_field` like
  `customfield_10016`, `epic_issue_type` default `Epic`, `story_issue_type` default `Story`) or
  `board_id`. Merge rule (pure `frontend/src/lib/connectorFields.ts`, unit-tested): advanced JSON is
  the base, typed fields override same-named keys, empty typed values are dropped.
- **API:** `POST /api/v1/connectors/connections` (token is encrypted at rest) · **MCP:**
  `list_connections`. A **tracker** connection given a canopy `project_id` — **beside** the
  config, `{provider, name, token, config, project_id}` (the project picker sends it so) — also
  **binds** that project to it — mirrored, scope from the config (e.g. `jira_project_key`), type
  and field mapping too (`story_point_field` → `estimate_field`), its existing work kept separate
  — the same as a switch (§C12); `409 project_already_bound` when the project is already
  mirrored (switch its tracking instead), `422` for a `project_id` on GitHub/Drive (only a
  tracker mirrors a project) and for the retired pre-binding shape, `config.project_id` on a
  tracker. GitHub and Drive keep their **canopy project** inside their config.
- **Delete:** `DELETE /api/v1/connectors/connections/{id}` refuses a connection that still feeds
  a project (`409 connection_in_use`, with the `project_ids` — switch them first); one that
  synced refs, past bindings, links or personal credentials still name is **deactivated**
  (kept, so that history keeps its meaning); anything else is deleted.
- **Cross-link:** the page notes that connecting **Claude Code itself** (MCP token + plugin) lives on
  **Agent Setup** (§A11), and Agent Setup links back here for **data** connectors — the two
  integration surfaces are now explicitly paired.

### J2. Connect via OAuth (shared service connection)
- **UI:** on a connection row → **Connect** (or **Reconnect**). The browser is redirected to the
  provider's consent screen; after approval the provider redirects back and the connection shows
  **authorized**.
- **API:** `GET /api/v1/connectors/oauth/{connection_id}/authorize` → provider URL (CSRF `state` is a
  signed JWT); provider redirects to `GET /api/v1/connectors/oauth/callback`, which exchanges the
  code, stores encrypted access + refresh tokens, and (for Jira) resolves the cloud id.
- **Scopes:** Jira `read:jira-work write:jira-work read:jira-user offline_access`; Linear
  `read,write`; Google Drive
  `drive.readonly` + `drive.file` (`drive.readonly` is the CASA-restricted one — an **Internal
  Workspace** app avoids Google verification); GitHub `repo read:org`.
- **Setup:** requires registered OAuth apps + `*_OAUTH_CLIENT_ID/SECRET` env vars.

### J2a. Per-user SSO — connect your own account **[new — Phase 2]**
When the admin enables `allow_user_connect` for a provider (§A8), a `Connection` is the
**integration definition** (target config + an *optional* shared service token) and each user can
attach their **own** OAuth credential to it — canopy then reads/writes **as that user**.
- **UI:** `/connectors` shows "per-user SSO available" on eligible connections with a **Connect my
  account** button (and "your account connected" once done).
- **API:** `POST /api/v1/connectors/oauth/{connection_id}/connect-me` (any authenticated user; 403 if
  the provider's `allow_user_connect` is off). The signed `state` carries the user id so the
  (unauthenticated) callback binds the tokens to a **`UserConnection`** (the user's personal
  credential, with **its own watermark**). `GET /connectors/connections` reports `allow_user_connect`
  + `user_connected` per row.
- **Resolution:** background reads (the reconciliation poll) use the shared service token; a
  **user-triggered** read (Sync now) uses the caller's own credential when present (else shared);
  **writes** (push-to-Jira §C10, export-to-Drive §S) use the caller's own credential for attribution,
  falling back to the shared token. A narrow-access user's pull is **non-destructive** — sync is
  upsert-only and each `UserConnection` keeps its own watermark, so it can't remove what the service
  token populated or disturb the service cursor (`app/services/integration_policy.py`).

### J3. Sync from Jira (any tracker)
- **UI:** on a Jira connection → **Sync now** (full sync). Every binding the connection feeds
  (§J0) is pulled through the shared engine: epics→summary tasks and stories→leaf tasks
  (idempotently, via `ExternalRef` — now scoped to the connection, since two sites can share
  ids), the tracker's status map refreshed on the binding, sprints mirrored when the binding
  syncs iterations, and the project **auto-replanned** when new tasks are created. The result
  shows created/updated/skipped.
- **Ownership (assignee → Engineer):** each issue's **assignee** is mapped onto a canopy
  **Engineer** — matched by the tracker identity (`EngineerIdentity`), then by email, then by
  exact name (case-insensitive, which records the identity), else **auto-created** — and set as the task's owner, so synced work
  arrives with clear individual ownership on the Gantt/Board/workspace (§C6a, §M). An issue that is
  **unassigned in Jira leaves a locally-set owner untouched** (local assignment stays usable);
  a set Jira assignee wins over a local one. Synced tasks are **Jira-owned** (`status_owner =
  jira`, key = the Jira key) and their status stays read-only in canopy.
- **Status history on every sync:** when a sync, webhook or ingest changes a task's status it
  appends a `TaskStatusHistory` row (dated by the issue's `updated`, `source = sync`, category
  stamped), so burndown, forecast, aging and delivery metrics have data from the first sync
  without calling the per-issue history endpoint. The changelog backfill (§J5) later replaces
  these approximate rows with the exact transitions.
- **Completion (progress %):** sync mirrors completion from the issue status — a **done** status
  marks the task **100%** complete, and an issue that regresses out of done drops back to 0 (a
  not-yet-done issue keeps any manually-entered partial progress). This keeps the status-derived
  views (board/burndown/forecast/DORA) and the progress %/portfolio rollups agreeing on one
  definition of done, so a Jira-driven project no longer reads as 0% complete with an inflated
  forecast. Shared by the direct sync and the MCP ingest (§J3a). **"Done" is recognized across the
  common completion columns** — `done/closed/resolved/complete(d)/shipped/deployed/released/live/
  merged/accepted` (the name heuristic in `app/services/workflow.py:resolve_category`, used when
  neither the tracker nor the workflow says), so a board that ends in "Shipped" registers as done
  everywhere; the status **category** stamped on the task and on each history row is what every
  view reads.
  Completion is counted **once per task** (last done transition) — a reopened-then-redone task no
  longer double-counts (which had inflated throughput and could drive burndown remaining negative).
- **API:** `POST /api/v1/connectors/connections/{id}/sync` (full) and `.../sync/incremental`
  (every binding of the connection), or one project's binding with
  `POST /api/v1/projects/{id}/tracking/sync` (§C12) · **MCP:** `sync_tracker`,
  `sync_project_tracking`.
- **Background:** an arq worker runs `tracker_incremental_sync` (every enabled tracker canopy
  reads directly) every
  `TRACKER_POLL_MINUTES` as the correctness backstop behind webhooks — one failing connection is
  logged and skipped — and a nightly `tracker_history_backfill` (03:30) that replays the next
  batch of mirrored tasks' changelogs past each binding's cursor (§J5).
- **Note:** the poll, webhooks, and "Sync now" all **stand down** when the provider's read strategy
  is `mcp`/`file` (§A8) — the data then arrives via ingest (§J3a) or a file drop (Phase 4).

### J3a. MCP-orchestrated ingest — Claude pushes data in **[new — Phase 3]**
When a provider's reads (or writes) are **MCP-managed** (admin set them to `mcp`, §A8), canopy
doesn't call the provider API. Instead **Claude** reads the external system with its own connectors
and pushes **normalized** data into canopy idempotently — the MCP twin of the direct sync. Every
ingest upserts via `ExternalRef` (never deletes), maps into the project the connection is bound to,
and (issues) replans on new tasks; ingest does **not** advance the connection watermark.
- **Issues → tasks (any tracker):** `POST /api/v1/connectors/connections/{id}/ingest/issues`
  (`{issues:[{external_id, external_key, summary, status, status_category?, issue_type?,
  kind? (epic|item|subitem), parent_external_id, updated, assignee_account_id?,
  assignee_name?, assignee_email?, estimate?, url?}], project_id?}`) · **MCP:**
  `ingest_work_items`. The connection must be a work tracker (else `400`); items land in its
  binding's target — pass `project_id` when it feeds several, and a connection bound to nothing
  is refused (both `400`). Epics→summary;
  re-ingest updates, never duplicates; assignees map to Engineers exactly like the direct sync
  (§J3 — the same engine). This is also how a tracker canopy can't read itself
  (`direct_read: false`) is kept in sync.
- **PRs → cache:** `POST .../ingest/pull-requests` · **MCP:** `ingest_github_pull_requests`. An
  item may also carry what the source knows of its review / check / merge state (`draft`,
  `merged`, `merged_at`, `merged_by`, `head_sha`, `additions` / `deletions` / `changed_files`,
  `review_decision`, `approved_by`, `checks_state` — §J6); omitted fields keep the cached value.
- **Draft push write-back (writes=`mcp`):** when finalising can't write to the tracker by policy,
  Claude creates the items itself then `POST /api/v1/draft-plans/{id}/record-push`
  (`{results:[{draft_task_id, provider?, external_id, external_key}]}` — `provider` defaults to
  the tracker the project is bound to, and must name a work tracker) stamps each task and flips
  the plan to `synced` (idempotent) · **MCP:** `record_draft_push`.
- **Auth:** ingest + record-push are **planner-gated but not human-only** — internal, idempotent
  two-way-door writes, so a scheduled Claude job using an **agent-scope token** (§A6) may call them
  (the external read/write happens through Claude's own connectors, outside canopy's agency gate).
- **Scheduling:** lives on the architect's Claude account (`/loop` or a scheduled task); canopy
  doesn't drive it. Runbook: skill **`mcp-ingest`**. Logic: `app/services/ingest.py` (shares the
  task-upsert core with the Jira sync so the two paths can't drift).

### J3b. File-drop ingest — import a JSON/CSV export **[new — Phase 4]**
A second *transport* for the same ingest (§J3a): drop an export file and canopy parses + loads it
idempotently. The entity type is inferred from the connection's provider (a work tracker →
items, GitHub→PRs); invalid rows are reported and skipped (a bad row never aborts the file). Two ways in:
- **Upload:** `/connectors` → **Import file** on a tracker/GitHub connection (or
  `POST /api/v1/connectors/connections/{id}/ingest/file`, multipart; planner-gated, agent-allowed).
  Accepts **JSON** (an array of `IngestIssue`/`IngestPullRequest` objects) or **CSV** (header row =
  field names). Returns `{provider, created, updated, skipped, parsed, errors}`.
- **Watched shared storage:** an arq cron (`poll_file_drops`) ingests files dropped into a
  configured backend — **local** directory or **S3** bucket (`[s3]` extra) by deployment, *not*
  Drive. Layout `<root>/<connection_id>/*.{json,csv}`; each file is moved to `processed/` (or
  `failed/` + an `.error` note) so the poll is idempotent without a tracking table. Disabled when
  no backend is configured. Config: `FILE_DROP_BACKEND` (`local`|`s3`), `FILE_DROP_LOCAL_DIR` /
  `FILE_DROP_S3_BUCKET` / `FILE_DROP_S3_PREFIX`, `FILE_DROP_POLL_MINUTES`.
- Logic: `app/services/file_ingest.py` (parser) + `app/services/file_drop.py` (storage backends +
  poll), reusing the §J3a idempotent ingest.

### J4. Receive provider webhooks (live updates)
- **Flow:** GitHub POSTs to `/webhooks/github`; Jira — like any tracker with the `webhooks`
  capability — to **`/webhooks/{provider}`** (`/webhooks/jira`) (verified by the tracker's own
  scheme, e.g. an HMAC header; `404` for an unknown, disabled or webhook-less provider). The
  receiver verifies the signature over the raw body **before** parsing, matches the event to
  the connections whose **bindings** it belongs to (the tracker's scope hint — for Jira the
  issue's project key — against each binding's scope), and enqueues an arq job (never processes
  inline). Tracker item events upsert the task; GitHub `pull_request` events upsert the PR cache
  (and link it to a task by key, §J6).
- **Trackers:** Linear signs with `Linear-Signature` (hex HMAC-SHA256 of the body) and is
  routed by the issue's team key; the generic tracker signs with `X-Canopy-Signature:
  sha256=<hex>` and is routed by the `scope` it sends (§J0).
- **Setup:** `JIRA_WEBHOOK_SECRET` / `GITHUB_WEBHOOK_SECRET` / `<PROVIDER>_WEBHOOK_SECRET` (e.g.
  `LINEAR_WEBHOOK_SECRET`, `GENERIC_WEBHOOK_SECRET`) — **required**: intake fails closed, so an endpoint answers `403` to
  every request until its secret is set, and `401` to a missing or forged signature. Intake
  ACKs-but-ignores when `integrations.webhooks` is off or the provider's reads are MCP/file.

### J5. Jira sprints & status history
- **API:** `GET /api/v1/connectors/jira/{id}/boards`, `.../sprints?board_id=`, and
  `POST /api/v1/connectors/jira/{id}/history?issue_key=` (pulls the issue changelog into
  `TaskStatusHistory` through the sync engine's per-task backfill, over the binding that feeds the
  issue's task; `source = backfill`, categories stamped; it **replaces** the approximate `sync`
  rows recorded for that task and keeps rows canopy recorded itself; `{added: 0}` when no synced
  task carries that key or no binding of the connection feeds it).
- **Automatic:** a sync backfills the first 50 tasks it creates; the nightly
  `tracker_history_backfill` job tops up the rest in batches (a cursor per binding, wrapping
  round once every task was seen) for every tracker with the `status_history` capability.

### J6. Read GitHub / Google Drive content
- **API:** `GET /api/v1/connectors/github/{id}/file?path=`, `.../github/{id}/pulls`,
  `.../github/cached-prs`; `GET /api/v1/connectors/gdrive/{id}/docs`, `.../gdrive/{id}/docs/{file_id}`
  · **MCP:** `read_repo_file`, `list_open_prs`, `read_design_doc`.
- **Review and check state:** the cache also keeps what stage checks and gates need
  ([`AGENT_EXECUTION.md`](./AGENT_EXECUTION.md) §11.3): `draft`, `merged` / `merged_at` /
  `merged_by`, the head branch and **`head_sha`**, size (`additions` / `deletions` /
  `changed_files`), the **latest review per reviewer** and from it `approved_by` (approvals of the
  *current head* — a stale approval doesn't count) and `review_decision` (`changes_requested`
  while any reviewer's latest review requests changes, else `approved` / `review_required`), and
  every check seen at the head rolled up as `checks_state` (`failing` / `pending` / `passing`; a
  neutral or skipped check is neither). Fed by the `pull_request`, `pull_request_review`,
  `check_suite`, `check_run` and `status` webhooks (pure roll-ups in `app/services/pr_signals.py`)
  and by MCP / file ingest; a new head resets the checks. Nothing here moves a task's status —
  except for **delegated** work (§AE): a GitHub approval from someone other than the person whose
  agent did the work, or the merge, may satisfy a gate that accepts that evidence, and a PR
  merged while its delegated, canopy-owned task is still upstream moves the task to done (a
  `merged_ahead_of_stage` event records the stages it skipped).
- **PR↔task link:** a cached `PullRequest` carries an optional `task_id` (the task it
  implements), set on ingest/webhook from the first issue key in its **title or head branch**
  (e.g. `feat/shop-12-checkout` → `SHOP-12`): a native canopy key (`Task.key`) or the key of any
  tracker item canopy mirrors; a PR already tied to a task keeps it. It surfaces the PR in that
  task's detail panel (§C1a) via `GET /api/v1/tasks/{id}/links`. MCP/file PR ingest takes an
  optional `branch`.
- **Drive uploads (write):** the Drive connector also has `upload_file` (multipart) used by export
  snapshots (§S) to store a generated PDF/CSV in Drive — the one place canopy writes to Drive.
- **Not built (v2 §J6):** PR **review metrics** (time-to-review, churn, test status) and commit
  attribution to components — these would feed a PR-latency quality-risk indicator (the quality
  family is currently fed by §J8 build failures / incidents instead).

### J8. CI / observability events **[new — minimal viable]**
- A generic event substrate: `kind` ∈ `deploy | build_failure | incident_open | incident_close`,
  optionally tagged to a component. Events appear in the **Activity** feed (§B3) and feed the
  **quality-risk** family (§Q1); an `incident_open` **auto-opens a postmortem** (§P2).
- **Webhook:** `POST /webhooks/events` (HMAC via `EVENTS_WEBHOOK_SECRET`, required — `403` until
  set; recorded inline — it's a light write). **API/UI:** `GET /api/v1/projects/{id}/activity` (feed) and
  `POST /api/v1/projects/{id}/activity` (planner-gated manual ingest, used by the Activity tab and
  the plugin) · **MCP:** `get_activity`, `record_activity`. Datadog / Sentry / GitHub Actions can be
  layered on this substrate.

### J9. Link tracker items (Jira tickets) to a project / initiative **[updated]**
- **What:** instead of mirroring a whole Jira project (§J3), the architect links one or more
  **specific** Jira tickets (initiative / epic / story) to a canopy **Project** or **Initiative**.
  canopy reads the linked ticket **plus its full descendant subtree** (BFS over Jira `parent`
  links) and maps it idempotently (via `ExternalRef`):
  - **target = project:** every issue becomes a Task in that project (epics → summary tasks,
    stories → leaf tasks, parented within the project). Auto-replans the project when tasks are
    created.
  - **target = initiative:** each descendant **epic becomes a Project** under the initiative and
    its stories become tasks in that project (Jira initiative→epic→story mirrored onto canopy
    initiative→project→task). Existing projects/tasks are re-used (idempotent); the initiative-level
    anchor ticket is associated by the link, not turned into a task.
  Status stays **Jira-owned** (never written back). Re-linking the same ticket is an update, not a
  duplicate. Each Jira issue maps to a single canopy entity regardless of how many links reference it.
- **UI:** the project's **Integrations → Tracker links** tab (§B3) and a **Linked tracker items**
  panel on the initiative cockpit (§R3): enter an item key + (if more than one) pick the tracker
  connection (trackers that can be read directly with a hierarchy) → **Link**; each link row has
  **Resync** / **Unlink** (writes are planner-gated; unlink keeps the already-mapped canopy
  entities). Shows projects/tasks created/updated/skipped per run. Uses `/tracker-links`.
- **API (any tracker with `hierarchy` + `direct_read`):** `POST /api/v1/tracker-links`
  (`connection_id`, `root_key`, `target_type` ∈ `project|initiative`, `target_id`) → maps the
  subtree and returns a `TrackerLinkSyncResult` (the link: `provider`, `root_key`, `root_type`,
  browse `url`, …); `GET /api/v1/tracker-links?target_type=&target_id=` (list),
  `POST /api/v1/tracker-links/{id}/resync`, `DELETE /api/v1/tracker-links/{id}` (deactivates the
  link — what it mapped stays). A link is a subtree `TrackerBinding` (§J0); writes are
  planner-gated and ownership-scoped (§R6). A non-tracker connection is `400`.
- **MCP:** `link_tracker_item`, `list_tracker_links`, `resync_tracker_link`,
  `unlink_tracker_item` (skill: `syncing-trackers`).
- **Limits:** linking a bare story directly to an *initiative* (no epic in its subtree) maps nothing
  and is reported in the result — link stories to a *project*, or link an epic/initiative-level
  ticket to an initiative. Traversal follows Jira `parent` links (the same hierarchy field §J3 uses),
  not classic "Epic Link"; ancestors are mapped only if you link them too.

### J7. PagerDuty / on-call **[not built]**
- Deferred: an optional connector to pull on-call schedules into capacity (v2 §J7). Needs the
  external PagerDuty integration; the interrupt-budget/on-call capacity model (§F2/§F4) is also not
  built, so there's nothing to feed yet.

---

## K. Real-time live refresh
- **Flow:** while logged in, the frontend opens a Server-Sent Events stream
  (`GET /api/v1/events/stream?token=`). Actions publish small change events (replan, baseline,
  board moves, proposals, sprints, tracking, agent work — `work` events for claims, gates and
  hand-offs); the client invalidates its caches so views refresh without a manual reload.
- **Across processes (`EVENTS_BACKEND`):** `memory` (the default for a bare `uvicorn`) delivers
  within one process; `redis` (what the compose files set) also publishes each event on the Redis
  channel `canopy:events`, and every API process listens and fans the other processes' events
  out to its own streams — so changes made by the **arq worker** (tracker syncs, webhook
  processing, the claim reaper) and by other API processes reach open pages at once. A Redis
  outage degrades to in-process delivery (logged) and never fails the action. The Decisions
  inbox, the Agents view and the Reviews badge also refetch every 30 seconds as a backstop.

---

## S. Export snapshots (PDF / CSV, viewable outside canopy) **[new]**

A point-in-time **snapshot** of a project, initiative, or portfolio as a portable file — so the
architect can store or share it where canopy isn't running. Two formats: **PDF** (the full visual
snapshot: headline stats, a vector **Gantt**, and data tables) and **CSV** (the headline tabular
dataset for that scope). Delivered two ways: **download** in the UI, or **save to a connected
Google Drive**. Snapshots reuse the same aggregation as the live views (`summarize_project`, the
initiative / portfolio rollups), so the numbers match what's on screen.

### S1. Download a snapshot
- **UI:** an **Export ▾** menu in the project header (§B3), the initiative cockpit (§R3), and the
  portfolio page (§B1) → **PDF** / **CSV** download. Open to any authenticated user (it's a read).
- **API:** `GET /api/v1/projects/{id}/export?fmt=pdf|csv`,
  `GET /api/v1/initiatives/{id}/export?fmt=`, `GET /api/v1/portfolio/export?fmt=` — returns the file
  with a `Content-Disposition` attachment. Rendering is `app/services/export_pdf.py` (reportlab —
  pure Python, no headless browser, CI-safe) + `app/services/export_csv.py`; the snapshot data is
  assembled in `app/api/v1/exports.py`. Project and initiative snapshots add a **Design docs**
  table — title, kind, review status, version ("r12 approved, now r14"), where it lives and the
  link; personal and archived docs are left out; in CSV it is a trailing section after a blank
  row (§V9).

### S2. Save a snapshot to Google Drive
- **UI:** the same Export menu → **Save to Google Drive** (pick a connection when more than one is
  authorized; shows the resulting Drive link).
- **API:** `POST /api/v1/projects/{id}/export/to-drive` (plus the `initiatives/{id}` and
  `/portfolio` variants) with `{connection_id, fmt}` → uploads the rendered file via the Drive
  connector's new `upload_file` (multipart) and returns `{file_id, name, link}`. An optional
  `folder_id` in the Drive connection config targets a folder.

### S3. What a snapshot contains / limits
- **PDF (project):** summary stats (tasks / completed / critical / end / risk / drift), a vector
  **Gantt** (critical bars red, % progress shaded, milestones marked; the chart is capped to ~26
  scheduled tasks — the full set is in the table), and tables for tasks, milestones, and decisions.
- **PDF (initiative / portfolio):** rollup stats + the sub-project / project table.
- **CSV:** the headline table per scope — a project's **tasks**, or the initiative / portfolio
  **rollup** (one row per project).
- **Not built:** capacity / burndown charts in the PDF, JSON / HTML formats, multi-table CSV
  bundles, and scheduled/automatic exports (snapshots are on-demand). No MCP tool — UI + API only.

---

## T. Scenario simulation (initiative what-if) **[new]**

A durable, named **what-if branch of an initiative**: change team composition, per-engineer
availability, milestones, deadlines, and scope (add/remove/resize tasks + dependencies), then
regenerate **every** analysis view and compare to the live plan before committing. Conceptually
the draft-plan pattern (§C10) raised to the whole initiative, and the only multi-dimensional
what-if (the Gantt's §C5 covers task durations only).

### T1. Create a scenario (snapshot)
- **UI:** initiative cockpit (`/initiatives/:id`) → **Scenarios** → "New scenario". Opens the
  scenario workspace at `/initiatives/:id/scenarios/:scenarioId`.
- **API:** `GET/POST /api/v1/initiatives/{id}/scenarios`, `GET/PATCH/DELETE /api/v1/scenarios/{id}`.
  Creating one **snapshots** the initiative's tasks, dependencies, milestones, allocations,
  availability, and per-project scheduling knobs into editable scenario tables (live data is
  untouched). `base_captured_at` records the snapshot moment. Status: draft | ready | applied |
  archived. · **MCP:** `list_scenarios`, `create_scenario`, `get_scenario`.

### T2. Edit the scenario (team / availability / milestones / deadlines / scope)
- **UI:** the workspace **Edit** tab — sub-panels for team & availability, milestones & deadlines,
  scope (tasks + dependencies), and per-project knobs (start/target/skip-weekends).
- **API (all planner-gated, scenario must be draft/ready):**
  `POST /api/v1/scenarios/{id}/tasks` + `PATCH/DELETE /api/v1/scenario-tasks/{tid}`, and the same
  shape for `dependencies`, `milestones`, `allocations`, `availability`; plus
  `PATCH /api/v1/scenarios/{id}/projects/{project_id}` for project knobs. Deleting a cloned row
  tombstones it (apply then deletes the live row); deleting an added row hard-deletes it.
  · **MCP:** `add_scenario_task`, `update_scenario_task`, `remove_scenario_task`,
  `add_scenario_dependency`, `set_scenario_availability`, `set_scenario_allocation`.

### T3. Regenerate all views over the scenario
- **UI:** the workspace mirrors the project cockpit's **two-level nav** (§B3, pure model in
  `lib/scenarioNav.ts`): a **Compare** entry (§T4, the default landing) plus **Schedule** (Gantt ·
  Dependencies · Critical path), **Execution** (Board · Capacity · Burndown), **Outlook** (Forecast ·
  Alerts), and **Edit** (§T2), reusing the same view components against scenario data. The active
  view is deep-linkable via `?tab=<view>`. Cross-project critical path + capacity are
  initiative-wide; the per-project projections (Gantt / Dependencies / Board / Burndown / Alerts)
  take a project picker.
- **API:** `GET /api/v1/scenarios/{id}/{gantt|capacity|board|burndown|forecast|alerts}`
  (`?project_id=` where relevant) and `GET /api/v1/scenarios/{id}/critical-path`. Each returns the
  **same schema as the live endpoint**, recomputed over the snapshot — never persisted. Cloned
  tasks pin at their live start (so an unedited scenario reproduces live); added tasks have no
  history (they count as remaining for forecast/burndown). · **MCP:** `scenario_critical_path`,
  `scenario_capacity`.

### T4. Compare to live
- **UI:** a persistent "Compare to live" panel — counts added/removed/changed, project-end delta,
  and critical-path working-day delta.
- **API:** `GET /api/v1/scenarios/{id}/compare` → the diff (by `live_*_id`/`removed` provenance) +
  any **staleness conflicts**. · **MCP:** `compare_scenario` (the key read before applying).

### T5. Apply (commit to canopy's planning layer)
- **UI:** "Apply scenario" (planner only) → a **pre-flight confirm** that states the change up front,
  leading with the destructive part: "create N, update M, **DELETE K live task(s)/dependency(ies)**;
  affected projects are re-planned; can't be undone" (from the compare diff counts). On a staleness
  conflict, offer force-apply (same confirm). Item-level Added/Removed/Changed lists are a follow-up
  (the `/compare` payload returns counts, not item names, today).
- **API:** `POST /api/v1/scenarios/{id}/apply` (`{force}`). In one transaction: create/update/
  delete the live tasks/dependencies/milestones/allocations/availability (remapping new scenario
  task ids), then replan each affected project, then flip status to `applied`. Returns
  created/updated/deleted + replanned projects. **409** with the conflict list when live drifted
  since the snapshot and `force` is false. · **MCP:** `apply_scenario`.
- **Source-of-truth boundary:** apply writes **canopy planning rows only — never Jira** (Jira
  stays the owner of tickets/status; use the draft-plan flow §C10 for plan→Jira). Replans publish
  live-refresh events (§K).

### T6. Not built (deliberate limits)
- **No resource-leveling / capacity-constrained scheduling:** availability informs the
  capacity/over-allocation views, **not** CPM dates.
- **No scenario → Jira**, **no scenario-vs-scenario diff/branch/merge**, and **no concurrent-edit
  locks** beyond the snapshot watermark conflict check. **Resync** (re-snapshotting after live
  drift) is API-pending.

---

## V. Document graph & coverage (link, don't store) **[new]**

Canopy is a document **graph**, not a document store. PRDs, Figma designs, tech-design docs,
architecture docs, release notes, and QA plans live where they already are (most often
attached to a **Jira epic**, plus Confluence/Drive/Figma URLs); canopy holds typed **links**
to them, deduplicated and attached to the right entity, so the same docs are discoverable for
everyone in context. It never copies the bytes (Source-of-truth boundaries hold). The
`DocReference` model (`app/models/doc.py`) is polymorphic by scope (project / initiative /
task, mirroring the risk register) with a `kind` (prd | design | tech_design | architecture |
release | qa | runbook | other), a `source` (jira_epic | manual | repo | drive), and a
`link_health` (unchecked | ok | stale | broken — checking is a follow-up).

### V1. List / add / manage references + coverage
- **API:** `GET /api/v1/docs?scope_level=&scope_id=&kind=` (open read; docs filed there or
  linked there, §V5), `POST /api/v1/docs` (planner on the scope, or a contributor on a project —
  §V7; validates the scope exists, no FK; dedupes into a link, §V5), `PATCH/DELETE
  /api/v1/docs/{id}` (the doc's writers, §V7),
  `GET /api/v1/docs/coverage?scope_level=&scope_id=` (which **expected** kinds — prd / design /
  tech_design / architecture — are present vs **missing**, rolled up so a project includes its
  tasks and an initiative includes its projects + their tasks; absence of a doc is a signal,
  not neutral) · **MCP:** `list_doc_references`, `add_doc_reference`, `get_doc_coverage`.

### V2. AI-driven epic→doc field mapping (one-time setup)
- Teaches canopy which Jira epic field holds which kind of doc, with the AI doing the work.
  Stored on the **Jira connection's config** (`doc_field_mappings`, same JSON home as
  `story_point_field`) — `{mappings: [{jira_field, field_name, doc_kind}],
  parse_description_links, parse_remote_links}`.
- **Flow (skill `mapping-epic-docs`):** `sample_epic_doc_fields` returns a sample of epics' URL-
  bearing fields (joined to Jira's field-name registry), description links, and remote links →
  Claude infers a field→kind mapping from field names + URL domains and **asks the admin to
  confirm** → `set_epic_doc_field_mapping` saves it.
- **API:** `GET /api/v1/connectors/jira/{id}/doc-fields/sample?limit=` (read),
  `GET/POST /api/v1/connectors/jira/{id}/doc-field-mapping` (read / planner-set) · **MCP:**
  `sample_epic_doc_fields`, `get_epic_doc_field_mapping`, `set_epic_doc_field_mapping`.

### V3. Harvest docs from epics
- **API:** `POST /api/v1/connectors/jira/{id}/harvest-docs` (planner) — fetches every synced
  epic, extracts URLs per the mapping (custom fields + optional description links + optional
  Jira remote links), and attaches a `DocReference` to whatever canopy entity the epic maps to
  (a **summary task** for a whole-project sync §J3, a **project** for an initiative-linked epic
  §J9, via `ExternalRef`). Idempotent (dedup per scope+url in the service); re-running updates,
  never duplicates. Returns created/updated/skipped/epics_scanned · **MCP:** `harvest_epic_docs`.
- Logic is pure-where-possible in `app/services/doc_graph.py` (URL/ADF extraction, mapping
  application, coverage roll-up — unit-tested); the Jira connector adds `list_fields`,
  `fetch_epics`, and `fetch_remote_links`.

### V4. Not built (deliberate limits)
- **UI:** a **Docs** tab on the project cockpit and a **Documents** panel on the initiative cockpit
  list docs grouped by kind with coverage badges, filters and an add form (§V5); the AI-driven
  epic *setup* / harvest stays conversational. Built.
- **No Jira attachments** harvest (only fields + remote/description links), and **no write-back**
  of canopy-added links onto the Jira epic (canopy-local for now).
- **AI doc *generation*** (drafting a tech-design from the PRD + ADRs, syncing the architecture
  doc to reality via drift) is a separate future slice, not part of this flow.

### V5. Design docs: register, identity, the open kind catalog **[new]**
A **design doc** is any document the work runs on — most often made in **Claude**: a Claude Doc,
or a published artifact (a markdown page, an image page, static HTML with interactive
illustrations, a prototype) — or a Drive / Figma / Confluence / repo doc. `DocReference` is one
row per *document*, however many places use it:
- **Identity.** `app/services/doc_urls.py` (pure) classifies a link by its **exact host**:
  `provider` (claude | gdrive | github | figma | confluence | jira | web), the provider's
  `external_id` (a claude.ai artifact id from `/artifact/[<title>-]<id>`, `/code/artifact/<uuid>`,
  `/public/artifacts/<uuid>`, `preview.claude.ai`; a Drive file id; a repo path…), a `format`
  hint, and a canonical link (a Claude title slug dropped, an `#anchor` kept). Registration
  dedupes on provider + id, else the link — a second registration returns the existing record
  and the new scope gets a **link**, never a copy. Registration accepts https only.
- **What canopy stores:** link, title, kind, `format` (document | page | prototype | diagram |
  image | deck | canvas | sheet — an open slug), `current_version` (the source's version label),
  a ≤2,000-character plain-text `summary`, `visibility`, `review_status` (NULL = an untracked
  plain link; `draft` once tracked), `supersedes_id`, who registered it. **Never the content** —
  a session may send a SHA-256 of the exported text (the MCP server hashes it locally) into the
  version log (`DocRevision`).
- **Kinds are data, not schema.** `kind` is an open slug (`Threat Model` → `threat_model`); the
  workspace **kind catalog** (`DocKindDef`, seeded with prd, design, tech_design, architecture,
  rfc, research, qa, release, runbook, other) gives each kind a label, a **lifecycle stage**
  (frame | define | design | decide | plan | build | release | learn | other) and an
  **expected** flag. An unknown kind joins under stage `other`; planners relabel/re-stage it;
  admins **merge** one kind into another. Coverage and filters read the stage, never the name.
- **Coverage** (`GET /docs/coverage`) now counts docs *linked* to the scope as well as filed
  there, ignores superseded / archived / personal docs, takes expected kinds from the catalog,
  and adds each expected kind's best state (approved | in_review | draft | linked | missing) and
  counts by stage.
- **Migration** (`0b1c2d3e4f5a`): `kind`/`source` became VARCHAR (open kinds; sources `agent`,
  `claude_sync`); existing links were classified; rows pointing at the same document were
  **merged** into one doc with links (survivor = the broadest home; proposal items re-pointed);
  each ADR `rfc_url` and spec `source_url` became a doc + a **basis** link (the fields stay,
  read-only aliases for one release).
- **API:** `POST /api/v1/docs/register` (201 created / 200 existing; `{doc, created}`) ·
  `GET /api/v1/docs` (filters: `scope_level`+`scope_id` = filed there **or** linked there,
  `entity_type`+`entity_id`, `kind`, `stage`, `provider`, `review_status` incl. `untracked`,
  `personal`) · `GET/PATCH/DELETE /api/v1/docs/{id}` · `POST /api/v1/docs` (the legacy add-link
  form: a plain link, deduped into a link) · `GET /api/v1/docs/kinds` · `PUT
  /api/v1/docs/kinds/{key}` (planner) · `POST /api/v1/docs/kinds/{key}/merge` (admin). All gated
  by `governance.docs`; SSE `docs` events refresh the views.
- **MCP:** `register_design_doc` (hashes optional `content` locally), `get_design_doc`,
  `list_design_docs`, `list_doc_kinds`; `add_doc_reference` / `list_doc_references` stay one
  release as aliases. **Skill:** `tracking-design-docs`.
- **UI:** the **Docs** tab — filters (status, where it lives, stage), per-doc badges (provider ·
  format · status · version, "via Claude", "not shared", "limited audience"), expandable summary
  + "linked to" chips, an **Add doc** form that classifies the link as you type, offers the
  catalog's kinds with free entry and asks who can open a Claude doc, and a **Kinds** panel
  (planners: label / stage / expected; admins: merge).

### V6. Personal and shared docs (the sharing rule) **[new]**
- **Personal** (`private_to_user_id`): anyone — viewers included — can track a doc for their own
  use; no sharing needed; it may have no home and links only to the owner's **own tasks**
  (reference). It is invisible to everyone else — planners, admins, and an admin impersonating
  its owner (one visibility filter, `design_docs.visible_clause`).
- **Shared:** filed under a home (project / initiative / task) and visible to everyone. **A Claude
  doc must be shared in Claude** (`visibility` users | org | public): registering it as shared,
  promoting it, linking it, staging it in a proposal (`doc_reference.create` now takes
  `visibility`) return **409 `doc_not_shared`** while it is `owner` or `unknown` (a shared
  record of the same artifact someone already made counts). A doc shared with named people
  shows a **limited audience** chip. Other providers keep today's behaviour.
- **Promote:** `POST /api/v1/docs/{id}/promote` `{scope_level, scope_id, visibility?}` — the
  owner files a personal doc under a home once it is shared; if the same document is already
  shared, the personal record folds into it (links moved).
- **UI:** **My docs** on `/me` (track a doc privately; "share with the team" → pick a project +
  who can open it). **MCP:** `register_design_doc(personal=True)`, `promote_design_doc`.

### V7. Links to the work a doc serves **[new]**
- `DocLink` (doc ↔ project | initiative | task | decision | spec | milestone | outcome | risk |
  retro | component) with a **relation**: `basis` (the entity was derived from / decided on the
  doc — pins `pinned_version` = the doc's current version), `gate` (should not complete until
  the doc is approved — advisory), `reference` (context). Idempotent per doc + entity.
- **Who may write:** a planner who may edit the doc's home (ownership rules, §R6; 403
  `not_initiative_lead`); a **contributor** for a doc they registered under a project or their
  own task, linking it to **their own tasks** only; a link's **target** must be work the caller
  may edit — so one PRD can serve two projects without either team editing the other's plan.
  Viewers track personal docs only.
- Deleting a task / project / initiative / spec / milestone / outcome / risk drops the links to
  it; a doc **homed** there moves to another place it is linked to (or goes, with its links and
  versions) — `design_docs.release_docs_homed_at`, used by `app/services/cascade.py`.
- **API:** `POST /api/v1/docs/{id}/links` · `PATCH/DELETE /api/v1/docs/links/{id}` ·
  `GET /api/v1/docs/links?entity_type=&entity_id=` (docs on one entity, with the link).
  **MCP:** `link_design_doc`, `register_design_doc(links=[…])`.
- **UI:** a **Design docs** panel (`LinkedDocs`) on the ADR detail (replacing the bare RFC link),
  the spec card (replacing the bare source link) and the task panel: relation, pinned version
  vs now ("doc now r14 — re-check"), unlink, and **Link a doc** (pick a project doc, or paste a
  link to register + link in one step).

### V8. Versions, review, approval and health **[new]**
- **Checks + the version log.** `POST /api/v1/docs/{id}/revisions` `{version?, content_hash?,
  change_summary?, reachable?, visibility?, snapshot_url?}` records what a session (or a person)
  saw: a new version label is appended to `DocRevision` (unique per doc + version) and becomes
  `current_version`; every call stamps `last_checked_at` and writes `link_health` (`ok`, or
  `broken` when `reachable=false`) — so "never checked" and "checked, unchanged" differ. A
  SHA-256 of the exported content is the only content-derived thing canopy receives.
  `GET …/revisions` lists the log. **MCP:** `record_design_doc_version` (hashes `content`
  locally).
- **Review.** `draft → in_review` (`POST …/request-review {version?}`; the doc's writers, agents
  included) names the version under review. **Approval** (`POST …/approve`) is **human-only**
  (`HumanOnly`, an agent token 403s) by a **planner on the doc's home** (admins exempt; a
  contributor — the author included — gets 403 `not_approver`), stamps `approved_version`,
  `approved_by_user_id`, `approved_at`. `design_docs.approve` is the **only** writer of the
  approved state (`tests/test_doc_review_single_writer.py`). A newer version does not demote an
  approved doc — it is flagged instead. `approved → in_review` again via request-review;
  `POST …/archive` retires a doc; registering a replacement with `supersedes_id` marks the old
  one `superseded`. Review and approval obey the sharing rule (409 `doc_not_shared`); a personal
  doc has none (409 `doc_personal`). **MCP:** `request_design_doc_review` (no approve tool).
- **Health** (pure `app/services/doc_health.py`, computed per read — never stored):
  `unverified` (a Claude doc never opened since registration), `check_due` (a tracked doc not
  re-checked within `DOC_CHECK_DAYS`, default 14), `changed_since_approval`, `behind_pin` (a
  basis link pinned an older version — names the ADR/spec/plan), `gate_open` (a gate link whose
  milestone is within `DOC_GATE_WINDOW_DAYS` or whose spec is still draft, and the doc is not
  approved), `restricted` (a shared Claude doc made private), `broken`. Superseded/archived docs
  raise nothing; personal docs raise check flags only. Every doc read carries `health`.
- **Where it surfaces:** the project **alerts** (§I — attention flags only), the initiative
  **digest**'s attention list (§R5), coverage's `needs_attention` count, **/me → Design docs to
  approve**, and the session worklist `GET /api/v1/docs/worklist?project_id=` (check flags,
  oldest first; `get_workspace_context.design_docs.checks_due`). **MCP:** `get_doc_worklist`.
- **UI:** health chips on each Docs-tab row and attention chips in the `LinkedDocs` panels; a
  **doc detail drawer** (`DocDetailPanel`: Open in Claude, summary, health, links with pinned vs
  current version, the **version timeline** with hashes and frozen copies, *Record check* / *can't
  open it*, *Request review*, *Approve* for planners, *archive*, *Supersede* with a new link).

### V9. Design docs across the lifecycle **[new]**
- **Pins at decision points.** Accepting an ADR (§G3), approving a spec (§W) and capturing a
  baseline (§C4) pin every **basis** link on that entity (the project + its tasks for a
  baseline) to the doc's current version — so a later edit raises `behind_pin` (§V8).
- **Advisory readiness.** The ADR review summary and the spec bundle report `docs_ready` /
  `docs_pending`: every doc the entity rests on (basis) or waits for (gate) is approved. Like
  `can_accept`, it is surfaced, not enforced.
- **An ADR from a doc's text** — `POST /architecture/adrs/import-text` (§G6), the doc linked as
  its basis · **MCP:** `import_adr_from_markdown`.
- **Proposals.** `doc_link.create` items; `proposalitem.entity_type` is now VARCHAR (migration
  `1c2d3e4f5a6b`). A proposal may name its **source doc** (`source_doc_id` +
  `source_doc_version`; shared docs only) — the review workspace shows "From <doc>, <version>"
  and warns when the doc has **moved on** since; the preview counts `docs_linked` (§AA).
- **Draft plans** carry a source doc; finalise links it to the created tasks (native) or cites
  it in the tickets (mirrored) (§C10).
- **Docs on more work.** A **docs** toggle (lazy `LinkedDocs`) on roadmap milestones (default
  relation `gate`), outcomes and risks (project or initiative scope) and retros.
- **Exports** add a Design docs table (§S); the **retro seeder** lists docs changed after
  approval (§P).
- **Freeze.** A session saves a copy of an approved version where the organization owns it —
  a repo file via a pull request, or a Drive file — with its own access, then records the link
  (`POST /docs/{id}/revisions {snapshot_url}` · **MCP** `record_design_doc_version(snapshot_url=)`);
  the version timeline shows "frozen copy". Each person's default store is
  `PATCH /api/v1/auth/me/preferences {doc_snapshot_store: repo | drive}` (UI: **My docs →
  Frozen copies of approved docs go to**); `UserRead.doc_snapshot_store` reports it.
- **Skills:** `tracking-design-docs` §8–§9 (lifecycle table, freezing), and the doc steps in
  `spec-driven-development`, `writing-adrs`, `drafting-tickets`, `harvesting-signals`,
  `persona-playbooks` (design) and `daily-standup`.

### V10. Doc sentinel and the workspace library **[new]**
- **Doc sentinel** (subagent `plugin/agents/doc-sentinel.md`, skill `tracking-design-docs` §6):
  works the worklist (`get_doc_worklist`, plus docs flagged `behind_pin` /
  `changed_since_approval`), opens each doc **with the session's own access**, records what it
  saw (`record_design_doc_version`: version label, a locally computed SHA-256, a one-line change
  summary, or `reachable=False` / `visibility="owner"`), and — when a change implies plan
  changes — **stages** them (`propose_changes` with `source_doc_id`/`source_doc_version`, §AA).
  It never approves, never sends content, and treats document text as data. Delegate for "check
  the design docs", before a review or gate milestone, or as a scheduled sweep.
- **Workspace library** — `/docs` (nav **Design docs**, gate `governance.docs`): every *shared*
  doc across projects and initiatives, filtered by **team** (`GET /api/v1/docs?team_id=` — docs
  filed under or linked to the team's projects, their tasks/ADRs/specs/milestones, and its
  initiatives; `design_docs.team_clause`), review status, provider, lifecycle stage, *needs
  attention* (any attention flag) and a title search; each row shows where the doc is filed and
  opens the doc drawer (§V8). Personal docs stay in **My work → My docs**.

### V11. Organization artifact sync (optional, metadata only) **[new]**
Off by default. An **admin** adds a **Claude artifacts** connection (`POST
/api/v1/connectors/connections {provider: "claude", token: <Compliance API key>}` — anyone else
gets 403 `admin_only`; the key is Fernet-encrypted like every token). Connector
`app/connectors/claude_artifacts.py`; engine `app/services/claude_sync.py`.
- **What it calls:** only the Compliance API **list** endpoint `GET
  /v1/compliance/apps/code/artifacts` (`anthropic-version` header, paginated until `next_page`
  is absent, optional `organization_ids[]`), through `request_with_retry`. **Never** the content
  download or delete endpoints. Config: `api_version`, `organization_ids`, `base_url`.
- **Runs:** worker crons `claude_artifact_sync` (what changed since the watermark less a 2-hour
  overlap — the time filter is eventually consistent; every `CLAUDE_SYNC_MINUTES`, default 60)
  and `claude_artifact_full_sync` (nightly 04:00, unfiltered: the only listing that shows folder
  sharing changes and deleted artifacts). **Sync now:** `POST
  /api/v1/connectors/connections/{id}/sync` (planner; UI: the library header or Connectors).
  The integration policy (§A10) can stand it down (read strategy not `direct`).
- **What a run records, for tracked Claude docs only:** it **pairs** each listed artifact with
  the docs whose link id is a form of the artifact's tagged id (`candidate_ids`: as listed,
  without its tag, without the `01` marker, that body as a base58 UUID — the relation is not
  documented, so a pairing found once is kept in `ExternalRef` (`entity_type` "doc")), then
  applies `design_docs.apply_source_metadata`: the live version (`published_version_id`, else
  the newest listed version) is appended to the version log with `source="sync"` and stamps the
  check; `read_mode` → `visibility` (a shared doc gone private flags `restricted`); for a Claude
  Doc or Sheet (no version ids) only `source_updated_at` moves — health then flags `check_due`
  ("changed in Claude after its last check") and, after approval, `changed_since_approval`.
  A paired artifact missing from a **complete, unfiltered** listing marks its docs `broken`.
  Owners are matched to canopy users by email (`ExternalRef` "user"; canopy accounts are
  admin-created, and an admin already holds the key, so the match grants no one more). The run's counts
  (listed, paired, new versions, sharing changes, missing, **unmatched** — tracked shared Claude
  docs never paired) are stored on the connection: `GET /api/v1/docs/artifact-sync`
  (UI: the library's sync line). Deleting a doc drops its pairing. **MCP:**
  `get_artifact_sync_status`; `get_workspace_context.design_docs.artifact_sync`.
- **Your untracked artifacts:** `GET /api/v1/docs/suggestions` lists **the caller's own**
  artifacts that no doc they can see tracks (another person's *personal* tracking does not hide
  one) — live, never stored; off while impersonating. Registering one: `POST /docs/register
  {…, source_artifact_id}` checks it is the caller's (404 `artifact_not_yours`; 403
  `impersonating` under impersonation), requires its
  claude.ai link (the listing carries none; 422 otherwise), takes the listed sharing, title,
  format and version, records the pairing and `source="claude_sync"`. Nothing is ever
  registered automatically. UI: **My docs → From Claude → Find my untracked artifacts → Track…**
  (paste its link). **MCP:** `list_my_untracked_artifacts`, `register_design_doc(artifact_id=)`.
- **Demo:** a demo Claude connection is served by the offline mock (`connectors/demo.py`): the
  seeded artifacts pair, the republished guest-checkout page leaves its decision `behind_pin`,
  and Leo and Sarah each have an untracked artifact to find.

### V12. Not built yet (design docs)
- **Known gaps of the organization sync:** pairing relies on id forms that are not documented —
  the `unmatched` count says how many tracked docs it could not pair (register them from a
  suggestion to pair explicitly); a Claude Doc's title is not in the listing; there is no
  admin UI beyond the connection form and the library's sync line.
- By design: **no content search, no embedded preview** (canopy never frames or fetches a doc;
  the sync never downloads content), **no mirrored comment threads** (review conversations
  stay in Claude), **no automatic registration** (a session or a person registers; suggestions
  only list), **no Slack/email delivery** of doc alerts (a hook over the alerts, like §I), **no
  enforced gates** (readiness and gate links are advisory, like `can_accept`).

---

## W. Specs — spec-driven development **[new]**

**Intent is the source of truth.** A `Spec` (`app/models/spec.py`) captures the *problem* and
explicit, checkable **acceptance criteria** before work begins; tasks implement it
(`Task.spec_id`); and afterward each criterion is **self-audited** (met | unmet | waived) against
the implementation. This is the intent end of the spine in
[`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) (roadmap gap #1) — the artifact that aligns
humans and agents and the thing an agent struggles without. Source docs (PRD/design) link via the
document graph (§V) or `source_url`; the governing decision links via `adr_id`. Status:
`draft → approved → in_progress → verified → archived` (set explicitly; not transition-gated).

### W1. Create / manage a spec
- **API:** `GET /api/v1/specs?project_id=&status=` (open read), `POST /api/v1/specs` (planner;
  validates the project exists), `PATCH/DELETE /api/v1/specs/{id}` (planner; delete unlinks its
  tasks and drops its criteria first — PG/MySQL enforce the FK) · **MCP:** `list_specs`,
  `create_spec`, `set_spec_status`.

### W2. Acceptance criteria
- **API:** `POST /api/v1/specs/{id}/criteria` (planner), `PATCH /api/v1/criteria/{id}`
  (**contributor** — the implementing engineer or the agent records the verdict),
  `DELETE /api/v1/criteria/{id}` (planner). A criterion carries `text`, `status`
  (open|met|unmet|waived), an optional `verification` note (how it was checked), and `sort_order`
  · **MCP:** `add_spec_criterion`, `update_spec_criterion`.

### W3. Link work + self-audit
- A task implements a spec via `Task.spec_id` (`PATCH /api/v1/tasks/{id}` with `spec_id`; planner,
  or an engineer on their own task) · **MCP:** `link_task_to_spec`.
- `GET /api/v1/specs/{id}` returns the **self-audit bundle**: the spec + its criteria + the linked
  tasks (name/status/percent) + computed **readiness** (`criteria_met` / `criteria_total` excluding
  waived, `acceptance_ratio`). Readiness is pure in `app/services/specs.py` · **MCP:** `get_spec`.
  The bundle also carries `docs_ready` / `docs_pending` (advisory — its source docs are approved;
  "source docs not approved" chip in the UI), and moving a spec to **approved** pins every
  basis design doc to its current version (§V9).
- **Skill `spec-driven-development`** scripts the loop: draft the spec from a PRD/ADRs → write
  checkable criteria → approve → plan + link the work (via `drafting-tickets`) → self-audit
  each criterion against the implementation → mark `verified` when all are met.

### W4. Not built (deliberate limits)
- **UI:** a **Specs** tab on the project cockpit lists specs, creates them, and expands each into
  its problem + acceptance criteria (with a readiness bar and contributor-writable verdicts) +
  implementing tasks. Built.
- **No status transition gating** (unlike ADRs §G2) and **no DraftPlan→Spec FK** (link a draft
  plan's `source` to the spec, then link the synced tasks). Decision→task traceability is the
  ledger (§G8, `Task.implements_adr_id`).

---

## X. Delivery metrics (DORA + flow) **[new]**

The quantitative backbone of [`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) (roadmap gap #3):
DORA + flow metrics computed from canopy's own signal — the §J8 activity substrate (deploys /
incidents) and `TaskStatusHistory` (throughput / cycle time) + the board (WIP / aging). Logic is
pure in `app/services/flow_metrics.py` (unit-tested); the endpoint reuses `build_board`,
`weekly_throughput`, and the status **categories** stamped on history so the numbers match the
board / forecast / burndown.

- **Team-level by design.** There is deliberately **no per-engineer breakdown** — per-individual
  delivery metrics are a Goodhart trap (velocity / diffs / tokens as a target). The response says
  so in its `notes`.
- **Honest, not falsely precise.** Flow reports `sufficient=false` with a reason under ~3 weeks of
  throughput (same bar as the forecast); change-fail rate is `null` with no deploys; metrics canopy
  can't compute from its data (PR-review latency, decision latency) are absent, not faked.

### X1. Read delivery metrics (project + initiative)
- **API:** `GET /api/v1/projects/{id}/delivery?weeks=` and `GET /api/v1/initiatives/{id}/delivery?weeks=`
  (default 12, max 52; the initiative variant aggregates across its sub-projects) · **MCP:**
  `get_delivery_metrics` (pass `project_id` *or* `initiative_id`). Open read.
- **DORA:** `deploys`, `deploy_frequency_per_week`, `failures` (incidents opened),
  `change_fail_rate` (≈ failures ÷ deploys), `recovered_incidents` + `mean`/`median_recovery_hours`
  (incident_open→close paired FIFO — an MTTR proxy).
- **Flow:** `completed_items`, `throughput_per_week`, `cycle_time_median_days` +
  `cycle_time_p85_days` (**started→done** over the window), `lead_time_median_days`
  (created→done), `wip` (leaves in an `in_progress` category right now — the backlog is not WIP),
  `aging_wip` (WIP over the team's cycle-time P85), `sufficient` + `reason`.

### X2. Not built (deliberate limits)
- **UI:** a **Delivery** tab on the project cockpit and a **Delivery metrics** panel on the
  initiative cockpit show the DORA + flow stat cards with a window selector and the honesty notes.
  Built.
- **No rework rate** (DORA 2025 — needs unplanned/rework tagging canopy doesn't have), **no flow
  efficiency** (needs an active-vs-wait status classification), and **no PR-review / decision
  latency** (need GitHub PR metrics §J6 / ADR status history). Surfaced as `notes`, not faked.

---

## Y. Outcomes — outcomes over output **[new]**

A project/initiative is a **bet**, not just a container of tasks (roadmap gap #2;
[`AI_NATIVE_EXECUTION.md`](./AI_NATIVE_EXECUTION.md) §1/§5). An `Outcome` (`app/models/outcome.py`)
captures the **hypothesis** ("we believe X will yield Y") + a **success metric**, tracked
**baseline → target → current** with a verdict — so the team optimizes for *the result*, not
output. Scope is polymorphic (project | initiative, like the risk register); an entity can carry
several (key results). The observed `current_value` is recorded by hand (canopy has no product-KPI
pipeline — an honest manual signal, like the weekly health note). `status`:
`pending → on_track / at_risk → validated | invalidated`.

### Y1. Define / track / verdict an outcome
- **API:** `GET /api/v1/outcomes?scope_level=&scope_id=&status=` (open read), `POST /api/v1/outcomes`
  (planner; validates the project/initiative exists), `GET /api/v1/outcomes/{id}`,
  `PATCH /api/v1/outcomes/{id}` (planner — record `current_value`, move `status`),
  `DELETE /api/v1/outcomes/{id}` (planner). `OutcomeRead` carries a computed **`progress_ratio`**
  ((current − baseline) / (target − baseline); pure in `app/services/outcomes.py`) ·
  **MCP:** `list_outcomes`, `add_outcome`, `update_outcome`.
- **UI:** an **Outcomes** panel on the project cockpit (below the delivery meta bar) and the
  initiative cockpit — list with a progress bar + status badge, an add form (statement · metric ·
  baseline/target/unit · date), an inline **record-current** input, and a status select.

### Y2. Retros evaluate the bet
- The retrospective seeder (§P1) now opens with an **"Outcomes — did the bet pay off?"** section
  listing each project outcome as `statement — current/target unit (status)`, so a retro evaluates
  the outcome, not just the schedule (`app/services/retro.py`).

### Y3. Not built (deliberate limits)
- **No automatic metric ingestion** — `current_value` is recorded by hand (no analytics/KPI
  connector). **No OKR hierarchy** (objectives → key results as a tree) — outcomes are a flat list
  per entity. **No initiative→project outcome rollup** yet.

---

## AA. Change proposals — the agent→human review queue **[new]**

The write path for **agent judgment**. When a Claude session (or a teammate) wants to
change canopy based on something it *inferred* — a Slack thread, an email, meeting notes, a
document, or its own analysis — it does not touch the live plan. It **stages a proposal**:
a batch of typed changes with per-item **provenance** (where each fact came from) that a
human reviews, prunes, and **applies from the UI**. Nothing staged is visible to the
Gantt/CPM/board/alerts until applied. This completes the bounded-agency posture (§A6) with
a *structural* human-in-the-loop: an `agent` token can stage and withdraw but is **403 on
apply/reject** — committing the change is reserved for a person. (Two staging lanes now
exist: **draft plans** stage *outbound* plan→Jira tickets (§C10); **proposals** stage
*inbound* changes to canopy itself.)

The review is **plan-first, then fine-grained, and conversational**: the reviewer first sees
what the proposal does to the plan *as a whole* (a **Current ⇄ With this proposal** toggle
over the schedule, §AA2), then goes through the changes one by one in plain words — editing
or excluding any of them — and can **ask Claude to revise the proposal in conversation while
the page is open**, watching it update live (§AA5).

### AA1. Stage a proposal (agent or contributor)
- **What an item can do:** `task.create/update` (planning fields, plus `status` — a column of
  the project's workflow — **on canopy-owned tasks only**: a mirrored task's status belongs to its
  tracker and is refused; apply writes it through the one status write path, so it lands in the
  history with the reviewer as author; `sprint_id` (null = back to the backlog) where canopy owns
  the task's sprint membership, and `story_points`; to move work in time stage `duration`, a dependency, or
  **`constraint_start`** — the "start no earlier than" pin — since a task's `start` is
  computed output the replan overwrites), `dependency.create`, `milestone.create/update`,
  `blocker.create/resolve`, `risk.create/update`, `outcome.create/update`,
  `decision.create` (lands as a **proposed** ADR — the §G lifecycle takes over),
  `doc_reference.create` (through the design-doc register-or-link path, with `visibility` — a
  private Claude doc is refused, §V6), `doc_link.create` (link a tracked doc — `doc_id`, or a
  `doc_ref` staged here — to work in scope — `entity_id`, or an `entity_ref` of the right kind
  — with a relation, §V9), `rule.create` (a **project** delivery rule, §AE7 — with
  `ai.stage_policy` on and a key new to the project; how a session turns a recurring review note
  into a rule a person accepts). Payloads are **whitelisted per
  entity/action** and validated through the same schemas as the REST API — no
  mass-assignment; a create item may declare a `ref` handle that later items point at
  (`parent_ref`, `predecessor_ref`, `task_ref`, …), so one proposal can stage "create
  phase → tasks under it → wire dependencies" before any ids exist.
- **Scope containment:** a proposal targets one **project or initiative**; every item must
  stay inside that scope (validated — a proposal reviewed under project A cannot mutate
  project B; initiative scope allows cross-sub-project items, e.g. a hand-off dependency).
- **Provenance:** each item carries `source_kind` (slack | email | calendar | meeting |
  jira | github | drive | document | chat), `source_label`, `source_url`, and a one-line
  `reason` — the reviewer can audit every line.
- **Strict at the door:** staging validates every item (shape, refs, targets exist, scope,
  and that every **person it names is a real engineer** — an unknown `assignee_engineer_id`
  is refused rather than failing the apply on a foreign key) and rejects the whole batch
  with per-item errors (400) so the author fixes it now, not the reviewer later. For
  `update`/`resolve` items a **before-snapshot** of the touched fields is captured at stage
  time.
- **API:** `POST /api/v1/proposals` (contributor+; **agent tokens allowed** — staging is a
  reversible two-way door) · **MCP:** `propose_changes` (returns a `review_url`).
- **Read:** `GET /api/v1/proposals?scope_level=&scope_id=&status=`,
  `GET /api/v1/proposals/{id}` (items + before/current values + `stale` flags + **`lookups`**:
  display names for every id the items mention — tasks, engineers, projects, specs — so a
  reader sees "Dana Lee", not `assignee_engineer_id: 14`; + the co-review trail `revision` /
  `revised_at` / `revision_note` and the author's `created_by`) · **MCP:** `list_proposals`,
  `get_proposal`.

### AA2. Review & commit (human, in the UI)
- **Queue — `/reviews`** (sidebar, with an **open-count badge**; with `ai.work_queue` on it has
  two tabs, **Changes** — this queue — and **Decisions**, agent work waiting on a person, §AE4):
  one scannable row per proposal — status, scope chip, title, the author's rationale (two lines), who staged it and
  when, the revision if it has been revised, a **shape chip** row (`+N` creates / `~N`
  updates / `✓N` resolves, from `action_counts`) and, when relevant, an amber
  **"⚠ N need attention"** flag (`attention_count`: items that errored or **drifted since
  staging**). Both are computed server-side on `ProposalRead`
  (`app/api/v1/proposals.py:_action_counts` / `_item_needs_attention`), so the list and the
  nav badge share one source of truth. Clicking a row opens its review workspace. The project
  cockpit (§B3) shows an amber **"staged change proposals await your review"** banner when
  any target it.
- **Review workspace — `/reviews/:id`** (the deep link the plugin hands the user;
  `frontend/src/pages/ReviewWorkspace.tsx`). Top to bottom:
  - **Header + "Why"** — title, status, scope (links to the project/initiative), who staged
    it and when, and the author's rationale.
  - **Impact strip** — the headline before any detail: the **finish date** current →
    proposed with the day delta (per project for an initiative-wide proposal), the critical-
    path task count when it changes, plain-language chips for the proposal's shape ("3 new
    tasks", "6 tasks move as a result", "1 blocker raised"…), and **apply-readiness** —
    "✓ Ready to apply" or "N things to fix before this can apply" with a **Show me** jump,
    known *before* clicking Apply.
  - **Plan tab — the plan as a whole, current ⇄ proposed.** A segmented toggle
    **Current plan | With this proposal** over the project Gantt (project pills pick one for
    an initiative-wide proposal). Both sides share one time axis and row order and the chart
    opens **fitted to the page width**, so flipping the toggle shows exactly what moves and
    nothing else. Rows are tinted by *why* they differ — **New** in this proposal (green),
    **Edited** by it (blue), **Moves as a result** (amber: untouched, but pushed/pulled by a
    change upstream) — and on the proposed side each moved bar carries a thin grey ghost of
    where it sits today plus a `+Nd` chip. Below: a **What moves** table (start/finish
    before → after per task, "now critical" when it joins the critical path), the
    **milestones** before → after, any **new deadline miss**, and a note when the proposal
    doesn't touch the schedule at all. **Clicking a tinted row** (chart or table) jumps to
    the change behind it.
  - **Changes tab — the fine-grained set to apply.** Changes are grouped by the part of the
    plan they touch (Schedule · Milestones · Blockers · Risks · Outcomes · Decisions · Docs)
    and each reads in plain words: an action label ("New task", "Update milestone", "Link
    tasks", "Raise blocker"), the thing's name, and its values with human labels, units and
    **names instead of ids** ("Assignee Isabel Moreno", "Under PCI hardening (new)",
    "Duration 12d → 16d") — plus the reason and a provenance chip/link. Filters: **All ·
    Needs attention · Just revised**. A change that would fail carries the reason inline
    ("Can't apply: needs “PCI hardening”, which is excluded…"); one whose target moved since
    staging shows the live value ("now 6d").
  - **Sticky action bar** — **Apply N changes** (disabled, with the reason, while anything is
    flagged), **Reject…** with a note, and what applying entails.
- **API behind the plan view:** `GET /api/v1/proposals/{id}/preview` → per project the
  `current` and `proposed` schedule (same shape as `GET /projects/{id}/gantt`),
  `end_current` / `end_proposed` / `end_delta_days`, critical-path counts, `task_changes`
  (`added | edited | shifted`, before/after dates, the `item_ids` behind each), `milestones`,
  `new_deadline_misses`, plus overall `counts` and `can_apply` / `issues`. A **pure
  simulation** — nothing is written (`app/services/proposal_preview.py`): the included items,
  with the reviewer's overrides, are replayed onto an in-memory copy of the plan and both
  graphs go through the **same scheduler apply uses**, so "proposed" is exactly what Apply
  produces (pinned by a test). "Current" is the live plan *recomputed*, so every difference
  is the proposal's doing; when the saved schedule was stale the project says so
  (`live_schedule_stale`). Tasks the proposal creates carry synthetic negative ids; a staged
  dependency cycle is reported (`cycle`, no proposed side) rather than raised. Open proposals
  only (409 once closed). Replan is project-local, so cross-project hand-off edges are not
  simulated. **MCP:** `preview_proposal`.
- **Review actions (planner + human-only — an agent token gets 403):**
  - **Include / exclude** — a checkbox per change, **Include all / Exclude all**, and
    "Exclude these" per group (`PATCH /api/v1/proposals/{id}/items` `{excluded, item_ids?}`
    for many at once; `PATCH …/items/{item_id}` `{excluded}` for one). Changes that build on
    each other **move together**: excluding a new phase also excludes the tasks and
    dependencies that hang off it, and re-including one brings back what it needs — with an
    "Also excluded N changes that depend on it · **Undo**" notice — so the remaining set can
    always still apply. The plan preview recomputes after every toggle.
  - **Edit in place (audit-preserving, T17)** — fix a value without rejecting the proposal.
    **Edit** on a card opens a small form over every plain value on that change, with the
    right control for each: a date picker for dates, a number box with its unit, a dropdown
    for enums (severity, status, link type…), a people list for assignee/owner, text areas
    for long text. **+ Add a field…** adds a value the proposal left out (an assignee, a
    deadline, a "start no earlier than" pin). **Save** applies the reviewer's values instead
    of the agent's; the agent's original stays as the record (shown struck next to the violet
    edit), the card carries an **"edited by …"** stamp, and **Reset to the proposed values**
    reverts. API: `PATCH …/items/{item_id}` with `{overrides: {field: value}}` (`{}` clears);
    an override that fails validation is **rejected at edit time** (400 `invalid_override`),
    not deferred to apply. Mechanics: `payload` (agent) is never mutated — `overrides`
    (reviewer) is layered on at apply via `effective_payload` (`app/services/proposals.py`),
    so the merged value is the single source validation, the preview and apply read from. An
    override may touch a value the proposal already sets or any whitelisted value field for
    that kind of change (`addable_fields` on each item lists them); **scope plumbing**
    (`project_id`, `scope_*`) and structural `*_ref` handles can never be set this way.
  - **Apply** — `POST /api/v1/proposals/{id}/apply`: re-validates every included item,
    executes **all-or-nothing** in one transaction (per-item failures report inline and
    nothing lands), **auto-replans** the affected projects (a staged dependency cycle →
    409), stamps reviewer + `applied_count`, and publishes SSE (§K) so every open view
    refreshes. Items record their `applied_entity_id`.
  - **Reject** — `POST /api/v1/proposals/{id}/reject` `{note}`: the note is the feedback
    the author (usually the agent) reads back before restaging. Delivery is **pull, not push**:
    the author discovers the rejection + note via `list_proposals` (MCP) / `GET /proposals?status=rejected`
    — an outbound Slack/email nudge would ride the same delivery hook as the alerts digest (§I, not built).
- **Withdraw:** the author (or a planner) can pull an open proposal back —
  `POST /api/v1/proposals/{id}/withdraw` (**agent-allowed**: cleaning up your own staged,
  never-applied change is reversible) · **MCP:** `withdraw_proposal`.
- **Lifecycle:** `open → applied | rejected | withdrawn` (terminal states are immutable
  history; re-applying an already-applied proposal → 409).

### AA3. Where it's enforced / wired
- Feature gate **`ai.proposals`** (§A10) on the router + the sidebar entry + banners.
- Human-only via `HumanOnly` (§A6) on apply/reject/item-review; roles via
  `ContributorWriter`/`PlannerWriter` (§A3a). `GET /api/v1/auth/session` now reports the
  token's `scope` so a session can see its own limits.
- Revise is `ContributorWriter` + author-or-planner and **open to agent tokens** (it is
  still staging); the preview is a plain authenticated read.
- Logic: `app/models/proposal.py` + `app/services/proposals.py` (whitelists, scope checks,
  ref resolution, snapshots, lookups, revise, all-or-nothing apply + replan) +
  `app/services/proposal_preview.py` (the pure current-vs-proposed simulation; shares
  `infer_project_start` / `rollup_summaries` with `app/services/planner.py`) +
  `app/api/v1/proposals.py`; UI `frontend/src/pages/Reviews.tsx` (queue),
  `src/pages/ReviewWorkspace.tsx`, `src/components/review/PlanCompare.tsx` +
  `ChangeList.tsx`, and the pure, unit-tested `src/lib/proposals.ts` (field catalog, plain-
  language facts, grouping, include/exclude dependency closure, preview helpers). The Gantt
  (`src/components/GanttChart.tsx`) gained optional `highlights` / `domain` / `ghostLabel` /
  `fit` props for the comparison; the Schedule tab's use of it is unchanged.

### AA4. Not built (deliberate limits)
- **No apply MCP tool by design** — the commit click lives in the UI only. (A human's
  full token *could* call the apply endpoint directly; the tool surface simply doesn't
  offer it.)
- **No chat box in the UI** — the conversation happens in the reviewer's own Claude session
  (the page offers a starter prompt to copy and updates live as Claude revises, §AA5); there
  are **no reviewer→agent comments on individual changes** beyond the reject note.
- **The plan preview is schedule-only** — it shows dates, critical path, milestones and
  deadline misses, not the knock-on effect on capacity, risk score or forecast (the what-if
  **scenarios**, §T, are the tool for that). Cross-project hand-off edges are not simulated
  (replan is project-local). A reviewer can't re-wire a staged dependency or re-parent a
  task in the form (structure is the author's — ask Claude to revise it).
- **Revision history is the last revision only** (`revision` counter + `revision_note`);
  items a revision removes are deleted, not kept as an audit trail.
- **No per-item partial apply** (apply is all-or-nothing over the included set); **no
  auto-expiry** of stale open proposals; **no engineer/assignee notification** when a
  proposal touches their work.
- Estimates/tags/health writes have no proposal lane (they stay direct, advisory,
  low-risk); Jira ticket **status** is never stageable anywhere (§Source-of-truth).

### AA5. Review together — revise in conversation while reviewing **[new]**
The review is not a one-shot hand-off. With the workspace open, the reviewer tells their
Claude session (the canopy plugin, §L) what to change in their own words — *"push the
pentest out a week"*, *"drop the vendor risk"*, *"add a go/no-go review after the fixes"*,
*"what does that do to the finish date?"* — and the open page updates as Claude revises.
- **In the UI:** a **"Refine it by talking to Claude"** strip on every open proposal with a
  **Copy a starter prompt** button (names the proposal and its URL) and a link to Agent
  Setup (§A11). When a revision lands the page refreshes itself (SSE, §K — no reload) and
  shows **"This proposal was just revised (revision N). “<the author's note>”"**; the
  impact strip and plan redraw, changed/new changes are tagged **revised**, and a **Just
  revised** filter isolates them. The reviewer's own edits and exclusions on untouched
  changes are kept.
- **Revise in place:** `POST /api/v1/proposals/{id}/revise`
  `{note?, update_items?, add_items?, remove_item_ids?, title?, summary?}` — the author or
  a planner; **agent tokens allowed** (still staging — nothing lands until a person
  applies). `update_items[].payload` is **merged** into the staged payload
  (`remove_fields` drops keys; `reason`/`source_*` replace); an item's entity, action and
  target can't change (remove + add instead); `add_items` take the same shape as staging,
  and items are **re-ordered automatically** so a ref declared late still resolves (add a
  phase, then hang an already-staged task under it). Bumps `Proposal.revision`, stamps
  `revised_at` + `revision_note`, marks each touched item with that revision, re-snapshots
  its `before`, and publishes the SSE `proposal` event.
- **Don't make it worse:** the revised set is re-validated and a revision that would
  *introduce* a problem is refused whole (400 `invalid_items`, errors keyed by `item_id` /
  `add_index`; nothing changes) — e.g. removing a phase other staged items hang under. A
  problem that was already there (a target deleted after staging) doesn't block an
  unrelated fix. A value the author rewrites **supersedes the reviewer's inline edit of that
  same field** (the newest instruction wins); other overrides and all exclusions survive.
- **MCP:** `revise_proposal` (returns the revised proposal **plus `impact`** — the compact
  before/after plan summary — so Claude can say "that pulls the finish back to Dec 23") and
  `preview_proposal` (the plan before vs after as data: finish-date movement, the tasks
  added / edited / shifted with dates, changed milestones, new deadline misses,
  `can_apply` + `issues`; `include_plan=true` adds both full Gantts). `get_proposal` shows
  what the reviewer has done so far (`excluded`, `overrides`) so Claude builds on it. The
  **`updating-canopy`** skill §5a is the runbook (re-read → revise in place → say what it
  did; questions are reads; the Apply click is the human's).
- **Still bounded:** a session on an agent token can stage, preview and revise, and still
  gets **403 on apply/reject** and on the reviewer's include/exclude/override actions.

---

## AE. Agent work queue — delegated execution **[new]**

A person **delegates** a task to agents; a Claude session **claims** it, reads its **brief** (the
task, its spec, the decisions that govern it, earlier attempts), records a **plan**, does the
work and **hands off**. canopy is the state machine and the keeper of the rules: it checks each
hand-off against the next column and moves the card — or holds the task for a person (a
**gate**: a question, an escalation, a parked task) and shows it in the Reviews inbox. Design:
[`AGENT_EXECUTION.md`](./AGENT_EXECUTION.md). Feature gate **`ai.work_queue`**; nothing changes
in a project until a planner switches its **intake** on. With **`ai.stage_policy`** on, each
column's **stage policy** says which role works it, what it requires to enter and when a person
looks (§AE6); **rules** carry the team's working agreements and Definition of Done (§AE7); and
the **agent-flow** measures show how it is going (§AE8). On a **mirrored** project canopy
clears moves instead of making them (§AE9); **notifications** tell runners and people when to act
(§AE10); **runners** are how sessions start (§AE11).

### AE1. Delegate a task · switch the project's intake
- **UI:** task panel (§C1a) → **Agent work** → **Delegate to agents** (it answers with advice
  when the task is a poor candidate: no description, no spec or criteria, larger than
  `WORK_SMALL_BATCH_DAYS`, no component, or a tag people usually keep —
  `WORK_KEEP_FOR_PEOPLE_TAGS`) / **Take it back**. Project → **Execution → Agents** → **Agent
  intake: On · Paused · Off**.
- **API:** `POST /api/v1/tasks/{id}/delegation` `{delegation: "agent" | null}` →
  `{task, hints}` · `POST /api/v1/tasks/{id}/take-over` · `POST /api/v1/projects/{id}/agent-intake`
  `{state: off|on|paused}` → `{agent_intake, stopped}`. All **human-only** (an agent token gets
  403 — it may stage a proposal instead, §AA); delegation and take-over: a planner who may edit
  the project or the task's assignee; intake: the project's planners. **MCP:** none (deliberate).
- **Notes:** the assignee stays **accountable**; an unassigned task is assigned to the claiming
  session's issuer. **Off is the kill switch**: running claims end and their sessions are told to
  stop at their next call; paused offers nothing new. Taking a task back (or undelegating) ends
  its claim and closes its open gates. Summary tasks can't be delegated (`422 not_a_leaf`);
  mirrored tasks can, and advance by clearance (§AE9).

### AE2. What is ready, and why the rest isn't
- **The built-in default pipeline** (columns with no stage policy stored, §AE6): the workflow's first
  in-progress column is worked by the **implementer** role and pulls from the last to-do column
  before it; the column after it requires a **hand-off** from agents (`block`) and warns when no
  PR is linked. A team that configured nothing gets exactly this.
- **Readiness** is computed, never stored. A delegated task is not offered when intake is off or
  paused, it is closed, not in an agent column, already claimed, held by an open gate, blocked,
  waiting on its dependencies, its column's checks or WIP limit (`block`) refuse it, it is
  **parked**, outside the active sprint (sprint teams), the token's role or project scope
  excludes it, it is someone else's (an engineer's token), or nobody would be accountable.
- **API:** `GET /api/v1/work/queue?role=&project_id=&team_id=&repo=` (ready tasks, best first —
  work already in the stage before work to pull — plus counts by reason) ·
  `GET /api/v1/tasks/{id}/execution` (the task's readiness per role, claims, artifacts, gates,
  events, exit contract) · `GET /api/v1/tasks/{id}/advance-check?to_status=` (the same policy
  evaluation a hand-off gets, as a dry run) · **MCP:** `find_work`, `get_task_execution`,
  `check_advance`.

### AE3. Claim → brief → plan → hand off (a session's side)
- **MCP (the worker verbs):** `claim_work(role, task_id?, project_id?, team_id?, repo?,
  wait_s?)` returns the **claim and the brief** in one call (nothing ready: `claim: null` +
  `retry_after_s` + reasons; `wait_s` ≤ 25 long-polls) · `get_work_brief(task_id)` ·
  `report_progress(claim_id, note, steps?)` · `submit_plan(claim_id, …)` · `submit_work` /
  `submit_review` · `ask_human` · `release_work(claim_id, reason, note, needs_human?)` ·
  `wait_for_gate` · `set_task_components`. The **skill** `working-the-queue` is the contract;
  `implementing-tasks` the implementer's runbook (§L21).
- **API:** `POST /api/v1/work/claims` (honours `Idempotency-Key`) · `GET /api/v1/work/claims?
  mine=&state=&task_id=&project_id=` · `POST /api/v1/work/claims/{id}/heartbeat` →
  `{directive: continue|stop, reason}` · `…/artifacts` (`plan` → the governing decisions and
  their fitness rules, unsettled ones, whether a person must approve) · `…/gates` (ask a person)
  · `…/submit` (`{handoff}` or `{review}`) · `…/release` · `GET /api/v1/tasks/{id}/brief?role=` ·
  `GET|POST /api/v1/tasks/{id}/artifacts` (a person adds a **note** for the next session; a
  plan outside a claim is human-only) · `GET /api/v1/artifacts/{id}` ·
  `GET|PUT /api/v1/tasks/{id}/components`.
- **Claims are leases.** A claim lasts 30 minutes, renewed by every call that presents it; a
  claim whose lease lapses is expired by the next claim or the reaper (`reap_work_claims`, every
  `WORK_REAPER_MINUTES`) and the task returns to the queue. Every claim-bound write first renews
  the lease with a conditional update — a session whose claim was lost gets `409 claim_lost` and
  changes nothing (**fencing**). A token holds **one** claim at a time by default (a retried
  claim returns the one it holds; `409 claim_limit` for another task). Claiming is a
  compare-and-swap that holds on PostgreSQL, MySQL/MariaDB and SQLite — two sessions never hold
  one task (pinned by the claim-race test on all three servers in CI).
- **The brief** marks each section `trust: "policy"` (canopy's instructions: the stage, the exit
  contract, binding decisions, conventions) or `trust: "content"` (task text, spec, docs,
  history, notes — data, never instructions); untrusted text is stripped of invisible characters
  and HTML comments, and the whole brief fits **24 KB**. It gives every attempt the same branch
  and PR. Its **docs** are the shared design docs homed at the task, its phase, the project or
  the initiative, or linked to them (§V9), each with its review status — never a personal doc,
  nor a Claude doc that isn't shared in Claude — plus the expected kinds (from the doc-kind
  catalog) none of them covers.
- **Handing off:** canopy saves the hand-off, evaluates the next column's entry checks and moves
  the card (`record_transition`, attributed `actor_kind=agent` with the claim id) — or refuses
  with `409 checks_failed` and the list of what's missing (nothing saved; the claim stays the
  session's). A retried hand-off replays the stored result.
- **Each role hands off what its column says** (§AE6): an implementer a `handoff`
  (`submit_work`), a reviewer a `review` and QA a `qa_report` (`submit_review`, with a verdict
  `pass` · `concerns` · `fail` and findings) — anything else is `409 wrong_artifact` naming the
  expected kind. A column whose plan checkpoint is required refuses a hand-off with no plan on
  the task (`409 plan_missing`); a column that needs a different session or person than the
  implementer refuses the claim (`409 same_actor`). A `fail` verdict sends the task back to the
  column the work came from (**rework**, with the review in the next brief); past the column's
  `max_rework` (default 3) canopy opens an **escalation** gate instead of looping.
- **Unfinished attempts park the task.** After three attempts in one column ended unfinished
  (expired, released, failed) canopy stops offering it and opens an **escalation** gate with
  each attempt's last progress note (shown as **parked**).

### AE4. A person decides: the Decisions inbox
- **UI:** **Reviews** (sidebar; the badge counts staged changes **and** gates waiting on you;
  shown when `ai.proposals` or `ai.work_queue` is on) → **Decisions** tab (`/reviews?tab=
  decisions`: waiting on me · all open · all) → a gate's page **`/reviews/gates/:id`**: the
  question (or why a person is asked), the plan / hand-off revision under review with the
  revision before it, the PR evidence, **what canopy checked** (the evaluation that raised the
  gate, split into what canopy **saw** — CI, the PR, its own records — and what a session
  **stated** — verdicts, criteria, attestations — so a reviewer knows what to spot-check), the
  trail — and **the decision**: approve · request
  changes · reject · answer (with the agent's suggested options) · retry with guidance · take it
  over, each saying what it does; request changes / reject / retry need a note. Stage policy
  adds three kinds (§AE6): **plan approval** and **hand-off approval** (a checkpoint's
  conditions held) and **sign-off** (a decision column). Gates also show
  on board cards (a link), in the task panel, on `/me` and `/me/today`, and in the Agents view.
- **API:** `GET /api/v1/gates?status=&mine=&project_id=&task_id=&kind=` ·
  `GET /api/v1/gates/{id}` (with the subject, previous revision, hand-off, reviews, trail) ·
  `POST /api/v1/gates/{id}/decide` `{decision, note?, option?, subject_revision}` (**human-only**)
  · `POST /api/v1/gates/{id}/reassign` `{approver_engineer_ids}` (planners, human-only) ·
  `POST /api/v1/gates/{id}/cancel` (whoever asked — their agent session included — or a planner)
  · `GET /api/v1/gates/{id}/wait?timeout_s=` (≤ 25 s) · **MCP:** `list_gates`, `get_gate`,
  `wait_for_gate` — there is **no tool to decide** (deliberate).
- **Rules:** who may decide follows the gate's approver rule (a question: the assignee or the
  project's planners), widened over time by **escalation** (the project owner, then the
  initiative's owners, then the team's directors); the person whose token produced the work
  can't approve it when no one else could too; a decision names the revision reviewed (`409
  stale_subject` if the work changed meanwhile); **nothing is approved by a timeout**. A
  decision routes the task: an answer or a retry offers it again with the answer in the next
  brief (a retry also resets the attempt count); take over undelegates it; reject cancels it.

### AE5. The Agents view (project)
- **UI:** project → **Execution → Agents**: the intake switch (the kill switch; planners), who
  works which column, what's **ready** by role and why the rest isn't, the sessions **working
  now** (heartbeat age, last progress note; a planner can **release** one back to the queue),
  what **waits on people**, what is **parked**, and how to run sessions (the plugin + an agent
  token, §A11). With `ai.stage_policy` on, the **pipeline** panel (§AE6) replaces the "who works
  which column" card, and the **agent-flow** cards (§AE8) and the **Graduated autonomy** card
  (§AE6) follow it.
- **API:** `GET /api/v1/projects/{id}/agents`.

### AE6. Stage policy — who works each column, what it requires, when a person looks
- **UI:** project → **Execution → Agents** → **Pipeline**: each column with who works it (an
  agent role, people — a **decision column** — or no one: a queue), what it **blocks** or
  **warns** without, and when a person approves. **Edit** (people who may edit the columns at
  the scope they come from: the project's planners for its own columns, the team's directors and
  managers for the team's, admins for the workspace template) opens a drawer: who works it, the
  entry checks as a checklist with an enforcement each (`off` · `warn` · `block`, applying to
  agents or everyone), the **plan** / **hand-off** checkpoints and when they need a person, the
  **decision** settings (who approves, not the requester, whether a PR approval or merge counts),
  `max_rework` and the instructions sessions read in their brief. **Start from the agentic
  delivery template** previews the Appendix A columns — Backlog → Ready → In Progress
  (implementer) → In Review (reviewer) → QA (qa) → Sign-off (people) → Done, + Cancelled — and
  where today's cards go, before saving them as the project's own (WIP enforcement `block`).
- **API:** `GET|PUT /api/v1/projects/{id}/workflow/policy` · `GET|PUT /api/v1/teams/{id}/workflow/policy`
  · `GET|PUT /api/v1/workflows/template/policy` (`{policies: {column: document | null}}` replaces
  every policy at that scope; `{}` returns it to the built-in default; `422 policy_invalid` names
  the column) · `POST /api/v1/projects/{id}/workflow/apply-template` ·
  `POST /api/v1/teams/{id}/workflow/apply-template` (`{dry_run, move_tasks_to}`; the preview lists
  the moves). Reads are open; every write is **human-only**. **MCP:** `get_stage_policy` (read).
- **Checks** a column can require — each **observed** (canopy saw it) or **attested** (a session
  stated it): predecessors done · no open blockers · spec approved · an artifact this round · the
  plan approved (when it needed to be) · a gate approved · a PR linked / its checks passing / approved
  by someone other than the requester / under a size · a review or QA verdict · acceptance
  criteria met · the Definition of Done attested (§AE7) · a different session or person than the
  implementer (claim-time). A person moving a card hits the checks that apply to **everyone**
  (`block` refuses, with a planner override).
- **When a person looks:** a **plan checkpoint** (required; a person approves when the work
  touches a one-way-door decision, a high-criticality component or an unsettled decision, has no
  approved spec, the plan's confidence is low, it is larger than the small-batch limits, or the
  project is on **probation** — fewer than N agent tasks done; or a task tag), a **hand-off
  checkpoint** on the same conditions, and **decision columns**: entering one opens a sign-off
  gate for its approvers. Sign-off always comes before done; a PR approval or merge by someone
  other than the requester counts (decision D3). Nothing is approved by a timeout.
- **Graduated autonomy — pre-approved change classes:** a plan or hand-off checkpoint can list
  change classes (`tag:<tag>`, by task tag) whose work no longer waits for a person there. The
  **safety floor** is never pre-approved: work touching a one-way-door decision, a
  high-criticality component or an unsettled decision, or a low-confidence plan, still asks, and
  so does a condition naming another tag (*always ask for `security` work* holds for a task
  tagged both `docs` and `security`); the other conditions (`always`, larger than the small-batch
  limits, no approved spec, probation, the class's own tag) are waived for a pre-approved class,
  and each waiver is recorded (a `pre_approved` work event). The
  Agents view's **Graduated autonomy** card shows what is pre-approved at the implementer's
  column, the evidence per class over 12 weeks (plans approved as written, median decision time,
  first-pass reviews, rework, parking) and what it suggests: **pre-approve** a class after ≥ 8
  decided checkpoints approved as written ≥ 95% of the time, none sent back, ≥ 5 first reviews
  passing ≥ 85% and nothing parked (never for `WORK_KEEP_FOR_PEOPLE_TAGS` — security, incident,
  compliance by default); **stop pre-approving** one whose work parked, came back for rework
  twice, or whose first reviews passed under 70%. A person applies a suggestion or removes a class
  — nothing changes on its own. **API:** `GET /api/v1/projects/{id}/autonomy?weeks=` ·
  `POST /api/v1/projects/{id}/autonomy` `{checkpoint: plan|handoff, change_class, action:
  add|remove}` (**human-only**, people who may edit the columns' policies; `409 no_checkpoint`
  when no agent column has that checkpoint). **MCP:** `get_autonomy_suggestions` (read).

### AE7. Rules — working agreements and the Definition of Done
- **UI:** project → **Governance → Rules**: the project's effective rules in two lists —
  **Definition of Done** (attested at every hand-off) and **Guidance** (in the brief) — each
  with an origin chip (workspace · team · project), a lock when lower scopes can't change it, what
  it replaces, who and what it reaches (roles, task tags, components, paths), its source decision
  or link, and a **stale** flag when that decision was superseded. **Add rule** (at the scopes you
  may edit), **Edit** / **Delete**, and on an inherited, unlocked rule **Override here** (the same
  key, your wording) or **Switch off here** (listed under *Switched off here* with **Turn back
  on**). A rule the merge sets aside (a locked rule above holds its key) is shown dimmed. Team page
  (`/teams/:id`) → **Rules** tab: the team's own rules beside the workspace's it inherits.
- **API:** `GET /api/v1/rules?scope_level=&scope_id=` (one scope's rows) ·
  `GET /api/v1/rules/effective?project_id=` (resolved, with `origin`, `overrides`, the merged
  `enforcement`, `stale`, `can_edit`) · `GET /api/v1/rules/scopes?project_id=|team_id=` (the
  scopes that reach it and whether you may edit each) · `POST /api/v1/rules` (`409 rule_exists`) ·
  `PATCH|DELETE /api/v1/rules/{id}`. **Human-only**: the workspace's rules — an admin; a team's —
  its directors and managers; a project's — planners who may edit it. **MCP:** `list_rules`
  (read); the brief carries the rules that apply to the session's role and task.
- **Resolution:** workspace, then team, then project; a rule with the same `key` lower down
  replaces the one above (nearest wins) unless that one is **locked**; `disabled` switches an
  inherited rule off; for Definition-of-Done items the **stricter** enforcement always wins (a
  project can tighten a locked rule, never loosen it). An attestation's enforcement applies even
  where the column's own `attestations_complete` check only warns. Code conventions belong in the
  repository's `CLAUDE.md`/`AGENTS.md` (decision D9); hard constraints are entry checks.
- **Hand-offs attest:** `submit_work(…, attestations=[{rule_key, status: done | n/a | not_done,
  evidence}])`; a reviewer can dispute one (a `fail`).
- **Suggested rules — when the same note keeps coming back:** canopy groups people's
  request-changes / reject notes on gates and reviewers' findings on failed or concerned reviews
  by the words they share; a theme seen ≥ 3 times across ≥ 2 tasks that no rule already says is a
  **suggestion** (how often, on which tasks, examples — shown as evidence, never as
  instructions). A session drafts a short rule from one and stages it as a `rule` proposal item
  (§AA1); a person accepts it in **Reviews** — rules stay human-written
  (AGENT_EXECUTION.md §10).
  **API:** `GET /api/v1/projects/{id}/rule-suggestions?weeks=` (default 12) · **MCP:**
  `suggest_rules`, then `propose_changes` (skill `reviewing-changes`).

### AE8. Agent flow — how the system is doing (team-level)
- **UI:** the Agents view's cards (with `ai.stage_policy` on): **Waiting on people** (open gates,
  past their reminder, parked), **Time to decide** (median per gate kind), **First-pass
  acceptance** (reviews and QA; plans and sign-offs), **Rework**, **Flow efficiency** (time under
  a claim ÷ first claim to done), **Unassisted** (agent tasks done that needed no person but the
  sign-off), and **gates as experiments** (a gate approved nearly every time, quickly, isn't
  protecting anything — narrow it).
- **API:** `GET /api/v1/projects|initiatives|teams/{id}/agent-flow?weeks=` (default 8) — queue by
  role and age, human wait by gate kind (median, P85), first-pass rates, rework, claim outcomes,
  flow efficiency, gate load, unassisted share, cost per task when sessions report usage.
  **Team-level only, never per person**; `sufficient: false` (with a reason) under 5 finished
  sessions instead of a rate from noise. **MCP:** `get_agent_flow`.
- **Alerts** (§I): `work_unclaimed`, `rework_loop`, `review_saturated`, `merged_ahead_of_stage`,
  `rule_stale`. The initiative digest (§R5) lists gates waiting past their reminder and parked
  tasks.

### AE9. Mirrored projects — canopy clears, the tracker moves
A mirrored ticket's status belongs to its tracker and canopy never writes it (P11). Everything
else works as on a native project — delegation, briefs, plans, rules, gates — except how work
advances.
- **Policies attach to the tracker's statuses** (stored on the tracker binding): the Agents
  view's pipeline panel edits them like a native project's (`PUT /projects/{id}/workflow/policy`
  on a tracker-scoped workflow); the agentic-delivery template doesn't apply (`409
  workflow_externally_owned` — its columns aren't the tracker's).
- **Claiming and handing off clear moves instead of making them.** A claim that pulls a ticket
  into the agent's column, a hand-off, a person's approval or request for changes all answer with
  `tracker_transition: {key, to_status}` (`cleared_to` on a hand-off) — the session makes that
  move with its own tracker tools, or the tracker's automation does. canopy sees it on the next
  sync or webhook. Until it does, nothing is offered to anyone (`awaiting_tracker_move`).
- **A move canopy didn't clear** (someone moved the ticket in the tracker) is recorded as
  `moved_without_clearance`: the running claim ends, gates holding it in its old column close,
  and an alert fires (§I). A clearance the tracker still doesn't show after
  `WORK_CLEARANCE_HOURS` raises `clearance_waiting`.
- **The approved plan goes onto the ticket**: when a person approves a plan in canopy, it is
  posted as a comment on the mirrored ticket (trackers with the `comments` capability — Jira,
  Linear), content only. With tracker writes routed through Claude (`write_strategy=mcp`), the
  decision carries `response_data.tracker_comment {key, body}` for the session to post instead.
- **UI:** a cleared card shows `→ <status>` on the board; the task panel and the gate page say
  "Move SHOP-12 to In Review in Jira". **API:** `tracker_transition` on `POST /work/claims`, `…/submit`,
  gate reads and `GET /tasks/{id}/execution`; `awaiting_move` on board cards.

### AE10. Notifications — push starts for runners, decisions for people
- **UI:** project → **Integrations → Notifications**, the team page's **Notifications** tab, and
  **Admin → Integrations** (the workspace's): webhooks with their scope, format (JSON, signed —
  or a Slack message), the events they hear, their health (last delivery, failures), **Send a
  test**, the delivery log, switch on/off, edit, delete. Only people who may edit a webhook see
  its full URL (a Slack URL is a credential) — the workspace's: admins; a team's: its directors
  and managers; a project's: its planners. Human-only.
- **Events:** `work.ready` (delegated work became ready for a role — the task key and the role
  only, so a forged call can start a session but never hand it work), `gate.opened`,
  `gate.reminder`, `gate.escalated`, `gate.decided`. JSON deliveries carry
  `X-Canopy-Signature: sha256=<HMAC of the body>` when the webhook has a secret, plus
  `X-Canopy-Event` and `X-Canopy-Delivery`. Notifications use canopy's wording and a link back,
  never text an agent wrote.
- **Email** to the people who may decide a gate (opened, reminder, escalation) when
  `NOTIFY_EMAIL_GATES` and `SMTP_*` are set.
- **Delivery:** a transactional outbox — the change that causes a notification queues it in its
  own transaction; the worker's `deliver_outbox` (kicked after the change, and every minute)
  sends it, retrying after 1, 5, 30, 120 and 480 minutes; a 4xx or a destination that resolves to
  a private address fails at once (https only, no internal hosts —
  `OUTBOUND_WEBHOOKS_ALLOW_PRIVATE` is for local development). Each readiness is announced once.
- **API:** `GET|POST /api/v1/outbound-webhooks` (`?project_id=` / `?team_id=` for what reaches
  them) · `PATCH|DELETE /api/v1/outbound-webhooks/{id}` · `POST …/{id}/test` · `GET …/{id}/deliveries`
  · `GET /api/v1/outbound-webhooks/catalog` · `GET /api/v1/outbound-webhooks/scopes`. Feature gate
  **`integrations.outbound`**. **MCP:** none (people configure where notifications go).

### AE11. Runners — where the sessions come from
canopy offers work; something you run starts sessions ([`AGENT_RUNNERS.md`](./AGENT_RUNNERS.md)
has a recipe for each): an engineer's own session, `/loop`, a headless `claude -p` job on cron or
CI, a scheduled cloud session, a reviewer started by pull-request events, a push start from a
`work.ready` webhook, and the **reference SDK daemon** in [`runners/sdk/`](../runners/sdk/README.md)
— one slot per agent token, one isolated Claude Agent SDK session per claim in its own git
worktree, a heartbeat for the claim, `max_turns` and `max_budget_usd` per session, and a release
with a note when a session stops without handing off.
- **API for runners:** `POST /api/v1/work/claims/{id}/release` takes the session's `usage`;
  `POST /api/v1/work/claims/{id}/usage` reports it after the session ended the claim itself (the
  claim's own token, within a day). The Agents view's cost per completed task reads it.

### AE12. Where it's enforced / wired
- `app/services/work_service.py` is the **only writer** of a claim's state and of
  `Task.active_claim_id`; `app/services/gates.py` of a gate's status and decision
  (`tests/test_work_invariants.py`). Pure logic: `stage_policy.py` (pipeline + checks),
  `work_queue.py` (readiness, leases), `work_brief.py` (the brief); data in `models/work.py`
  (`WorkClaim`, `TaskArtifact`, `WorkEvent` — the audit trail) and `models/gate.py`.
- The GitHub webhook and PR ingest feed gates (§J6); board moves by a person end claims
  (§C9.3); alerts (§I); cascades cover every new table (`tests/test_cascade_delete.py`); live
  refresh publishes `work` events (§K); the demo seed runs agent work through the real
  services (§Z1). The plugin's hooks keep claims alive and stop a session ending with one held
  (§L21).
- Stage policy: pure `stage_policy.py` (the policy document, checks, conditions, routing, the
  template), stored per column by `policy_store.py` (`StagePolicy` rows, carried over on column
  renames), resolved with the workflow by `policy_service.py`; the template is applied by
  `policy_template.py` (the API and the demo seed share it). Rules: `models/policy.py`
  (`DeliveryRule`) + `services/rules.py` (pure `merge`/`applies`). Agent flow: pure
  `agent_flow.py` + `agent_flow_service.py`. `tests/test_stage_policy.py` walks the Appendix A
  pipeline end to end (implement → review → QA → sign-off → done, with rework and attestations).
- Mirrored projects: `work_service.py` is the only writer of `Task.clearance_status` /
  `clearance_at` (`tests/test_work_invariants.py`); the inbound sync calls
  `work_service.on_tracker_move` after `record_transition`; `tests/test_work_mirrored.py` walks
  claim → clear → tracker move → hand-off → review, an uncleared move and a gate approval.
  Notifications: `models/notify.py` (`OutboundWebhook`, `OutboxMessage`) + `services/notify.py`
  (queueing, SSRF guard, delivery) + `api/v1/outbound.py`; `tests/test_outbound.py`. The runner's
  tests fake canopy, git and the session (`runners/sdk/test_canopy_runner.py`).
- The learning loop: pre-approval is decided in pure `stage_policy.py`
  (`PRE_APPROVAL_FLOOR`, `checkpoint_outcome`) through `gates.checkpoint_decision`; the evidence and
  suggestions are pure `autonomy.py` + `autonomy_service.py`; the retro's agent-work lines are pure
  `retro.agent_work_lines`; rule themes are pure `rule_suggestions.py`, and `rule` proposal items
  apply through `proposals.py`. `tests/test_work_policy.py` (floor, suggestions, themes),
  `tests/test_stage_policy.py` (pre-approved classes through the API; recurring notes → a rule
  proposal → applied), `tests/test_retro.py`.

### AE13. Not built yet
- Graduated autonomy tunes one column per project (the implementer's, else the first agent column
  with a checkpoint), by task tag only; there is no class by path or component yet, and no
  pre-approval at team or workspace scope.
- Rule suggestions group notes by shared words (no semantic matching), and a staged rule is a
  project rule — a team or workspace rule is still written by hand (§AE7).
- Per-person notification preferences (email is an install-wide switch today).

---

## L. Claude plugin (agentic flows)

### L1. Install & configure the plugin
- Install the `canopy` plugin (cataloged by `.claude-plugin/marketplace.json`). Configure
  `api_base_url` (e.g. `http://localhost:8000`), `dashboard_url` (where the React app lives —
  used to build the **review links** the plugin hands the user, §AA; defaults to
  `http://localhost:5173` for dev, and in production is usually the same origin as the API),
  and either `api_token` (a JWT from `POST /auth/login` — or better, a bounded **agent token**
  §A6, which structurally cannot commit its own proposals) or `api_email`+`api_password` (a
  service account the server logs in as, **auto-refreshing its JWT** when it expires — the
  zero-maintenance choice for long-lived services). The MCP server then exposes curated tools
  that call the REST API.
- **Transport.** Locally the plugin launches the MCP server over **stdio** (`plugin/.mcp.json`).
  For production / cloud Claude sessions, run the server as a long-lived service over
  **streamable HTTP** (`CANOPY_MCP_TRANSPORT=http` + `CANOPY_MCP_HOST`/`PORT`/`PATH`, default path
  `/mcp`; **SSE remains as a legacy option**) and point the session at
  `https://<host>/mcp` with `"type": "http"`. `CANOPY_MCP_AUTH_TOKEN` is required to bind beyond
  loopback (the server refuses to start without it) — clients send `Authorization: Bearer <token>`.
  **Per-caller mode** (`CANOPY_MCP_AUTH_MODE=per_caller`): each client sends **its own** canopy
  agent token instead; the server validates it with the API (`GET /auth/session`, re-checked at
  least once a minute so a revoked token stops working) and uses it for that request's calls, so
  every session acts as itself with its own scope (§A6) and the server holds no canopy credential. Backend
  connection and transport are all read from **environment variables**, so a headless cloud
  session needs no interactive plugin config. See README → *Production deployment* and
  `docs/PRODUCTION.md` (Caddy routes `/mcp` and ngrok exposes it publicly).
- **Feature awareness.** `get_enabled_features` returns the admin's feature-gate map (§A10);
  gated-off surfaces answer 403 with `{code:"feature_disabled"}` — Claude should report the gate
  rather than retry.

### L2. Plan a roadmap (skill + subagent)
- Ask Claude to plan/break down/sequence work. The **`planning-roadmaps`** skill (and **`gantt-planner`**
  subagent for heavier work) create projects/phases/tasks/dependencies and run `replan_schedule`,
  reporting the critical path and end date. Two landing lanes: a **fresh project dictated
  live** is built directly; a **re-shape of an existing live plan** (or a plan derived from
  docs/threads) is staged as one `propose_changes` batch the architect applies from the
  review queue (§AA — apply replans automatically); the planner then calls
  `preview_proposal` and reports what the batch does to the plan (finish date, knock-on
  shifts), the same current ⇄ proposed picture the review page opens on.

### L3. Sync from the tracker (skill + subagent) **[updated]**
- Ask Claude to "sync Jira" / "sync the tracker". The **`syncing-trackers`** skill /
  **`tracker-sync`** subagent orient with `get_workspace_context` + `get_project_tracking`, sync
  each bound project (`sync_project_tracking`, or a connection with `sync_tracker`), then
  reconcile the plan (`replan_schedule`); a tracker canopy can't read directly is routed to
  `mcp-ingest`. The skill also covers **linking a specific item** (initiative/epic/story) via
  `link_tracker_item` / `list_tracker_links` / `resync_tracker_link` / `unlink_tracker_item`
  (§J9), and **binding, unbinding or switching** a project's tracker with
  `switch_project_tracking` — preview, then a human applies (§C12). The subagent is
  `tracker-sync`.

### L4. Write, propose & shepherd decisions (skill)
- The **`writing-adrs`** skill drafts an ADR with a consistent template and records it (`create_adr`),
  proposes one on an engineer's behalf (`propose_adr`), runs it through the review lifecycle
  (`transition_adr`), discusses/reviews it (`comment_adr`, `get_adr`), or imports one from a
  repo/Drive doc (`import_adr`). It also reads the **decision queue** (`decision_queue`) as a
  morning surface.
- **Not built:** a `/canopy propose-adr` slash command — proposing is available as the
  `propose_adr` MCP tool today.

### L5. Plan capacity (skill)
- The **`capacity-planning`** skill reads `get_capacity` + `list_alerts`, cross-references the critical
  path, and uses `whatif_schedule` to test staffing/scope changes before committing them.

### L6. Assess risk (subagent)
- The **`risk-analyst`** subagent leads with `get_risk` (score + breakdown), then drills with
  `list_alerts`, `get_burndown`, the critical path, `decision_queue`, and `adr_impact` into a
  prioritized risk report — and can record agreed mitigations via `log_risk_mitigation`.

### L7. Inspect the current user's workspace (tool)
- `my_workspace` returns the caller's linked engineer profile, assigned open tasks, and the
  decisions they own / must review (the API behind §M).

### L8. Detect architecture drift (subagent) **[new — v2 §L7]**
- The **`drift-sentinel`** subagent reads code via its tools, maps imports back to components using
  their code-binding `module_prefix`es, flags implicit decisions, and calls `scan_drift` — then
  reports the refreshed drift score + queue and can `reconcile_drift` with the architect's go-ahead.
  Tools: `list_components`, `list_code_bindings`, `read_repo_file`, `scan_drift`, `get_drift`,
  `reconcile_drift`, `adr_impact`. This is the producer behind the Drift tab (§N).
### L9. Decision-deadline nudger (skill) **[new — v2 §L8]**
- The **`decision-deadline-nudger`** skill reads the `decision_queue`, finds `deferred` ADRs whose
  `decide_by` is approaching/overdue, and posts a nudge (alternatives + the open question) to the
  owner via `comment_adr`.

### L10. PR-to-ADR linker (skill) **[new — v2 §L9]**
- The **`pr-to-adr-linker`** skill maps a PR's changed paths to components (via code bindings),
  finds the ADRs governing them (`adr_impact`), and judges whether the PR implements / contradicts /
  is unrelated to each — building implementation traceability. A confirmed *implements* is
  recorded on the PR's task (`link_task_to_decision`), which the traceability ledger reads (§G8).

### L11. Draft a plan → tickets or tasks (skill) **[updated]**
- The **`drafting-tickets`** skill turns inputs (a codebase via `read_repo_file`, a design
  doc/PRD via `read_design_doc`, what's already planned) into a reviewable **draft plan**
  (`create_draft_plan` + `add_draft_task` with estimates + story points), refines it with the
  architect (`get_draft_plan` / `update_draft_task` / `delete_draft_task`), then has the human
  **finalise** it (`finalize_draft_plan` — native tasks, or tickets in the project's tracker that a
  `sync_project_tracking` pulls back). Content only — status is never written (§C10).

### L12. Explore a what-if scenario (subagent) **[new]**
- The **`scenario-architect`** subagent answers what-if questions on an initiative without touching
  the live plan: it `create_scenario`s a branch, makes the edits (`set_scenario_allocation`,
  `set_scenario_availability`, `add_scenario_task` / `add_scenario_dependency`,
  `update_scenario_task`), then reads `compare_scenario` (+ `scenario_critical_path` /
  `scenario_capacity`) and reports the project-end and critical-path trade-off. It **does not
  `apply_scenario`** unless explicitly told to (apply writes canopy's plan + replans, never Jira).
  This is the agentic surface behind §T.

### L13. Enrich delivery metadata (subagent) **[new]**
- The **`delivery-enricher`** subagent annotates a project the way a PM / eng-leader would: it reads
  the plan (`list_tasks`, `get_gantt`, `get_risk`) then **proposes** 3-point estimates
  (`set_task_estimates`, advisory — never moves `duration`), logs qualitative risks in the register
  (`add_risk` / `update_risk` / `close_risk`, kept separate from the computed score), tags work
  (`add_tags`), flags impediments (`raise_blocker` with category/severity/needed-by), and sets a
  weekly health headline (`set_project_health`). Estimates/risks are proposals the architect
  confirms; Jira status is never written. When the enrichment is broad or unsolicited (a
  scheduled pass), it stages the risk/blocker items as a change proposal (§AA) instead of
  writing them directly. This is the agentic surface behind §C1a / §Q3a. (The read-only
  **`risk-analyst`** §L6 still owns assessment of the computed score.)

### L14. Map epic documents into the doc graph (skill) **[new]**
- The **`mapping-epic-docs`** skill runs the one-time, AI-driven setup behind §V: it samples a
  Jira connection's epics (`sample_epic_doc_fields`), infers which field holds which kind of doc
  from field names + URL domains, **confirms the mapping with the admin**, saves it
  (`set_epic_doc_field_mapping`), harvests (`harvest_epic_docs`), and reports coverage
  (`get_doc_coverage`). canopy reads only — links are never written back to Jira and documents
  are never stored.

### L15. Spec-driven development (skill) **[new]**
- The **`spec-driven-development`** skill runs the spec loop (§W): draft a `Spec` from a PRD/design
  (doc graph §V) + ADRs (`create_spec`), write explicit checkable acceptance criteria
  (`add_spec_criterion`), approve it, plan + link the implementing work (`link_task_to_spec`, with
  `drafting-tickets`), then **self-audit** each criterion against the implementation
  (`get_spec` → `update_spec_criterion` met/unmet) and mark the spec `verified` when all are met.

### L16. Daily standup / health digest (skill) **[new]**
- The **`daily-standup`** skill builds a manage-by-exception briefing (§R5): it reads
  `get_initiative_digest` for the spine (headline + attention list + status + outcomes), drills the
  exceptions (`list_blockers`, `decision_queue`, `get_drift`, `get_forecast`,
  `get_initiative_critical_path`, `list_outcomes`), and writes a tight, exception-first update.
  Composes existing read tools; its only write is **optional staging** of the follow-ups it
  surfaced (blockers/risks/decisions) as a change proposal (§AA) — safe on any cadence (pair
  with `/loop`). Delivery to Slack/email is a hook over the digest content.

### L17. Session orientation + the write ladder (skill + tool) **[new]**
- **`get_workspace_context`** is the orientation verb every canopy session calls first: the
  user + their **persona** (`function`, §A7) and role, the token's **scope** (§A6), the
  feature-gate map (§A10), the projects/initiatives to anchor ids against, the **open
  proposals** already awaiting review (§AA), and the dashboard/review URLs.
- The **`updating-canopy`** skill is the plugin's operating contract for *any* session that
  writes canopy: orient first, then place every intended change on the **write ladder** —
  read-only → small explicit reversible edits (direct tools) → anything **inferred from
  external sources / multi-entity / schedule-shaping** (stage a proposal, §AA) → one-way-door
  and external-write actions (human-only, hand over the review link). It also carries the
  provenance discipline (every harvested fact cites its source) and the source-of-truth rules
  (Jira status never written; structured mirror-sync ≠ proposals).
- **Reviewing together (§AA5):** after staging, the skill has Claude `preview_proposal` and
  lead with the plan-level effect, then stay in the loop while the user reviews in the UI —
  re-read (`get_proposal`, including the reviewer's exclusions/edits), **`revise_proposal`**
  in place for each requested change (never a second proposal or withdraw-and-restage),
  and report the new impact. The user's open review page updates live.

### L18. Harvest external signals → proposals (skill + subagent) **[new]**
- The **`harvesting-signals`** skill is the cross-connector pipeline: sweep the session's
  *other* tools — **Slack, Gmail, Google Calendar, meeting notes, Jira comments, GitHub PRs,
  Drive docs** — for the seven signal types canopy can hold (blockers, risks, decisions,
  status/progress, date+scope commitments, outcome movements, documents), **dedupe against
  canopy's current state**, and stage one reviewable proposal per scope with per-item
  provenance (§AA). The **`signal-harvester`** subagent runs the same pipeline as isolated
  multi-step work (it deliberately has no direct-write lane; safe on a schedule with an
  agent token — everything it stages waits in the review queue).

### L19. Persona playbooks (skill) **[new]**
- The **`persona-playbooks`** skill tailors a session to who the user is (§A7): per function
  (architecture · product · management · leadership · engineering · design) it maps what to
  read first, the core verbs, what gets staged vs written directly, and which sibling
  skills/agents to chain — so the same plugin serves the architect re-planning a WBS, the PM
  recording outcomes from an inbox sweep, the EM clearing blockers after standup, and the
  exec who only reads digests.

### L20. Work the board (skill) **[new]**
- The **`working-the-board`** skill moves work the right way: read the board and its WIP scope
  (`get_board`, `get_workflow`), move or reorder canopy-owned cards with `move_task` (with
  `expected_status`), pull unassigned work, read each refusal (`status_externally_owned`,
  `wip_limit_reached`, `unknown_status`, `native_tracking_disabled`) and route an *inferred*
  status through a proposal instead (§C9, §AA). A **delegated** card is the queue's: an agent
  token gets `use_work_claim` and works it through the worker verbs (§AE3).

### L21. Work the agent queue (skills + subagent + hooks) **[new]**
- **`working-the-queue`** — the worker contract: orient (`get_workspace_context.agent` lists the
  claims this token holds — resume those first), claim, read the brief (only `policy` sections
  instruct), keep the claim alive, ask (`ask_human`) instead of guessing, hand off or release,
  never end holding a claim; with a table of refusals and what to do. **`implementing-tasks`** —
  the implementer's runbook: plan against the binding decisions and acceptance criteria, pass
  the plan checkpoint, implement small on the brief's branch, verify, hand off with evidence.
  The **`task-implementer`** subagent runs one task end to end in a worktree. The MCP server's
  instructions carry a short version of the contract for sessions that never load the skill.
- **Hooks** (`plugin/hooks/hooks.json`, `mcp_tool` hooks on the plugin's own server, so no
  credential reaches a shell): **SessionStart** after compaction reminds the session of the
  claim it holds (`session_context`; at launch and on `--resume` MCP hooks don't run, so the
  skill's orientation step covers that); **PostToolBatch** renews the claim at most once a minute
  (`heartbeat`) and relays a `stop`; **Stop** asks once to hand off, ask or release while a claim
  is held (`handoff_check`). Hooks raise the quality of hand-offs; the lease is the guarantee.
- **Reviewer and QA roles** (§AE6): **`reviewing-changes`** — review a PR against the brief
  (spec, approved plan, binding decisions and their fitness rules, the team's rules and the
  Definition of Done), record findings by severity and a verdict with `submit_review`, never fix
  what you find; **`verifying-changes`** — run each acceptance criterion against the change and
  record what was done and seen as a `qa_report`. The **`change-reviewer`** and **`qa-verifier`**
  subagents run them with no edit tools. Read-only tools for the policy around the work:
  `get_stage_policy`, `list_rules`, `get_agent_flow`, `get_autonomy_suggestions`. When the same
  finding keeps coming back, a reviewer checks `suggest_rules` and stages the rule it would have
  wanted as a `rule` proposal item (§AE7) — a person accepts it.
- **Mirrored tickets** (§AE9): the contract adds one step — when a response carries
  `tracker_transition`, make exactly that move in the tracker; never move the ticket anywhere
  canopy didn't clear.
- **Plugin options:** *Agent label* and *Agent runner* name the session on its claims
  (`CANOPY_AGENT_LABEL`, `CANOPY_AGENT_RUNNER`; `CANOPY_SESSION_REF` records a session id).

---

## M. Engineer workspace (`/me`)

Makes engineers first-class (v1 had no engineer-facing surface). A logged-in user is mapped to a
team member via `Engineer.user_id` (§A5).

### M1. My work
- **UI:** `/me` (also "My work" at the top of the sidebar) → the user's profile (role + linked
  engineer's GitHub / timezone / committed hours / skill tags), their **assigned open tasks**
  (most-critical first, then soonest due), and the **decisions they own** and **decisions to
  review** — each linking into the owning project's Gantt / Decisions tab.
- **API:** `GET /api/v1/me/workspace` · **MCP:** `my_workspace`. The response also includes
  **`blockers`** — open impediments on your tasks or raised by you (§D0), with flag/resolve in the UI
  — and **`my_sprints`** ("My sprint"): each active sprint you have work in, with just your tasks
  (§C11); **`gates`** — agent work waiting on a decision you may make (§AE4; empty with
  `ai.work_queue` off); and **`docs_to_review`** — design docs in review that you approve (a
  planner on their home, §V8) — rendered as **Design docs to approve** (Approve in place).
  **My docs** lists your personal docs (§V6).
- **Note:** if no engineer is linked to the account, the page prompts to have an admin link one on
  the Team page; tasks/decisions are empty until then.

### M2. Today (daily focus) **[updated]**
- **UI:** `/me/today` (linked from `/me`) → today's focus, now covering the four time-sensitive
  daily signals: an **"N staged changes await your review"** banner (→ `/reviews`, gated on
  `ai.proposals`), your **open blockers** (from the `/me/workspace` payload, with resolve),
  assigned open tasks that are **critical or due within 7 days**, and the decisions to push (owned
  ADRs in `proposed`/`under_discussion`) — plus **agent work waiting on your decision** (each
  gate links to its decision page, §AE4; `gates` in the `/me/today` payload).
- **API:** `GET /api/v1/me/today` + `GET /api/v1/me/workspace` (blockers) +
  `GET /api/v1/proposals?status=open` (review count) — the last two composed client-side.
- **Not built (v2 §M):** PRs awaiting the user's review (needs GitHub PR-metrics, §J6) and
  decision-queue items filtered to the user's components.

---

## Z. Demo / seeded-data mode (local & dev only) **[new]**

A switch (`DEMO_MODE=true`, **never** in production) that makes the whole app explorable from a
single, repository-resident seed dataset — and lets an admin reset/reload it from the UI. It is also
the substrate for browser e2e tests (the seed is extended as features grow). Seed data lives in
`backend/app/services/seed/` (`catalog.py` = the declarative schema, `ecommerce.py` +
`ecommerce_projects.py` = the data, `loader.py` = the build/reset engine).

### Z1. What the seed contains
A single, relatable narrative — a fictional **online retailer** (generic e-commerce, no real
brand; every login, link and repository is a placeholder on `example.com`-style domains). Five
initiatives anyone who has shopped online will recognise — **Checkout Modernization** (a one-page
checkout on top of a payments-provider migration), **Search & Discovery** (search relevance and
personalized recommendations), **Delivery Promise** (real-time inventory and a delivery date
shoppers can trust), **Marketplace Launch** (third-party seller onboarding and payouts) and
**Holiday Peak Readiness** (load tests, a checkout waiting room, storefront performance) — over
**10 fully-populated projects**, two per initiative. The flagship is **One-Page Checkout**.

The org is modelled end to end (§R6): **two teams** (Shopping Experience, Commerce Operations),
each with **pods**, a **director** and a **manager**. Every initiative has its **owners** seated as
`InitiativeLead` rows (technical / product / design, plus a manager seat on the peak programme);
some people own several initiatives, two initiatives span pods, and every project has one owner
and a pod. **Leadership** (a CTO and a CPO — `viewer` logins with the `leadership` function) sits
above with seeded **leadership notes** (§BR) on risks, milestones, decisions and outcomes.

It includes users across **every role** (admin / architect / engineering_manager / engineer /
viewer / member) and **every persona/function** (engineering / product / design / architecture /
management / leadership), so each persona's landing page has content; a cross-functional **team**
(~28 people) with skill tags, timezones, committed hours and **availability** (PTO / on-call /
conferences / split roles). Each project is a scheduled
**WBS** (phases → tasks, dependencies, milestones, holidays) run through the real CPM planner, with
**cross-project hand-offs** inside initiatives (so the cross-project critical path is real), a
**baseline + variance** on the flagship, and **back-dated status history / activity / risk
snapshots** so every time-series view (burndown, Monte-Carlo forecast, DORA + flow, risk timeline)
shows real trends. **Rich content is on every project**: an architecture map, **ADRs** (accepted /
in-discussion with a review thread / proposed / deferred / rejected — populating all four
**decision-queue** buckets, including overdue ones), **fitness functions** + **drift** events (open
and triaged, plus a code-bound project whose scan is due), **specs** + criteria, **risks** (RAID,
project + initiative scope), **blockers**, **outcomes**, **doc references**, **retros** (including
**incident postmortems**), **draft plans**, five **scenarios** (one rich what-if per initiative —
each a full snapshot of the live plan plus a coherent set of edits across tasks, dependencies,
milestones, allocations and availability, in `draft`/`ready` status — so the §T
Compare/Capacity/Gantt/Milestones tabs all show a real delta), two **open change proposals**
in the review queue (§AA — one that reshapes the Payments schedule with edits, a new phase,
dependencies and knock-on shifts past the code-freeze deadline; one for Tracking that only
touches registers and a milestone — staged through the same validation as `propose_changes`,
so both preview and apply cleanly), three demo **connections**, **agent work** (§AE) on
One-Page Checkout and the Payments migration — both with intake on, run through the real
work-queue services as Rahul's agent tokens: a task handed off into review with its plan and
hand-off, a headless worker's open **question** ("which wallets ship at GA?") waiting past its
reminder, a session **working** a task right now, a task **parked** after three sessions gave it
back, and one delegated and ready; Payments then adopted the **agentic-delivery template**
(§AE6), so its delegated cut-over task waits on its predecessors; on the Jira-mirrored flagship a
Jira-owned ticket is delegated too, held back by its open blocker (§AE9); two example
**webhooks**, switched off (§AE10) — **rules** at every scope
(§AE7: workspace guidance and a locked Definition-of-Done item, a team rule per team, a Payments
override of "small PRs", a blocking card-data attestation from its tokenization ADR, and a rule
Search switched off) — and
project state that makes the **alerts** digest fire (deadline miss, overdue milestone,
over-allocation, overdue risk, open blocker, a gate waiting on a person, a parked task) and the
flow board flag **aging** work.

### Z1a. Datasets are pluggable
The loader is generic over a `Dataset` holder (`catalog.py`): a narrative is a pure data module
that builds one, registered by key in `DATASETS` (`seed/__init__.py`). One dataset ships today
(`ecommerce`). `DEMO_DATASET` (env; default `ecommerce`) picks the default — the login screen's
click-to-fill accounts and a plain reseed use it — and an unknown value (e.g. a stale `.env` naming
a dataset from an older release) falls back to the default with a warning instead of breaking demo
mode. When more than one dataset is registered, `/admin/demo` shows a **Dataset** dropdown
(`POST /admin/demo/reseed?dataset=<key>`; an unknown explicit key → 400). The loader silently skips
names it cannot resolve, so `tests/test_demo_seed.py` checks that every cross-reference of every
registered dataset resolves (engineers, tasks, components, milestones, note targets).

### Z2. Reset / reload from the UI *(admin, demo mode)*
- **UI:** sidebar **"Demo data"** (admin only) → **`/admin/demo`**. Shows current row counts + the
  demo logins, with **"Reset & load demo data"** (wipe everything, then rebuild — a **Dataset**
  dropdown picks the narrative when more than one is registered, §Z1a) and **"Clear all data"**
  (wipe to empty). Both keep the acting admin **and** the configured superuser signed in;
  everything else (including other users) is wiped and re-seeded.
- **API:** `GET /api/v1/admin/demo/status` (counts + logins + the default `dataset` and the
  registered `datasets`) · `POST /api/v1/admin/demo/reseed?dataset=` (optional; default
  `DEMO_DATASET`, unknown key → 400) · `POST /api/v1/admin/demo/clear` — all admin-gated **and**
  double-gated on `DEMO_MODE` (they 403 when it is off, so they can never run against prod).
  `GET /api/v1/health` reports `demo_mode`.
- **Login helper:** `GET /api/v1/admin/demo/public` (unauthenticated) lists the demo accounts +
  shared password when demo mode is on; the **login screen** shows them as click-to-fill (empty
  otherwise). Every demo login uses the password `canopy-demo`.

### Z3. Offline connectors (mocked services)
When demo mode is on, any connection whose config carries `demo: true` is served by an **in-process
HTTP mock** (`backend/app/connectors/demo.py`), so **Sync from Jira** (§J3), GitHub PR reads, Drive
doc reads, ADR import, doc harvest, and draft → Jira push (§C10.2) all work with **no real
credentials and no network**. Policy is unchanged (default direct reads/writes); the mock is injected
at the connector's `open_client()` chokepoint. The fixtures match the flagship: a `SHOP` Jira project
(one epic + three stories on an active sprint), the `example-shop/checkout` repository (PRs + a
markdown ADR) and a Drive folder of checkout and payments docs.

### Z4. Not built (deliberate limits)
- Demo mode is **not** a multi-tenant or production feature; it is gated off by default and the
  reset/reseed endpoints refuse to run unless `DEMO_MODE=true`.
- The mock returns a small, fixed fixture set (not a full Jira/GitHub/Drive emulation) — enough to
  exercise every read/sync flow end-to-end, not to fuzz the providers.

---

## Known UI gaps (currently API/MCP-only)
These flows work via the API and the Claude plugin but have no React form yet — candidates for the UI
backlog:
- The **epic doc-field mapping / harvest** setup (§V2/§V3) stays conversational (AI-driven via the
  plugin) — no React wizard (deliberate); the Docs **tab** itself is built (read + add links).
- Project rename/archive/date edits (B4) — the header has the weekend toggle + health/status/tags
  meta bar; renaming/archiving/dates are still API-only.
- Agent work (§AE): **reassigning** a gate to named engineers and **withdrawing** a gate are
  API-only (`POST /gates/{id}/reassign`, `/cancel`); **edit and approve** (a planner's own plan
  revision in one step) isn't offered on the gate page — add a note or request changes instead;
  the per-claim **artifact history** (every plan revision) reads through `GET
  /tasks/{id}/artifacts`, while the panel shows the latest of each.
- *(closed previously: G5 blast radius; Risk (§Q) + portfolio scores (§B1); user/role mgmt (A3) +
  engineer workspace (§M); per-role enforcement (§A3a); drift detection (§N); retros/postmortems
  (§P). Closed prior revision: **CI/observability events + Activity feed** (§J8) with incident
  postmortem auto-open (§P2); the **quality** risk family + **drift-into-risk** + **risk timeline**
  (§Q); **ADR doc-import** UI (G6); **component owner/criticality/tier** (§G1); **`/me/today`** (§M);
  the **decision-deadline nudger** + **PR-to-ADR linker** skills (§L8/§L9); the **Agent Setup** tab
  — self-service agent-token mint/list/revoke + plugin & MCP setup instructions (§A11). Closed this
  revision: **holiday** management (C7) — a `HolidaysEditor` panel on the Gantt tab; **WBS
  parenting** and **dependency type/lag** in the Add-task/Add-dependency forms (C1/C2); **task
  delete** and **dependency delete** from the UI (C1/C1a/C2); the **initiative digest** now
  renders in the UI, not just MCP/API (R5); the **portfolio "needs attention" band** (B1) and a
  matching band on **`/team`** (F1); and non-engineering personas landing on read-first surfaces
  instead of a create-list / admin page (A7). Since closed: **what-if** scheduling (C5) — a What-if
  panel under the Gantt chart. Closed this revision: the **team page** — team board, sprint
  planning, sprint report, delivery settings (§C11); the project **Tracking** tab with the switch
  wizard (§C12), the catalog-driven **Connectors** form (§J1), **Tracker links** (§J9) and
  **Draft plans** finalising into tasks or any tracker (§C10).)*

## Not built (deliberately deferred — with rationale)
- **OIDC/SSO + `HttpOnly`-cookie tokens** (§A1): a substantial auth overhaul; the `Bearer` JWT path
  works and is the safe default. Deferred rather than half-built.
- **Capacity overhaul** (§F2–F5): hours-based allocation, interrupt budget, planned-vs-realized,
  PTO→CPM, skill-task fit — a large model change; allocation stays percent-based.
- **PagerDuty / on-call** (§J7): an external connector with nothing to feed until the capacity
  overhaul lands.
- **GitHub PR-latency metrics** (§J6): needs deep repo crawling (like drift's live path); the
  quality-risk family is fed by §J8 events instead.
- **Agent execution — work queue, stage policy and human gates**: delegating a task to agents,
  claims with leases, the work brief, plan / hand-off / review artifacts on a task, checks and
  human gates at stage transitions, and team/project rules (Definition of Done) are **designed
  in [`AGENT_EXECUTION.md`](./AGENT_EXECUTION.md) and not built**. Today an agent session changes
  work only through the board verbs it is explicitly told to use (§C9.3) and staged proposals
  (§AA); nothing offers it work, tracks which session holds a task, or blocks a stage for a
  person.
- Smaller follow-ups: Slack/email **alert delivery** (I) + **decision SLA notifications** (G3);
  hard-enforced decision **approval gates** (G3, `can_accept` is advisory); connector **RBAC**;
  resource **leveling**; drift **suppression-management UI** + non-Python analysis. *(Nightly
  **risk-snapshot** scheduling is built — arq worker, §Q2. Nightly **drift scans** still need the
  Drift Sentinel agent; a push-webhook that enqueues it is the remaining piece — §N.)*

---

*Maintained alongside the code. See `CLAUDE.md` → "Keeping USER_FLOWS.md in sync".*
