import { describe, expect, it } from "vitest";

import { visibleNavItems, type NavContext } from "./nav";

const ctx = (over: Partial<NavContext> = {}): NavContext => ({
  role: "engineer",
  isAdmin: false,
  canContribute: true,
  isFeatureOn: () => true,
  ...over,
});

describe("visibleNavItems", () => {
  it("always shows the core links (my work, portfolio, projects, team, agent setup)", () => {
    const paths = visibleNavItems(ctx({ isFeatureOn: () => false, canContribute: false })).map(
      (n) => n.to,
    );
    expect(paths).toEqual(
      expect.arrayContaining(["/me", "/portfolio", "/projects", "/team", "/agent-setup"]),
    );
  });

  it("hides feature-gated links when their feature is off", () => {
    const off = new Set(["ai.proposals", "portfolio.initiatives", "architecture", "integrations"]);
    const paths = visibleNavItems(ctx({ isFeatureOn: (f) => !off.has(f) })).map((n) => n.to);
    expect(paths).not.toContain("/reviews");
    expect(paths).not.toContain("/initiatives");
    expect(paths).not.toContain("/decisions");
    expect(paths).not.toContain("/connectors");
  });

  it("shows feature-gated links when their feature is on", () => {
    const paths = visibleNavItems(ctx()).map((n) => n.to);
    expect(paths).toEqual(
      expect.arrayContaining(["/reviews", "/initiatives", "/decisions", "/connectors"]),
    );
  });

  it("gates Connectors on contributor permission as well as the integrations feature", () => {
    const paths = visibleNavItems(ctx({ canContribute: false })).map((n) => n.to);
    expect(paths).not.toContain("/connectors");
  });

  it("only shows admin links to admins, grouped separately", () => {
    expect(visibleNavItems(ctx()).some((n) => n.group === "admin")).toBe(false);
    const admin = visibleNavItems(ctx({ isAdmin: true })).filter((n) => n.group === "admin");
    expect(admin.map((n) => n.to)).toEqual([
      "/admin/users",
      "/admin/features",
      "/admin/integrations",
      "/admin/demo",
    ]);
  });

  it("tags the reviews link with its badge", () => {
    const reviews = visibleNavItems(ctx()).find((n) => n.to === "/reviews");
    expect(reviews?.badge).toBe("reviews");
  });
});
