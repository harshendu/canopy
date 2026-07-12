import { describe, expect, it } from "vitest";

import { featureOn } from "./useFeatures";
import { personaHome } from "./persona";

describe("featureOn", () => {
  it("defaults unknown/unloaded keys to on", () => {
    expect(featureOn({}, "tracking.board")).toBe(true);
  });

  it("respects an explicit off", () => {
    expect(featureOn({ "tracking.board": false }, "tracking.board")).toBe(false);
    expect(featureOn({ "tracking.board": true }, "tracking.board")).toBe(true);
  });
});

describe("personaHome with feature gates", () => {
  it("keeps the persona landing when its surface is on", () => {
    expect(personaHome("product", {})).toBe("/initiatives");
    expect(personaHome("architecture", {})).toBe("/decisions");
    expect(personaHome("engineering", {})).toBe("/me");
  });

  it("falls back to /projects when the landing surface is gated off", () => {
    expect(personaHome("product", { "portfolio.initiatives": false })).toBe("/projects");
    expect(personaHome("design", { "portfolio.initiatives": false })).toBe("/projects");
    expect(personaHome("architecture", { architecture: false })).toBe("/projects");
  });

  it("leaves ungated landings alone", () => {
    expect(personaHome("management", { "portfolio.initiatives": false })).toBe("/team");
    expect(personaHome(undefined, { architecture: false })).toBe("/projects");
  });
});
