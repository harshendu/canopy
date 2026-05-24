export const DRIFT_KIND_LABELS: Record<string, string> = {
  unexpected_dependency: "Unexpected dependency",
  dead_dependency: "Dead (declared, unbuilt) dependency",
  unimplemented_adr: "Unimplemented decision",
  implicit_decision: "Implicit decision (no ADR)",
  fitness_violation: "Fitness violation (decision broken)",
};

export function driftKindLabel(kind: string): string {
  return DRIFT_KIND_LABELS[kind] ?? kind;
}

export const RECONCILE_ACTIONS: { action: string; label: string; hint: string }[] = [
  { action: "accepted", label: "Accept → ADR", hint: "Propose an ADR for this change" },
  { action: "rejected", label: "Reject → task", hint: "Open a task to revert it" },
  { action: "false_positive", label: "False positive", hint: "Suppress this rule going forward" },
];
