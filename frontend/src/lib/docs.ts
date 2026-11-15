/** Design docs (USER_FLOWS §V5): labels, the client-side link classifier the add form uses as
 *  you type, the sharing rule, and grouping. Pure — unit-tested in docs.test.ts. The backend
 *  (`app/services/doc_urls.py`) stays the authority; this mirror only drives hints. */

import { ApiError } from "../api/client";
import type {
  DesignDoc,
  DocHealthFlag,
  DocHealthFlagName,
  DocKindDef,
  DocLinkEntity,
  DocProvider,
  DocReference,
  DocRelation,
  DocReviewStatus,
  DocStage,
  DocVisibility,
} from "../api/types";

export const PROVIDER_LABEL: Record<DocProvider, string> = {
  claude: "Claude",
  gdrive: "Google Drive",
  github: "GitHub",
  figma: "Figma",
  confluence: "Confluence",
  jira: "Jira",
  web: "Web",
};

export const FORMAT_LABEL: Record<string, string> = {
  document: "Doc",
  page: "Page",
  prototype: "Prototype",
  diagram: "Diagram",
  image: "Image",
  deck: "Deck",
  canvas: "Canvas",
  sheet: "Sheet",
  other: "Other",
};

export const FORMATS = Object.keys(FORMAT_LABEL);

export const STATUS_LABEL: Record<DocReviewStatus, string> = {
  draft: "Draft",
  in_review: "In review",
  approved: "Approved",
  superseded: "Superseded",
  archived: "Archived",
};

export const STATUS_TONE: Record<DocReviewStatus | "link", string> = {
  draft: "bg-slate-100 text-slate-600",
  in_review: "bg-sky-100 text-sky-700",
  approved: "bg-emerald-100 text-emerald-700",
  superseded: "bg-slate-100 text-slate-400 line-through",
  archived: "bg-slate-100 text-slate-400",
  link: "bg-slate-50 text-slate-400",
};

export const VISIBILITY_LABEL: Record<DocVisibility, string> = {
  owner: "Only me",
  users: "Named people",
  org: "My organization",
  public: "Anyone with the link",
  unknown: "Not known",
};

export const RELATION_LABEL: Record<DocRelation, string> = {
  basis: "Basis",
  gate: "Gate",
  reference: "Reference",
};

export const RELATION_HINT: Record<DocRelation, string> = {
  basis: "Derived from or decided on this doc — pins its version",
  gate: "Should not complete until the doc is approved",
  reference: "Context for whoever does the work",
};

export const STAGES: DocStage[] = [
  "frame",
  "define",
  "design",
  "decide",
  "plan",
  "build",
  "release",
  "learn",
  "other",
];

export const STAGE_LABEL: Record<DocStage, string> = {
  frame: "Frame",
  define: "Define",
  design: "Design",
  decide: "Decide",
  plan: "Plan",
  build: "Build",
  release: "Release",
  learn: "Learn",
  other: "Other",
};

export const ENTITY_LABEL: Record<DocLinkEntity, string> = {
  project: "Project",
  initiative: "Initiative",
  task: "Task",
  decision: "ADR",
  spec: "Spec",
  milestone: "Milestone",
  outcome: "Outcome",
  risk: "Risk",
  retro: "Retro",
  component: "Component",
};

/** `"Threat Model"` → `threat_model` (the backend's `normalize_slug`). */
export function slugify(raw: string, maxLength = 48): string {
  const slug = raw
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, maxLength)
    .replace(/_+$/g, "");
  return slug || "other";
}

/** `threat_model` → `Threat model`. */
export function humanize(slug: string): string {
  const words = slug.replace(/_/g, " ").trim();
  return words ? words[0].toUpperCase() + words.slice(1) : slug;
}

export function providerLabel(provider: string | undefined): string {
  return PROVIDER_LABEL[(provider ?? "web") as DocProvider] ?? humanize(provider ?? "web");
}

export function formatLabel(format: string | undefined): string {
  return FORMAT_LABEL[format ?? "other"] ?? humanize(format ?? "other");
}

export function statusLabel(status: DocReviewStatus | null | undefined): string {
  return status ? STATUS_LABEL[status] : "Link";
}

export function stageLabel(stage: string): string {
  return STAGE_LABEL[stage as DocStage] ?? humanize(stage);
}

export function isSharedVisibility(visibility: string | null | undefined): boolean {
  return visibility === "users" || visibility === "org" || visibility === "public";
}

/** The sharing rule: a Claude doc joins shared work only once it is shared in Claude. */
export function needsSharing(provider: string | undefined, visibility: string | undefined): boolean {
  return provider === "claude" && !isSharedVisibility(visibility);
}

const CLAUDE_HOSTS = new Set(["claude.ai", "www.claude.ai", "preview.claude.ai"]);

export interface UrlHint {
  provider: DocProvider;
  https: boolean;
  /** A Claude artifact id parsed from the link, when there is one. */
  artifactId: string | null;
  formatHint: string | null;
}

/** Classify a link as it is typed (exact-host match, like the backend — never a substring). */
export function classifyUrl(raw: string): UrlHint | null {
  let url: URL;
  try {
    url = new URL(raw.trim());
  } catch {
    return null;
  }
  if (url.protocol !== "https:" && url.protocol !== "http:") return null;
  const host = url.hostname.toLowerCase();
  const https = url.protocol === "https:";
  const parts = url.pathname.split("/").filter(Boolean);
  if (CLAUDE_HOSTS.has(host)) {
    let slug: string | undefined;
    if (parts[0] === "artifact") slug = parts[1];
    else if (parts[0] === "code" && parts[1] === "artifact") slug = parts[2];
    else if (parts[0] === "public" && parts[1] === "artifacts") slug = parts[2];
    let artifactId: string | null = null;
    if (slug) {
      const uuid = slug.match(/([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$/i);
      const tail = slug.split("-").pop() ?? "";
      artifactId = uuid ? uuid[1].toLowerCase() : /^[A-Za-z0-9]{10,64}$/.test(tail) ? tail : null;
    }
    return { provider: "claude", https, artifactId, formatHint: null };
  }
  if (host === "docs.google.com") {
    const kind = parts[0];
    const formatHint =
      kind === "spreadsheets" ? "sheet" : kind === "presentation" ? "deck" : kind === "drawings" ? "diagram" : "document";
    return { provider: "gdrive", https, artifactId: null, formatHint };
  }
  if (host === "drive.google.com") return { provider: "gdrive", https, artifactId: null, formatHint: null };
  if (host === "github.com" || host === "www.github.com") {
    const file = parts.slice(4).join("/").toLowerCase();
    const formatHint = /\.(md|markdown|rst|txt|pdf)$/.test(file)
      ? "document"
      : /\.(png|jpe?g|gif)$/.test(file)
        ? "image"
        : /\.(svg|drawio|mmd|puml)$/.test(file)
          ? "diagram"
          : /\.html?$/.test(file)
            ? "page"
            : null;
    return { provider: "github", https, artifactId: null, formatHint };
  }
  if (host === "figma.com" || host === "www.figma.com") {
    const formatHint = parts[0] === "proto" ? "prototype" : parts[0] === "slides" ? "deck" : "canvas";
    return { provider: "figma", https, artifactId: null, formatHint };
  }
  if (host.endsWith(".atlassian.net")) {
    if (parts[0] === "wiki") return { provider: "confluence", https, artifactId: null, formatHint: "document" };
    if (parts[0] === "browse") return { provider: "jira", https, artifactId: null, formatHint: null };
  }
  return { provider: "web", https, artifactId: null, formatHint: null };
}

/** The label of a kind: the catalog's when known, else humanized from its slug. */
export function kindLabel(kind: string, catalog?: DocKindDef[]): string {
  const hit = catalog?.find((k) => k.key === kind);
  return hit ? hit.label : humanize(kind);
}

/** Group docs by kind in catalog order (kinds the catalog lacks go last, alphabetically). */
export function groupByKind<T extends DocReference>(
  docs: T[],
  catalog: DocKindDef[] = [],
): { kind: string; docs: T[] }[] {
  const groups = new Map<string, T[]>();
  for (const d of docs) groups.set(d.kind, [...(groups.get(d.kind) ?? []), d]);
  const order = catalog.map((k) => k.key);
  const known = order.filter((k) => groups.has(k));
  const rest = [...groups.keys()].filter((k) => !order.includes(k)).sort();
  return [...known, ...rest].map((kind) => ({ kind, docs: groups.get(kind) ?? [] }));
}

/** True when the doc moved on after it was approved (the version that was signed off is not
 *  the version that is there now). */
export function changedSinceApproval(doc: DocReference): boolean {
  return (
    doc.review_status === "approved" &&
    !!doc.approved_version &&
    !!doc.current_version &&
    doc.approved_version !== doc.current_version
  );
}

/** "r14" · "approved r12 → now r14" · "" */
export function versionLabel(doc: DocReference): string {
  if (changedSinceApproval(doc)) return `approved ${doc.approved_version} → now ${doc.current_version}`;
  return doc.current_version ?? "";
}

export function docTitle(doc: Pick<DocReference, "title" | "url">): string {
  return doc.title || doc.url;
}

/** Links of a doc grouped for "linked to" chips, scope links first. */
export function linkChips(doc: DesignDoc): { key: string; text: string; relation: DocRelation }[] {
  const scopeFirst = (t: string) => (t === "project" || t === "initiative" || t === "task" ? 0 : 1);
  return [...doc.links]
    .sort((a, b) => scopeFirst(a.entity_type) - scopeFirst(b.entity_type) || a.id - b.id)
    .map((l) => ({
      key: `${l.entity_type}:${l.entity_id}`,
      text: `${ENTITY_LABEL[l.entity_type] ?? humanize(l.entity_type)}: ${l.label ?? `#${l.entity_id}`}`,
      relation: l.relation,
    }));
}

/** A pinned basis link whose doc has moved on since it was pinned. */
export function behindPin(pinned: string | null, current: string | null | undefined): boolean {
  return !!pinned && !!current && pinned !== current;
}

/** Best-first sort for a doc list: approved, in review, draft, plain links, then the rest. */
const STATUS_RANK: Record<string, number> = {
  approved: 0,
  in_review: 1,
  draft: 2,
  "": 3,
  superseded: 4,
  archived: 5,
};

export function sortDocs<T extends DocReference>(docs: T[]): T[] {
  return [...docs].sort(
    (a, b) =>
      (STATUS_RANK[a.review_status ?? ""] ?? 3) - (STATUS_RANK[b.review_status ?? ""] ?? 3) ||
      docTitle(a).localeCompare(docTitle(b)),
  );
}

/** The message of a refused doc call (`{detail: {code, message}}`), for inline display. */
export function docErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const body = JSON.parse(err.message) as { detail?: { message?: string } | string };
      if (typeof body.detail === "string") return body.detail;
      if (body.detail?.message) return body.detail.message;
    } catch {
      /* not JSON */
    }
    return err.message;
  }
  return err instanceof Error ? err.message : "Something went wrong";
}

export const HEALTH_LABEL: Record<DocHealthFlagName, string> = {
  unverified: "not checked yet",
  check_due: "check due",
  changed_since_approval: "changed since approval",
  behind_pin: "decision behind the doc",
  gate_open: "gate open",
  restricted: "private in Claude",
  broken: "can't be opened",
};

/** Flags that need a person (they raise project alerts); the rest are a session's to clear. */
export const ATTENTION_FLAGS: ReadonlySet<DocHealthFlagName> = new Set([
  "changed_since_approval",
  "behind_pin",
  "gate_open",
  "restricted",
  "broken",
]);

export function healthTone(flag: DocHealthFlag): string {
  if (flag.severity === "error") return "bg-red-100 text-red-700";
  if (flag.severity === "warning") return "bg-amber-100 text-amber-800";
  return "bg-slate-100 text-slate-500";
}

/** One chip per kind of flag (several behind_pin flags read as one), attention first. */
export function healthChips(flags: DocHealthFlag[] | undefined): DocHealthFlag[] {
  const seen = new Set<string>();
  const out: DocHealthFlag[] = [];
  const ordered = [...(flags ?? [])].sort(
    (a, b) => Number(ATTENTION_FLAGS.has(b.flag)) - Number(ATTENTION_FLAGS.has(a.flag)),
  );
  for (const f of ordered) {
    if (seen.has(f.flag)) continue;
    seen.add(f.flag);
    out.push(f);
  }
  return out;
}

/** A short form of a content hash for the version timeline. */
export function shortHash(hash: string | null): string {
  return hash ? hash.slice(0, 8) : "";
}
