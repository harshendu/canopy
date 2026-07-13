import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "../api/client";
import type { AgentToken, AgentTokenInfo } from "../api/types";
import { featureOn, useFeatures } from "../lib/useFeatures";
import {
  EXPIRY_OPTIONS,
  TOKEN_PLACEHOLDER,
  expiryPhrase,
  formatDate,
  mcpJsonSnippet,
  statusChipClass,
} from "../lib/agentSetup";
import { PageHeader } from "../components/PageHeader";

/** Copy-to-clipboard button with a brief "Copied" confirmation. */
function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => {
        void navigator.clipboard?.writeText(text);
        setCopied(true);
        setTimeout(() => setCopied(false), 1500);
      }}
      className="shrink-0 rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
    >
      {copied ? "Copied" : label}
    </button>
  );
}

/** A read-only, horizontally-scrolling code block with a copy button. */
function CodeBlock({ code }: { code: string }) {
  return (
    <div className="flex items-start gap-2 rounded border border-slate-200 bg-slate-50 p-2">
      <pre className="min-w-0 flex-1 overflow-x-auto whitespace-pre font-mono text-xs text-slate-800">
        {code}
      </pre>
      <CopyButton text={code} />
    </div>
  );
}

const DEFAULT_EXPIRY = EXPIRY_OPTIONS[0].minutes;

export default function AgentSetup() {
  const qc = useQueryClient();
  const features = useFeatures();
  const canMint = featureOn(features, "ai.agent_tokens");

  const [label, setLabel] = useState("");
  const [expiryMinutes, setExpiryMinutes] = useState(DEFAULT_EXPIRY);
  const [justMinted, setJustMinted] = useState<AgentToken | null>(null);
  const [confirmingId, setConfirmingId] = useState<number | null>(null);
  const [mode, setMode] = useState<"plugin" | "mcp">("plugin");

  const tokens = useQuery({
    queryKey: ["agent-tokens"],
    queryFn: () => api.get<AgentTokenInfo[]>("/auth/agent-tokens"),
  });

  const generate = useMutation({
    mutationFn: () =>
      api.post<AgentToken>("/auth/agent-token", {
        label: label.trim() || null,
        expires_minutes: expiryMinutes,
      }),
    onSuccess: (token) => {
      setJustMinted(token);
      setLabel("");
      void qc.invalidateQueries({ queryKey: ["agent-tokens"] });
    },
  });

  const revoke = useMutation({
    mutationFn: (id: number) => api.del(`/auth/agent-tokens/${id}`),
    onSuccess: () => {
      setConfirmingId(null);
      void qc.invalidateQueries({ queryKey: ["agent-tokens"] });
    },
  });

  const now = Date.now();
  const apiBaseUrl = window.location.origin;
  const activeToken = justMinted?.access_token ?? TOKEN_PLACEHOLDER;
  const serverPath = "/path/to/canopy/plugin/mcp_server/server.py";

  return (
    <div className="max-w-3xl space-y-8">
      <PageHeader
        title="Agent Setup"
        subtitle={
          <>
            Generate an access token so Claude Code can work in canopy on your behalf through the
            MCP server, then connect it as a full plugin or a bare MCP server. The token is{" "}
            <strong>agent-scoped</strong>: it carries your own permissions but is blocked from
            one-way-door / external-write actions (accepting an irreversible decision, pushing to
            Jira, applying a scenario) — those stay human-only.
          </>
        }
      />

      {/* --- Token management --- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Your MCP token</h2>

        {canMint ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              generate.mutate();
            }}
            className="flex flex-wrap items-end gap-3 rounded-lg border border-slate-200 bg-white p-4"
          >
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              Name (optional)
              <input
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                placeholder="e.g. My laptop"
                className="w-48 rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
              />
            </label>
            <label className="flex flex-col gap-1 text-xs font-medium text-slate-500">
              Expires
              <select
                value={expiryMinutes}
                onChange={(e) => setExpiryMinutes(Number(e.target.value))}
                className="rounded border border-slate-300 px-3 py-2 text-sm font-normal text-slate-800"
              >
                {EXPIRY_OPTIONS.map((o) => (
                  <option key={o.minutes} value={o.minutes}>
                    {o.label}
                  </option>
                ))}
              </select>
            </label>
            <button
              disabled={generate.isPending}
              className="rounded bg-canopy-500 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {generate.isPending ? "Generating…" : "Generate token"}
            </button>
          </form>
        ) : (
          <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
            Token generation is turned off by an administrator (the{" "}
            <code className="rounded bg-amber-100 px-1">Bounded agent tokens</code> feature). You can
            still revoke existing tokens and follow the setup steps below.
          </div>
        )}

        {generate.isError && (
          <p className="text-sm text-red-600">{(generate.error as Error).message}</p>
        )}

        {justMinted && (
          <div className="space-y-2 rounded-lg border border-canopy-500/40 bg-canopy-50 p-4">
            <div className="flex items-center justify-between">
              <span className="text-sm font-semibold text-canopy-700">
                Token “{justMinted.label}” created
              </span>
              <span className="text-xs text-canopy-700">
                Expires {formatDate(justMinted.expires_at)}
              </span>
            </div>
            <p className="text-xs text-slate-600">
              Copy it now — for your security this is the <strong>only</strong> time the token is
              shown. It drops into the setup steps below automatically.
            </p>
            <CodeBlock code={justMinted.access_token} />
          </div>
        )}

        <div className="divide-y divide-slate-200 rounded-lg border border-slate-200 bg-white">
          {tokens.isLoading && (
            <div className="px-4 py-6 text-center text-sm text-slate-400">Loading…</div>
          )}
          {tokens.data?.map((t) => (
            <div key={t.id} className="flex flex-wrap items-center gap-3 px-4 py-3">
              <span className="min-w-0 flex-1 truncate font-medium text-slate-800">{t.label}</span>
              <span
                className={`rounded-full border px-2 py-0.5 text-xs font-medium capitalize ${statusChipClass(
                  t.status,
                )}`}
              >
                {t.status}
              </span>
              <span className="text-xs text-slate-500">{expiryPhrase(t, now)}</span>
              {t.status === "revoked" ? (
                <span className="w-16 text-right text-xs text-slate-300">—</span>
              ) : confirmingId === t.id ? (
                <span className="flex items-center gap-2">
                  <button
                    onClick={() => revoke.mutate(t.id)}
                    disabled={revoke.isPending}
                    className="rounded bg-red-600 px-2 py-1 text-xs font-medium text-white disabled:opacity-50"
                  >
                    Confirm
                  </button>
                  <button
                    onClick={() => setConfirmingId(null)}
                    className="text-xs text-slate-400 hover:text-slate-600"
                  >
                    Cancel
                  </button>
                </span>
              ) : (
                <button
                  onClick={() => setConfirmingId(t.id)}
                  className="rounded border border-slate-300 px-2 py-1 text-xs font-medium text-slate-600 hover:bg-slate-50"
                >
                  Revoke
                </button>
              )}
            </div>
          ))}
          {tokens.data?.length === 0 && (
            <div className="px-4 py-6 text-center text-sm text-slate-400">
              No tokens yet. Generate one above to connect Claude.
            </div>
          )}
        </div>
        {revoke.isError && <p className="text-sm text-red-600">{(revoke.error as Error).message}</p>}
      </section>

      {/* --- Setup instructions --- */}
      <section className="space-y-4">
        <h2 className="text-lg font-semibold">Connect Claude Code</h2>
        <div className="inline-flex rounded-lg border border-slate-200 bg-slate-50 p-0.5 text-sm">
          <button
            onClick={() => setMode("plugin")}
            className={`rounded-md px-3 py-1.5 font-medium ${
              mode === "plugin" ? "bg-white text-canopy-700 shadow-sm" : "text-slate-500"
            }`}
          >
            Full plugin
          </button>
          <button
            onClick={() => setMode("mcp")}
            className={`rounded-md px-3 py-1.5 font-medium ${
              mode === "mcp" ? "bg-white text-canopy-700 shadow-sm" : "text-slate-500"
            }`}
          >
            MCP only
          </button>
        </div>

        {!justMinted && (
          <p className="text-xs text-slate-400">
            Generate a token above and it will be filled into the commands below; until then they
            show a <code className="rounded bg-slate-100 px-1">{TOKEN_PLACEHOLDER}</code>{" "}
            placeholder.
          </p>
        )}

        {mode === "plugin" ? (
          <ol className="space-y-4 text-sm text-slate-700">
            <li>
              <p className="font-medium">1. Add the canopy plugin marketplace</p>
              <p className="mb-1 text-slate-500">
                In Claude Code, run this slash command (use your own repository if you forked it):
              </p>
              <CodeBlock code="/plugin marketplace add harshendu/canopy" />
            </li>
            <li>
              <p className="font-medium">2. Install the plugin</p>
              <CodeBlock code="/plugin install canopy@canopy" />
            </li>
            <li>
              <p className="font-medium">3. Configure it when prompted</p>
              <p className="mb-1 text-slate-500">
                Set <code className="rounded bg-slate-100 px-1">api_base_url</code> and{" "}
                <code className="rounded bg-slate-100 px-1">api_token</code> (leave{" "}
                <code className="rounded bg-slate-100 px-1">api_email</code>/
                <code className="rounded bg-slate-100 px-1">api_password</code> blank):
              </p>
              <CodeBlock code={`api_base_url = ${apiBaseUrl}\napi_token    = ${activeToken}`} />
            </li>
            <li>
              <p className="font-medium">4. Start a session</p>
              <p className="text-slate-500">
                The canopy MCP tools, skills, and subagents are now available. Ask Claude something
                like “show me the portfolio” to confirm the connection.
              </p>
            </li>
          </ol>
        ) : (
          <ol className="space-y-4 text-sm text-slate-700">
            <li>
              <p className="font-medium">1. Get the MCP server + its dependencies</p>
              <p className="mb-1 text-slate-500">
                The server ships in the canopy repo. Clone it and install its Python deps:
              </p>
              <CodeBlock
                code={
                  "git clone https://github.com/harshendu/canopy.git\n" +
                  "cd canopy/plugin\n" +
                  "python -m venv .venv && . .venv/bin/activate\n" +
                  "pip install -r mcp_server/requirements.txt"
                }
              />
            </li>
            <li>
              <p className="font-medium">2. Register the server with Claude Code</p>
              <p className="mb-1 text-slate-500">
                Add this to your project’s{" "}
                <code className="rounded bg-slate-100 px-1">.mcp.json</code> (replace the{" "}
                <code className="rounded bg-slate-100 px-1">args</code> path with where you cloned
                it):
              </p>
              <CodeBlock code={mcpJsonSnippet(apiBaseUrl, activeToken, serverPath)} />
            </li>
            <li>
              <p className="font-medium">3. Restart Claude Code</p>
              <p className="text-slate-500">
                It launches the server over stdio and authenticates to canopy with your token — no
                plugin, skills, or subagents, just the MCP tools.
              </p>
            </li>
          </ol>
        )}

        <p className="rounded-lg border border-slate-200 bg-slate-50 px-4 py-3 text-xs text-slate-500">
          <strong>API URL:</strong> the steps use{" "}
          <code className="rounded bg-slate-100 px-1">{apiBaseUrl}</code> (this dashboard’s origin).
          In local development the backend usually runs separately at{" "}
          <code className="rounded bg-slate-100 px-1">http://localhost:8000</code> — use that
          instead. A team running a shared, always-on MCP server over HTTPS should follow{" "}
          <code className="rounded bg-slate-100 px-1">docs/PRODUCTION.md</code> instead of a local
          token.
        </p>
      </section>
    </div>
  );
}
