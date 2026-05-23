import { describe, expect, it } from "vitest";

import { riskTone, scoreBar } from "./risk";

describe("riskTone", () => {
  it("maps known levels", () => {
    expect(riskTone("critical").label).toBe("Critical");
    expect(riskTone("low").bar).toBe("bg-emerald-500");
  });

  it("falls back for an unknown level", () => {
    expect(riskTone("bogus").label).toBe("Unknown");
  });
});

describe("scoreBar", () => {
  it("ramps by severity", () => {
    expect(scoreBar(0)).toBe("bg-emerald-500");
    expect(scoreBar(30)).toBe("bg-amber-500");
    expect(scoreBar(50)).toBe("bg-orange-500");
    expect(scoreBar(90)).toBe("bg-red-600");
  });
});
