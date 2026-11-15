import { describe, expect, it } from "vitest";

import type { DesignDoc, DocKindDef, DocReference } from "../api/types";
import {
  artifactTypeLabel,
  behindPin,
  changedSinceApproval,
  classifyUrl,
  formatLabel,
  groupByKind,
  humanize,
  kindLabel,
  linkChips,
  needsSharing,
  providerLabel,
  revisionSourceLabel,
  slugify,
  sortDocs,
  suggestionTitle,
  syncSummary,
  versionLabel,
} from "./docs";

function doc(over: Partial<DocReference> = {}): DocReference {
  return {
    id: 1,
    scope_level: "project",
    scope_id: 1,
    kind: "prd",
    title: "PRD",
    url: "https://example.com/prd",
    source: "manual",
    owner_engineer_id: null,
    connection_id: null,
    external_field: null,
    link_health: "unchecked",
    last_checked_at: null,
    created_at: "2026-11-01T00:00:00",
    ...over,
  };
}

const ID = "FeJDTrUMxp1SgJzj8o4inL";

describe("classifyUrl", () => {
  it("parses every claude.ai artifact shape", () => {
    expect(classifyUrl(`https://claude.ai/artifact/${ID}`)?.artifactId).toBe(ID);
    expect(classifyUrl(`https://claude.ai/artifact/checkout-design-${ID}#tab`)?.artifactId).toBe(ID);
    const uuid = "5fbea6f3-0b1c-4d2e-8f3a-1b2c3d4e5f6a";
    expect(classifyUrl(`https://claude.ai/code/artifact/${uuid.toUpperCase()}`)?.artifactId).toBe(uuid);
    expect(classifyUrl(`https://preview.claude.ai/artifact/${ID}`)?.provider).toBe("claude");
  });

  it("matches the exact host, never a substring", () => {
    expect(classifyUrl(`https://claude.ai.example.com/artifact/${ID}`)?.provider).toBe("web");
    expect(classifyUrl(`https://evilclaude.ai/artifact/${ID}`)?.provider).toBe("web");
  });

  it("knows the other providers and their media", () => {
    expect(classifyUrl("https://docs.google.com/presentation/d/x/edit")).toMatchObject({
      provider: "gdrive",
      formatHint: "deck",
    });
    expect(classifyUrl("https://github.com/a/b/blob/main/docs/flow.svg")).toMatchObject({
      provider: "github",
      formatHint: "diagram",
    });
    expect(classifyUrl("https://www.figma.com/proto/K/x")?.formatHint).toBe("prototype");
    expect(classifyUrl("https://acme.atlassian.net/wiki/spaces/X/pages/1")?.provider).toBe("confluence");
    expect(classifyUrl("https://acme.atlassian.net/browse/A-1")?.provider).toBe("jira");
  });

  it("flags non-https and rejects non-URLs", () => {
    expect(classifyUrl("http://wiki.example.com/x")?.https).toBe(false);
    expect(classifyUrl("javascript:alert(1)")).toBeNull();
    expect(classifyUrl("not a url")).toBeNull();
  });
});

describe("kinds", () => {
  it("slugs any kind like the backend", () => {
    expect(slugify("Threat Model")).toBe("threat_model");
    expect(slugify("tech-design")).toBe("tech_design");
    expect(slugify("  ")).toBe("other");
    expect(humanize("threat_model")).toBe("Threat model");
  });

  it("labels kinds from the catalog, else from the slug", () => {
    const catalog: DocKindDef[] = [
      { key: "prd", label: "PRD", stage: "define", expected: true, builtin: true, sort_order: 0, doc_count: 1 },
    ];
    expect(kindLabel("prd", catalog)).toBe("PRD");
    expect(kindLabel("api_contract", catalog)).toBe("Api contract");
  });

  it("groups in catalog order, unknown kinds last", () => {
    const catalog: DocKindDef[] = [
      { key: "prd", label: "PRD", stage: "define", expected: true, builtin: true, sort_order: 0, doc_count: 0 },
      { key: "design", label: "Design", stage: "define", expected: true, builtin: true, sort_order: 1, doc_count: 0 },
    ];
    const groups = groupByKind(
      [doc({ id: 1, kind: "zeta" }), doc({ id: 2, kind: "design" }), doc({ id: 3, kind: "prd" })],
      catalog,
    );
    expect(groups.map((g) => g.kind)).toEqual(["prd", "design", "zeta"]);
  });
});

describe("sharing + versions", () => {
  it("applies the sharing rule to Claude docs only", () => {
    expect(needsSharing("claude", "owner")).toBe(true);
    expect(needsSharing("claude", "unknown")).toBe(true);
    expect(needsSharing("claude", "users")).toBe(false);
    expect(needsSharing("gdrive", "unknown")).toBe(false);
  });

  it("spots a doc that moved on after approval or past its pin", () => {
    const moved = doc({ review_status: "approved", approved_version: "r12", current_version: "r14" });
    expect(changedSinceApproval(moved)).toBe(true);
    expect(versionLabel(moved)).toBe("approved r12 → now r14");
    const same = doc({ review_status: "approved", approved_version: "r3", current_version: "r3" });
    expect(changedSinceApproval(same)).toBe(false);
    expect(versionLabel(same)).toBe("r3");
    expect(behindPin("r12", "r14")).toBe(true);
    expect(behindPin(null, "r14")).toBe(false);
  });

  it("sorts best-first and labels providers/formats", () => {
    const sorted = sortDocs([
      doc({ id: 1, title: "B", review_status: null }),
      doc({ id: 2, title: "A", review_status: "approved" }),
      doc({ id: 3, title: "C", review_status: "draft" }),
    ]);
    expect(sorted.map((d) => d.id)).toEqual([2, 3, 1]);
    expect(providerLabel("claude")).toBe("Claude");
    expect(formatLabel("prototype")).toBe("Prototype");
    expect(formatLabel("storyboard")).toBe("Storyboard");
  });

  it("lists scope links first in the chips", () => {
    const design: DesignDoc = {
      ...doc(),
      kind_label: "PRD",
      stage: "define",
      personal: false,
      links: [
        { id: 2, doc_id: 1, entity_type: "decision", entity_id: 7, relation: "basis", pinned_version: "r1", pinned_at: null, created_by_user_id: null, created_at: "", label: "ADR-0007 Bus" },
        { id: 3, doc_id: 1, entity_type: "task", entity_id: 9, relation: "reference", pinned_version: null, pinned_at: null, created_by_user_id: null, created_at: "", label: null },
      ],
    };
    expect(linkChips(design).map((c) => c.text)).toEqual(["Task: #9", "ADR: ADR-0007 Bus"]);
  });
});

describe("docErrorMessage", () => {
  it("reads the structured refusal the doc endpoints send", async () => {
    const { ApiError } = await import("../api/client");
    const { docErrorMessage } = await import("./docs");
    const err = new ApiError(409, JSON.stringify({ detail: { code: "doc_not_shared", message: "Share it first" } }));
    expect(docErrorMessage(err)).toBe("Share it first");
    expect(docErrorMessage(new ApiError(500, "boom"))).toBe("boom");
  });
});

describe("health chips", () => {
  it("collapses repeated flags and puts attention first", async () => {
    const { healthChips, shortHash } = await import("./docs");
    const chips = healthChips([
      { flag: "check_due", severity: "info", message: "", entity_type: null, entity_id: null },
      { flag: "behind_pin", severity: "warning", message: "a", entity_type: "decision", entity_id: 1 },
      { flag: "behind_pin", severity: "warning", message: "b", entity_type: "spec", entity_id: 2 },
    ]);
    expect(chips.map((c) => c.flag)).toEqual(["behind_pin", "check_due"]);
    expect(healthChips(undefined)).toEqual([]);
    expect(shortHash("a".repeat(64))).toBe("aaaaaaaa");
  });
});

describe("organization artifact sync", () => {
  it("names untitled Claude Docs by their type", () => {
    expect(suggestionTitle({ title: null, artifact_type: "claude_docs" })).toBe("Untitled Claude Doc");
    expect(suggestionTitle({ title: "  ", artifact_type: "claude_sheets" })).toBe("Untitled Sheet");
    expect(suggestionTitle({ title: "Returns flow", artifact_type: "code" })).toBe("Returns flow");
    expect(artifactTypeLabel("something_new")).toBe("Artifact");
  });

  it("labels only the version sources worth a mark", () => {
    expect(revisionSourceLabel("sync")).toBe("org sync");
    expect(revisionSourceLabel("session")).toBeNull();
  });

  it("summarises a run in counts", () => {
    const report = {
      full: true,
      complete: true,
      listed: 40,
      paired: 12,
      newly_paired: 1,
      updated: 4,
      new_versions: 3,
      sharing_changed: 1,
      missing: 0,
      unmatched: 2,
      identities: 0,
      ran_at: "2026-11-15T04:00:00",
    };
    expect(syncSummary(report)).toBe(
      "12 tracked docs seen · 3 new versions · 1 sharing change · 2 not matched to an artifact " +
        "(full listing, 2026-11-15 04:00 UTC)",
    );
    expect(syncSummary({ ...report, full: false, paired: 1, new_versions: 0, sharing_changed: 0, unmatched: null })).toBe(
      "1 tracked doc seen (changes only, 2026-11-15 04:00 UTC)",
    );
  });
});
