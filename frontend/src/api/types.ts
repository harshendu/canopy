export type TaskType = "task" | "milestone" | "summary";
export type DependencyType = "FS" | "SS" | "FF" | "SF";
export type ADRStatus =
  | "proposed"
  | "under_discussion"
  | "accepted"
  | "rejected"
  | "superseded"
  | "deprecated"
  | "deferred";
export type Reversibility = "one_way" | "two_way";
export type ADRCommentKind = "comment" | "approve" | "request_changes" | "reject";
export type DecisionRule = "owner_decides" | "consensus" | "lazy_consensus";
/** A connection's provider: "github", "gdrive", or a work tracker's key as `GET /meta/trackers`
 *  lists it ("jira", "linear", "generic", …) — label it from that catalog, never assume Jira. */
export type Provider = string;

// --- Delivery metadata ---
export type ProjectHealth = "on_track" | "at_risk" | "off_track";
export type RiskScope = "task" | "project" | "initiative";
export type RiskCategory =
  | "schedule"
  | "scope"
  | "technical"
  | "resource"
  | "external"
  | "quality"
  | "security";
export type RiskStatus = "open" | "mitigating" | "accepted" | "resolved" | "occurred";
export type RiskGrade = "low" | "medium" | "high";
export type BlockerCategory = "dependency" | "resource" | "decision" | "external" | "technical";
export type BlockerSeverity = "low" | "medium" | "high" | "critical";

export interface Project {
  id: number;
  key: string;
  name: string;
  description: string | null;
  initiative_id: number | null;
  /** The pod that runs the project and its single owner (USER_FLOWS §R6). */
  pod_id?: number | null;
  owner_engineer_id?: number | null;
  start_date: string | null;
  target_date: string | null;
  archived: boolean;
  skip_weekends: boolean;
  decision_rule: DecisionRule;
  decision_sla_hours: number;
  tags: string[];
  health: ProjectHealth | null;
  status_note: string | null;
  status_updated_at: string | null;
  /** native: canopy owns every status; mirrored: a bound tracker owns the work it knows (§C12). */
  tracking_mode?: TrackingMode;
  task_key_prefix?: string | null;
  /** Whether delegated tasks are offered to agents (docs/AGENT_EXECUTION.md §6.1). */
  agent_intake?: AgentIntake;
}

export interface Initiative {
  id: number;
  key: string;
  name: string;
  outcome_statement: string | null;
  start_date: string | null;
  target_date: string | null;
  owner_engineer_id: number | null;
  /** The team (product/platform group) the initiative belongs to (§R6). */
  team_id?: number | null;
  archived: boolean;
  tags: string[];
  health: ProjectHealth | null;
  status_note: string | null;
  status_updated_at: string | null;
}

export interface CriticalPathNode {
  task_id: number;
  name: string;
  project_id: number;
  project_key: string;
  es: number;
  ef: number;
  duration: number;
}

export interface CriticalPathHandoff {
  predecessor_id: number;
  successor_id: number;
  from_project_key: string;
  to_project_key: string;
}

export interface InitiativeCriticalPath {
  initiative_id: number;
  total_working_days: number;
  spans_projects: boolean;
  tasks: CriticalPathNode[];
  handoffs: CriticalPathHandoff[];
}

export interface InitiativeRollup {
  initiative: Initiative;
  projects: ProjectSummary[];
  total_tasks: number;
  completed_tasks: number;
  avg_percent_complete: number;
  project_end: string | null;
  risk_score: number;
  risk_level: string;
  drift_score: number;
  drift_level: string;
  open_decisions: number;
  on_track: boolean | null;
  /** Ownership (§R6): may the current user plan here, and who leads it. */
  can_edit: boolean;
  leads: InitiativeLead[];
  team_id: number | null;
  team_name: string | null;
  /** Pods the initiative spans (derived from its projects' pods). */
  pods: string[];
}

/** Manage-by-exception weekly roll-up (§R5) — leads with `attention`, the exception list. */
export interface InitiativeDigest {
  initiative_id: number;
  name: string;
  generated_on: string;
  headline: string;
  on_track: boolean | null;
  risk_level: string;
  drift_level: string;
  p85_date: string | null;
  open_blockers: number;
  open_decisions: number;
  attention: string[];
  outcomes: string[];
  markdown: string;
}

export interface RiskItem {
  id: number;
  scope_level: RiskScope;
  scope_id: number;
  title: string;
  description: string | null;
  category: RiskCategory;
  probability: RiskGrade;
  impact: RiskGrade;
  status: RiskStatus;
  owner_engineer_id: number | null;
  mitigation: string | null;
  contingency: string | null;
  target_resolution_date: string | null;
  resolved_at: string | null;
  created_at: string;
  probability_value: number;
  impact_value: number;
  exposure: number;
  exposure_level: RiskLevel;
}

export interface RiskItemCreate {
  scope_level: RiskScope;
  scope_id: number;
  title: string;
  description?: string | null;
  category?: RiskCategory;
  probability?: RiskGrade;
  impact?: RiskGrade;
  status?: RiskStatus;
  owner_engineer_id?: number | null;
  mitigation?: string | null;
  contingency?: string | null;
  target_resolution_date?: string | null;
}

export interface Task {
  id: number;
  project_id: number;
  parent_id: number | null;
  name: string;
  description: string | null;
  type: TaskType;
  start: string | null;
  end: string | null;
  duration: number;
  percent_complete: number;
  baseline_start: string | null;
  baseline_end: string | null;
  is_critical: boolean;
  total_float: number;
  status: string | null;
  /** What the status means — every flow metric reads this, never the display name (§C9). */
  status_category: StatusCategory | null;
  /** "canopy", or the provider key of the tracker that owns this task's status (e.g. "jira").
   *  Only canopy-owned status changes in canopy — via a move, never a PATCH. */
  status_owner: string;
  /** Human key: `<prefix>-<n>` for canopy-owned work, the tracker's key when mirrored. */
  key: string | null;
  /** The sprint the task is planned into (§C11) — changed via the sprint membership
   *  endpoints, never a PATCH. */
  sprint_id: number | null;
  /** Sprint planning size (a team estimating in points plans with it). PATCH-able. */
  story_points: number | null;
  deadline: string | null;
  assignee_engineer_id: number | null;
  tags: string[];
  estimate_optimistic: number | null;
  estimate_likely: number | null;
  estimate_pessimistic: number | null;
  pert_mean: number | null;
  estimate_spread: number | null;
  /** "agent" when a person delegated the task to the agent work queue; they stay accountable. */
  delegation?: Delegation | null;
  delegated_at?: string | null;
  /** The claim of the session working it right now, if any. */
  active_claim_id?: number | null;
  implements_adr_id?: number | null;
}

export interface GanttTask {
  id: number;
  text: string;
  start_date: string | null;
  end_date: string | null;
  baseline_start: string | null;
  baseline_end: string | null;
  deadline: string | null;
  duration: number;
  progress: number;
  parent: number;
  type: TaskType;
  is_critical: boolean;
  total_float: number;
  assignee_engineer_id: number | null;
  assignee_name: string | null;
}

export interface Milestone {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  target_date: string | null;
  status: string;
}

export interface Holiday {
  id: number;
  project_id: number;
  day: string;
  name: string | null;
}

export interface GanttLink {
  id: number;
  source: number;
  target: number;
  type: DependencyType;
  lag: number;
}

export interface GanttResponse {
  project_id: number;
  tasks: GanttTask[];
  links: GanttLink[];
}

export interface ReplanResult {
  project_id: number;
  scheduled_tasks: number;
  critical_path: number[];
  project_end: string | null;
  deadline_violations: number[];
}

export interface Baseline {
  id: number;
  project_id: number;
  note: string | null;
  task_count: number;
  project_end: string | null;
  created_at: string;
}

export interface ForecastResponse {
  scope: "project" | "initiative";
  id: number;
  sufficient: boolean;
  reason: string | null;
  remaining_items: number;
  history_weeks: number;
  trials: number;
  p50_weeks: number | null;
  p85_weeks: number | null;
  p50_date: string | null;
  p85_date: string | null;
}

export interface Connection {
  id: number;
  provider: Provider;
  name: string;
  config: Record<string, unknown>;
  watermark: string | null;
  active: boolean;
  authorized: boolean;
  // Per-user SSO (Phase 2): whether this provider permits per-user connect (admin policy),
  // and whether the current user has connected their own account to this connection.
  allow_user_connect: boolean;
  user_connected: boolean;
  // Integration policy (Phase 1/3): so the UI can show when reads/writes are MCP-managed.
  read_strategy: ReadStrategy;
  write_strategy: WriteStrategy;
}

// Per-provider integration policy (admin-chosen). See backend app/services/integration_policy.py.
export type ReadStrategy = "direct" | "mcp" | "file";
export type WriteStrategy = "direct" | "mcp" | "disabled";

export interface IntegrationSetting {
  provider: Provider;
  read_strategy: ReadStrategy;
  write_strategy: WriteStrategy;
  allow_user_connect: boolean;
}

export interface ADR {
  id: number;
  project_id: number;
  number: number;
  title: string;
  status: ADRStatus;
  context: string | null;
  decision: string | null;
  consequences: string | null;
  alternatives: string[];
  reversibility: Reversibility | null;
  decision_owner_id: number | null;
  proposed_by_id: number | null;
  decide_by: string | null;
  rfc_url: string | null;
  supersedes_id: number | null;
  pr_links: string[];
  component_ids: number[];
  stakeholder_ids: number[];
}

export interface ADRComment {
  id: number;
  adr_id: number;
  engineer_id: number | null;
  author_name: string | null;
  body: string;
  kind: ADRCommentKind;
  created_at: string;
}

export interface ReviewSummary {
  required: number;
  approved: number;
  changes_requested: number;
  rejected: number;
  pending: number;
  can_accept: boolean;
  /** Advisory: every design doc the decision rests on (basis) or waits for (gate) is approved. */
  docs_ready?: boolean;
  docs_pending?: string[];
}

export interface FitnessFunction {
  id: number;
  adr_id: number;
  kind: string; // forbid | require
  source_component_id: number;
  target_component_id: number;
  description: string | null;
}

export interface ADRDetail extends ADR {
  comments: ADRComment[];
  review: ReviewSummary;
  fitness_functions: FitnessFunction[];
}

export interface DecisionQueueItem {
  id: number;
  project_id: number;
  number: number;
  title: string;
  status: ADRStatus;
  bucket: string; // needs_triage | stuck | discussing | deferred_soon
  reason: string;
  overdue: boolean;
  decide_by: string | null;
  age_hours: number;
}

export interface DecisionQueueResponse {
  items: DecisionQueueItem[];
}

export interface Component {
  id: number;
  project_id: number;
  name: string;
  kind: string;
  description: string | null;
  repo_url: string | null;
  owner_engineer_id: number | null;
  criticality: string | null;
  tier: string | null;
  observability_url: string | null;
}

export interface ImpactResponse {
  adr_id: number;
  direct_component_ids: number[];
  downstream_component_ids: number[];
}

/** Decision-to-code traceability (PROPOSED_FLOWS §T): the verdict is computed, never stored. */
export type TraceVerdict =
  | "retired"
  | "pending"
  | "violated"
  | "unimplemented"
  | "at_risk"
  | "no_linked_work"
  | "in_progress"
  | "honored";

export interface TracedTask {
  task_id: number;
  key: string | null;
  name: string;
  status: string | null;
  done: boolean;
  implements: boolean;
  governed: boolean;
}

export interface TracedPullRequest {
  task_id: number | null;
  repo: string;
  number: number;
  url: string | null;
  state: string;
  merged: boolean;
  checks_state: string | null;
  review_decision: string | null;
}

export interface TracedReview {
  task_id: number;
  artifact_id: number;
  verdict: string | null;
  checked: boolean;
}

export interface TracedFitness {
  fitness_id: number;
  kind: string;
  source: string;
  target: string;
  description: string | null;
  violated: boolean;
}

export interface TracedDrift {
  drift_id: number;
  kind: string;
  summary: string;
}

export interface DecisionTrace {
  adr_id: number;
  number: number;
  title: string;
  status: string;
  reversibility: string | null;
  verdict: TraceVerdict;
  reason: string;
  components: string[];
  tasks: TracedTask[];
  pull_requests: TracedPullRequest[];
  reviews: TracedReview[];
  fitness: TracedFitness[];
  drift: TracedDrift[];
}

export interface TraceLedgerRow {
  adr_id: number;
  number: number;
  title: string;
  status: string;
  verdict: TraceVerdict;
  reason: string;
  tasks: number;
  implementing: number;
  done: number;
  prs: number;
  merged: number;
  fitness: number;
  violated: number;
  reviews_checked: number;
  open_drift: number;
}

export interface ComponentLink {
  id: number;
  source_id: number;
  target_id: number;
  kind: string;
}

export interface BurndownPoint {
  week: string;
  total: number;
  completed: number;
  remaining: number;
}

export interface BurndownResponse {
  project_id: number;
  points: BurndownPoint[];
}

export interface CapacityRow {
  engineer_id: number;
  engineer_name: string;
  cells: Record<string, number>;
  projects?: string[]; // contributing project keys (org-wide view)
  availability?: Record<string, number>; // week ISO -> capacity factor (<1 = reduced)
}

export interface CapacityResponse {
  project_id: number | null; // null = org-wide
  weeks: string[];
  rows: CapacityRow[];
}

export interface ProjectSummary {
  id: number;
  key: string;
  name: string;
  total_tasks: number;
  completed_tasks: number;
  avg_percent_complete: number;
  critical_tasks: number;
  project_end: string | null;
  target_date: string | null;
  risk_score: number;
  risk_level: RiskLevel;
  drift_score: number;
  drift_level: RiskLevel;
  tags: string[];
  health: ProjectHealth | null;
  status_note: string | null;
  open_risks: number;
  pod_id?: number | null;
  pod_name?: string | null;
  owner_engineer_id?: number | null;
  owner_name?: string | null;
}

export interface CodeBinding {
  id: number;
  component_id: number;
  connection_id: number | null;
  repo: string | null;
  path_glob: string;
  module_prefix: string | null;
}

export interface DriftEvent {
  id: number;
  project_id: number;
  kind: string;
  rule_key: string;
  summary: string;
  detail: string | null;
  suspected_cause: string | null;
  affected_component_ids: number[];
  status: string;
}

export interface DriftResponse {
  project_id: number;
  score: number;
  level: RiskLevel;
  events: DriftEvent[];
  last_scanned_at: string | null;
  scan_due: boolean;
}

export type RiskLevel = "low" | "moderate" | "high" | "critical";

export interface RiskIndicator {
  key: string;
  label: string;
  score: number;
  summary: string;
  details: string[];
}

export interface RiskFamily {
  key: string;
  label: string;
  available: boolean;
  score: number;
  weight: number;
  indicators: RiskIndicator[];
}

export interface RiskMitigation {
  id: number;
  project_id: number;
  indicator_key: string;
  note: string;
  owner_engineer_id: number | null;
  check_in: string | null;
  resolved: boolean;
}

export interface RiskResponse {
  project_id: number;
  score: number;
  level: RiskLevel;
  confidence: "high" | "low";
  confidence_note: string;
  families: RiskFamily[];
  mitigations: RiskMitigation[];
}

export interface RiskSnapshot {
  id: number;
  project_id: number;
  score: number;
  level: RiskLevel;
  created_at: string;
}

export interface PortfolioResponse {
  projects: ProjectSummary[];
}

export interface Role {
  id: number;
  name: string;
}

export interface Engineer {
  id: number;
  name: string;
  email: string | null;
  title: string | null;
  role_id: number | null;
  active: boolean;
  user_id: number | null;
  skill_tags: string[];
  github_login: string | null;
  timezone: string | null;
  committed_hours_per_week: number | null;
}

export type UserRole =
  | "admin"
  | "architect"
  | "engineering_manager"
  | "engineer"
  | "viewer"
  | "member";

export type UserFunction =
  | "engineering"
  | "product"
  | "design"
  | "architecture"
  | "management"
  | "leadership";

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  function: UserFunction;
  is_active: boolean;
  /** Where this person keeps frozen copies of approved design docs (§V9). */
  doc_snapshot_store?: "repo" | "drive" | null;
}

export interface Token {
  access_token: string;
  token_type?: string;
}

/** The effective feature map every client reads to hide gated surfaces (GET /features). */
export interface FeatureMap {
  features: Record<string, boolean>;
}

/** One feature gate row on the admin panel (GET/PATCH /admin/features). */
export interface FeatureGate {
  key: string;
  label: string;
  description: string;
  group: string | null;
  enabled: boolean;
  effective: boolean;
}

/** The active session: the effective (possibly impersonated) user plus, when an admin is
 *  impersonating, the real admin behind it. */
export interface SessionInfo {
  user: User;
  impersonator: User | null;
  scope?: "full" | "agent";
  /** For an agent token: what it is narrowed to (null for a person's own session). */
  agent_token?: AgentTokenScope | null;
}

/** What an agent token is narrowed to — empty lists mean "whatever the issuer may do". */
export interface AgentTokenScope {
  id: number;
  label: string;
  roles: string[];
  project_ids: number[];
  max_active_claims: number;
}

// --- Agent tokens (Agent Setup tab: mint a bounded token for Claude / the MCP server, §A6) ---
export interface AgentTokenRequest {
  label?: string | null;
  expires_minutes?: number | null;
  /** The agent roles it may claim work as, and the projects it may work in (empty = any). */
  roles?: string[];
  project_ids?: number[];
  max_active_claims?: number | null;
}

/** A freshly minted token — the only time `access_token` (the secret) is returned. */
export interface AgentToken {
  access_token: string;
  token_type?: string;
  scope: string;
  id: number;
  label: string;
  expires_minutes: number;
  expires_at: string;
  roles?: string[];
  project_ids?: number[];
  max_active_claims?: number;
}

/** A minted token as listed later — metadata only, never the secret. */
export interface AgentTokenInfo {
  id: number;
  label: string;
  scope: string;
  issued_at: string;
  expires_at: string;
  revoked_at: string | null;
  status: "active" | "expired" | "revoked";
  roles?: string[];
  project_ids?: number[];
  max_active_claims?: number;
  last_used_at?: string | null;
}

/** Non-secret instance metadata (GET /api/v1/meta) — drives the Agent Setup snippets so a fork
 *  or self-hosted deployment shows its own repo/marketplace, not the upstream default. */
export interface SetupMeta {
  project_name: string;
  plugin_marketplace_ref: string;
  plugin_repo_url: string;
  plugin_mcp_server_path: string;
}

// --- Demo / seeded-data mode (local & dev only) ---
export interface DemoAccount {
  email: string;
  full_name: string;
  role: string;
  function: string;
}

export interface DemoDataset {
  key: string;
  name: string;
  description: string;
}

export interface DemoStatus {
  demo_mode: boolean;
  seeded: boolean;
  counts: Record<string, number>;
  password: string | null;
  accounts: DemoAccount[];
  /** The default dataset key (`DEMO_DATASET`) — what the login screen's accounts come from. */
  dataset: string | null;
  datasets: DemoDataset[];
}

export interface DemoPublic {
  demo_mode: boolean;
  password: string | null;
  accounts: DemoAccount[];
}

export type ActivityKind = "deploy" | "build_failure" | "incident_open" | "incident_close";

export interface ActivityEvent {
  id: number;
  project_id: number;
  kind: string;
  summary: string;
  component_id: number | null;
  source: string;
  reference: string | null;
  created_at: string;
}

export type RetrospectiveKind = "project_retro" | "incident_postmortem";

export interface Retrospective {
  id: number;
  project_id: number;
  kind: RetrospectiveKind;
  title: string;
  body: string | null;
  status: string;
  affected_component_ids: number[];
}

export interface RetrospectiveComment {
  id: number;
  retrospective_id: number;
  engineer_id: number | null;
  author_name: string | null;
  body: string;
  created_at: string;
}

export interface RetrospectiveDetail extends Retrospective {
  comments: RetrospectiveComment[];
}

// --- Kanban board, moves + workflows (USER_FLOWS §C9) ---
/** What a status means: `done` is throughput, `cancelled` leaves WIP but never counts as
 *  throughput, `in_progress` is started work, `todo` is not started. */
export type StatusCategory = "todo" | "in_progress" | "done" | "cancelled";
/** `warn` lets a move into a full column through (with a warning); `block` refuses it. */
export type WipEnforcement = "off" | "warn" | "block";
/** `native`: canopy owns every task's status; `mirrored`: a tracker owns the tasks it knows. */
export type TrackingMode = "native" | "mirrored";

/** A card. The fields after `aging` are optional: the scenario board renders a projection
 *  that may omit them (the live board always sends them — see `lib/board.ts:normalizeBoard`). */
export interface BoardTaskItem {
  id: number;
  name: string;
  status: string;
  assignee_engineer_id: number | null;
  is_done: boolean;
  age_days: number;
  aging: boolean;
  project_id?: number | null;
  key?: string | null;
  status_category?: StatusCategory | null;
  /** "canopy", or the provider key of the tracker that owns this card's status. */
  status_owner?: string;
  /** The card's status can be changed in canopy (it is canopy-owned). */
  movable?: boolean;
  /** The tracker item behind a mirrored card. */
  external_url?: string | null;
  rank?: number;
  parent_id?: number | null;
  blocked?: boolean;
  is_critical?: boolean;
  deadline?: string | null;
  tags?: string[];
  sprint_id?: number | null;
  story_points?: number | null;
  /** Working days — the estimate of teams that size sprints in days. */
  duration?: number | null;
  /** Agent work (docs/AGENT_EXECUTION.md §16): delegated to the queue, the session working it,
   *  the gate holding it for a person, and whether canopy parked it. */
  delegation?: Delegation | null;
  claim?: BoardClaim | null;
  gate?: BoardGate | null;
  parked?: boolean;
  /** A mirrored card canopy cleared to move: the status its tracker should show next (§17). */
  awaiting_move?: string | null;
}

/** The session working a card. */
export interface BoardClaim {
  id: number;
  role: string;
  label: string | null;
  since: string;
  heartbeat_age_s: number;
}

/** The open gate holding a card for a person. */
export interface BoardGate {
  id: number;
  kind: GateKind;
  origin: GateOrigin;
  parked: boolean;
  title: string;
  age_hours: number;
}

/** A column: the workflow's columns arrive in order, empty ones included. `in_workflow=false`
 *  marks an extra column for a status the workflow doesn't name (e.g. a mirrored status). */
export interface BoardLane {
  status: string;
  is_done: boolean;
  /** Open cards in this column on this board. */
  wip: number;
  tasks: BoardTaskItem[];
  category?: StatusCategory | null;
  position?: number;
  wip_limit?: number | null;
  /** Open cards in this column across the WIP scope (every project sharing the columns, e.g.
   *  the team's) — more than `wip` when the board shows only part of it (one project of a
   *  team, a sprint, a pod). The limit is judged on this when set. */
  scope_wip?: number | null;
  over_limit?: boolean;
  in_workflow?: boolean;
  /** Who works the column: an agent role, "human" (a decision column), or none. */
  worked_by?: string | null;
}

/** What the caller may do on the board. */
export interface BoardViewer {
  /** May move any canopy-owned card and edit the workflow. */
  can_plan: boolean;
  /** May move cards assigned to this engineer, or pull an unassigned one. */
  engineer_id: number | null;
  /** Feature `tracking.native` (canopy-owned status) is on. */
  native_enabled: boolean;
}

export interface BoardResponse {
  /** 0 on a team board (cards then carry their own `project_id`). */
  project_id: number;
  lanes: BoardLane[];
  cycle_time_p85_days: number | null;
  aging_count: number;
  mode?: TrackingMode;
  wip_enforcement?: WipEnforcement;
  viewer?: BoardViewer | null;
  /** Set on a team board. */
  team_id?: number | null;
  /** The one sprint the board shows (`?sprint=<id>`, or `active` with a single active sprint). */
  sprint_id?: number | null;
  /** The delivery method in effect for these cards' team (§C11). */
  delivery_method?: DeliveryMethod;
}

// --- Delivery methods + sprints (USER_FLOWS §C11) ---
/** How a team runs its work across all its projects. */
export type DeliveryMethod = "kanban" | "sprint" | "both";
/** What sprint sizes are counted in: story points, task duration (days) or a task count. */
export type EstimateUnit = "points" | "days" | "count";
export type SprintState = "planned" | "active" | "completed";

export interface TeamDelivery {
  team_id: number;
  /** What the team chose. */
  delivery_method: DeliveryMethod;
  /** What applies — kanban while the `tracking.sprints` feature is off. */
  effective_method: DeliveryMethod;
  sprint_length_days: number;
  estimate_unit: EstimateUnit;
  sprints_enabled: boolean;
  /** The caller may change these settings (the team's directors/managers, or an admin). */
  can_manage: boolean;
  active_sprint_id: number | null;
}

export interface TeamDeliveryUpdate {
  delivery_method?: DeliveryMethod;
  sprint_length_days?: number;
  estimate_unit?: EstimateUnit;
}

export interface Sprint {
  id: number;
  team_id: number;
  pod_id: number | null;
  name: string;
  goal: string | null;
  start_date: string | null;
  end_date: string | null;
  state: SprintState;
  /** "canopy", or the tracker it is mirrored from (then read-only). */
  owner: string;
  estimate_unit: string | null;
  /** Captured when the sprint starts / completes. */
  committed: number | null;
  completed: number | null;
  started_at: string | null;
  completed_at: string | null;
  /** Live counts over the current members, in `unit`. */
  task_count: number;
  done_count: number;
  scope: number;
  done: number;
  unit: EstimateUnit;
}

export interface SprintCreate {
  name?: string | null;
  goal?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  pod_id?: number | null;
}

export interface SprintUpdate {
  name?: string;
  goal?: string | null;
  start_date?: string | null;
  end_date?: string | null;
}

export interface SprintCompleteRequest {
  /** Where unfinished work goes. */
  carry_over: "next" | "backlog";
  next_sprint_id?: number | null;
}

export interface EngineerCapacity {
  engineer_id: number;
  name: string;
  person_days: number;
}

export interface SprintCapacity {
  /** Allocated capacity over the sprint's working days. */
  person_days: number;
  engineers: EngineerCapacity[];
  /** The team's mean completed estimate per sprint. */
  velocity_mean: number | null;
  /** The members' open estimate. */
  committed: number;
  unit: EstimateUnit;
  /** Planned beyond capacity — warns, never blocks; null when there is nothing to compare. */
  over_capacity: boolean | null;
}

export interface SprintDetail extends Sprint {
  tasks: Task[];
  capacity: SprintCapacity | null;
}

export interface SprintBurndownDay {
  day: string;
  remaining: number;
  ideal: number;
  /** Estimate that joined after the start, cumulative to this day. */
  scope_added: number;
}

export interface SprintReport {
  sprint: Sprint;
  unit: EstimateUnit;
  /** One row per day from the start to today (or the end). */
  burndown: SprintBurndownDay[];
  committed: number;
  completed: number;
  scope_added: number;
  scope_removed: number;
  carried_over: number;
  /** completed ÷ committed. */
  reliability: number | null;
}

export interface VelocityPoint {
  sprint_id: number;
  name: string;
  end_date: string | null;
  committed: number;
  completed: number;
  reliability: number | null;
}

export interface SprintForecast {
  sufficient: boolean;
  remaining: number;
  history_sprints: number;
  p50_sprints: number | null;
  p85_sprints: number | null;
  p50_date: string | null;
  p85_date: string | null;
  reason: string | null;
}

/** Team-level only — never per engineer. */
export interface Velocity {
  team_id: number;
  unit: EstimateUnit;
  /** Completed sprints, oldest first. */
  points: VelocityPoint[];
  mean: number | null;
  low: number | null;
  high: number | null;
  mean_reliability: number | null;
  sufficient: boolean;
  reason: string | null;
  forecast: SprintForecast;
}

/** An active sprint the caller has work in, with just their tasks (`/me`). */
export interface MySprint {
  sprint: Sprint;
  tasks: Task[];
}

/** `POST /tasks/{id}/move`: omit `to_status` to only reorder. Placement is between
 *  `after_task_id` and `before_task_id` (either may be omitted), else the `position` end. */
export interface TaskMoveRequest {
  to_status?: string;
  after_task_id?: number;
  before_task_id?: number;
  position?: "top" | "bottom";
  /** Guards a lost update: 409 `stale` when the card's status no longer matches. */
  expected_status?: string;
}

export interface TaskMoveResponse {
  task: Task;
  changed: boolean;
  /** e.g. `wip_limit_exceeded` (enforcement `warn` let an over-limit move through). */
  warnings: string[];
}

/** Where a workflow's columns are defined. `tracker`: a mirrored project's columns are its
 *  tracker's statuses (read-only in canopy — a PUT is 409 `workflow_externally_owned`). */
export type WorkflowScope = "project" | "team" | "template" | "default" | "tracker";

export interface WorkflowColumn {
  name: string;
  category: StatusCategory;
  position: number;
  wip_limit: number | null;
}

export interface WorkflowRead {
  id: number | null;
  scope: WorkflowScope;
  team_id: number | null;
  project_id: number | null;
  name: string;
  wip_enforcement: WipEnforcement;
  /** True when the asked-for project/team has no workflow of its own and uses this one. */
  inherited: boolean;
  columns: WorkflowColumn[];
}

export interface WorkflowColumnInput {
  name: string;
  category: StatusCategory;
  wip_limit?: number | null;
  /** Set to rename an existing column; its canopy-owned tasks follow it. */
  previous_name?: string | null;
}

export interface WorkflowUpdate {
  name: string;
  wip_enforcement: WipEnforcement;
  columns: WorkflowColumnInput[];
  /** Where the canopy-owned tasks of a removed column go: `{"Old column": "New column"}`. */
  move_tasks_to: Record<string, string>;
}

export interface Blocker {
  id: number;
  task_id: number;
  reason: string;
  raised_by_engineer_id: number | null;
  blocking_task_id: number | null;
  resolved_at: string | null;
  created_at: string;
  category: BlockerCategory | null;
  severity: BlockerSeverity | null;
  owner_engineer_id: number | null;
  needed_by: string | null;
}

export interface MyWorkspace {
  user: User;
  engineer: Engineer | null;
  assigned_tasks: Task[];
  owned_decisions: ADR[];
  stakeholder_decisions: ADR[];
  blockers: Blocker[];
  /** "My sprint": my tasks in active sprints (§C11). */
  my_sprints: MySprint[];
  /** Agent work waiting on my decision (ai.work_queue). */
  gates?: MyGate[];
  /** Design docs in review this user may approve (§V8). */
  docs_to_review?: DocReference[];
}

export interface MyToday {
  user: User;
  focus_tasks: Task[];
  decisions_to_push: ADR[];
  gates?: MyGate[];
}

/** An open gate this person may decide. */
export interface MyGate {
  id: number;
  task_id: number;
  project_id: number;
  kind: GateKind;
  origin: GateOrigin;
  title: string;
  stage: string | null;
  task_key: string | null;
  task_name: string | null;
  project_key: string | null;
  age_hours: number;
  parked: boolean;
}

export interface Allocation {
  id: number;
  engineer_id: number;
  project_id: number | null;
  task_id: number | null;
  percent_allocation: number;
  capacity_hours_per_week: number;
  start_date: string | null;
  end_date: string | null;
}

export interface Alert {
  kind: string;
  severity: string;
  message: string;
  entity_type: string | null;
  entity_id: number | null;
}

export interface AlertsResponse {
  project_id: number;
  alerts: Alert[];
}

export interface DraftPlan {
  id: number;
  project_id: number;
  title: string;
  description: string | null;
  status: string;
  source: string | null;
  synced_at: string | null;
  created_at: string;
  /** The tracked design doc the plan was drafted from, and the version read (§V9). */
  source_doc_id?: number | null;
  source_doc_version?: string | null;
}

export interface DraftTask {
  id: number;
  plan_id: number;
  parent_id: number | null;
  name: string;
  description: string | null;
  type: TaskType;
  estimate_days: number;
  story_points: number | null;
  sort_order: number;
  /** The tracker item finalising created for this draft task (any tracker). */
  external_provider: string | null;
  external_id: string | null;
  external_key: string | null;
  /** The canopy task a native finalise created (a re-finalise updates it). */
  task_id: number | null;
}

export interface DraftPlanDetail extends DraftPlan {
  tasks: DraftTask[];
}

export interface DraftPushTaskResult {
  draft_task_id: number;
  name: string;
  /** created | updated | failed */
  action: string;
  error: string | null;
  /** The tracker item's key, or the native task's key. */
  external_key: string | null;
  /** The canopy task (native finalise). */
  task_id: number | null;
}

/** `POST /draft-plans/{id}/finalize`: canopy tasks (native) or the bound tracker's items. */
export interface DraftFinalizeResult {
  plan_id: number;
  mode: "native" | "tracker";
  provider: string | null;
  connection_id: number | null;
  created: number;
  updated: number;
  failed: number;
  results: DraftPushTaskResult[];
}

export interface ExportToDriveResult {
  file_id: string;
  name: string;
  link: string | null;
}

// --- Scenario simulation ---
export interface Scenario {
  id: number;
  initiative_id: number;
  title: string;
  description: string | null;
  status: "draft" | "ready" | "applied" | "archived";
  base_captured_at: string;
  applied_at: string | null;
}

export interface ScenarioCounts {
  tasks: number;
  dependencies: number;
  milestones: number;
  allocations: number;
  availability: number;
  projects: number;
}

export interface ScenarioDetail extends Scenario {
  counts: ScenarioCounts;
}

export interface ScenarioTaskRead {
  id: number;
  scenario_id: number;
  project_id: number;
  live_task_id: number | null;
  parent_id: number | null;
  name: string;
  description: string | null;
  type: TaskType;
  duration: number;
  deadline: string | null;
  percent_complete: number;
  assignee_engineer_id: number | null;
  removed: boolean;
}

export interface ScenarioAvailabilityRead {
  id: number;
  scenario_id: number;
  live_availability_id: number | null;
  engineer_id: number;
  start_date: string;
  end_date: string;
  capacity_factor: number;
  note: string | null;
  removed: boolean;
}

export interface ScenarioProjectDelta {
  project_id: number;
  project_key: string;
  live_end: string | null;
  scenario_end: string | null;
  end_delta_days: number | null;
}

export interface ScenarioDiff {
  tasks_added: number;
  tasks_removed: number;
  tasks_changed: number;
  deps_added: number;
  deps_removed: number;
  milestones_changed: number;
  allocations_changed: number;
  availability_changed: number;
  live_project_end: string | null;
  scenario_project_end: string | null;
  end_delta_days: number | null;
  live_cp_working_days: number;
  scenario_cp_working_days: number;
  cp_delta_days: number;
  per_project: ScenarioProjectDelta[];
}

export interface ScenarioConflict {
  entity_type: string;
  entity_id: number | null;
  reason: string;
}

export interface ScenarioCompareResponse {
  scenario_id: number;
  diff: ScenarioDiff;
  conflicts: ScenarioConflict[];
}

export interface ScenarioApplyResult {
  scenario_id: number;
  status: string;
  created: number;
  updated: number;
  deleted: number;
  replanned_projects: number[];
  conflicts: ScenarioConflict[];
}

// Live engineer availability (PTO / leave / ramp-up).
export interface Availability {
  id: number;
  engineer_id: number;
  start_date: string;
  end_date: string;
  capacity_factor: number;
  note: string | null;
}

// --- Delivery metrics (DORA + flow; team-level only) ---
export interface DoraMetrics {
  window_weeks: number;
  deploys: number;
  deploy_frequency_per_week: number;
  failures: number;
  change_fail_rate: number | null;
  recovered_incidents: number;
  mean_recovery_hours: number | null;
  median_recovery_hours: number | null;
}

export interface FlowMetrics {
  completed_items: number;
  throughput_per_week: number | null;
  cycle_time_median_days: number | null;
  cycle_time_p85_days: number | null;
  wip: number;
  aging_wip: number;
  sufficient: boolean;
  reason: string | null;
}

export interface DeliveryMetrics {
  scope_level: "project" | "initiative";
  scope_id: number;
  window_weeks: number;
  dora: DoraMetrics;
  flow: FlowMetrics;
  notes: string[];
}

// --- Outcomes (outcomes over output) ---
export type OutcomeScope = "project" | "initiative";
export type OutcomeStatus = "pending" | "on_track" | "at_risk" | "validated" | "invalidated";

export interface Outcome {
  id: number;
  scope_level: OutcomeScope;
  scope_id: number;
  statement: string;
  metric: string | null;
  unit: string | null;
  baseline_value: number | null;
  target_value: number | null;
  current_value: number | null;
  status: OutcomeStatus;
  target_date: string | null;
  owner_engineer_id: number | null;
  created_at: string;
  progress_ratio: number | null;
}

// --- Specs (spec-driven development) ---
export type SpecStatus = "draft" | "approved" | "in_progress" | "verified" | "archived";
export type CriterionStatus = "open" | "met" | "unmet" | "waived";

export interface Spec {
  id: number;
  project_id: number;
  title: string;
  problem: string;
  context: string | null;
  out_of_scope: string | null;
  status: SpecStatus;
  owner_engineer_id: number | null;
  adr_id: number | null;
  source_url: string | null;
  created_at: string;
}

export interface SpecCriterion {
  id: number;
  spec_id: number;
  text: string;
  status: CriterionStatus;
  verification: string | null;
  sort_order: number;
  created_at: string;
}

export interface SpecLinkedTask {
  id: number;
  name: string;
  status: string | null;
  percent_complete: number;
  is_critical: boolean;
}

export interface SpecDetail extends Spec {
  criteria: SpecCriterion[];
  linked_tasks: SpecLinkedTask[];
  criteria_total: number;
  criteria_met: number;
  acceptance_ratio: number;
  /** Advisory: the source docs (basis / gate links) are approved. */
  docs_ready?: boolean;
  docs_pending?: string[];
}

// --- Document graph (link, don't store) + design docs (USER_FLOWS §V5) ---
/** Any kind is allowed — an open slug backed by the workspace kind catalog. */
export type DocKind = string;
export type DocScope = "project" | "initiative" | "task";
export type DocSource = "jira_epic" | "manual" | "repo" | "drive" | "agent" | "claude_sync";
export type DocLinkHealth = "unchecked" | "ok" | "stale" | "broken";
export type DocProvider =
  | "claude"
  | "gdrive"
  | "github"
  | "figma"
  | "confluence"
  | "jira"
  | "web";
export type DocReviewStatus = "draft" | "in_review" | "approved" | "superseded" | "archived";
export type DocVisibility = "owner" | "users" | "org" | "public" | "unknown";
export type DocRelation = "basis" | "gate" | "reference";
export type DocLinkEntity =
  | "project"
  | "initiative"
  | "task"
  | "decision"
  | "spec"
  | "milestone"
  | "outcome"
  | "risk"
  | "retro"
  | "component";
export type DocStage =
  | "frame"
  | "define"
  | "design"
  | "decide"
  | "plan"
  | "build"
  | "release"
  | "learn"
  | "other";

export interface DocReference {
  id: number;
  /** The doc's home; null only for a personal doc not filed under anything. */
  scope_level: DocScope | null;
  scope_id: number | null;
  kind: DocKind;
  title: string | null;
  url: string;
  source: string;
  owner_engineer_id: number | null;
  connection_id: number | null;
  external_field: string | null;
  link_health: DocLinkHealth;
  last_checked_at: string | null;
  created_at: string;
  provider?: string;
  external_id?: string | null;
  format?: string;
  private_to_user_id?: number | null;
  visibility?: string;
  review_status?: DocReviewStatus | null;
  review_version?: string | null;
  current_version?: string | null;
  approved_version?: string | null;
  approved_by_user_id?: number | null;
  approved_at?: string | null;
  summary?: string | null;
  supersedes_id?: number | null;
  created_by_user_id?: number | null;
  updated_at?: string | null;
  /** When the source last changed, per the organization artifact sync (§V11). */
  source_updated_at?: string | null;
}

export interface DocLink {
  id: number;
  doc_id: number;
  entity_type: DocLinkEntity;
  entity_id: number;
  relation: DocRelation;
  pinned_version: string | null;
  pinned_at: string | null;
  created_by_user_id: number | null;
  created_at: string;
  /** The target's display name. */
  label: string | null;
}

export type DocHealthFlagName =
  | "unverified"
  | "check_due"
  | "changed_since_approval"
  | "behind_pin"
  | "gate_open"
  | "restricted"
  | "broken";

/** One reason a doc needs a look (computed server-side, never stored). */
export interface DocHealthFlag {
  flag: DocHealthFlagName;
  severity: "info" | "warning" | "error";
  message: string;
  entity_type: string | null;
  entity_id: number | null;
}

export interface DocRevision {
  id: number;
  doc_id: number;
  version: string;
  content_hash: string | null;
  change_summary: string | null;
  snapshot_url: string | null;
  recorded_by_user_id: number | null;
  source: string;
  created_at: string;
}

/** A doc with its catalog entry, its labelled links and its health. */
export interface DesignDoc extends DocReference {
  kind_label: string;
  stage: DocStage | string;
  personal: boolean;
  links: DocLink[];
  health?: DocHealthFlag[];
}

export interface DesignDocDetail extends DesignDoc {
  revisions: DocRevision[];
}

export interface DocRevisionResult {
  doc: DesignDoc;
  new_version: boolean;
  revision: DocRevision | null;
}

export interface DocWorklist {
  total: number;
  docs: DesignDoc[];
}

export interface EntityDoc {
  link: DocLink;
  doc: DesignDoc;
}

export interface DocRegisterResult {
  doc: DesignDoc;
  created: boolean;
}

/** Counts from the organization artifact sync's last run (USER_FLOWS §V11). */
export interface ArtifactSyncReport {
  full: boolean;
  complete: boolean;
  listed: number;
  paired: number;
  newly_paired: number;
  updated: number;
  new_versions: number;
  sharing_changed: number;
  missing: number;
  unmatched: number | null;
  identities: number;
  ran_at: string;
}

export interface ArtifactSyncStatus {
  available: boolean;
  connection_id?: number | null;
  connection_name?: string | null;
  last_sync?: ArtifactSyncReport | null;
}

/** One of your own Claude artifacts no doc you can see tracks yet — metadata, listed live. */
export interface ArtifactSuggestion {
  artifact_id: string;
  artifact_type: string;
  title: string | null;
  format: string;
  read_mode: string;
  visibility: string;
  version: string | null;
  updated_at: string | null;
}

export interface ArtifactSuggestions {
  available: boolean;
  complete: boolean;
  items: ArtifactSuggestion[];
}

export interface DocKindDef {
  key: string;
  label: string;
  stage: DocStage | string;
  expected: boolean;
  builtin: boolean;
  sort_order: number;
  doc_count: number;
}

export interface DocCoverageKind {
  kind: string;
  label: string;
  stage: string;
  state: "approved" | "in_review" | "draft" | "linked" | "missing";
}

export interface DocCoverage {
  scope_level: DocScope;
  scope_id: number;
  total_references: number;
  present: DocKind[];
  missing: DocKind[];
  by_kind: Record<string, number>;
  expected?: DocCoverageKind[];
  by_stage?: { stage: string; total: number; approved: number }[];
  needs_attention?: number;
}

export interface PullRequest {
  id: number;
  repo: string;
  number: number;
  title: string;
  state: string;
  url: string | null;
  author: string | null;
  task_id: number | null;
}

/** The tracker item behind a mirrored task, whatever the tracker. */
export interface TrackerItemLink {
  provider: string;
  /** The tracker's display name, e.g. "Jira". */
  label: string;
  key: string;
  url: string | null;
}

export interface TaskExternalLinks {
  /** The tracker item a mirrored task comes from (null for canopy-only work). */
  tracker: TrackerItemLink | null;
  pull_requests: PullRequest[];
  docs: DocReference[];
}

// --- Tracker links + tracker catalog ---
/** What a tracker link maps an item's subtree into. */
export type TrackerLinkTarget = "project" | "initiative";

export interface TrackerLink {
  id: number;
  connection_id: number;
  provider: string;
  /** The tracker item the link roots at (e.g. an epic). */
  root_id: string;
  root_key: string;
  root_type: string | null;
  target_type: string;
  target_id: number;
  url: string | null;
  last_synced_at: string | null;
  created_at: string;
}

export interface TrackerLinkCreate {
  connection_id: number;
  root_key: string;
  target_type: TrackerLinkTarget;
  target_id: number;
}

export interface TrackerLinkSyncResult {
  link: TrackerLink;
  projects_created: number;
  projects_linked: number;
  tasks_created: number;
  tasks_updated: number;
  skipped: number;
  created_project_ids: number[];
  notes: string[];
}

export interface TrackerCapabilities {
  direct_read: boolean;
  hierarchy: boolean;
  status_categories: boolean;
  status_history: boolean;
  iterations: boolean;
  webhooks: boolean;
  create_items: boolean;
  update_items: boolean;
  estimates: boolean;
  oauth: boolean;
}

export interface TrackerInfo {
  provider: string;
  label: string;
  enabled: boolean;
  capabilities: TrackerCapabilities;
  config_schema: Record<string, unknown>;
  scope_schema: Record<string, unknown>;
  webhook_path: string | null;
  webhook_secret_setting: string | null;
}

export interface TrackerCatalog {
  trackers: TrackerInfo[];
  default_tracking_mode: TrackingMode;
}

// --- Project tracking: native or mirrored, the binding, switching (USER_FLOWS §C12) ---
/** One of a tracker's statuses — a mirrored board's columns, in the tracker's order. */
export interface TrackerStatus {
  name: string;
  category: StatusCategory;
  position: number;
}

/** Where a project mirrors its work from: a tracker connection and a scope inside it. */
export interface TrackerBinding {
  id: number;
  connection_id: number;
  connection_name: string | null;
  provider: string;
  /** The tracker's display name, e.g. "Jira". */
  label: string;
  scope_kind: string;
  /** Validated against the tracker's `scope_schema` (e.g. `{project_key, board_id}`). */
  scope: Record<string, unknown>;
  /** Type/field mapping (epic types, estimate field…). */
  mapping: Record<string, unknown>;
  status_map: TrackerStatus[];
  /** Mirror the tracker's sprints/cycles. */
  sync_iterations: boolean;
  active: boolean;
  last_synced_at: string | null;
  /** When it stopped feeding the project (past bindings only). */
  detached_at: string | null;
  created_at: string;
}

/** `GET /projects/{id}/tracking`. */
export interface ProjectTracking {
  project_id: number;
  mode: TrackingMode;
  /** The active binding; null for a native project (or a mirrored one not bound yet). */
  binding: TrackerBinding | null;
  /** Trackers the project used before, newest first. */
  history: TrackerBinding[];
  /** The bound tracker's capabilities. */
  capabilities: TrackerCapabilities | null;
  canopy_owned: number;
  tracker_owned: number;
  /** A planner who may edit this project. */
  can_edit: boolean;
  /** Provider keys a project may be bound to on this instance. */
  trackers_enabled: string[];
}

/** `PUT /projects/{id}/tracking` — adjust the active binding in place. A new scope resets the
 *  sync watermark and status map, so the next sync is a full one. */
export interface ProjectTrackingUpdate {
  scope?: Record<string, unknown>;
  mapping?: Record<string, unknown>;
  sync_iterations?: boolean;
}

/** What happens to the work a project already has when it gets a tracker. */
export type TrackingStrategy = "keep_separate" | "match" | "publish";

export interface TrackingSwitchRequest {
  to_mode: TrackingMode;
  connection_id?: number | null;
  scope: Record<string, unknown>;
  mapping: Record<string, unknown>;
  sync_iterations: boolean;
  strategy: TrackingStrategy;
  /** Preview (true) or apply exactly the previewed plan (false, human-only). */
  dry_run: boolean;
}

/** What a switch does to one task. */
export interface TrackingSwitchAction {
  task_id: number;
  name: string;
  key: string | null;
  /** keep | adopt | publish | release | remap */
  action: string;
  detail: string | null;
}

export interface TrackingPublishResult {
  created: number;
  skipped: number;
  failed: number;
  errors: string[];
}

export interface TrackingSwitchResult {
  project_id: number;
  from_mode: TrackingMode;
  to_mode: TrackingMode;
  from_provider: string | null;
  to_provider: string | null;
  strategy: TrackingStrategy;
  dry_run: boolean;
  applied: boolean;
  /** Tasks per action. */
  counts: Record<string, number>;
  actions: TrackingSwitchAction[];
  warnings: string[];
  binding?: TrackerBinding | null;
  published?: TrackingPublishResult | null;
  synced_created?: number | null;
  synced_updated?: number | null;
}

export interface TrackingSyncResult {
  provider: string;
  created: number;
  updated: number;
  skipped: number;
}

// --- Change proposals (agent-staged writes, human-reviewed) ---
export type ProposalScopeLevel = "project" | "initiative";
export type ProposalStatus = "open" | "applied" | "rejected" | "withdrawn";
export type ProposalEntityType =
  | "task"
  | "dependency"
  | "milestone"
  | "blocker"
  | "risk"
  | "outcome"
  | "decision"
  | "doc_reference"
  | "doc_link"
  | "rule";
export type ProposalActionType = "create" | "update" | "resolve";

export interface ProposalItem {
  id: number;
  sort_order: number;
  entity_type: ProposalEntityType;
  action: ProposalActionType;
  entity_id: number | null;
  ref: string | null;
  payload: Record<string, unknown>;
  before: Record<string, unknown> | null;
  reason: string | null;
  source_kind: string | null;
  source_label: string | null;
  source_url: string | null;
  excluded: boolean;
  /** Reviewer's audit-preserving inline field overrides, layered over `payload` at apply time. */
  overrides: Record<string, unknown> | null;
  overridden_by_user_id: number | null;
  /** resolved display name of the reviewer who overrode (read-time) */
  overridden_by: string | null;
  overridden_at: string | null;
  applied_entity_id: number | null;
  error: string | null;
  /** The proposal revision that added or last rewrote this item (== the proposal's own
   *  `revision` means "changed in the latest revise"). */
  revision?: number;
  /** live values recomputed at read time (open proposals, update/resolve items) */
  current?: Record<string, unknown> | null;
  /** the target moved (or vanished) since the before-snapshot was taken */
  stale?: boolean;
  /** Whitelisted fields the proposal doesn't set yet that the reviewer may add inline. */
  addable_fields?: string[];
}

export interface Proposal {
  id: number;
  scope_level: ProposalScopeLevel;
  scope_id: number;
  title: string;
  summary: string | null;
  origin: string | null;
  status: ProposalStatus;
  created_by_user_id: number | null;
  reviewed_by_user_id: number | null;
  reviewed_at: string | null;
  review_note: string | null;
  applied_count: number;
  created_at: string;
  item_count: number;
  excluded_count: number;
  /** Per-action tally for the collapsed-card shape chip: {"create": n, "update": n, "resolve": n}. */
  action_counts: Record<string, number>;
  /** Items that errored or drifted since staging — surfaced as a "needs attention" flag. */
  attention_count: number;
  scope_label: string | null;
  /** Bumped each time the author revises the open proposal in place (co-review). */
  revision: number;
  revised_at: string | null;
  /** The author's "what changed" line for the latest revision. */
  revision_note: string | null;
  /** resolved display name of the author */
  created_by: string | null;
  /** The design doc the changes were derived from, as it stands now (§V9). */
  source_doc_id?: number | null;
  source_doc_version?: string | null;
  source_doc?: ProposalSourceDoc | null;
}

export interface ProposalSourceDoc {
  id: number;
  title: string | null;
  url: string;
  provider: string;
  current_version: string | null;
  /** The doc moved on since the proposal read it. */
  moved_on: boolean;
}

/** Display names for the ids a proposal's items mention: `{kind: {"<id>": name}}`. */
export type ProposalLookups = Partial<
  Record<"task" | "engineer" | "project" | "initiative" | "spec" | "doc", Record<string, string>>
>;

export interface ProposalDetail extends Proposal {
  items: ProposalItem[];
  lookups: ProposalLookups;
}

// --- Proposal plan preview: the plan as a whole, current vs proposed ---
export type PreviewTaskKind = "added" | "edited" | "shifted";

export interface PreviewIssue {
  item_id: number | null;
  project_id: number | null;
  error: string;
}

export interface PreviewTaskChange {
  /** live id; a task the proposal creates has a synthetic negative id */
  task_id: number;
  name: string;
  kind: PreviewTaskKind;
  is_summary: boolean;
  item_ids: number[];
  start_before: string | null;
  start_after: string | null;
  end_before: string | null;
  end_after: string | null;
  end_delta_days: number | null;
  critical_before: boolean;
  critical_after: boolean;
}

export interface PreviewMilestone {
  milestone_id: number;
  name: string;
  kind: "added" | "edited" | "unchanged";
  item_ids: number[];
  target_before: string | null;
  target_after: string | null;
  status_before: string | null;
  status_after: string | null;
}

export interface PreviewDeadlineMiss {
  task_id: number;
  name: string;
  deadline: string;
  end: string;
}

export interface ProjectPlanPreview {
  project_id: number;
  key: string;
  name: string;
  current: GanttResponse;
  /** null when the staged dependencies form a cycle */
  proposed: GanttResponse | null;
  end_current: string | null;
  end_proposed: string | null;
  end_delta_days: number | null;
  critical_current: number;
  critical_proposed: number;
  task_changes: PreviewTaskChange[];
  milestones: PreviewMilestone[];
  new_deadline_misses: PreviewDeadlineMiss[];
  live_schedule_stale: boolean;
  cycle: boolean;
}

export interface PreviewCounts {
  tasks_added: number;
  tasks_edited: number;
  tasks_shifted: number;
  dependencies_added: number;
  milestones_added: number;
  milestones_edited: number;
  blockers_raised: number;
  blockers_resolved: number;
  risks_added: number;
  risks_edited: number;
  outcomes_added: number;
  outcomes_edited: number;
  decisions_added: number;
  docs_added: number;
  rules_added?: number;
  docs_linked?: number;
}

export interface ProposalPreview {
  proposal_id: number;
  revision: number;
  included: number;
  excluded: number;
  can_apply: boolean;
  issues: PreviewIssue[];
  counts: PreviewCounts;
  projects: ProjectPlanPreview[];
}

export interface ProposalApplyResult {
  proposal: Proposal;
  applied: number;
  skipped: number;
  replanned_projects: number[];
}

// --- Initiative lead teams / ownership (USER_FLOWS §R6) ---
export type LeadRole = "technical" | "product" | "design" | "manager";

export interface InitiativeLead {
  initiative_id: number;
  engineer_id: number;
  engineer_name: string;
  lead_role: LeadRole;
  user_id: number | null;
}

export interface InitiativeAccess {
  /** Initiatives the user is an owner of. */
  led_initiative_ids: number[];
  /** Owned + every initiative in a team the user directs. */
  editable_initiative_ids: number[];
  /** Projects the user is the single owner of. */
  owned_project_ids: number[];
  leads: InitiativeLead[];
}

export type TeamRole = "director" | "manager";

export interface Pod {
  id: number;
  team_id: number;
  name: string;
}

export interface TeamMember {
  team_id: number;
  engineer_id: number;
  engineer_name: string;
  role: TeamRole;
  user_id: number | null;
}

export interface Team {
  id: number;
  key: string;
  name: string;
  description: string | null;
  pods: Pod[];
  members: TeamMember[];
  /** How the team runs work across its projects (§C11; always sent, defaulted). */
  delivery_method?: DeliveryMethod;
  sprint_length_days?: number;
  estimate_unit?: EstimateUnit;
}

export interface ProjectAccess {
  project_id: number;
  initiative_id: number | null;
  initiative_name: string | null;
  can_edit: boolean;
  leads: InitiativeLead[];
  owner_name: string | null;
  pod_name: string | null;
  /** The initiative's team (who leads it). */
  team_name: string | null;
  /** The team that runs the project — its pod's team, else its initiative's — whose board,
   *  workflow and sprints it uses (§C11). */
  team_id?: number | null;
  running_team_name?: string | null;
}

// --- Leadership notes + business review (USER_FLOWS §BR) ---
export type LeadershipScope = "initiative" | "project";
export type LeadershipNoteKind = "watch" | "priority" | "feedback";
export type LeadershipTargetKind = "decision" | "risk" | "outcome" | "milestone";
export type LeadershipNoteStatus = "open" | "acknowledged" | "resolved";

export interface LeadershipNote {
  id: number;
  scope_level: LeadershipScope;
  scope_id: number;
  target_kind: LeadershipTargetKind | null;
  target_id: number | null;
  target_label: string | null;
  kind: LeadershipNoteKind;
  priority: number | null;
  body: string;
  author_user_id: number;
  author_name: string | null;
  status: LeadershipNoteStatus;
  response: string | null;
  responded_by_user_id: number | null;
  responded_by_name: string | null;
  responded_at: string | null;
  created_at: string;
}

export interface ReviewOutcome {
  id: number;
  statement: string;
  status: string;
  current_value: number | null;
  target_value: number | null;
  unit: string | null;
}

export interface ReviewInitiative {
  id: number;
  key: string;
  name: string;
  team_id: number | null;
  pods: string[];
  outcome_statement: string | null;
  target_date: string | null;
  health: ProjectHealth | null;
  status_note: string | null;
  leads: InitiativeLead[];
  project_count: number;
  avg_percent_complete: number;
  project_end: string | null;
  on_track: boolean | null;
  risk_score: number;
  risk_level: string;
  drift_score: number;
  drift_level: string;
  open_decisions: number;
  open_blockers: number;
  outcomes: ReviewOutcome[];
  open_notes: LeadershipNote[];
}

export interface BusinessReview {
  generated_on: string;
  teams: Team[];
  initiatives: ReviewInitiative[];
  open_note_count: number;
  attention: string[];
}


// --- Agent work: the work queue, claims, artifacts, gates (docs/AGENT_EXECUTION.md) ---------

export type AgentIntake = "off" | "on" | "paused";
export type Delegation = "agent";
export type ClaimState = "active" | "completed" | "released" | "expired" | "failed" | "superseded";
export type ClaimOutcome =
  | "advanced"
  | "returned"
  | "gated"
  | "released"
  | "failed"
  | "expired"
  | "superseded";
export type ArtifactKind = "plan" | "handoff" | "review" | "qa_report" | "note";
export type GateKind = "plan_approval" | "handoff_approval" | "signoff" | "question" | "escalation";
export type GateOrigin = "checkpoint" | "column" | "agent" | "system";
export type GateStatus =
  | "open"
  | "approved"
  | "changes_requested"
  | "rejected"
  | "answered"
  | "cancelled";
export type GateDecision =
  | "approve"
  | "edit_and_approve"
  | "approve_with_conditions"
  | "request_changes"
  | "reject"
  | "answer"
  | "retry"
  | "take_over"
  | "cancelled";

export interface WorkClaim {
  id: number;
  task_id: number;
  role: string;
  stage: string;
  attempt: number;
  state: ClaimState;
  outcome: ClaimOutcome | null;
  end_reason: string | null;
  user_id: number;
  agent_token_id: number | null;
  agent_label: string | null;
  runner: string | null;
  session_ref: string | null;
  claimed_at: string;
  heartbeat_at: string;
  lease_minutes: number;
  lease_expires_at: string;
  finished_at: string | null;
  progress_note: string | null;
  branch: string | null;
  pr_url: string | null;
  usage: Record<string, unknown> | null;
}

export interface TaskArtifact {
  id: number;
  task_id: number;
  kind: ArtifactKind;
  revision: number;
  title: string | null;
  body: string;
  data: Record<string, unknown>;
  verdict: string | null;
  head_sha: string | null;
  author_kind: string;
  author_user_id: number | null;
  work_claim_id: number | null;
  created_at: string;
}

export interface GateOption {
  value: string;
  label?: string | null;
}

export interface Gate {
  id: number;
  task_id: number;
  project_id: number;
  kind: GateKind;
  origin: GateOrigin;
  stage: string | null;
  status: GateStatus;
  title: string;
  prompt: string | null;
  options: GateOption[];
  allow_text: boolean;
  allowed_decisions: GateDecision[];
  reasons: string[];
  evidence: Record<string, unknown>;
  subject_artifact_id: number | null;
  requested_by_claim_id: number | null;
  requested_by_user_id: number | null;
  approvers: string;
  exclude_requester: boolean;
  satisfied_by: string[];
  remind_at: string | null;
  escalate_at: string | null;
  escalation_level: number;
  decision: GateDecision | null;
  decided_by_user_id: number | null;
  decided_by_label: string | null;
  decided_via: string | null;
  decided_at: string | null;
  response_note: string | null;
  response_data: Record<string, unknown>;
  routed_at: string | null;
  created_at: string;
  task_key: string | null;
  task_name: string | null;
  project_key: string | null;
  requester_name: string | null;
  age_hours: number;
  /** The caller may decide this gate (always false for an agent token). */
  may_decide: boolean;
  /** Approved, but the next column's checks aren't met yet (e.g. the PR isn't merged). */
  waiting_for_evidence: boolean;
  tracker_transition?: TrackerTransition | null;
}

export interface WorkEvent {
  id: number;
  task_id: number | null;
  project_id: number;
  at: string;
  kind: string;
  actor_kind: string;
  user_id: number | null;
  agent_token_id: number | null;
  work_claim_id: number | null;
  gate_id: number | null;
  artifact_id: number | null;
  data: Record<string, unknown>;
}

export interface GateDetail {
  gate: Gate;
  task: Task;
  subject: TaskArtifact | null;
  previous: TaskArtifact | null;
  handoff: TaskArtifact | null;
  reviews: TaskArtifact[];
  trail: WorkEvent[];
}

export interface GateDecideRequest {
  decision: GateDecision;
  note?: string | null;
  option?: string | null;
  subject_revision?: number | null;
}

export interface RoleReadiness {
  ready: boolean;
  reason: string | null;
  stage: string | null;
  detail: string | null;
}

export interface TaskExecution {
  task_id: number;
  delegation: Delegation | null;
  stage: string | null;
  worked_by: string | null;
  active_claim: WorkClaim | null;
  claims: WorkClaim[];
  artifacts: TaskArtifact[];
  gates: Gate[];
  events: WorkEvent[];
  exit_contract: Record<string, unknown> | null;
  readiness: { intake: AgentIntake; by_role: Record<string, RoleReadiness> } | null;
  tracker_transition?: TrackerTransition | null;
}

/** A move canopy cleared on a mirrored ticket but may not make itself (§17): someone makes it
 *  in the tracker (or the tracker's automation does), and canopy sees it on the next sync. */
export interface TrackerTransition {
  key: string | null;
  provider: string;
  from_status: string | null;
  to_status: string;
  cleared_at: string | null;
}

export interface DelegationResponse {
  task: Task;
  hints: string[];
}

export interface QueueItem {
  task_id: number;
  key: string | null;
  name: string;
  project_id: number;
  project_key: string;
  status: string | null;
  stage: string;
  pull: boolean;
  rank: number;
}

export interface AgentStage {
  status: string;
  category: string;
  worked_by: string | null;
  source: string;
}

export interface AgentsWorking {
  claim: WorkClaim;
  task_key: string | null;
  task_name: string;
  heartbeat_age_s: number;
}

export interface ParkedTask {
  task_id: number;
  key: string | null;
  name: string;
  gate_id: number;
}

export interface AgentsView {
  project_id: number;
  agent_intake: AgentIntake;
  can_manage: boolean;
  /** False while the project runs on the built-in default pipeline. */
  configured: boolean;
  stages: AgentStage[];
  ready: Record<string, QueueItem[]>;
  reasons: Record<string, number>;
  working: AgentsWorking[];
  waiting: Gate[];
  parked: ParkedTask[];
  delegated: number;
}

export interface IntakeResponse {
  project_id: number;
  agent_intake: AgentIntake;
  stopped: number;
}

// --- Stage policy, rules and agent-flow metrics (docs/AGENT_EXECUTION.md §9, §10, §19) -------

export type Enforcement = "off" | "warn" | "block";

export interface CheckDoc {
  check: string;
  params?: Record<string, unknown>;
  enforcement: Enforcement;
  applies_to?: "agents" | "everyone";
}

export interface DecisionDoc {
  kind?: string;
  when?: string | string[];
  approvers?: string;
  approver_engineer_ids?: number[];
  exclude_requester?: boolean;
  satisfied_by?: string[];
  remind_after_hours?: number;
  escalate_after_hours?: number;
  on_approve?: string | null;
  on_changes?: string | null;
  on_reject?: string | null;
}

export interface CheckpointDoc {
  required?: boolean;
  approval_when?: string | string[];
  decision?: DecisionDoc;
}

export interface StagePolicyDoc {
  worked_by: string | null;
  artifact?: "handoff" | "review" | "qa_report" | null;
  instructions?: string;
  pulls_from?: string[] | null;
  enter?: { checks?: CheckDoc[] };
  on_changes?: string | null;
  decision?: DecisionDoc | null;
  checkpoints?: Record<string, CheckpointDoc>;
  lease_minutes?: number;
  max_attempts?: number;
  max_rework?: number;
}

export interface StageColumn {
  status: string;
  category: string;
  position: number;
  wip_limit: number | null;
  worked_by: string | null;
  hands_off: string | null;
  source: string;
  policy: StagePolicyDoc | null;
}

export interface PipelineRead {
  scope: "project" | "team" | "template" | "default" | "tracker";
  inherited: boolean;
  workflow_id: number | null;
  team_id: number | null;
  configured: boolean;
  wip_enforcement: string;
  roles: string[];
  columns: StageColumn[];
  can_edit: boolean;
}

export interface TemplatePreview {
  template: string;
  columns: { name: string; category: string; worked_by: string | null; policy: StagePolicyDoc | null }[];
  current_columns: string[];
  moves: { from_status: string; to_status: string; tasks: number }[];
  wip_enforcement: string;
  applied: boolean;
  pipeline: PipelineRead | null;
}

export type RuleScope = "workspace" | "team" | "project";

export interface DeliveryRule {
  id: number;
  scope_level: RuleScope;
  scope_id: number;
  key: string;
  title: string;
  body: string;
  kind: "guidance" | "attestation";
  roles: string[];
  selector: { tags?: string[]; components?: number[]; paths?: string[] };
  enforcement: Enforcement;
  locked: boolean;
  disabled: boolean;
  source_adr_id: number | null;
  source_url: string | null;
  created_at: string;
  updated_at: string;
}

/** A scope whose rules reach a project or team, and whether the caller may edit it. */
export interface RuleScopeInfo {
  scope_level: RuleScope;
  scope_id: number;
  name: string;
  can_edit: boolean;
}

export interface RuleWrite {
  scope_level?: RuleScope;
  scope_id?: number;
  key?: string;
  title: string;
  body: string;
  kind: "guidance" | "attestation";
  roles: string[];
  selector: { tags: string[]; components: number[]; paths: string[] };
  enforcement: Enforcement;
  locked: boolean;
  disabled?: boolean;
  source_adr_id: number | null;
  source_url: string | null;
}

export interface EffectiveRule {
  rule: DeliveryRule;
  origin: RuleScope;
  overrides: RuleScope[];
  enforcement: Enforcement;
  stale: boolean;
  stale_reason: string | null;
  can_edit: boolean;
}

export interface AgentFlow {
  scope: string;
  scope_id: number;
  weeks: number;
  projects: number;
  sufficient: boolean;
  reason: string | null;
  queue: {
    ready_by_role: Record<string, number>;
    oldest_ready_hours: number | null;
    held_by_kind: Record<string, number>;
    parked: number;
  };
  human_wait: {
    by_kind: Record<string, { decided: number; median_hours: number | null; p85_hours: number | null }>;
    open: number;
    open_past_reminder: number;
    open_past_escalation: number;
  };
  first_pass: { approvals: number | null; reviews: number | null };
  rework: { tasks_returned_share: number | null; rounds_per_returned_task: number | null };
  claims: { finished: number; by_outcome: Record<string, number>; attempts_per_task: number | null };
  flow_efficiency: number | null;
  gate_load: { opened: number; per_week: number; by_kind: Record<string, number>; top_reasons: { reason: string; count: number }[] };
  gates_as_experiments: { kind: string; decided: number; approval_rate: number | null; median_hours: number | null }[];
  unassisted_share: number | null;
  agent_tasks_done: number;
  cost_per_task_usd: number | null;
}

// --- Outbound notifications (USER_FLOWS §AE9) ---

export type WebhookEvent = "work.ready" | "gate.opened" | "gate.reminder" | "gate.escalated" | "gate.decided";

export interface OutboundWebhook {
  id: number;
  scope_level: RuleScope;
  scope_id: number;
  scope_name: string | null;
  name: string;
  /** The full URL only for people who may edit it (a Slack URL is a credential). */
  url: string;
  format: "json" | "slack";
  events: WebhookEvent[];
  has_secret: boolean;
  enabled: boolean;
  last_delivery_at: string | null;
  last_status: string | null;
  consecutive_failures: number;
  can_edit: boolean;
  created_at: string;
}

export interface WebhookCatalog {
  events: WebhookEvent[];
  formats: ("json" | "slack")[];
  email_enabled: boolean;
  signature_header: string;
}

export interface WebhookDelivery {
  id: number;
  event: string;
  channel: string;
  status: "pending" | "sent" | "failed";
  attempts: number;
  task_id: number | null;
  response_status: number | null;
  last_error: string | null;
  created_at: string;
  sent_at: string | null;
  next_attempt_at: string;
}

export interface WebhookTestResult {
  delivered: boolean;
  status: string;
  response_status: number | null;
  error: string | null;
}

// --- Graduated autonomy (USER_FLOWS §AE6) ---

export interface ChangeClassStats {
  change_class: string;
  tasks: number;
  decided: Record<string, number>;
  approval_rate: Record<string, number | null>;
  median_decision_hours: Record<string, number | null>;
  reviews: number;
  first_pass_rate: number | null;
  rework_tasks: number;
  parked: number;
}

export interface AutonomySuggestion {
  action: "pre_approve" | "revoke";
  checkpoint: "plan" | "handoff";
  change_class: string;
  reason: string;
}

export interface AutonomyRead {
  stage: string | null;
  checkpoints: ("plan" | "handoff")[];
  pre_approved: Record<string, string[]>;
  floor: string[];
  weeks: number;
  classes: ChangeClassStats[];
  suggestions: AutonomySuggestion[];
  can_edit: boolean;
}
