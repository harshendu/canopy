import type { AgentTokenInfo } from "../api/types";

/** Placeholder dropped into the setup snippets until the user generates a real token. */
export const TOKEN_PLACEHOLDER = "<your-agent-token>";

export interface ExpiryOption {
  label: string;
  minutes: number;
}

/** Lifetimes offered when minting (backend caps at 30 days). */
export const EXPIRY_OPTIONS: ExpiryOption[] = [
  { label: "7 days", minutes: 7 * 24 * 60 },
  { label: "14 days", minutes: 14 * 24 * 60 },
  { label: "30 days", minutes: 30 * 24 * 60 },
];

export function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

/** Whole days from `now` (ms epoch) until `iso`, rounded up; negative once past. Pure. */
export function daysUntil(iso: string, now: number): number {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return 0;
  return Math.ceil((t - now) / (24 * 60 * 60 * 1000));
}

/** A short human phrase for a token's expiry, given its display status. Pure (takes `now`). */
export function expiryPhrase(
  info: Pick<AgentTokenInfo, "status" | "expires_at">,
  now: number,
): string {
  if (info.status === "revoked") return "Revoked";
  if (info.status === "expired") return `Expired ${formatDate(info.expires_at)}`;
  const days = daysUntil(info.expires_at, now);
  const rel = days <= 0 ? "today" : days === 1 ? "in 1 day" : `in ${days} days`;
  return `Expires ${formatDate(info.expires_at)} · ${rel}`;
}

const STATUS_CHIP: Record<AgentTokenInfo["status"], string> = {
  active: "border-canopy-500/30 bg-canopy-50 text-canopy-700",
  expired: "border-slate-200 bg-slate-100 text-slate-500",
  revoked: "border-red-200 bg-red-50 text-red-700",
};

export function statusChipClass(status: AgentTokenInfo["status"]): string {
  return STATUS_CHIP[status];
}

/** The directory `git clone <url>` creates — the URL's last path segment without a trailing
 *  `.git` or slashes. Falls back to "canopy" for an unparseable URL. Pure. */
export function repoDirName(repoUrl: string): string {
  const last = repoUrl.replace(/\/+$/, "").split("/").pop() ?? "";
  const name = last.replace(/\.git$/, "").trim();
  return name || "canopy";
}

/** MCP-only bootstrap: clone the repo, enter its plugin dir, make a venv, install deps. Pure —
 *  driven by the deployment's configured repo URL (§GET /meta), not a hardcoded fork. */
export function cloneSnippet(repoUrl: string): string {
  return [
    `git clone ${repoUrl}`,
    `cd ${repoDirName(repoUrl)}/plugin`,
    "python -m venv .venv && . .venv/bin/activate",
    "pip install -r mcp_server/requirements.txt",
  ].join("\n");
}

/** Display path for the `.mcp.json` `args` entry: an obvious `/path/to/` prefix the user swaps
 *  for their real clone location, plus the config-driven repo dir + in-repo server path. Pure. */
export function mcpServerDisplayPath(repoUrl: string, serverPathInRepo: string): string {
  return `/path/to/${repoDirName(repoUrl)}/${serverPathInRepo}`;
}

/** The `.mcp.json` a user pastes to run the stdio MCP server directly (no full plugin). The MCP
 *  server reads `CANOPY_API_TOKEN` to call the canopy API as the token's issuer. */
export function mcpJsonSnippet(apiBaseUrl: string, token: string, serverPath: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        canopy: {
          command: "python",
          args: [serverPath],
          env: {
            CANOPY_API_BASE_URL: apiBaseUrl,
            CANOPY_API_TOKEN: token,
          },
        },
      },
    },
    null,
    2,
  );
}
