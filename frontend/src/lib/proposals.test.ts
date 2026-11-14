import { describe, expect, it } from "vitest";

import type {
  GanttTask,
  PreviewCounts,
  ProjectPlanPreview,
  ProposalItem,
} from "../api/types";
import {
  addableFields,
  buildContext,
  buildOverrides,
  coerceInput,
  dayDiff,
  displayValue,
  fieldMeta,
  formatDay,
  formatDayShort,
  formatDelta,
  formatValue,
  ganttForMode,
  groupItems,
  impactChips,
  includedCount,
  itemAttention,
  itemFacts,
  itemKindLabel,
  itemScopeNote,
  itemTitle,
  planDomain,
  planHighlights,
  proposalShape,
  reviewPrompt,
  scheduleUntouched,
  timeAgo,
  visibleFacts,
  withDependents,
  withPrerequisites,
} from "./proposals";

function item(overrides: Partial<ProposalItem>): ProposalItem {
  return {
    id: 1,
    sort_order: 0,
    entity_type: "task",
    action: "create",
    entity_id: null,
    ref: null,
    payload: {},
    before: null,
    reason: null,
    source_kind: null,
    source_label: null,
    source_url: null,
    excluded: false,
    overrides: null,
    overridden_by_user_id: null,
    overridden_by: null,
    overridden_at: null,
    applied_entity_id: null,
    error: null,
    ...overrides,
  };
}

const ctx = buildContext({
  items: [item({ id: 9, ref: "phase", payload: { name: "Hardening", type: "summary" } })],
  lookups: {
    engineer: { "3": "Dana Lee", "4": "Priya Shah" },
    task: { "7": "Build ingest", "8": "Ship" },
    project: { "1": "CHK · Checkout" },
  },
});

describe("values read the way a person says them", () => {
  it("renders empties as an em dash", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue(undefined)).toBe("—");
    expect(formatValue("")).toBe("—");
    expect(formatValue([])).toBe("—");
    expect(displayValue("task", "deadline", null)).toBe("—");
  });
  it("joins arrays and stringifies scalars", () => {
    expect(formatValue(["a", "b"])).toBe("a, b");
    expect(formatValue(5)).toBe("5");
    expect(formatValue(false)).toBe("false");
  });
  it("formats days without a timezone", () => {
    expect(formatDay("2026-03-16")).toBe("Mar 16, 2026");
    expect(formatDay("2026-12-01T10:00:00")).toBe("Dec 1, 2026");
    expect(formatDay(null)).toBe("—");
    expect(formatDayShort("2026-03-16")).toBe("Mar 16");
    expect(dayDiff("2026-03-08", "2026-03-14")).toBe(6);
  });
  it("formats signed deltas", () => {
    expect(formatDelta(7)).toBe("+7d");
    expect(formatDelta(-3)).toBe("−3d");
    expect(formatDelta(0)).toBe("±0");
    expect(formatDelta(null)).toBe("—");
  });
  it("uses units, option labels and names instead of raw ids", () => {
    expect(displayValue("task", "duration", 5, ctx)).toBe("5d");
    expect(displayValue("task", "constraint_start", "2026-03-16", ctx)).toBe("Mar 16, 2026");
    expect(displayValue("task", "assignee_engineer_id", 3, ctx)).toBe("Dana Lee");
    expect(displayValue("task", "assignee_engineer_id", 99, ctx)).toBe("#99");
    expect(displayValue("risk", "status", "mitigating", ctx)).toBe("Mitigating");
    expect(displayValue("dependency", "type", "FS", ctx)).toBe("Finish → start");
    expect(displayValue("task", "type", "summary", ctx)).toBe("Phase");
  });
  it("resolves a ref handle to the staged item it points at", () => {
    expect(displayValue("task", "parent_ref", "phase", ctx)).toBe("Hardening (new)");
    expect(displayValue("task", "parent_ref", "unknown", ctx)).toBe("unknown (new)");
    expect(fieldMeta("task", "parent_ref").label).toBe("Under");
  });
  it("gives the same field a different meaning per entity", () => {
    expect(fieldMeta("risk", "status").options).toContain("mitigating");
    expect(fieldMeta("milestone", "status").options).toContain("hit");
    expect(fieldMeta("task", "made_up_field").label).toBe("Made up field");
  });
});

describe("a change in plain words", () => {
  it("names the kind of change as an action", () => {
    expect(itemKindLabel(item({ payload: { name: "X" } }))).toBe("New task");
    expect(itemKindLabel(item({ payload: { name: "X", type: "summary" } }))).toBe("New phase");
    expect(itemKindLabel(item({ action: "update", entity_id: 7 }))).toBe("Update task");
    expect(itemKindLabel(item({ entity_type: "blocker", action: "resolve" }))).toBe(
      "Resolve blocker"
    );
    expect(itemKindLabel(item({ entity_type: "dependency" }))).toBe("Link tasks");
  });
  it("titles a create by its new name and an update by the live one", () => {
    expect(itemTitle(item({ payload: { name: "External pentest", duration: 5 } }))).toBe(
      "External pentest"
    );
    const rename = item({
      action: "update",
      entity_id: 7,
      payload: { name: "Build the ingest" },
      before: { name: "Build ingest" },
    });
    expect(itemTitle(rename)).toBe("Build ingest");
    expect(itemTitle(item({ entity_type: "blocker", action: "resolve", entity_id: 42 }))).toBe(
      "#42"
    );
  });
  it("titles a dependency by its two ends (names or refs)", () => {
    const dep = item({
      entity_type: "dependency",
      payload: { predecessor_id: 7, successor_ref: "phase" },
    });
    expect(itemTitle(dep, ctx)).toBe("Build ingest → Hardening");
  });
  it("says where a change lands when the proposal's scope doesn't", () => {
    const onTask = item({
      entity_type: "risk",
      payload: { title: "R", scope_level: "task", scope_id: 7 },
    });
    expect(itemScopeNote(onTask, ctx, "project")).toBe("on Build ingest");
    const inProject = item({ payload: { name: "T", project_id: 1 } });
    expect(itemScopeNote(inProject, ctx, "project")).toBeNull();
    expect(itemScopeNote(inProject, ctx, "initiative")).toBe("CHK · Checkout");
  });
});

describe("itemFacts", () => {
  it("pairs an update's values with what they replace, in reading order", () => {
    const facts = itemFacts(
      item({
        action: "update",
        entity_id: 7,
        payload: { assignee_engineer_id: 4, duration: 8 },
        before: { duration: 5, assignee_engineer_id: 3, name: "Build ingest" },
      }),
      ctx
    );
    expect(facts.map((f) => [f.label, f.before, f.after])).toEqual([
      ["Duration", "5d", "8d"],
      ["Assignee", "Dana Lee", "Priya Shah"],
    ]);
    expect(facts.every((f) => f.editable)).toBe(true);
  });
  it("hides scope plumbing and keeps a create's own title out of the read view", () => {
    const create = item({
      payload: { name: "Pentest", duration: 5, parent_ref: "phase", project_id: 1 },
    });
    const facts = itemFacts(create, ctx);
    expect(facts.map((f) => f.field)).toEqual(["name", "parent_ref", "duration"]);
    expect(visibleFacts(create, facts).map((f) => f.field)).toEqual(["parent_ref", "duration"]);
    const parent = facts.find((f) => f.field === "parent_ref");
    expect(parent?.after).toBe("Hardening (new)");
    expect(parent?.editable).toBe(false); // structure, not a value
    expect(facts.find((f) => f.field === "name")?.before).toBeNull();
  });
  it("marks an update that sets what is already there, instead of faking a change", () => {
    const facts = itemFacts(
      item({
        entity_type: "milestone",
        action: "update",
        entity_id: 3,
        payload: { status: "at_risk", target_date: "2026-12-26" },
        before: { status: "at_risk", target_date: "2026-12-12" },
      })
    );
    expect(facts.map((f) => [f.field, f.unchanged])).toEqual([
      ["target_date", false],
      ["status", true],
    ]);
  });
  it("titles a doc link by its title and keeps the URL as a fact", () => {
    const doc = item({
      entity_type: "doc_reference",
      payload: { url: "https://example.com/sow", title: "Pentest SOW", kind: "other" },
    });
    expect(itemTitle(doc)).toBe("Pentest SOW");
    expect(visibleFacts(doc, itemFacts(doc)).map((f) => f.label)).toEqual(["Link", "Doc type"]);
    const bare = item({ entity_type: "doc_reference", payload: { url: "https://example.com/x" } });
    expect(itemTitle(bare)).toBe("https://example.com/x");
  });
  it("doesn't repeat a new task's kind — the card heading already says it", () => {
    const phase = item({ payload: { name: "Hardening", type: "summary" } });
    expect(itemFacts(phase).map((f) => f.field)).toEqual(["name", "type"]); // still editable
    expect(visibleFacts(phase, itemFacts(phase))).toEqual([]);
  });
  it("drops a dependency's ends (they are its title) but keeps its type", () => {
    const dep = item({
      entity_type: "dependency",
      payload: { predecessor_id: 7, successor_id: 8, type: "SS", lag: 2 },
    });
    expect(itemFacts(dep, ctx).map((f) => [f.label, f.after])).toEqual([
      ["Link type", "Start → start"],
      ["Lag", "2d"],
    ]);
  });
  it("surfaces staleness only when the live value moved after staging", () => {
    const stale = item({
      action: "update",
      entity_id: 7,
      payload: { duration: 8 },
      before: { duration: 4 },
      current: { duration: 6 },
      stale: true,
    });
    expect(itemFacts(stale)[0].current).toBe("6d");
    const fresh = item({
      action: "update",
      entity_id: 7,
      payload: { duration: 8 },
      before: { duration: 4 },
      current: { duration: 4 },
    });
    expect(itemFacts(fresh)[0].current).toBeNull();
  });
  it("shows a reviewer's override as the value, keeping the agent's as the record", () => {
    const edited = item({
      payload: { name: "Load test", duration: 5 },
      overrides: { duration: 9, deadline: "2026-10-01" },
    });
    const facts = itemFacts(edited);
    const duration = facts.find((f) => f.field === "duration");
    expect(duration?.after).toBe("9d");
    expect(duration?.proposed).toBe("5d");
    const deadline = facts.find((f) => f.field === "deadline");
    expect(deadline?.added).toBe(true); // the reviewer introduced it
    expect(deadline?.proposed).toBeNull();
  });
});

describe("editing", () => {
  it("offers only addable fields the form knows how to edit", () => {
    const it_ = item({ addable_fields: ["deadline", "assignee_engineer_id", "weird_blob"] });
    expect(addableFields(it_)).toEqual(["deadline", "assignee_engineer_id", "weird_blob"]);
    expect(addableFields(item({ addable_fields: ["tags"] }))).toEqual([]); // a list
    expect(addableFields(item({}))).toEqual([]);
  });
  it("coerces a control's string to the typed value", () => {
    expect(coerceInput(fieldMeta("task", "duration"), "9")).toBe(9);
    expect(coerceInput(fieldMeta("task", "duration"), "lots")).toBe("lots"); // server explains
    expect(coerceInput(fieldMeta("task", "assignee_engineer_id"), "4")).toBe(4);
    expect(coerceInput(fieldMeta("task", "deadline"), "2026-10-01")).toBe("2026-10-01");
    expect(coerceInput(fieldMeta("task", "deadline"), "")).toBeNull();
    expect(coerceInput(fieldMeta("task", "name"), " Keep spaces ")).toBe(" Keep spaces ");
  });
  it("records only what the reviewer genuinely changed", () => {
    const staged = item({ payload: { name: "Load test", duration: 5 }, overrides: { duration: 9 } });
    // A new value overrides; putting the agent's value back is a revert.
    expect(buildOverrides(staged, { name: "Soak test" })).toEqual({
      duration: 9,
      name: "Soak test",
    });
    expect(buildOverrides(staged, { duration: 5 })).toEqual({});
    // Adding a field the agent never set, then clearing it again.
    expect(buildOverrides(staged, { deadline: "2026-10-01" })).toEqual({
      duration: 9,
      deadline: "2026-10-01",
    });
    const added = item({ payload: { name: "X" }, overrides: { deadline: "2026-10-01" } });
    expect(buildOverrides(added, { deadline: null })).toEqual({});
    // Clearing a value the agent DID set is a real override (e.g. unassign).
    const assigned = item({ payload: { name: "X", assignee_engineer_id: 3 } });
    expect(buildOverrides(assigned, { assignee_engineer_id: null })).toEqual({
      assignee_engineer_id: null,
    });
  });
});

describe("the list of changes", () => {
  it("groups by the part of the plan a change touches, schedule first", () => {
    const groups = groupItems([
      item({ id: 1, entity_type: "risk" }),
      item({ id: 2, entity_type: "dependency" }),
      item({ id: 3, entity_type: "task" }),
    ]);
    expect(groups.map((g) => [g.group.label, g.items.map((i) => i.id)])).toEqual([
      ["Schedule", [2, 3]],
      ["Risks", [1]],
    ]);
  });
  it("flags what would fail and what moved, and nothing on an excluded change", () => {
    const pentest = item({ id: 5, payload: { name: "Pentest", parent_ref: "phase" } });
    const issues = [
      {
        item_id: 5,
        project_id: null,
        error: "parent_ref 'phase' does not match any earlier item's ref",
      },
    ];
    const blocked = itemAttention(pentest, issues, ctx);
    expect(blocked?.tone).toBe("error");
    expect(blocked?.message).toContain("“Hardening”");
    expect(itemAttention(item({ id: 6, stale: true, current: { duration: 6 } }), issues)?.tone).toBe(
      "warn"
    );
    expect(itemAttention(item({ id: 6, stale: true, current: null }), [])?.message).toContain(
      "no longer exists"
    );
    expect(itemAttention(item({ id: 5, excluded: true }), issues)).toBeNull();
    expect(itemAttention(item({ id: 7 }), issues)).toBeNull();
    expect(itemAttention(item({ id: 7, error: "task 9 not found in scope" }), [])?.message).toBe(
      "Task 9 not found in scope"
    );
  });
  it("moves changes that build on each other together", () => {
    const batch = [
      item({ id: 1, ref: "phase", payload: { name: "Hardening", type: "summary" } }),
      item({ id: 2, ref: "pentest", payload: { name: "Pentest", parent_ref: "phase" } }),
      item({ id: 3, payload: { name: "Fixes", parent_ref: "phase" } }),
      item({
        id: 4,
        entity_type: "dependency",
        payload: { predecessor_ref: "pentest", successor_id: 9 },
      }),
      item({ id: 5, entity_type: "risk", payload: { title: "Unrelated" } }),
    ];
    // Excluding the phase takes everything under it — and what hangs off *those* — along.
    expect(withDependents(batch, [1])).toEqual([1, 2, 3, 4]);
    expect(withDependents(batch, [2])).toEqual([2, 4]);
    expect(withDependents(batch, [5])).toEqual([5]);
    // Re-including the link brings back the task it points at and the phase above that.
    expect(withPrerequisites(batch, [4])).toEqual([1, 2, 4]);
    expect(withPrerequisites(batch, [3, 5])).toEqual([1, 3, 5]);
  });
  it("counts only non-excluded items", () => {
    expect(
      includedCount([item({ id: 1 }), item({ id: 2, excluded: true }), item({ id: 3 })])
    ).toBe(2);
  });
});

describe("proposalShape", () => {
  it("returns non-zero create/update/resolve chips in a fixed order", () => {
    expect(proposalShape({ resolve: 1, create: 3, update: 2 })).toEqual([
      { action: "create", count: 3, glyph: "+" },
      { action: "update", count: 2, glyph: "~" },
      { action: "resolve", count: 1, glyph: "✓" },
    ]);
  });
  it("omits zero and missing actions", () => {
    expect(proposalShape({ create: 0, update: 1 })).toEqual([
      { action: "update", count: 1, glyph: "~" },
    ]);
    expect(proposalShape(undefined)).toEqual([]);
  });
});

function ganttTask(id: number, start: string, end: string): GanttTask {
  return {
    id,
    text: `T${id}`,
    start_date: start,
    end_date: end,
    baseline_start: null,
    baseline_end: null,
    deadline: null,
    duration: 1,
    progress: 0,
    parent: 0,
    type: "task",
    is_critical: false,
    total_float: 0,
    assignee_engineer_id: null,
    assignee_name: null,
  };
}

function plan(overrides: Partial<ProjectPlanPreview> = {}): ProjectPlanPreview {
  return {
    project_id: 1,
    key: "CHK",
    name: "Checkout",
    current: {
      project_id: 1,
      tasks: [ganttTask(1, "2026-03-02", "2026-03-05"), ganttTask(2, "2026-03-05", "2026-03-07")],
      links: [],
    },
    proposed: {
      project_id: 1,
      tasks: [
        ganttTask(1, "2026-03-02", "2026-03-05"),
        ganttTask(2, "2026-03-07", "2026-03-09"),
        ganttTask(-11, "2026-03-09", "2026-03-13"),
      ],
      links: [],
    },
    end_current: "2026-03-07",
    end_proposed: "2026-03-13",
    end_delta_days: 6,
    critical_current: 2,
    critical_proposed: 3,
    task_changes: [
      {
        task_id: 2,
        name: "T2",
        kind: "shifted",
        is_summary: false,
        item_ids: [],
        start_before: "2026-03-05",
        start_after: "2026-03-07",
        end_before: "2026-03-07",
        end_after: "2026-03-09",
        end_delta_days: 2,
        critical_before: true,
        critical_after: true,
      },
      {
        task_id: -11,
        name: "T-11",
        kind: "added",
        is_summary: false,
        item_ids: [11],
        start_before: null,
        start_after: "2026-03-09",
        end_before: null,
        end_after: "2026-03-13",
        end_delta_days: null,
        critical_before: false,
        critical_after: true,
      },
    ],
    milestones: [],
    new_deadline_misses: [],
    live_schedule_stale: false,
    cycle: false,
    ...overrides,
  };
}

describe("the plan, current ⇄ proposed", () => {
  it("spans both states with one time window so the toggle never rescales", () => {
    expect(planDomain(plan())).toEqual({ min: "2026-03-02", max: "2026-03-13" });
    expect(
      planDomain(plan({ current: { project_id: 1, tasks: [], links: [] }, proposed: null }))
    ).toBeNull();
  });
  it("puts a moved task's current dates in the ghost-bar slot on the proposed side", () => {
    const proposed = ganttForMode(plan(), "proposed");
    const byId = new Map(proposed.tasks.map((t) => [t.id, t]));
    expect(byId.get(1)?.baseline_start).toBeNull(); // didn't move → no ghost
    expect([byId.get(2)?.baseline_start, byId.get(2)?.baseline_end]).toEqual([
      "2026-03-05",
      "2026-03-07",
    ]);
    expect(byId.get(-11)?.baseline_start).toBeNull(); // new → nothing to compare with
    expect(ganttForMode(plan(), "current").tasks).toHaveLength(2);
    // A staged dependency cycle leaves only the current side to draw.
    expect(ganttForMode(plan({ proposed: null }), "proposed").tasks).toHaveLength(2);
  });
  it("tints what the proposal touches — new tasks only where they exist", () => {
    expect([...planHighlights(plan(), "proposed")]).toEqual([
      [2, "shifted"],
      [-11, "added"],
    ]);
    expect([...planHighlights(plan(), "current")]).toEqual([[2, "shifted"]]);
  });
  it("summarises the proposal's shape as plain-language chips", () => {
    const counts: PreviewCounts = {
      tasks_added: 3,
      tasks_edited: 1,
      tasks_shifted: 4,
      dependencies_added: 1,
      milestones_added: 0,
      milestones_edited: 1,
      blockers_raised: 1,
      blockers_resolved: 0,
      risks_added: 2,
      risks_edited: 0,
      outcomes_added: 0,
      outcomes_edited: 0,
      decisions_added: 0,
      docs_added: 0,
    };
    expect(impactChips(counts).map((c) => c.label)).toEqual([
      "3 new tasks",
      "1 task edited",
      "4 tasks move as a result",
      "1 new dependency",
      "1 milestone changed",
      "1 blocker raised",
      "2 new risks",
    ]);
    expect(scheduleUntouched(counts)).toBe(false);
    expect(
      scheduleUntouched({
        ...counts,
        tasks_added: 0,
        tasks_edited: 0,
        tasks_shifted: 0,
        dependencies_added: 0,
      })
    ).toBe(true);
    expect(impactChips({ ...counts, tasks_shifted: 1 })[2].label).toBe("1 task moves as a result");
  });
});

describe("reviewing with Claude", () => {
  it("builds a starter prompt that names the proposal and where it is open", () => {
    const prompt = reviewPrompt({ id: 12, title: "Standup follow-ups" }, "http://x/reviews/12");
    expect(prompt).toContain("proposal #12");
    expect(prompt).toContain("“Standup follow-ups”");
    expect(prompt).toContain("http://x/reviews/12");
  });
  it("reads API timestamps as UTC and phrases them relatively", () => {
    const now = new Date("2026-11-14T12:00:00Z");
    expect(timeAgo("2026-11-14T11:59:40", now)).toBe("just now");
    expect(timeAgo("2026-11-14T11:15:00", now)).toBe("45 min ago");
    expect(timeAgo("2026-11-14T07:00:00Z", now)).toBe("5 h ago");
    expect(timeAgo("2026-11-12T12:00:00", now)).toBe("2 days ago");
    expect(timeAgo("2026-10-01T12:00:00", now)).toBe("Oct 1, 2026");
    expect(timeAgo(null, now)).toBe("");
  });
});
