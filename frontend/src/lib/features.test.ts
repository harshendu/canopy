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
    // Product/leadership/design land on the cross-project Home (§B1) — read-first, and always
    // on (unlike /initiatives, which needs portfolio.initiatives), so no gate fallback applies.
    expect(personaHome("product", {})).toBe("/portfolio");
    expect(personaHome("leadership", {})).toBe("/portfolio");
    expect(personaHome("design", {})).toBe("/portfolio");
    expect(personaHome("architecture", {})).toBe("/decisions");
    expect(personaHome("engineering", {})).toBe("/me");
  });

  it("falls back to /projects when the landing surface is gated off", () => {
    expect(personaHome("architecture", { architecture: false })).toBe("/projects");
  });

  it("leaves ungated landings alone", () => {
    expect(personaHome("product", { "portfolio.initiatives": false })).toBe("/portfolio");
    expect(personaHome("management", { "portfolio.initiatives": false })).toBe("/team");
    expect(personaHome(undefined, { architecture: false })).toBe("/projects");
  });
});
