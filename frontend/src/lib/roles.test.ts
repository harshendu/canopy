import { describe, expect, it } from "vitest";

import { ASSIGNABLE_ROLES, roleLabel } from "./roles";

describe("roleLabel", () => {
  it("labels known roles and notes the legacy one", () => {
    expect(roleLabel("engineering_manager")).toBe("Eng. Manager");
    expect(roleLabel("member")).toBe("Member (legacy)");
  });

  it("falls back to the raw value for unknown roles", () => {
    expect(roleLabel("superuser")).toBe("superuser");
  });
});

describe("ASSIGNABLE_ROLES", () => {
  it("offers the five real roles and excludes the legacy member", () => {
    expect(ASSIGNABLE_ROLES).toHaveLength(5);
    expect(ASSIGNABLE_ROLES).not.toContain("member");
  });
});
