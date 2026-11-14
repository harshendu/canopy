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
export type Provider = "jira" | "github" | "gdrive";

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
  /** Legacy: the sprint's name (kept in step with `sprint_id`). */
  sprint: string | null;
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
  jira_account_id: string | null;
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
}

// --- Agent tokens (Agent Setup tab: mint a bounded token for Claude / the MCP server, §A6) ---
export interface AgentTokenRequest {
  label?: string | null;
  expires_minutes?: number | null;
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
}

export interface MyToday {
  user: User;
  focus_tasks: Task[];
  decisions_to_push: ADR[];
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
  jira_issue_id: string | null;
  jira_key: string | null;
}

export interface DraftPlanDetail extends DraftPlan {
  tasks: DraftTask[];
}

export interface DraftPushTaskResult {
  draft_task_id: number;
  name: string;
  action: string;
  jira_key: string | null;
  error: string | null;
}

export interface DraftPushResult {
  plan_id: number;
  connection_id: number;
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

export type JiraLinkTarget = "project" | "initiative";

export interface JiraLink {
  id: number;
  connection_id: number;
  jira_issue_id: string;
  jira_key: string;
  jira_issue_type: string | null;
  target_type: string;
  target_id: number;
  last_synced_at: string | null;
  created_at: string;
}

export interface JiraLinkSyncResult {
  link: JiraLink;
  projects_created: number;
  projects_linked: number;
  tasks_created: number;
  tasks_updated: number;
  skipped: number;
  created_project_ids: number[];
  notes: string[];
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
}

// --- Document graph (link, don't store) ---
export type DocKind =
  | "prd"
  | "design"
  | "tech_design"
  | "architecture"
  | "release"
  | "qa"
  | "runbook"
  | "other";
export type DocScope = "project" | "initiative" | "task";
export type DocSource = "jira_epic" | "manual" | "repo" | "drive";
export type DocLinkHealth = "unchecked" | "ok" | "stale" | "broken";

export interface DocReference {
  id: number;
  scope_level: DocScope;
  scope_id: number;
  kind: DocKind;
  title: string | null;
  url: string;
  source: DocSource;
  owner_engineer_id: number | null;
  connection_id: number | null;
  external_field: string | null;
  link_health: DocLinkHealth;
  last_checked_at: string | null;
  created_at: string;
}

export interface DocCoverage {
  scope_level: DocScope;
  scope_id: number;
  total_references: number;
  present: DocKind[];
  missing: DocKind[];
  by_kind: Record<string, number>;
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

export interface JiraIssueLink {
  key: string;
  url: string | null;
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
  /** Preferred over `jira`. */
  tracker?: TrackerItemLink | null;
  /** Deprecated alias of `tracker`, set only when the tracker is Jira. */
  jira: JiraIssueLink | null;
  pull_requests: PullRequest[];
  docs: DocReference[];
}

// --- Tracker links + tracker catalog (neutral successors of the Jira links) ---
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
  target_type: string;
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
  | "doc_reference";
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
}

/** Display names for the ids a proposal's items mention: `{kind: {"<id>": name}}`. */
export type ProposalLookups = Partial<
  Record<"task" | "engineer" | "project" | "initiative" | "spec", Record<string, string>>
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
  team_name: string | null;
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
