import type { UserRole } from "../api/types";

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  architect: "Architect",
  engineering_manager: "Eng. Manager",
  engineer: "Engineer",
  viewer: "Viewer",
  member: "Member (legacy)",
};

// Roles assignable in the admin UI (legacy `member` is read-only, not offered).
export const ASSIGNABLE_ROLES: UserRole[] = [
  "admin",
  "architect",
  "engineering_manager",
  "engineer",
  "viewer",
];

export function roleLabel(role: string): string {
  return ROLE_LABELS[role as UserRole] ?? role;
}
