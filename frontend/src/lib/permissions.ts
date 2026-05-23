import type { UserRole } from "../api/types";

// Mirrors the backend matrix in app/api/deps.py. Legacy `member` ~= architect.
const PLANNERS: UserRole[] = ["admin", "architect", "engineering_manager", "member"];
const PROJECT_WRITERS: UserRole[] = ["admin", "architect", "member"];

/** Plan / capacity / risk writes + ADR status transitions (admin/architect/eng-manager). */
export function isPlanner(role: UserRole | undefined): boolean {
  return role != null && PLANNERS.includes(role);
}

/** Project create / settings (admin/architect). */
export function canWriteProjects(role: UserRole | undefined): boolean {
  return role != null && PROJECT_WRITERS.includes(role);
}

/** Propose / comment on decisions, edit own tasks (anyone except viewer). */
export function canContribute(role: UserRole | undefined): boolean {
  return role != null && role !== "viewer";
}

export function isViewer(role: UserRole | undefined): boolean {
  return role === "viewer";
}
