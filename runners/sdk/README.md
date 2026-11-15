# canopy reference runner (Claude Agent SDK)

A small daemon that turns canopy's agent work queue into running sessions: it claims ready
tasks for one role, works each in its own git worktree with one isolated
[Claude Agent SDK](https://code.claude.com/docs/en/agent-sdk/python) session, keeps the claim
alive, and gives the task back with a note when a session stops without handing off. Design:
[`docs/AGENT_EXECUTION.md`](../../docs/AGENT_EXECUTION.md) §15; every way to run sessions,
including this one: [`docs/AGENT_RUNNERS.md`](../../docs/AGENT_RUNNERS.md).

```
            canopy (REST)                          canopy MCP server (as the same token)
               ▲  claim · heartbeat · release · usage        ▲
               │                                              │ get_work_brief · submit_plan ·
   ┌───────────┴────────────┐   one session per claim   ┌─────┴──────────────────────┐
   │ runner slot (token t1) │ ─────────────────────────▶│ Agent SDK session in a     │
   │ runner slot (token t2) │                           │ worktree on the brief's    │
   └────────────────────────┘                           │ branch (max_turns, budget) │
                                                        └────────────────────────────┘
```

## Run it

```bash
cd runners/sdk
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r ../../plugin/mcp_server/requirements.txt
export CANOPY_API_BASE_URL=https://canopy.example.com
export CANOPY_AGENT_TOKENS=<token-1>,<token-2>     # one agent token per concurrent slot
export CANOPY_RUNNER_REPO_DIR=/srv/checkouts/shop   # a clone with an `origin` remote
export ANTHROPIC_API_KEY=…                          # or any credential the Agent SDK accepts
python canopy_runner.py            # daemon; --once works one task per slot and exits
```

Mint the tokens on canopy's **Agent Setup** page, scoped to the runner's role (and project).
One token per slot keeps canopy's rule of one claim per token, so each session acts under
exactly the claim the runner took.

## Settings

| Variable | Default | What it does |
|---|---|---|
| `CANOPY_API_BASE_URL` | `http://localhost:8000` | canopy's origin (the runner calls `/api/v1`) |
| `CANOPY_AGENT_TOKENS` | — | comma-separated agent tokens; the number of tokens is the concurrency |
| `CANOPY_RUNNER_ROLE` | `implementer` | the role every slot claims: `implementer`, `reviewer`, `qa`, … |
| `CANOPY_RUNNER_PROJECT_ID` / `_TEAM_ID` / `_REPO` | — | narrow the queue to a project, a team or a repository |
| `CANOPY_RUNNER_REPO_DIR` | `.` | the git checkout worktrees are created from |
| `CANOPY_RUNNER_WORKTREES` | `<repo>/.canopy-worktrees` | where worktrees go |
| `CANOPY_RUNNER_BASE_REF` | `origin/main` | where a new branch starts (an earlier attempt's branch is continued) |
| `CANOPY_MCP_MODE` | `stdio` | `stdio` spawns the plugin's MCP server per session with the slot's token; `http` uses `CANOPY_MCP_URL`, which must run with `CANOPY_MCP_AUTH_MODE=per_caller` |
| `CANOPY_RUNNER_PERMISSION_MODE` | `dontAsk` | anything not pre-approved is denied |
| `CANOPY_RUNNER_ALLOWED_TOOLS` | by role | implementers: `Read, Glob, Grep, Bash, Edit, Write, mcp__canopy`; reviewers and QA get no edit tools |
| `CANOPY_RUNNER_MAX_TURNS` | `80` | per session |
| `CANOPY_RUNNER_MAX_BUDGET_USD` | `5` | per session (a client-side estimate — leave headroom) |
| `CANOPY_RUNNER_SESSION_TIMEOUT_S` | `7200` | wall-clock limit per session |
| `CANOPY_RUNNER_MODEL` | SDK default | the model sessions use |
| `CANOPY_RUNNER_KEEP_WORKTREES` | `false` | keep worktrees after a session (debugging) |

## What it does with a claim

1. Prepares a worktree on the brief's branch (`conventions.branch`): an earlier attempt's
   pushed branch is continued, so every attempt shares one branch and one PR.
2. Starts a session with canopy's MCP server bound to the slot's token, the repository's own
   `CLAUDE.md` (`setting_sources=["project"]`), and an opening message naming the claim and the
   task by id and key only — the task's text reaches the session through the brief, marked as
   content.
3. Heartbeats the claim every `heartbeat_interval_s`. A stop that a person or canopy caused
   (taken over, intake off, the ticket moved) interrupts the session; the session's own
   hand-off just ends the heartbeat.
4. When the session ends: if it handed off or asked a person, the runner reports the session's
   cost (`POST /work/claims/{id}/usage`); if it still holds the claim, the runner releases it
   with the session's last words as the note. canopy parks a task after three unfinished
   attempts and asks a person.

## Containment is yours

canopy offers work and checks what comes back; it does not sandbox sessions. Run the runner in
a container or VM with no production credentials, a network allow-list, a Git credential
limited to the repository behind branch protection that requires a human review, and the
default `dontAsk` permission mode with narrow allowed tools. Never `bypassPermissions` outside
a disposable container.

## Tests

```bash
python -m pytest -q    # fakes canopy, git and the session — no SDK or API key needed
```
