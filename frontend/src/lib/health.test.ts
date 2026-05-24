import { describe, expect, it } from "vitest";

import { healthTone } from "./health";

describe("healthTone", () => {
  it("maps known health states", () => {
    expect(healthTone("on_track").label).toBe("On track");
    expect(healthTone("at_risk").badge).toContain("amber");
    expect(healthTone("off_track").badge).toContain("red");
  });

  it("falls back to Auto when health is null", () => {
    expect(healthTone(null).label).toBe("Auto");
    expect(healthTone(undefined).label).toBe("Auto");
  });
});
