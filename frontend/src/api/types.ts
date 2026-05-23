export type TaskType = "task" | "milestone" | "summary";
export type DependencyType = "FS" | "SS" | "FF" | "SF";
export type ADRStatus = "proposed" | "accepted" | "superseded" | "deprecated";
export type Provider = "jira" | "github" | "gdrive";

export interface Project {
  id: number;
  key: string;
  name: string;
  description: string | null;
  start_date: string | null;
  target_date: string | null;
  archived: boolean;
  skip_weekends: boolean;
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
  supersedes_id: number | null;
  pr_links: string[];
  component_ids: number[];
}

export interface Component {
  id: number;
  project_id: number;
  name: string;
  kind: string;
  description: string | null;
  repo_url: string | null;
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
}

export interface CapacityResponse {
  project_id: number;
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
