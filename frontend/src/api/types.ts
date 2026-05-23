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

export interface Project {
  id: number;
  key: string;
  name: string;
  description: string | null;
  initiative_id: number | null;
  start_date: string | null;
  target_date: string | null;
  archived: boolean;
  skip_weekends: boolean;
  decision_rule: DecisionRule;
  decision_sla_hours: number;
}

export interface Initiative {
  id: number;
  key: string;
  name: string;
  outcome_statement: string | null;
  start_date: string | null;
  target_date: string | null;
  owner_engineer_id: number | null;
  archived: boolean;
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
  sprint: string | null;
  deadline: string | null;
  assignee_engineer_id: number | null;
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
}

export interface Milestone {
  id: number;
  project_id: number;
  name: string;
  description: string | null;
  target_date: string | null;
  status: string;
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

export interface ADRDetail extends ADR {
  comments: ADRComment[];
  review: ReviewSummary;
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

export interface User {
  id: number;
  email: string;
  full_name: string | null;
  role: UserRole;
  is_active: boolean;
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

export interface MyWorkspace {
  user: User;
  engineer: Engineer | null;
  assigned_tasks: Task[];
  owned_decisions: ADR[];
  stakeholder_decisions: ADR[];
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
