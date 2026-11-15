import type {
  CheckDoc,
  DecisionDoc,
  DeliveryRule,
  Enforcement,
  PipelineRead,
  RuleScope,
  RuleScopeInfo,
  RuleWrite,
  StageColumn,
  StagePolicyDoc,
} from "../api/types";

/**
 * Stage policy and rules in plain language (docs/AGENT_EXECUTION.md §9, §10): the check
 * catalog, the conditions that make a person look, where each scope's policy is edited, and
 * one-line summaries of a column's policy. Pure, so the editor and the summaries share wording
 * and stay unit-tested. The server validates every document again (422 policy_invalid).
 */

export type FactKind = "observed" | "attested";

export interface CheckDef {
  check: string;
  label: string;
  fact: FactKind;
  /** The params the check takes, as the editor asks for them. */
  params?: { name: string; label: string; options?: string[]; number?: boolean }[];
}

export const CHECKS: CheckDef[] = [
  { check: "dependencies_done", label: "Predecessors are done", fact: "observed" },
  { check: "no_open_blockers", label: "No open blockers", fact: "observed" },
  { check: "spec_approved", label: "The spec is approved", fact: "observed" },
  {
    check: "artifact",
    label: "An artifact was recorded this round",
    fact: "observed",
    params: [{ name: "kind", label: "kind", options: ["plan", "handoff", "review", "qa_report"] }],
  },
  { check: "plan_approved", label: "The plan was approved (when it needed to be)", fact: "observed" },
  {
    check: "gate_approved",
    label: "A gate of a kind was approved",
    fact: "observed",
    params: [{ name: "kind", label: "kind", options: ["plan_approval", "handoff_approval", "signoff"] }],
  },
  {
    check: "pr_linked",
    label: "A pull request is linked",
    fact: "observed",
    params: [{ name: "state", label: "state", options: ["", "open", "merged"] }],
  },
  {
    check: "pr_checks",
    label: "The PR's checks pass",
    fact: "observed",
    params: [{ name: "state", label: "state", options: ["passing"] }],
  },
  { check: "pr_approved", label: "Someone other than the requester approved the PR", fact: "observed" },
  {
    check: "pr_size",
    label: "The PR is small",
    fact: "observed",
    params: [{ name: "max_changed_lines", label: "max lines", number: true }],
  },
  {
    check: "verdict",
    label: "A review / QA verdict allows it",
    fact: "attested",
    params: [{ name: "kind", label: "kind", options: ["review", "qa_report"] }],
  },
  { check: "criteria_met", label: "Acceptance criteria are met or waived", fact: "attested" },
  { check: "attestations_complete", label: "The Definition of Done is attested", fact: "attested" },
  {
    check: "distinct_actor",
    label: "A different session than the role's",
    fact: "observed",
    params: [{ name: "role", label: "role" }],
  },
  {
    check: "distinct_issuer",
    label: "A different person than the role's issuer",
    fact: "observed",
    params: [{ name: "role", label: "role" }],
  },
];

const CHECK_BY_NAME = new Map(CHECKS.map((c) => [c.check, c]));

export function checkDef(name: string): CheckDef | undefined {
  return CHECK_BY_NAME.get(name);
}

/** The conditions that make a person approve a plan / hand-off / sign-off (§9.3). */
export const CONDITIONS: { value: string; label: string }[] = [
  { value: "one_way_door", label: "It touches a one-way-door decision or declares a risky change" },
  { value: "high_criticality", label: "It touches a high-criticality component" },
  { value: "unsettled_decision", label: "It touches a decision still under discussion" },
  { value: "no_spec", label: "It has no approved spec with criteria" },
  { value: "low_confidence", label: "The plan's own confidence is low" },
  { value: "large_change", label: "It is larger than the small-batch limits" },
  { value: "probation:5", label: "Fewer than 5 agent tasks are done in the project" },
];

export const APPROVERS: { value: string; label: string }[] = [
  { value: "project_planners", label: "The project's planners" },
  { value: "project_owner", label: "The project's owner" },
  { value: "assignee", label: "The task's assignee" },
  { value: "initiative_leads", label: "The initiative's owners" },
  { value: "team_directors", label: "The team's directors" },
];

export const ENFORCEMENTS: Enforcement[] = ["off", "warn", "block"];

/** Where a pipeline's policies are read and written: the scope its columns come from. */
export function policyPath(
  scope: PipelineRead["scope"],
  ids: { projectId?: number; teamId?: number | null },
): string | null {
  if ((scope === "project" || scope === "tracker") && ids.projectId != null) {
    return `/projects/${ids.projectId}/workflow/policy`;
  }
  if (scope === "team" && ids.teamId != null) return `/teams/${ids.teamId}/workflow/policy`;
  if (scope === "template") return "/workflows/template/policy";
  return null; // the built-in default: nothing stored to edit until the scope has columns
}

export const SCOPE_LABEL: Record<PipelineRead["scope"], string> = {
  project: "this project's own columns",
  team: "the team's shared columns",
  template: "the workspace template",
  default: "the built-in default",
  tracker: "the tracker's statuses (canopy clears moves; the tracker makes them)",
};

/** "worked by implementer · hands off a hand-off" — who works a column. */
export function workedByText(column: Pick<StageColumn, "worked_by" | "hands_off">): string {
  if (!column.worked_by) return "No one works it (a queue)";
  if (column.worked_by === "human") return "People decide here (a decision column)";
  const what = column.hands_off === "review" ? "a review" : column.hands_off === "qa_report" ? "a QA report" : "a hand-off";
  return `Agents work it as ${column.worked_by}, handing off ${what}`;
}

function paramText(value: unknown): string {
  return Array.isArray(value) ? value.map(String).join(" or ") : String(value);
}

function checkLabel(c: CheckDoc): string {
  const def = checkDef(c.check);
  const params = Object.values(c.params ?? {})
    .filter((v) => v !== "" && v != null)
    .map(paramText);
  const base = def?.label ?? c.check;
  return params.length ? `${base} (${params.join(", ")})` : base;
}

/** The entry checks a column enforces, as "blocks: …" / "warns: …" lines. */
export function checksSummary(doc: StagePolicyDoc | null | undefined): string[] {
  const checks = doc?.enter?.checks ?? [];
  const out: string[] = [];
  const blocking = checks.filter((c) => c.enforcement === "block").map(checkLabel);
  const warning = checks.filter((c) => c.enforcement === "warn").map(checkLabel);
  if (blocking.length) out.push(`Blocks without: ${blocking.join("; ")}`);
  if (warning.length) out.push(`Warns without: ${warning.join("; ")}`);
  return out;
}

function conditionsText(when: string | string[] | undefined): string {
  if (when === undefined || when === "always") return "always";
  if (when === "never") return "never";
  const list = Array.isArray(when) ? when : [when];
  return list
    .map((w) => CONDITIONS.find((c) => c.value === w)?.label.toLowerCase() ?? w.replaceAll("_", " "))
    .join(", or ");
}

/** What makes a person look at work in this column. */
export function gateSummary(doc: StagePolicyDoc | null | undefined): string[] {
  if (!doc) return [];
  const out: string[] = [];
  const plan = doc.checkpoints?.plan;
  if (plan) {
    out.push(
      `${plan.required === false ? "A plan is optional" : "A plan is required"}; a person approves it when ${conditionsText(plan.approval_when)}`,
    );
  }
  const handoff = doc.checkpoints?.handoff;
  if (handoff) out.push(`A person approves the hand-off when ${conditionsText(handoff.approval_when ?? handoff.decision?.when)}`);
  if (doc.decision) out.push(decisionText(doc.decision));
  return out;
}

export function decisionText(d: DecisionDoc): string {
  const who = APPROVERS.find((a) => a.value === d.approvers)?.label ?? d.approvers ?? "the project's planners";
  const via = (d.satisfied_by ?? ["canopy"]).filter((s) => s !== "canopy");
  const parts = [`${who} sign off ${conditionsText(d.when) === "always" ? "every task" : `when ${conditionsText(d.when)}`}`];
  if (d.exclude_requester !== false) parts.push("not the requester");
  if (via.length) parts.push(`a ${via.map((v) => (v === "pr_merge" ? "merge" : "PR approval")).join(" or ")} counts`);
  return parts.join(" · ");
}

/** A rule's origin chip text. */
export const ORIGIN_LABEL: Record<RuleScope, string> = {
  workspace: "workspace",
  team: "team",
  project: "project",
};

const SCOPE_RANK: Record<RuleScope, number> = { workspace: 0, team: 1, project: 2 };

/** Is a rule from `origin` inherited by `here` (it comes from a broader scope)? */
export function inheritedFrom(origin: RuleScope, here: RuleScope): boolean {
  return SCOPE_RANK[origin] < SCOPE_RANK[here];
}

/** "Tests added" → "tests-added": a rule key the server accepts (`^[a-z0-9][a-z0-9_.-]*$`). */
export function slugKey(title: string): string {
  return title
    .toLowerCase()
    .replace(/[^a-z0-9_.-]+/g, "-")
    .replace(/^[^a-z0-9]+/, "")
    .replace(/-+$/, "")
    .slice(0, 64);
}

export const RULE_KEY_RE = /^[a-z0-9][a-z0-9_.-]*$/;

/** "a, b ,, c" → ["a", "b", "c"] (deduplicated, order kept). */
export function parseList(text: string, lower = false): string[] {
  const out: string[] = [];
  for (const raw of text.split(",")) {
    const item = lower ? raw.trim().toLowerCase() : raw.trim();
    if (item && !out.includes(item)) out.push(item);
  }
  return out;
}

/** Who and what a rule is for, in a few words. */
export function ruleReachText(rule: Pick<DeliveryRule, "roles" | "selector">): string {
  const parts = [rule.roles.length ? `for ${rule.roles.join(", ")}` : "for every role"];
  const sel = rule.selector ?? {};
  if (sel.tags?.length) parts.push(`tagged ${sel.tags.join(", ")}`);
  if (sel.components?.length) {
    parts.push(`${sel.components.length} component${sel.components.length === 1 ? "" : "s"}`);
  }
  if (sel.paths?.length) parts.push(`paths ${sel.paths.join(", ")}`);
  return parts.join(" · ");
}

/** What a rule does to a hand-off: guidance is read; an attestation must be attested. */
export function ruleEffectText(kind: DeliveryRule["kind"], enforcement: Enforcement): string {
  if (kind === "guidance") return "Guidance in the brief";
  if (enforcement === "block") return "Definition of Done · a hand-off without it is refused";
  if (enforcement === "warn") return "Definition of Done · a hand-off without it is flagged";
  return "Definition of Done · not checked";
}

/** The scopes a person may add a rule to, broadest first. */
export function addableScopes(scopes: RuleScopeInfo[] | undefined): RuleScopeInfo[] {
  return (scopes ?? []).filter((s) => s.can_edit);
}

export interface RuleDraft {
  scope: string; // "<level>:<id>"
  key: string;
  title: string;
  body: string;
  kind: DeliveryRule["kind"];
  enforcement: Enforcement;
  roles: string;
  tags: string;
  paths: string;
  locked: boolean;
  sourceAdrId: string;
  sourceUrl: string;
}

export function emptyDraft(scope: RuleScopeInfo | undefined): RuleDraft {
  return {
    scope: scope ? `${scope.scope_level}:${scope.scope_id}` : "",
    key: "",
    title: "",
    body: "",
    kind: "guidance",
    enforcement: "warn",
    roles: "",
    tags: "",
    paths: "",
    locked: false,
    sourceAdrId: "",
    sourceUrl: "",
  };
}

/** A draft from an existing rule — to edit it, or (with `scope`) to override it lower down. */
export function draftFrom(rule: DeliveryRule, scope?: RuleScopeInfo): RuleDraft {
  return {
    scope: scope ? `${scope.scope_level}:${scope.scope_id}` : `${rule.scope_level}:${rule.scope_id}`,
    key: rule.key,
    title: rule.title,
    body: rule.body,
    kind: rule.kind,
    enforcement: rule.enforcement,
    roles: rule.roles.join(", "),
    tags: (rule.selector?.tags ?? []).join(", "),
    paths: (rule.selector?.paths ?? []).join(", "),
    locked: scope ? false : rule.locked,
    sourceAdrId: rule.source_adr_id != null ? String(rule.source_adr_id) : "",
    sourceUrl: rule.source_url ?? "",
  };
}

/** The request body for a draft (`components` keeps what the rule had: no picker yet). */
export function ruleBody(draft: RuleDraft, components: number[] = []): RuleWrite {
  const [level, id] = draft.scope.split(":");
  return {
    scope_level: level as RuleScope,
    scope_id: Number(id),
    key: draft.key.trim(),
    title: draft.title.trim(),
    body: draft.body.trim(),
    kind: draft.kind,
    roles: parseList(draft.roles, true),
    selector: { tags: parseList(draft.tags, true), components, paths: parseList(draft.paths) },
    enforcement: draft.kind === "guidance" ? "warn" : draft.enforcement,
    locked: level === "project" ? false : draft.locked,
    source_adr_id: draft.sourceAdrId ? Number(draft.sourceAdrId) : null,
    source_url: draft.sourceUrl.trim() || null,
  };
}

/** Why a draft can't be saved yet, or null. */
export function draftProblem(draft: RuleDraft): string | null {
  if (!draft.scope) return "Pick where the rule lives";
  if (!RULE_KEY_RE.test(draft.key.trim())) {
    return "The key is lowercase letters, digits, dots, dashes or underscores";
  }
  if (!draft.title.trim()) return "Give the rule a title";
  if (draft.body.length > 800) return "Keep the body under 800 characters";
  return null;
}

/** "45%" for a 0..1 share; "—" when unknown. */
export function percent(value: number | null | undefined): string {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}

/** "3.5 h" / "2 d" for hours; "—" when unknown. */
export function hoursText(value: number | null | undefined): string {
  if (value == null) return "—";
  if (value < 48) return `${Math.round(value * 10) / 10} h`;
  return `${Math.round(value / 24)} d`;
}

/** One check from a gate's evidence (`gate.evidence.results`, the evaluation that raised it). */
export interface EvidenceCheck {
  check: string;
  label: string;
  enforcement: Enforcement;
  fact: FactKind;
  passed: boolean;
  message: string;
}

function asCheck(raw: unknown): EvidenceCheck | null {
  if (!raw || typeof raw !== "object") return null;
  const r = raw as Record<string, unknown>;
  if (typeof r.check !== "string" || typeof r.passed !== "boolean") return null;
  const enforcement = r.enforcement === "block" || r.enforcement === "off" ? r.enforcement : "warn";
  // The catalog's plain wording first: the server's label is the check's key and params.
  return {
    check: r.check,
    label: checkDef(r.check)?.label ?? (typeof r.label === "string" ? r.label : r.check),
    enforcement,
    fact: r.fact === "attested" ? "attested" : r.fact === "observed" ? "observed" : (checkDef(r.check)?.fact ?? "observed"),
    passed: r.passed,
    message: typeof r.message === "string" ? r.message : "",
  };
}

/** A gate's checks split by who vouches for them: what canopy saw for itself (CI, the PR, its
 *  own records) and what a session stated (verdicts, criteria, attestations) — so a reviewer
 *  knows which facts to spot-check. Null when the gate carries no evaluation. */
export function evidenceChecks(
  evidence: Record<string, unknown> | null | undefined,
): { observed: EvidenceCheck[]; attested: EvidenceCheck[] } | null {
  const results = evidence?.results;
  if (!Array.isArray(results) || results.length === 0) return null;
  const checks = results.map(asCheck).filter((c): c is EvidenceCheck => c !== null);
  if (checks.length === 0) return null;
  return {
    observed: checks.filter((c) => c.fact === "observed"),
    attested: checks.filter((c) => c.fact === "attested"),
  };
}
