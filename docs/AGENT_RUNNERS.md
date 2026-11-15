# Running agent sessions against canopy

canopy is the work queue and the keeper of rules and decisions; it never starts a session
itself (`AGENT_EXECUTION.md` §15, principle P2). Something you run does. This page has a recipe
for each kind of runner, from a person's own terminal to an unattended daemon, plus how to start
sessions the moment work is ready. Every recipe uses the same contract — the
`working-the-queue` skill (`plugin/skills/working-the-queue/SKILL.md`) — and the same MCP tools.

| Runner | Starts a session when | Supervised by | Recipe |
|---|---|---|---|
| Interactive | an engineer asks for their next task | the engineer | [1](#1-interactive) |
| `/loop` | a minute-scale loop in an open session | the person at the terminal | [2](#2-a-loop-in-an-open-session) |
| Headless `claude -p` | cron or CI fires | nobody — containment matters | [3](#3-headless-claude--p-cron-or-ci) |
| Scheduled cloud session | a Claude Code scheduled task fires | nobody | [4](#4-a-scheduled-cloud-session) |
| Reviewer on PR events | a pull request opens or changes | nobody | [5](#5-a-reviewer-on-pull-request-events) |
| SDK daemon | work is ready for its role | the daemon's limits | [6](#6-the-reference-sdk-daemon) |
| Push start | canopy says work is ready | the runner it starts | [7](#7-push-starts-from-canopy-webhooks) |

**Before any runner:** a person delegates tasks (task panel → *Delegate to agents*) and switches
the project's intake on (project → Execution → Agents). Mint an agent token on **Agent Setup**,
scoped to the role (and project) the runner works; one token per concurrent session.

## 1. Interactive

Install the canopy plugin, paste the agent token into its settings, and in a checkout of the
repository ask: *"Work on my next canopy task."* The session claims a task, reads its brief,
plans, implements and hands off; you watch and steer. Supervised work is the place to start.

## 2. A loop in an open session

`/loop 10m Work on the next canopy task for the implementer role; if nothing is ready, say why
and stop.` — a supervised worker that keeps pulling. Loops have a one-minute minimum interval,
recurring loops expire after seven days, and the loop ends with the terminal.

## 3. Headless `claude -p` (cron or CI)

One task per run, in a clean checkout or container:

```bash
claude -p "Work on the next canopy task for the implementer role. Follow the working-the-queue
skill. If nothing is ready, say why and stop." \
  --permission-mode dontAsk \
  --allowedTools "Read,Glob,Grep,Edit,Write,Bash,mcp__canopy" \
  --max-turns 80 --max-budget-usd 5
```

- Non-interactive runs start in the default permission mode, so set `--permission-mode` and
  `--allowedTools`; there is no one to answer a prompt.
- `AskUserQuestion` and MCP elicitation aren't available unattended: `ask_human` is the
  channel — it opens a decision in canopy and ends the claim.
- Keep plugins and hooks on (don't use `--bare`): the hooks renew the claim and ask the session
  to hand off before it ends.
- The plugin's MCP server reads the token from the plugin settings, or point the session at a
  per-caller HTTP server with `--mcp-config` and the token in an `Authorization` header.

## 4. A scheduled cloud session

Create a Claude Code scheduled task per repository and role with the worker prompt from recipe
3. Each run is a fresh clone; canopy is reached over its HTTP MCP endpoint (run the server with
`CANOPY_MCP_AUTH_MODE=per_caller` and give each scheduled task its own agent token). Schedules
run at most hourly — for faster pickup, use a push start (recipe 7).

## 5. A reviewer on pull-request events

A GitHub workflow that starts a reviewer session when a PR opens or changes. The reviewer claims
the task in *In Review* (canopy refuses if the same session implemented it), reviews against the
brief, and submits a verdict; it has no edit tools, so it can't be talked into changing the code.

```yaml
name: canopy reviewer
on:
  pull_request:
    types: [opened, synchronize, ready_for_review]
permissions:
  contents: read
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { persist-credentials: false }
      - run: npm install -g @anthropic-ai/claude-code
      - name: Review the PR's canopy task
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          CANOPY_MCP_URL: ${{ vars.CANOPY_MCP_URL }}
          CANOPY_REVIEWER_TOKEN: ${{ secrets.CANOPY_REVIEWER_TOKEN }}
        run: |
          cat > /tmp/mcp.json <<JSON
          {"mcpServers": {"canopy": {"type": "http", "url": "$CANOPY_MCP_URL",
            "headers": {"Authorization": "Bearer $CANOPY_REVIEWER_TOKEN"}}}}
          JSON
          claude -p "Claim the next canopy task ready for review in this repository with claim_work(role=\"reviewer\", repo=\"$GITHUB_REPOSITORY\"), review it against its brief, and submit your verdict. If nothing is ready for review, say why and stop." \
            --mcp-config /tmp/mcp.json \
            --permission-mode dontAsk \
            --allowedTools "Read,Glob,Grep,Bash(git diff *),Bash(git log *),mcp__canopy" \
            --disallowedTools "Edit,Write,NotebookEdit" \
            --max-turns 40 --max-budget-usd 3
```

Nothing from the pull request (its title, branch or body) goes into the script or the prompt:
those are attacker-controlled text, and interpolating `${{ github.event.* }}` into a `run:`
block is a script-injection hole. canopy's queue already knows which tasks wait in review for
this repository. The token is a reviewer-scoped agent token: it can't approve, merge, or decide
anything — sign-off stays with a person (or a PR approval from someone other than the
requester, decision D3).

## 6. The reference SDK daemon

[`runners/sdk/`](../runners/sdk/README.md) is a small daemon on the Claude Agent SDK: one slot
per agent token, long-polling for ready work, one isolated session per claim in its own git
worktree, a heartbeat for the claim while the session runs, `max_turns` and `max_budget_usd` per
session, and a release with a note when a session stops without handing off. It reports each
session's cost to canopy, which shows cost per completed task in the Agents view.

```bash
CANOPY_AGENT_TOKENS=t1,t2 CANOPY_RUNNER_ROLE=implementer CANOPY_RUNNER_REPO_DIR=/srv/shop \
  python runners/sdk/canopy_runner.py
```

## 7. Push starts from canopy webhooks

Instead of polling, let canopy say when work is ready. Add a webhook (project → Integrations →
Notifications, or a team's or the workspace's) that hears `work.ready`. The payload is the task
key and the role and nothing more — a forged or replayed call can start a session but can't hand
it work, because the session still claims through canopy. Verify the signature anyway:

```python
# A relay that turns canopy's work.ready into a GitHub repository_dispatch.
import hashlib
import hmac
import os

import httpx
from fastapi import FastAPI, HTTPException, Request

app = FastAPI()
SECRET = os.environ["CANOPY_WEBHOOK_SECRET"].encode()
REPO = os.environ["GITHUB_REPOSITORY"]  # owner/name


@app.post("/canopy")
async def canopy(request: Request) -> dict[str, bool]:
    body = await request.body()
    expected = "sha256=" + hmac.new(SECRET, body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, request.headers.get("X-Canopy-Signature", "")):
        raise HTTPException(status_code=401)
    event = await request.json()
    if event.get("event") == "work.ready":
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.github.com/repos/{REPO}/dispatches",
                headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                         "Accept": "application/vnd.github+json"},
                json={"event_type": "canopy-work-ready",
                      "client_payload": {"role": event["role"]}},
            )
    return {"ok": True}
```

and a workflow `on: repository_dispatch: types: [canopy-work-ready]` that runs the SDK daemon
with `--once` (or recipe 3) for the role in `github.event.client_payload.role` — pass it through
an `env:` entry and check it against the roles you run, never interpolate it into `run:`.
`gate.decided` works the same way for a runner that pauses sessions at a gate and resumes them
when a person decides.

## Containment checklist (every unattended runner)

- A container, VM or cloud environment; no production credentials in the worker's environment.
- `dontAsk` (or `auto` with prompts off), narrow allow rules, explicit deny rules; the Bash
  sandbox on; a network allow-list.
- A Git credential limited to the repository, behind branch protection that requires a human
  review — and, where the forge offers it, approval before workflows run on an agent's pushes.
- `bypassPermissions` only in a disposable container.
- Spend caps per session (`--max-budget-usd` / `max_budget_usd`) and a concurrency cap (tokens).
- An agent token per runner (or slot), scoped to its role and project, revoked from Agent Setup
  the moment the runner is retired.
