/**
 * A navigable entity that can be shown in the right-side preview drawer before the user
 * commits to a full page navigation. Kept pure (no React) so route resolution is testable
 * and shared between `PreviewLink` (the trigger) and `PreviewPanel` (the "Open" action).
 */
export type PreviewTarget =
  | { kind: "project"; id: number; tab?: string }
  | { kind: "initiative"; id: number }
  | { kind: "scenario"; id: number; initiativeId: number };

/** The full-page route a preview target opens to. */
export function targetPath(t: PreviewTarget): string {
  switch (t.kind) {
    case "project":
      return `/projects/${t.id}${t.tab ? `?tab=${t.tab}` : ""}`;
    case "initiative":
      return `/initiatives/${t.id}`;
    case "scenario":
      return `/initiatives/${t.initiativeId}/scenarios/${t.id}`;
  }
}

/** Human label for the target's kind, e.g. shown as the drawer eyebrow. */
export function targetKindLabel(t: PreviewTarget): string {
  switch (t.kind) {
    case "project":
      return "Project";
    case "initiative":
      return "Initiative";
    case "scenario":
      return "Scenario";
  }
}

/** Stable identity for a target — used to key queries and dedupe re-opens. */
export function targetKey(t: PreviewTarget): string {
  return t.kind === "project" && t.tab ? `${t.kind}:${t.id}:${t.tab}` : `${t.kind}:${t.id}`;
}
