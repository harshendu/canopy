import { describe, expect, it } from "vitest";

import {
  EXPIRY_OPTIONS,
  cloneSnippet,
  daysUntil,
  expiryPhrase,
  mcpJsonSnippet,
  mcpServerDisplayPath,
  repoDirName,
  statusChipClass,
} from "./agentSetup";

const DAY = 24 * 60 * 60 * 1000;
const NOW = Date.UTC(2026, 6, 13); // 2026-07-13

describe("agentSetup", () => {
  it("offers 7/14/30-day lifetimes (backend caps at 30)", () => {
    expect(EXPIRY_OPTIONS.map((o) => o.minutes)).toEqual([
      7 * 24 * 60,
      14 * 24 * 60,
      30 * 24 * 60,
    ]);
  });

  it("daysUntil rounds up and goes negative once past", () => {
    expect(daysUntil(new Date(NOW + 7 * DAY).toISOString(), NOW)).toBe(7);
    expect(daysUntil(new Date(NOW - 1 * DAY).toISOString(), NOW)).toBe(-1);
    expect(daysUntil("not-a-date", NOW)).toBe(0);
  });

  it("expiryPhrase reflects status", () => {
    const future = new Date(NOW + 6 * DAY).toISOString();
    expect(expiryPhrase({ status: "active", expires_at: future }, NOW)).toContain("in 6 days");
    expect(expiryPhrase({ status: "revoked", expires_at: future }, NOW)).toBe("Revoked");
    expect(expiryPhrase({ status: "expired", expires_at: future }, NOW)).toContain("Expired");
  });

  it("statusChipClass covers every status", () => {
    for (const s of ["active", "expired", "revoked"] as const) {
      expect(statusChipClass(s)).toMatch(/border-/);
    }
  });

  it("repoDirName strips .git and trailing slashes, falls back to canopy", () => {
    expect(repoDirName("https://github.com/harshendu/canopy.git")).toBe("canopy");
    expect(repoDirName("https://github.com/acme/canopy-fork.git")).toBe("canopy-fork");
    expect(repoDirName("git@github.com:acme/plat.git")).toBe("plat");
    expect(repoDirName("https://example.com/repo/")).toBe("repo");
    expect(repoDirName("")).toBe("canopy");
  });

  it("cloneSnippet is driven by the configured repo URL (not a hardcoded fork)", () => {
    const snippet = cloneSnippet("https://github.com/acme/canopy-fork.git");
    expect(snippet).toContain("git clone https://github.com/acme/canopy-fork.git");
    expect(snippet).toContain("cd canopy-fork/plugin");
    expect(snippet).toContain("pip install -r mcp_server/requirements.txt");
  });

  it("mcpServerDisplayPath composes the configured repo dir + in-repo server path", () => {
    expect(
      mcpServerDisplayPath("https://github.com/acme/canopy-fork.git", "plugin/mcp_server/server.py"),
    ).toBe("/path/to/canopy-fork/plugin/mcp_server/server.py");
  });

  it("mcpJsonSnippet wires the token + base URL into a valid stdio config", () => {
    const snippet = mcpJsonSnippet("http://localhost:8000", "tok-123", "/srv/server.py");
    const parsed = JSON.parse(snippet) as {
      mcpServers: {
        canopy: { command: string; args: string[]; env: Record<string, string> };
      };
    };
    expect(parsed.mcpServers.canopy.command).toBe("python");
    expect(parsed.mcpServers.canopy.args).toEqual(["/srv/server.py"]);
    expect(parsed.mcpServers.canopy.env.CANOPY_API_TOKEN).toBe("tok-123");
    expect(parsed.mcpServers.canopy.env.CANOPY_API_BASE_URL).toBe("http://localhost:8000");
  });
});
