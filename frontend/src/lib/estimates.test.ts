import { describe, expect, it } from "vitest";

import { estimateSpread, pertMean, spreadConfidence } from "./estimates";

describe("pertMean", () => {
  it("computes the PERT expected value", () => {
    expect(pertMean(2, 5, 14)).toBe((2 + 4 * 5 + 14) / 6);
  });
});

describe("estimateSpread", () => {
  it("is pessimistic minus optimistic", () => {
    expect(estimateSpread(3, 10)).toBe(7);
  });
});

describe("spreadConfidence", () => {
  it("labels a wide spread", () => {
    expect(spreadConfidence(2, 5, 20)).toBe("wide");
  });
  it("labels a moderate spread", () => {
    expect(spreadConfidence(4, 6, 9)).toBe("moderate");
  });
  it("labels a tight spread", () => {
    expect(spreadConfidence(4, 6, 5)).toBe("tight");
  });
});
