import { describe, expect, it } from "vitest";

import type { CapacityResponse } from "../api/types";
import { countOverAllocatedWeeks } from "./capacityAttention";

describe("countOverAllocatedWeeks", () => {
  it("returns 0 for undefined data", () => {
    expect(countOverAllocatedWeeks(undefined)).toBe(0);
  });

  it("returns 0 when nothing exceeds 100%", () => {
    const data: CapacityResponse = {
      project_id: null,
      weeks: ["2026-07-06", "2026-07-13"],
      rows: [{ engineer_id: 1, engineer_name: "A", cells: { "2026-07-06": 80, "2026-07-13": 100 } }],
    };
    expect(countOverAllocatedWeeks(data)).toBe(0);
  });

  it("counts each engineer-week strictly over 100%", () => {
    const data: CapacityResponse = {
      project_id: null,
      weeks: ["2026-07-06", "2026-07-13"],
      rows: [
        { engineer_id: 1, engineer_name: "A", cells: { "2026-07-06": 120, "2026-07-13": 50 } },
        { engineer_id: 2, engineer_name: "B", cells: { "2026-07-06": 150, "2026-07-13": 110 } },
      ],
    };
    expect(countOverAllocatedWeeks(data)).toBe(3);
  });

  it("treats a missing cell as 0% (not over-allocated)", () => {
    const data: CapacityResponse = {
      project_id: null,
      weeks: ["2026-07-06"],
      rows: [{ engineer_id: 1, engineer_name: "A", cells: {} }],
    };
    expect(countOverAllocatedWeeks(data)).toBe(0);
  });
});
