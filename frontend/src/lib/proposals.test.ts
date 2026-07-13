import { describe, expect, it } from "vitest";

import type { ProposalItem } from "../api/types";
import {
  diffRows,
  formatValue,
  includedCount,
  itemHeadline,
  proposalShape,
  targetLabel,
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
    applied_entity_id: null,
    error: null,
    ...overrides,
  };
}

describe("formatValue", () => {
  it("renders empties as an em dash", () => {
    expect(formatValue(null)).toBe("—");
    expect(formatValue(undefined)).toBe("—");
    expect(formatValue("")).toBe("—");
    expect(formatValue([])).toBe("—");
  });
  it("joins arrays and stringifies scalars", () => {
    expect(formatValue(["a", "b"])).toBe("a, b");
    expect(formatValue(5)).toBe("5");
    expect(formatValue(false)).toBe("false");
  });
});

describe("itemHeadline / targetLabel", () => {
  it("uses the payload name for creates", () => {
    const it_ = item({ payload: { name: "External pentest", duration: 5 } });
    expect(itemHeadline(it_)).toBe("Add task — External pentest");
  });
  it("falls back to the before-snapshot label for updates", () => {
    const it_ = item({
      action: "update",
      entity_id: 7,
      payload: { duration: 8 },
      before: { name: "Build ingest", duration: 4 },
    });
    expect(itemHeadline(it_)).toBe("Update task — Build ingest");
  });
  it("describes a dependency by its endpoints (refs or ids)", () => {
    const it_ = item({
      entity_type: "dependency",
      payload: { predecessor_ref: "pentest", successor_id: 12 },
    });
    expect(targetLabel(it_)).toBe("pentest → 12");
  });
  it("labels resolves by the entity id when no text is available", () => {
    const it_ = item({ entity_type: "blocker", action: "resolve", entity_id: 3, payload: {} });
    expect(itemHeadline(it_)).toBe("Resolve blocker — #3");
  });
});

describe("diffRows", () => {
  it("pairs update payload fields with the before-snapshot", () => {
    const rows = diffRows(
      item({
        action: "update",
        entity_id: 7,
        payload: { duration: 8 },
        before: { name: "Build ingest", duration: 4 },
      })
    );
    expect(rows).toEqual([{ field: "duration", before: "4", after: "8", current: null }]);
  });
  it("shows creates without a before and renders refs as pointers", () => {
    const rows = diffRows(
      item({ payload: { name: "Pentest fixes", parent_ref: "phase" } })
    );
    expect(rows).toEqual([
      { field: "name", before: null, after: "Pentest fixes", current: null },
      { field: "parent_ref", before: null, after: "→ phase", current: null },
    ]);
  });
  it("surfaces staleness when the live value moved after staging", () => {
    const rows = diffRows(
      item({
        action: "update",
        entity_id: 7,
        payload: { duration: 8 },
        before: { duration: 4 },
        current: { duration: 6 },
      })
    );
    expect(rows[0]).toEqual({ field: "duration", before: "4", after: "8", current: "6" });
  });
});

describe("includedCount", () => {
  it("counts only non-excluded items", () => {
    expect(
      includedCount([item({}), item({ excluded: true }), item({ id: 3 })])
    ).toBe(2);
  });
});

describe("proposalShape", () => {
  it("returns non-zero create/update/resolve chips in a fixed order", () => {
    const chips = proposalShape({ update: 2, create: 3, resolve: 1 });
    expect(chips.map((c) => c.action)).toEqual(["create", "update", "resolve"]);
    expect(chips.map((c) => c.count)).toEqual([3, 2, 1]);
    expect(chips.map((c) => c.glyph)).toEqual(["+", "~", "✓"]);
  });
  it("omits zero and missing actions", () => {
    expect(proposalShape({ create: 2 }).map((c) => c.action)).toEqual(["create"]);
    expect(proposalShape({ update: 0 })).toEqual([]);
    expect(proposalShape(undefined)).toEqual([]);
  });
});
