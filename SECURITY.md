# Security policy

## Reporting a vulnerability

**Please do not open a public issue, discussion, or pull request for a security problem.**

Report it privately through GitHub's private vulnerability reporting:
[**Security → Report a vulnerability**](https://github.com/harshendu/canopy/security/advisories/new).
Only the maintainer can see the report, and we can work on a fix together in a private advisory.

Helpful details to include:

- what an attacker can do and what they need first (an account? a role? network access to which
  endpoint?),
- step-by-step reproduction (a request, a payload, or a failing test is ideal),
- the version or commit you tested and how canopy was deployed (Docker / bare metal, database,
  whether `DEMO_MODE` was on),
- any suggested fix.

canopy is maintained by volunteers, so timelines are best-effort: we aim to acknowledge reports
within a week. Confirmed issues are fixed on `main` first, and published as a GitHub security advisory
(with a CVE when warranted) once a fix is available. Reporters are credited unless they ask not to
be.

## Supported versions

canopy is pre-1.0 and has no long-term-support branches. Security fixes land on `main` (and in the
next release once releases are tagged), so run a recent `main` and upgrade promptly.

## Deploying canopy safely

Most real-world risk sits in deployment configuration. Before exposing an instance beyond your
laptop, work through the security checklist in [`docs/PRODUCTION.md`](docs/PRODUCTION.md). In
particular:

- **Set real secrets.** `SECRET_KEY` signs every access token and defaults to a public placeholder;
  `TOKEN_ENCRYPTION_KEY` encrypts connector credentials at rest (and falls back to a key derived
  from `SECRET_KEY` when empty). Generate both — `scripts/init.py` does it for you.
- **Set the webhook secrets** (`GITHUB_WEBHOOK_SECRET`, `JIRA_WEBHOOK_SECRET`,
  `EVENTS_WEBHOOK_SECRET`) on any internet-reachable deployment. Signature verification is skipped
  when a secret is empty, so an unset secret means unauthenticated webhook payloads are accepted.
- **Never enable `DEMO_MODE` in production.** It unlocks endpoints that wipe and reseed all data.
- **Protect the MCP endpoint** with `CANOPY_MCP_AUTH_TOKEN`, and give the MCP service account the
  least-privileged role that works (or a bounded *agent token*, which cannot take one-way-door
  actions such as pushing to Jira).
- **Rotate the first admin's password** after the first login.

## Known limitations

A deliberate, documented trade-off rather than a vulnerability (see
[`docs/USER_FLOWS.md`](docs/USER_FLOWS.md) → *Not built*): access tokens are bearer JWTs kept in the
browser's `localStorage`. There is no OIDC/SSO or `HttpOnly`-cookie session yet, so an XSS bug would
expose the signed-in user's token.
