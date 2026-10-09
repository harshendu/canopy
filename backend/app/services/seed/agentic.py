"""Alternate demo dataset — **Northstar**, a talent-technology company building agentic products.

Five initiatives mirror the product portfolio:

  * **AI Interviewer** — a conversational agent that runs voice and video sessions between an
    AI agent and a human (screening interviews first).
  * **Talent Pilot** — a deeply integrated agent harness for recruiters, inside the tools they
    already use.
  * **Talent Forge** — an agent harness customers use to build and deploy fully customizable
    applications.
  * **Agent Builder** — the runtime engine that powers every agent in the company.
  * **Dev Agents** — internal agents for monitoring, remediation, on-call support and developer
    productivity.

Instead of a single architect, a cross-functional **core team of project leads** — a technical
lead, a product lead and a UX lead — jointly plays the "architect" role (each holds the
``architect`` role with a different ``function``). Ten projects (two per initiative) are fully
populated: a scheduled WBS with cross-project hand-offs, ADRs with review threads and fitness
functions, drift, specs, risks, outcomes, docs, blockers, retros, draft plans and a what-if
scenario per initiative. Pure data; the generic loader turns it into rows.
"""

from __future__ import annotations

from app.models.base import UserFunction, UserRole
from app.services.seed.catalog import (
    ADRCommentSpec,
    ADRSpec,
    BindingSpec,
    BlockerSpec,
    ComponentSpec,
    CriterionSpec,
    Dataset,
    DemoAvailability,
    DemoConnection,
    DemoEngineer,
    DemoUser,
    DocSpec,
    DraftSpec,
    DraftTaskSpec,
    DriftSpec,
    FitnessSpec,
    IncidentSpec,
    InitiativeSpec,
    LinkSpec,
    MilestoneSpec,
    MitigationSpec,
    OutcomeSpec,
    PhaseSpec,
    ProjectSpec,
    PullRequestSpec,
    RetroCommentSpec,
    RetroSpec,
    RiskSpec,
    ScenarioAddedTask,
    ScenarioAllocSpec,
    ScenarioAvailSpec,
    ScenarioMilestonePull,
    ScenarioSpec,
    SpecSpec,
    TaskSpec,
)

# --------------------------------------------------------------------------- #
# People — the core team (project leads) + the delivery team
# --------------------------------------------------------------------------- #
USERS: tuple[DemoUser, ...] = (
    DemoUser("admin@northstar.ai", "Rowan Ellis", UserRole.admin, UserFunction.management),
    DemoUser("cto@northstar.ai", "Maya Lindqvist", UserRole.viewer, UserFunction.leadership),
    # The core team: three project leads who jointly hold the architect role.
    DemoUser("tech@northstar.ai", "Priya Raman", UserRole.architect, UserFunction.engineering),
    DemoUser("product@northstar.ai", "Daniel Reyes", UserRole.architect, UserFunction.product),
    DemoUser("ux@northstar.ai", "Mei Nakamura", UserRole.architect, UserFunction.design),
    DemoUser("em@northstar.ai", "Jonah Fields", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser("leila@northstar.ai", "Leila Haddad", UserRole.engineer, UserFunction.engineering),
    DemoUser("tomas@northstar.ai", "Tomás Silva", UserRole.engineer, UserFunction.engineering),
    DemoUser("ananya@northstar.ai", "Ananya Bose", UserRole.engineer, UserFunction.engineering),
    DemoUser("chris@northstar.ai", "Chris Walker", UserRole.engineer, UserFunction.engineering),
    DemoUser("talent@northstar.ai", "Grace Tan", UserRole.viewer, UserFunction.product),
    DemoUser("noor@northstar.ai", "Noor Abadi", UserRole.member, UserFunction.engineering),
)

TEAM_ROLES: tuple[str, ...] = (
    "Core Team", "Management", "Agent Platform", "Realtime", "ML & Evals", "Frontend",
    "Platform / SRE", "Security", "Integrations", "Data", "QA",
)

ENGINEERS: tuple[DemoEngineer, ...] = (
    DemoEngineer("Priya Raman", "Technical Lead (core team)",
                 ("architecture", "agents", "distributed-systems"), "America/New_York", 30,
                 "priyaraman", "Core Team", "tech@northstar.ai"),
    DemoEngineer("Daniel Reyes", "Product Lead (core team)",
                 ("product", "recruiting", "roadmap"), "America/Chicago", 30, "danielreyes",
                 "Core Team", "product@northstar.ai"),
    DemoEngineer("Mei Nakamura", "UX Lead (core team)",
                 ("ux", "research", "conversation-design"), "America/Los_Angeles", 30,
                 "meinakamura", "Core Team", "ux@northstar.ai"),
    DemoEngineer("Jonah Fields", "Engineering Manager",
                 ("management", "backend"), "Europe/London", 20, "jonahfields",
                 "Management", "em@northstar.ai"),
    DemoEngineer("Leila Haddad", "Realtime Engineer",
                 ("webrtc", "audio", "streaming"), "Europe/Paris", 40, "leilahaddad",
                 "Realtime", "leila@northstar.ai"),
    DemoEngineer("Tomás Silva", "Agent Platform Engineer",
                 ("backend", "python", "agents"), "America/Sao_Paulo", 40, "tomassilva",
                 "Agent Platform", "tomas@northstar.ai"),
    DemoEngineer("Ananya Bose", "ML Engineer, Evals",
                 ("ml", "evals", "python"), "Asia/Kolkata", 40, "ananyabose",
                 "ML & Evals", "ananya@northstar.ai"),
    DemoEngineer("Chris Walker", "Frontend Engineer",
                 ("frontend", "react", "typescript"), "Europe/Berlin", 40, "chriswalker",
                 "Frontend", "chris@northstar.ai"),
    DemoEngineer("Sam Okoro", "Site Reliability Engineer",
                 ("infra", "kubernetes", "observability"), "Africa/Lagos", 40, "samokoro",
                 "Platform / SRE", None),
    DemoEngineer("Yara Cohen", "Security Engineer",
                 ("security", "privacy", "compliance"), "Asia/Jerusalem", 40, "yaracohen",
                 "Security", None),
    DemoEngineer("Kenji Mori", "Integrations Engineer",
                 ("integrations", "ats", "apis"), "Asia/Tokyo", 40, "kenjimori",
                 "Integrations", None),
    DemoEngineer("Olivia Grant", "Data Engineer",
                 ("data", "etl", "postgres"), "America/New_York", 40, "oliviagrant",
                 "Data", None),
    DemoEngineer("Noor Abadi", "QA / Release Engineer",
                 ("qa", "automation", "e2e"), "Asia/Dubai", 32, "noorabadi", "QA",
                 "noor@northstar.ai"),
)

AVAILABILITY: tuple[DemoAvailability, ...] = (
    DemoAvailability("Leila Haddad", 1, 2, 0.5, "Speaking at a realtime-media conference"),
    DemoAvailability("Tomás Silva", -1, 1, 0.5, "Ramping onto the interview orchestrator"),
    DemoAvailability("Chris Walker", 2, 4, 0.0, "Vacation"),
    DemoAvailability("Sam Okoro", 3, 4, 0.7, "On-call rotation"),
    DemoAvailability("Jonah Fields", -4, 16, 0.5, "Split between management and delivery"),
    DemoAvailability("Kenji Mori", 0, 6, 0.5, "Embedded with a design-partner customer"),
    DemoAvailability("Yara Cohen", 2, 3, 0.0, "Parental leave"),
)

# Engineer-to-project allocations (Leila and Tomás span projects → over-allocation alerts).
ALLOCATIONS: tuple[tuple[str, str, float], ...] = (
    ("Tomás Silva", "RUNTIME", 50), ("Olivia Grant", "RUNTIME", 40),
    ("Ananya Bose", "GATEWAY", 60), ("Yara Cohen", "GATEWAY", 20),
    ("Leila Haddad", "SESSION", 70), ("Yara Cohen", "SESSION", 30),
    ("Leila Haddad", "INTERVIEW", 50), ("Tomás Silva", "INTERVIEW", 30),
    ("Ananya Bose", "INTERVIEW", 40), ("Chris Walker", "INTERVIEW", 30),
    ("Noor Abadi", "INTERVIEW", 40), ("Priya Raman", "INTERVIEW", 30),
    ("Mei Nakamura", "INTERVIEW", 30), ("Olivia Grant", "INTERVIEW", 20),
    ("Kenji Mori", "ATSHUB", 70), ("Olivia Grant", "ATSHUB", 40),
    ("Tomás Silva", "COPILOT", 30), ("Kenji Mori", "COPILOT", 30),
    ("Chris Walker", "COPILOT", 20), ("Daniel Reyes", "COPILOT", 30),
    ("Chris Walker", "STUDIO", 60), ("Mei Nakamura", "STUDIO", 30),
    ("Noor Abadi", "STUDIO", 30),
    ("Sam Okoro", "DEPLOY", 50), ("Yara Cohen", "DEPLOY", 40),
    ("Sam Okoro", "ONCALL", 50), ("Tomás Silva", "ONCALL", 20),
    ("Noor Abadi", "DEVPROD", 30),
)


# --------------------------------------------------------------------------- #
# Initiatives
# --------------------------------------------------------------------------- #
INITIATIVES: tuple[InitiativeSpec, ...] = (
    InitiativeSpec(
        "INTERVIEWER", "AI Interviewer",
        "Run structured voice and video screening interviews with an AI agent, at a candidate "
        "satisfaction level on par with human screens.",
        18, "Leila Haddad", ("voice", "video", "conversation"), "at_risk",
        "The session service is stable; the orchestrator's turn-taking integration is the "
        "critical path and currently at risk.",
        outcomes=(
            OutcomeSpec("Candidate satisfaction parity", "post-interview CSAT", "/5",
                        3.6, 4.3, 4.0, "on_track", "Mei Nakamura"),
            OutcomeSpec("Faster screening turnaround", "hours from apply to screen", "h",
                        72.0, 4.0, 18.0, "at_risk", "Daniel Reyes"),
        ),
        risks=(
            RiskSpec("Turn-taking latency degrades the conversational experience", "technical",
                     "high", "high", "mitigating", "Leila Haddad",
                     "Semantic end-of-turn detection plus a hard latency budget per turn."),
        ),
        docs=(
            DocSpec("prd", "AI Interviewer PRD",
                    "https://drive.google.com/file/d/doc-prd-interviewer/view", "drive"),
        ),
    ),
    InitiativeSpec(
        "PILOT", "Talent Pilot",
        "Give every recruiter an integrated agent harness that handles sourcing, screening "
        "and scheduling inside the tools they already use.",
        16, "Kenji Mori", ("recruiting", "copilot", "integrations"), "on_track",
        "The ATS integration hub is live with two vendors; the copilot's scheduling flows are "
        "in build.",
        outcomes=(
            OutcomeSpec("Recruiter hours saved per hire", "hours saved per hire", "h",
                        0.0, 10.0, 6.0, "on_track", "Daniel Reyes"),
            OutcomeSpec("Faster time to first screen", "days from req to first screen", "days",
                        9.0, 2.0, 4.0, "on_track", "Kenji Mori"),
        ),
        risks=(
            RiskSpec("ATS vendors rate-limit bulk candidate sync", "external", "medium", "high",
                     "open", "Kenji Mori",
                     "Incremental sync with vendor-approved quotas; back off on 429s."),
        ),
        docs=(
            DocSpec("prd", "Talent Pilot PRD",
                    "https://drive.google.com/file/d/doc-prd-pilot/view", "drive"),
        ),
    ),
    InitiativeSpec(
        "FORGE", "Talent Forge",
        "Let customers build and deploy fully customizable agent applications on the platform "
        "without engineering involvement.",
        20, "Chris Walker", ("builder", "low-code", "deployment"), "on_track",
        "The Studio designer is in private beta; the multi-tenant deploy pipeline is the long "
        "pole.",
        outcomes=(
            OutcomeSpec("Apps built without engineering help", "share of apps self-built", "%",
                        0.0, 80.0, 45.0, "on_track", "Mei Nakamura"),
            OutcomeSpec("Faster deploys", "minutes from publish to live", "min",
                        90.0, 10.0, 35.0, "on_track", "Sam Okoro"),
        ),
        risks=(
            RiskSpec("Customization surface outgrows the guardrails", "scope", "medium", "high",
                     "mitigating", "Priya Raman",
                     "Ship a constrained template set first; expand with design partners."),
        ),
    ),
    InitiativeSpec(
        "BUILDER", "Agent Builder",
        "Provide one runtime engine that every agent in the company runs on, with evaluation "
        "and guardrails built in.",
        14, "Tomás Silva", ("runtime", "platform", "evals"), "on_track",
        "The runtime core is generally available for internal agents; model-gateway routing "
        "and the eval harness are landing.",
        outcomes=(
            OutcomeSpec("Agents on the shared runtime", "share of agents on the runtime", "%",
                        20.0, 100.0, 70.0, "on_track", "Tomás Silva"),
            OutcomeSpec("Eval coverage of production agents", "agents with a passing eval", "%",
                        10.0, 90.0, 55.0, "on_track", "Ananya Bose"),
        ),
        risks=(
            RiskSpec("Model-provider changes break routing contracts", "external", "medium",
                     "medium", "mitigating", "Ananya Bose",
                     "Adapter conformance tests run nightly against every provider."),
        ),
        docs=(
            DocSpec("architecture", "Agent Builder reference architecture",
                    "https://drive.google.com/file/d/doc-arch-builder/view", "drive"),
        ),
    ),
    InitiativeSpec(
        "DEVAGENTS", "Dev Agents",
        "Reduce on-call load and raise developer throughput with internal agents for "
        "monitoring, remediation and code review.",
        12, "Sam Okoro", ("internal", "on-call", "productivity"), "on_track",
        "The monitoring agent triages alerts in production; the productivity agents are in "
        "early rollout.",
        outcomes=(
            OutcomeSpec("Alerts auto-triaged", "share of alerts triaged by the agent", "%",
                        0.0, 70.0, 40.0, "on_track", "Sam Okoro"),
            OutcomeSpec("Faster PR review turnaround", "hours to first review", "h",
                        26.0, 8.0, 14.0, "on_track", "Priya Raman"),
        ),
        risks=(
            RiskSpec("Agent-suggested remediations applied without review", "security", "low",
                     "high", "open", "Yara Cohen",
                     "Approval gate in front of every production-affecting action."),
        ),
    ),
)


# =========================================================================== #
# AGENT BUILDER
# =========================================================================== #
_RUNTIME = ProjectSpec(
    "RUNTIME", "Agent Runtime Core",
    "The orchestration loop, tool calling, memory and state management every agent runs on.",
    "BUILDER", 12, 8, True, "on_track",
    "Orchestration loop and tool sandboxing shipped; memory store and gateway integration in "
    "flight.",
    ("runtime", "platform", "backend"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Runtime architecture", 3, "Done", 50, "Priya Raman", ("architecture",)),
            TaskSpec("Tool-calling contract", 4, "Done", 40, "Tomás Silva", ("design",),
                     (3, 4, 7)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Orchestration loop", 6, "Done", 26, "Tomás Silva", ("backend",),
                     (5, 6, 10)),
            TaskSpec("Tool registry & sandboxing", 5, "Done", 18, "Tomás Silva",
                     ("backend", "security"), (4, 5, 9)),
            TaskSpec("Conversation memory store", 5, "In Progress", 12, "Olivia Grant",
                     ("data",), (4, 5, 8)),
            TaskSpec("Integrate model gateway", 4, "In Progress", 6, "Tomás Silva",
                     ("backend",)),
            TaskSpec("Streaming responses", 3, "To Do", 0, "Tomás Silva", ("backend",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Migrate internal agents", 5, "To Do", 0, "Tomás Silva", ("rollout",)),
            TaskSpec("Runtime GA", 0, "To Do", 0, None, (), None, True, 8),
        )),
    ),
    milestones=(
        MilestoneSpec("Architecture sign-off", -9, "hit"),
        MilestoneSpec("Internal GA", 3),
        MilestoneSpec("Runtime GA", 8),
    ),
    components=(
        ComponentSpec("runtime-api", "service", "presentation", "high", "Tomás Silva"),
        ComponentSpec("orchestrator", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("tool-registry", "module", "business", "high"),
        ComponentSpec("memory-store", "datastore", "data", "high", "Olivia Grant"),
        ComponentSpec("model-gateway", "external", "infra", "high", "Ananya Bose"),
    ),
    component_links=(
        LinkSpec("runtime-api", "orchestrator", "calls"),
        LinkSpec("orchestrator", "tool-registry", "depends_on"),
        LinkSpec("orchestrator", "memory-store", "reads_from"),
        LinkSpec("orchestrator", "model-gateway", "calls"),
        LinkSpec("tool-registry", "model-gateway", "calls"),  # violates the sandboxing ADR
    ),
    bindings=(BindingSpec("orchestrator", "runtime/orchestrator/**", "northstar.runtime"),),
    adrs=(
        ADRSpec("Tools run sandboxed and never call models directly", "accepted", "one_way",
                "Priya Raman", "Tomás Silva",
                "Tools that reach a model on their own bypass guardrails, metering and evals.",
                "All model calls go through the orchestrator; tools are pure functions over "
                "their inputs.",
                "Predictable cost and auditability; some tools become slightly more verbose.",
                components=("orchestrator", "tool-registry"),
                fitness=FitnessSpec("forbid", "tool-registry", "model-gateway",
                                    "Tools must not call the model gateway directly."),
                created_days_ago=42),
        ADRSpec("Conversation memory: vector store vs relational", "under_discussion",
                "two_way", "Olivia Grant", "Olivia Grant",
                "Agents need recall across sessions without unbounded context growth.",
                "Proposed: relational store with embedded summaries; a vector index only for "
                "long-tail recall.",
                components=("memory-store",),
                stakeholders=("Olivia Grant", "Tomás Silva", "Priya Raman"),
                comments=(
                    ADRCommentSpec("Tomás Silva", "Relational keeps retention policies simple.",
                                   "approve"),
                    ADRCommentSpec("Priya Raman", "Please specify the retention window before "
                                   "we accept.", "request_changes"),
                    ADRCommentSpec("Ananya Bose", "Recall quality should be part of the eval "
                                   "suite.", "comment"),
                ),
                created_days_ago=11),
        ADRSpec("Multi-agent hand-off protocol", "deferred", owner="Tomás Silva",
                context="Agents increasingly delegate to one another; the hand-off contract is "
                        "ad hoc today.",
                created_days_ago=9, decide_by_weeks=2),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "tool-registry calls model-gateway directly",
                  ("tool-registry", "model-gateway"),
                  "Violates the tool-sandboxing decision.",
                  "PR #142 (summarise-tool shortcut)"),
    ),
    specs=(
        SpecSpec("Tool execution isolation",
                 "A tool must not reach models, secrets or other tenants' data on its own.",
                 "in_progress", "Tomás Silva",
                 context="Underpins the sandboxing decision and the eval gate.",
                 adr_title="Tools run sandboxed and never call models directly",
                 criteria=(
                     CriterionSpec("Tools execute with no network access by default.", "met",
                                   "Verified by the sandbox test suite."),
                     CriterionSpec("Every model call is attributable to an orchestrator run.",
                                   "unmet", "The summarise tool bypasses the orchestrator."),
                     CriterionSpec("Tool inputs and outputs are logged per run.", "open"),
                 ),
                 task_names=("Tool registry & sandboxing", "Orchestration loop")),
    ),
    risks=(
        RiskSpec("Latency budget exceeded under tool fan-out", "technical", "medium", "high",
                 "mitigating", "Tomás Silva", "Parallel tool execution with a per-run budget."),
        RiskSpec("Memory retention conflicts with the data policy", "security", "low", "high",
                 "open", "Yara Cohen", "Retention window defined in the memory ADR."),
    ),
    mitigations=(
        MitigationSpec("over_allocation", "Rebalance Tomás off the copilot next sprint.",
                       "Jonah Fields", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Orchestration overhead", "p95 overhead per turn", "ms",
                    400.0, 120.0, 180.0, "on_track", "Tomás Silva"),
    ),
    docs=(
        DocSpec("tech_design", "Runtime design doc",
                "https://github.com/northstar-ai/agent-runtime/blob/main/docs/runtime.md",
                "repo"),
    ),
    blockers=(
        BlockerSpec("Integrate model gateway",
                    "Waiting on the routing API contract from the gateway team.", "dependency",
                    "high", "Ananya Bose", "Tomás Silva", False, 4, 1),
    ),
    retro=RetroSpec("Runtime internal-GA retrospective", "project_retro",
                    "## Went well\n- The tool contract made onboarding agents straightforward."
                    "\n\n## Improve\n- Gateway contract should have been agreed earlier.\n\n"
                    "## Actions\n- Agree cross-team contracts at design sign-off.",
                    ("orchestrator",),
                    (RetroCommentSpec("Tomás Silva", "The contract-first approach paid off."),
                     RetroCommentSpec("Priya Raman", "Let us lock hand-off contracts at "
                                      "design sign-off next time."))),
    deploy_weeks=10,
)

_GATEWAY = ProjectSpec(
    "GATEWAY", "Model Gateway & Evals",
    "Model routing with fallbacks and cost control, guardrail policies, and the evaluation "
    "harness every agent must pass.",
    "BUILDER", 10, 7, True, "on_track",
    "Provider adapters shipped; routing API and guardrail policies in review.",
    ("runtime", "ml", "evals"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Gateway architecture", 3, "Done", 44, "Ananya Bose", ("architecture",)),
            TaskSpec("Eval harness design", 3, "Done", 36, "Ananya Bose", ("design",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Provider adapters", 5, "Done", 22, "Ananya Bose", ("backend",),
                     (4, 5, 8)),
            TaskSpec("Model routing API", 4, "In Progress", 9, "Ananya Bose", ("backend",),
                     (3, 4, 7)),
            TaskSpec("Guardrail policies", 4, "In Progress", 7, "Yara Cohen",
                     ("security",)),
            TaskSpec("Eval harness runner", 5, "To Do", 0, "Ananya Bose", ("ml",)),
            TaskSpec("Cost & usage metering", 3, "To Do", 0, "Olivia Grant", ("data",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Eval dashboards", 3, "To Do", 0, "Chris Walker", ("frontend",)),
            TaskSpec("Gateway GA", 0, "To Do", 0, None, (), None, True, 7),
        )),
    ),
    milestones=(
        MilestoneSpec("Design review", -6, "hit"),
        MilestoneSpec("Routing beta", 2),
        MilestoneSpec("Gateway GA", 7),
    ),
    components=(
        ComponentSpec("gateway-api", "service", "presentation", "high", "Ananya Bose"),
        ComponentSpec("router", "module", "business", "high", "Ananya Bose"),
        ComponentSpec("provider-adapters", "module", "infra", "med"),
        ComponentSpec("eval-harness", "service", "business", "high", "Ananya Bose"),
        ComponentSpec("usage-ledger", "datastore", "data", "med", "Olivia Grant"),
    ),
    component_links=(
        LinkSpec("gateway-api", "router", "calls"),
        LinkSpec("router", "provider-adapters", "depends_on"),
        LinkSpec("gateway-api", "usage-ledger", "publishes_to"),
        LinkSpec("eval-harness", "gateway-api", "calls"),
    ),
    bindings=(BindingSpec("router", "gateway/router/**", "northstar.gateway"),),
    adrs=(
        ADRSpec("Every model call is metered through the gateway", "accepted", "one_way",
                "Priya Raman", "Ananya Bose",
                "Cost attribution and rate control require one chokepoint for model traffic.",
                "The gateway API records every call in the usage ledger before routing it.",
                "Accurate cost per agent; the ledger becomes a critical dependency.",
                components=("gateway-api", "usage-ledger"),
                fitness=FitnessSpec("require", "gateway-api", "usage-ledger",
                                    "The gateway must publish every call to the usage ledger."),
                created_days_ago=38),
        ADRSpec("Provider fallback order", "under_discussion", "two_way", "Ananya Bose",
                "Ananya Bose",
                "Outages at a single provider must not take agents down.",
                "Proposed: quality-ranked primary with a latency-ranked fallback per task class.",
                components=("router",),
                stakeholders=("Ananya Bose", "Tomás Silva", "Daniel Reyes"),
                comments=(
                    ADRCommentSpec("Tomás Silva", "Task-class routing matches how agents are "
                                   "built.", "approve"),
                    ADRCommentSpec("Daniel Reyes", "Please include a cost ceiling per class.",
                                   "request_changes"),
                ),
                created_days_ago=8),
        ADRSpec("Self-hosted models for sensitive workloads", "deferred", owner="Yara Cohen",
                context="Some customers require that candidate data never reach a third-party "
                        "model provider.",
                created_days_ago=20, decide_by_weeks=-1),
    ),
    drift=(
        DriftSpec("unimplemented_adr",
                  "The eval gate is accepted in principle but not enforced in the release "
                  "pipeline", ("eval-harness",), status="open"),
    ),
    specs=(
        SpecSpec("Routing policy",
                 "Every request is routed by task class with a defined fallback and cost "
                 "ceiling.", "approved", "Ananya Bose",
                 adr_title="Every model call is metered through the gateway",
                 criteria=(
                     CriterionSpec("Each task class has a primary and a fallback provider.",
                                   "met", "Routing table reviewed."),
                     CriterionSpec("A provider outage fails over within 5 seconds.", "open"),
                     CriterionSpec("Cost per agent is reported daily.", "open"),
                 ),
                 task_names=("Model routing API", "Cost & usage metering")),
    ),
    risks=(
        RiskSpec("A provider outage loops through fallbacks", "technical", "medium", "medium",
                 "mitigating", "Ananya Bose", "Circuit breaker per provider."),
        RiskSpec("Guardrail policies block legitimate recruiter workflows", "quality", "medium",
                 "medium", "open", "Yara Cohen", "Shadow mode before enforcement."),
    ),
    outcomes=(
        OutcomeSpec("Model spend per agent run", "cost per run", "cents",
                    9.0, 4.0, 6.0, "on_track", "Olivia Grant"),
    ),
    docs=(
        DocSpec("tech_design", "Gateway technical design",
                "https://northstar.atlassian.net/wiki/spaces/AB/gateway", "manual"),
        DocSpec("qa", "Eval harness test plan",
                "https://drive.google.com/file/d/doc-eval-plan/view", "drive",
                "Eval harness runner"),
    ),
    blockers=(
        BlockerSpec("Guardrail policies", "Waiting on the security review of the policy set.",
                    "decision", "medium", "Yara Cohen", "Ananya Bose", False, 3, 2),
    ),
    retro=RetroSpec("Provider outage postmortem", "incident_postmortem",
                    "## Impact\n- Agents failed over in a loop for 3 hours.\n\n"
                    "## Root cause\n- No circuit breaker between providers.\n\n"
                    "## Actions\n- Add per-provider breakers; alert on fallback rate.",
                    ("router",),
                    (RetroCommentSpec("Sam Okoro", "We need the fallback-rate alert in the "
                                      "monitoring agent."),)),
    incidents=(IncidentSpec("Provider outage caused a failover loop", 12, 3, "router"),),
    deploy_weeks=8,
)


# =========================================================================== #
# AI INTERVIEWER
# =========================================================================== #
_SESSION = ProjectSpec(
    "SESSION", "Realtime Session Service",
    "Voice and video sessions between an AI agent and a human: WebRTC signalling, streaming "
    "speech, turn-taking and consented recording.",
    "INTERVIEWER", 7, 9, True, "on_track",
    "Signalling and the speech bridge shipped; turn-taking tuning is the hand-off the "
    "orchestrator is waiting on.",
    ("voice", "video", "webrtc"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Session architecture", 3, "Done", 48, "Leila Haddad", ("architecture",)),
            TaskSpec("Media pipeline ADR", 3, "Done", 42, "Leila Haddad", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("WebRTC signalling", 7, "Done", 30, "Leila Haddad", ("realtime",),
                     (5, 7, 10)),
            TaskSpec("Streaming speech bridge", 8, "Done", 20, "Leila Haddad", ("realtime",),
                     (6, 8, 12)),
            TaskSpec("Turn-taking & barge-in", 5, "In Progress", 12, "Leila Haddad",
                     ("realtime", "ux"), (4, 5, 9)),
            TaskSpec("Session recording & consent", 4, "In Progress", 8, "Yara Cohen",
                     ("security",)),
            TaskSpec("Video avatar rendering", 4, "To Do", 0, "Chris Walker", ("frontend",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Load test at 500 concurrent sessions", 4, "To Do", 0, "Noor Abadi",
                     ("qa",)),
            TaskSpec("Session GA", 0, "To Do", 0, None, (), None, True, 9),
        )),
    ),
    milestones=(
        MilestoneSpec("Architecture sign-off", -8, "hit"),
        MilestoneSpec("Voice beta", 1),
        MilestoneSpec("Session GA", 9),
    ),
    components=(
        ComponentSpec("signalling", "service", "presentation", "high", "Leila Haddad"),
        ComponentSpec("media-pipeline", "service", "business", "high", "Leila Haddad"),
        ComponentSpec("speech-bridge", "module", "business", "high"),
        ComponentSpec("session-store", "datastore", "data", "med"),
        ComponentSpec("recording-vault", "datastore", "data", "high", "Yara Cohen"),
    ),
    component_links=(
        LinkSpec("signalling", "media-pipeline", "calls"),
        LinkSpec("media-pipeline", "speech-bridge", "depends_on"),
        LinkSpec("media-pipeline", "session-store", "reads_from"),
        LinkSpec("media-pipeline", "recording-vault", "publishes_to"),
        LinkSpec("signalling", "recording-vault", "reads_from"),  # violates the consent ADR
    ),
    bindings=(BindingSpec("media-pipeline", "session/media/**", "northstar.session.media"),),
    adrs=(
        ADRSpec("Recordings require explicit consent and are never served by signalling",
                "accepted", "one_way", "Priya Raman", "Yara Cohen",
                "Interview recordings are sensitive personal data in every jurisdiction we "
                "operate in.",
                "Recording starts only after consent is captured; playback is served by a "
                "dedicated, audited path.",
                "Clear compliance posture; playback features take a little longer to build.",
                components=("media-pipeline", "recording-vault"),
                fitness=FitnessSpec("forbid", "signalling", "recording-vault",
                                    "The signalling layer must not read recordings."),
                created_days_ago=40),
        ADRSpec("Turn-taking: voice activity vs semantic end-of-turn", "under_discussion",
                "two_way", "Leila Haddad", "Leila Haddad",
                "Interrupting the candidate mid-sentence is the top complaint from the beta.",
                "Proposed: semantic end-of-turn detection with a voice-activity fallback.",
                components=("speech-bridge",),
                stakeholders=("Leila Haddad", "Mei Nakamura", "Priya Raman"),
                comments=(
                    ADRCommentSpec("Mei Nakamura", "Semantic end-of-turn felt considerably "
                                   "more natural in usability sessions.", "approve"),
                    ADRCommentSpec("Priya Raman", "Please state the latency budget this adds "
                                   "per turn.", "request_changes"),
                    ADRCommentSpec("Ananya Bose", "We can evaluate both on the transcript "
                                   "corpus.", "comment"),
                ),
                created_days_ago=10),
        ADRSpec("Video avatar vendor", "deferred", owner="Mei Nakamura",
                context="A rendered avatar may improve rapport; vendor quality varies widely.",
                created_days_ago=7, decide_by_weeks=3),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "signalling reads recording-vault",
                  ("signalling", "recording-vault"),
                  "Violates the consent and playback decision.",
                  "PR #88 (playback shortcut for the beta)"),
    ),
    specs=(
        SpecSpec("Natural turn-taking",
                 "The agent responds promptly without talking over the candidate.",
                 "in_progress", "Leila Haddad",
                 context="The experience bar for the interviewer beta.",
                 adr_title="Turn-taking: voice activity vs semantic end-of-turn",
                 criteria=(
                     CriterionSpec("Median response latency is under 800 ms.", "unmet",
                                   "Currently 950 ms on the beta corpus."),
                     CriterionSpec("Barge-in interrupts speech within 200 ms.", "met",
                                   "Verified in the realtime test harness."),
                     CriterionSpec("No overlapping speech in 95% of turns.", "open"),
                 ),
                 task_names=("Turn-taking & barge-in", "Streaming speech bridge")),
    ),
    risks=(
        RiskSpec("Turn-taking latency misses the experience target", "technical", "high",
                 "high", "mitigating", "Leila Haddad",
                 "Semantic end-of-turn plus a per-turn latency budget.", target_weeks=1),
        RiskSpec("Consent requirements differ by region", "external", "medium", "high",
                 "open", "Yara Cohen", "Region-specific consent scripts.", target_weeks=-1),
    ),
    mitigations=(
        MitigationSpec("quality_signals", "Added a realtime latency harness to CI.",
                       "Leila Haddad", True),
    ),
    outcomes=(
        OutcomeSpec("End-of-turn latency", "median response latency", "ms",
                    1400.0, 800.0, 950.0, "on_track", "Leila Haddad"),
    ),
    docs=(
        DocSpec("tech_design", "Media pipeline design",
                "https://github.com/northstar-ai/session-service/blob/main/docs/media.md",
                "repo"),
        DocSpec("runbook", "Session service runbook",
                "https://github.com/northstar-ai/session-service/blob/main/docs/runbook.md",
                "repo"),
    ),
    blockers=(
        BlockerSpec("Turn-taking & barge-in",
                    "Waiting on the end-of-turn decision before tuning thresholds.", "decision",
                    "high", "Leila Haddad", "Mei Nakamura", False, 5, 1),
    ),
    retro=RetroSpec("Voice beta retrospective", "project_retro",
                    "## Went well\n- The speech bridge hit its latency target.\n\n"
                    "## Improve\n- Turn-taking should have been prototyped earlier.\n\n"
                    "## Actions\n- Usability-test turn-taking before the video beta.",
                    ("media-pipeline",),
                    (RetroCommentSpec("Leila Haddad", "Prototype the hard part first."),
                     RetroCommentSpec("Mei Nakamura", "Research sessions caught the "
                                      "interruption issue early."))),
    incidents=(IncidentSpec("Media pipeline restart dropped live sessions", 10, 2,
                            "media-pipeline"),),
    deploy_weeks=9,
)

_INTERVIEW = ProjectSpec(
    "INTERVIEW", "Interview Orchestrator",
    "Structured interview flows, question banks, rubric-based scoring, transcripts and the "
    "recruiter review experience, running on the realtime session service.",
    "INTERVIEWER", 9, 11, True, "at_risk",
    "Flow engine shipped; the realtime-session integration is the critical path and the "
    "customer pilot has slipped.",
    ("voice", "interviews", "scoring"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Interview flow architecture", 3, "Done", 52, "Priya Raman",
                     ("architecture",)),
            TaskSpec("Rubric & scoring ADR", 3, "Done", 45, "Ananya Bose",
                     ("architecture", "ml")),
            TaskSpec("Interview experience spec", 4, "Done", 38, "Mei Nakamura", ("design",),
                     (3, 4, 7)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Conversation flow engine", 6, "Done", 28, "Tomás Silva", ("backend",),
                     (5, 6, 11)),
            TaskSpec("Rubric scoring service", 5, "In Progress", 34, "Ananya Bose",
                     ("ml", "backend"), (4, 5, 9)),
            TaskSpec("Wire realtime session in", 5, "In Progress", 10, "Leila Haddad",
                     ("realtime", "backend"), (3, 5, 9), deadline_weeks=1),
            TaskSpec("Transcript & highlights", 4, "To Do", 0, "Olivia Grant", ("data",)),
            TaskSpec("Recruiter review UI", 4, "To Do", 0, "Chris Walker", ("frontend",)),
        )),
        PhaseSpec("Harden & Launch", (
            TaskSpec("Bias & fairness audit", 5, "To Do", 0, "Noor Abadi", ("qa", "ml")),
            TaskSpec("Customer pilot", 0, "at_risk", 0, None, (), None, True, -2),
            TaskSpec("Interviewer GA", 0, "To Do", 0, None, (), None, True, 11),
        )),
    ),
    milestones=(
        MilestoneSpec("Experience sign-off", -8, "hit"),
        MilestoneSpec("Customer pilot", -2, "at_risk"),  # overdue → alert
        MilestoneSpec("Interviewer GA", 11),
    ),
    components=(
        ComponentSpec("interview-api", "service", "presentation", "high", "Chris Walker"),
        ComponentSpec("flow-engine", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("scoring-service", "module", "business", "high", "Ananya Bose"),
        ComponentSpec("transcript-store", "datastore", "data", "high"),
        ComponentSpec("session-service", "external", "infra", "high", "Leila Haddad"),
    ),
    component_links=(
        LinkSpec("interview-api", "flow-engine", "calls"),
        LinkSpec("flow-engine", "scoring-service", "depends_on"),
        LinkSpec("flow-engine", "transcript-store", "reads_from"),
        LinkSpec("flow-engine", "session-service", "calls"),
        LinkSpec("scoring-service", "session-service", "calls"),  # violates the scoring ADR
    ),
    bindings=(
        BindingSpec("flow-engine", "interviewer/flow/**", "northstar.interviewer.flow"),
        BindingSpec("scoring-service", "interviewer/scoring/**",
                    "northstar.interviewer.scoring"),
    ),
    adrs=(
        ADRSpec("Scoring uses transcripts only, never raw audio or video", "accepted",
                "one_way", "Priya Raman", "Ananya Bose",
                "Scoring on voice or appearance signals is an unacceptable fairness risk.",
                "The scoring service consumes transcript text and the rubric; it has no path "
                "to the media session.",
                "Defensible, explainable scores; some conversational nuance is lost.",
                components=("scoring-service", "flow-engine"),
                fitness=FitnessSpec("forbid", "scoring-service", "session-service",
                                    "Scoring must not call the session service; only "
                                    "transcripts may feed a score."),
                created_days_ago=44),
        ADRSpec("Flow engine: state machine vs model-planned", "accepted", "two_way",
                "Priya Raman", "Tomás Silva",
                "Interviews must stay on-rubric while allowing natural follow-ups.",
                "A state machine owns the structure; the model plans within a step.",
                alternatives=("Fully model-planned", "Scripted only"),
                components=("flow-engine",), created_days_ago=40),
        ADRSpec("Candidate data retention period", "under_discussion", "one_way",
                "Yara Cohen", "Yara Cohen",
                "How long may transcripts and recordings be kept, and who can delete them?",
                "Proposed: 30 days by default, customer-configurable, with a verified "
                "deletion job.",
                components=("transcript-store",),
                stakeholders=("Yara Cohen", "Daniel Reyes", "Priya Raman"),
                comments=(
                    ADRCommentSpec("Daniel Reyes", "Thirty days matches our customer "
                                   "commitments.", "approve"),
                    ADRCommentSpec("Priya Raman", "The deletion flow needs to be specified "
                                   "before we accept.", "request_changes"),
                    ADRCommentSpec("Yara Cohen", "Agreed; I will add the deletion design.",
                                   "comment"),
                ),
                created_days_ago=22),  # stuck (> 14d)
        ADRSpec("Multilingual interviews", "deferred", owner="Mei Nakamura",
                context="Design partners have asked for Spanish and German; quality varies by "
                        "language.",
                created_days_ago=9, decide_by_weeks=2),
    ),
    drift=(
        DriftSpec("unexpected_dependency",
                  "scoring-service calls session-service for audio features",
                  ("scoring-service", "session-service"),
                  "Violates the transcript-only scoring decision.",
                  "PR #231 (confidence feature experiment)"),
        DriftSpec("unimplemented_adr",
                  "Retention period agreed in discussion but no deletion job exists",
                  ("transcript-store",), status="open"),
    ),
    specs=(
        SpecSpec("Fair, explainable scoring",
                 "Every score must be explainable from the transcript and free of audio, video "
                 "or demographic signals.",
                 "in_progress", "Ananya Bose",
                 context="The core trust promise of the AI Interviewer.",
                 out_of_scope="Rubric authoring UX (separate spec).",
                 adr_title="Scoring uses transcripts only, never raw audio or video",
                 source_url="https://northstar.atlassian.net/wiki/spaces/AII/scoring",
                 criteria=(
                     CriterionSpec("Every score cites transcript evidence.", "met",
                                   "Evidence spans are stored with each score."),
                     CriterionSpec("Scores never use audio or video features.", "unmet",
                                   "A confidence-feature experiment currently violates this "
                                   "(drift)."),
                     CriterionSpec("The rubric is versioned per customer.", "open"),
                     CriterionSpec("An adverse-impact analysis runs per release.", "open"),
                 ),
                 task_names=("Rubric scoring service", "Wire realtime session in")),
    ),
    risks=(
        RiskSpec("Scoring uses signals beyond the transcript", "security", "medium", "high",
                 "mitigating", "Ananya Bose",
                 "Remove the audio-feature path; add a fitness check in CI.",
                 "Disable scoring and fall back to recruiter review.", target_weeks=1),
        RiskSpec("Pilot slips past the customer commitment", "schedule", "high", "high",
                 "open", "Daniel Reyes", "Re-sequence session integration ahead of the "
                 "review UI.", target_weeks=-2),
        RiskSpec("Realtime expertise concentrated in one engineer", "resource", "medium",
                 "high", "open", "Jonah Fields", "Pair Tomás with Leila on the integration."),
    ),
    mitigations=(
        MitigationSpec("deadline_violations",
                       "Re-sequencing the session integration to protect the GA date.",
                       "Priya Raman", False, 1),
        MitigationSpec("quality_signals", "Added the fairness audit to the launch checklist.",
                       "Noor Abadi", True),
    ),
    outcomes=(
        OutcomeSpec("Score agreement with human reviewers", "Cohen's kappa", "κ",
                    0.4, 0.8, 0.66, "on_track", "Ananya Bose"),
        OutcomeSpec("Interview completion rate", "share of started interviews completed", "%",
                    70.0, 92.0, 84.0, "on_track", "Mei Nakamura"),
    ),
    docs=(
        DocSpec("tech_design", "Orchestrator technical design",
                "https://northstar.atlassian.net/wiki/spaces/AII/orchestrator", "manual"),
        DocSpec("architecture", "Fairness review",
                "https://drive.google.com/file/d/doc-fairness/view", "drive"),
        DocSpec("architecture", "Interviewer ADR log (repo)",
                "https://github.com/northstar-ai/interviewer/blob/main/docs/adr/README.md",
                "repo"),
        DocSpec("design", "Interview experience spec (Figma)",
                "https://www.figma.com/file/interview-experience", "jira_epic",
                "Interview experience spec"),
        DocSpec("runbook", "Session integration notes",
                "https://github.com/northstar-ai/interviewer/blob/main/docs/session.md", "repo",
                "Wire realtime session in"),
        DocSpec("tech_design", "Scoring service design",
                "https://drive.google.com/file/d/doc-scoring/view", "drive",
                "Rubric scoring service"),
    ),
    blockers=(
        BlockerSpec("Wire realtime session in",
                    "Waiting on the data-retention decision before persisting session "
                    "recordings.", "decision", "high", "Yara Cohen", "Leila Haddad", False, 5,
                    1),
        BlockerSpec("Conversation flow engine",
                    "Was blocked on a staging media cluster (now resolved).", "resource",
                    "medium", "Sam Okoro", "Tomás Silva", True, 22),
    ),
    retro=RetroSpec("Pilot readiness retrospective", "project_retro",
                    "## Went well\n- The state-machine flow kept interviews on-rubric.\n\n"
                    "## Improve\n- The retention decision started too late.\n\n"
                    "## Actions\n- Raise data decisions at design sign-off.",
                    ("flow-engine",),
                    (RetroCommentSpec("Tomás Silva", "Structure first, then flexibility — "
                                      "it worked."),
                     RetroCommentSpec("Daniel Reyes", "We should surface compliance decisions "
                                      "a sprint earlier."))),
    draft=DraftSpec("Pilot hardening plan", "Proposed hardening before the customer pilot.",
                    "Hardening",
                    (DraftTaskSpec("Automate the bias & fairness audit", "task", 5, 8.0),
                     DraftTaskSpec("Candidate consent flow", "task", 4, 5.0),
                     DraftTaskSpec("Rubric versioning", "task", 3, 5.0))),
    incidents=(IncidentSpec("Scoring latency spike after rubric deploy", 16, 5,
                            "scoring-service"),),
    deploy_weeks=9,
)


# =========================================================================== #
# TALENT PILOT
# =========================================================================== #
_ATSHUB = ProjectSpec(
    "ATSHUB", "ATS Integration Hub",
    "Connectors to the applicant-tracking systems recruiters live in, a normalised candidate "
    "store, and the sync API the copilot consumes.",
    "PILOT", 10, 8, True, "on_track",
    "Greenhouse and Lever connectors live; candidate sync API in flight, Workday next.",
    ("recruiting", "integrations", "backend"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Integration architecture", 3, "Done", 46, "Kenji Mori",
                     ("architecture",)),
            TaskSpec("Candidate data model", 3, "Done", 40, "Olivia Grant", ("data",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Greenhouse connector", 5, "Done", 26, "Kenji Mori", ("integrations",),
                     (4, 5, 8)),
            TaskSpec("Lever connector", 4, "Done", 16, "Kenji Mori", ("integrations",)),
            TaskSpec("Candidate sync API", 4, "In Progress", 9, "Kenji Mori", ("backend",),
                     (3, 4, 7)),
            TaskSpec("Webhook ingestion", 4, "In Progress", 6, "Olivia Grant", ("data",)),
            TaskSpec("Workday connector", 6, "To Do", 0, "Kenji Mori", ("integrations",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Sync observability", 3, "To Do", 0, "Sam Okoro", ("infra",)),
            TaskSpec("Hub GA", 0, "To Do", 0, None, (), None, True, 8),
        )),
    ),
    milestones=(
        MilestoneSpec("Design sign-off", -7, "hit"),
        MilestoneSpec("Two-vendor beta", 1),
        MilestoneSpec("Hub GA", 8),
    ),
    components=(
        ComponentSpec("hub-api", "service", "presentation", "high", "Kenji Mori"),
        ComponentSpec("connector-framework", "module", "business", "high", "Kenji Mori"),
        ComponentSpec("candidate-store", "datastore", "data", "high", "Olivia Grant"),
        ComponentSpec("sync-worker", "service", "business", "med"),
        ComponentSpec("ats-vendors", "external", "infra", "high"),
    ),
    component_links=(
        LinkSpec("hub-api", "candidate-store", "reads_from"),
        LinkSpec("sync-worker", "connector-framework", "depends_on"),
        LinkSpec("connector-framework", "ats-vendors", "calls"),
        LinkSpec("sync-worker", "candidate-store", "publishes_to"),
        LinkSpec("hub-api", "ats-vendors", "calls"),  # violates the normalisation ADR
    ),
    bindings=(BindingSpec("connector-framework", "hub/connectors/**", "northstar.hub"),),
    adrs=(
        ADRSpec("Candidate data is normalised once; the API never calls a vendor directly",
                "accepted", "one_way", "Priya Raman", "Kenji Mori",
                "Vendor schemas differ and change; consumers must not inherit that churn.",
                "All reads go through the normalised candidate store; only the connector "
                "framework talks to vendors.",
                "Stable consumer contract; freshness depends on sync cadence.",
                components=("hub-api", "candidate-store"),
                fitness=FitnessSpec("forbid", "hub-api", "ats-vendors",
                                    "The hub API must not call ATS vendors directly."),
                created_days_ago=41),
        ADRSpec("Sync strategy: polling vs webhooks", "under_discussion", "two_way",
                "Kenji Mori", "Olivia Grant",
                "Webhooks are fresher but not every vendor offers them reliably.",
                "Proposed: webhooks where available, with polling as a reconciliation pass.",
                components=("sync-worker",),
                stakeholders=("Kenji Mori", "Olivia Grant", "Daniel Reyes"),
                comments=(
                    ADRCommentSpec("Olivia Grant", "Reconciliation keeps us honest when a "
                                   "webhook is lost.", "approve"),
                    ADRCommentSpec("Daniel Reyes", "Please quantify freshness per vendor.",
                                   "request_changes"),
                ),
                created_days_ago=9),
        ADRSpec("Workday priority", "deferred", owner="Daniel Reyes",
                context="Two enterprise prospects require Workday; the connector is the "
                        "largest single item on the plan.",
                created_days_ago=18, decide_by_weeks=-1),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "hub-api calls ats-vendors directly",
                  ("hub-api", "ats-vendors"), "Violates the normalisation decision.",
                  "PR #67 (live candidate lookup)"),
    ),
    specs=(
        SpecSpec("Candidate sync freshness",
                 "A change in the ATS is visible to the copilot within minutes, without "
                 "exceeding vendor quotas.",
                 "in_progress", "Kenji Mori",
                 adr_title="Sync strategy: polling vs webhooks",
                 criteria=(
                     CriterionSpec("Webhook-driven changes land within 2 minutes.", "met",
                                   "Measured on Greenhouse sandbox."),
                     CriterionSpec("Polling never exceeds the vendor quota.", "open"),
                     CriterionSpec("A lost webhook is reconciled within an hour.", "open"),
                 ),
                 task_names=("Candidate sync API", "Webhook ingestion")),
    ),
    risks=(
        RiskSpec("Vendor sandbox access delays Workday", "external", "medium", "medium",
                 "open", "Kenji Mori", "Escalate through the partnership contact."),
        RiskSpec("PII handling across vendors", "security", "low", "high", "mitigating",
                 "Yara Cohen", "Field-level classification in the candidate model."),
    ),
    outcomes=(
        OutcomeSpec("Sync freshness", "p95 minutes to visibility", "min",
                    60.0, 5.0, 12.0, "on_track", "Kenji Mori"),
    ),
    docs=(
        DocSpec("tech_design", "Integration hub design",
                "https://github.com/northstar-ai/talent-hub/blob/main/docs/hub.md", "repo"),
        DocSpec("other", "Vendor API notes",
                "https://drive.google.com/file/d/doc-vendor-notes/view", "drive"),
    ),
    blockers=(
        BlockerSpec("Webhook ingestion", "Waiting on vendor sandbox credentials.", "external",
                    "medium", "Kenji Mori", "Olivia Grant", False, 4, 1),
    ),
    retro=RetroSpec("Two-vendor beta retrospective", "project_retro",
                    "## Went well\n- The connector framework made Lever a two-week job.\n\n"
                    "## Improve\n- Request vendor sandboxes earlier.\n\n"
                    "## Actions\n- Sandbox access as a design-phase task.",
                    ("connector-framework",),
                    (RetroCommentSpec("Kenji Mori", "Framework first was the right call."),)),
    deploy_weeks=8,
)

_COPILOT = ProjectSpec(
    "COPILOT", "Recruiter Copilot",
    "The recruiter-facing agent harness: sourcing, screening summaries and scheduling, "
    "surfaced inside the ATS, Slack and email.",
    "PILOT", 7, 12, True, "on_track",
    "Recruiter journey mapped; screening summaries in build, scheduling agent next.",
    ("recruiting", "copilot", "frontend"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Recruiter journey map", 4, "Done", 36, "Mei Nakamura", ("design",)),
            TaskSpec("Copilot architecture", 3, "Done", 30, "Priya Raman", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Consume candidate sync", 3, "In Progress", 6, "Tomás Silva",
                     ("backend",)),
            TaskSpec("Screening summaries", 5, "In Progress", 8, "Ananya Bose", ("ml",),
                     (4, 5, 8)),
            TaskSpec("Scheduling agent", 5, "To Do", 0, "Kenji Mori", ("backend",)),
            TaskSpec("Slack & email surfaces", 4, "To Do", 0, "Chris Walker", ("frontend",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Recruiter pilot", 4, "To Do", 0, "Noor Abadi", ("qa",)),
            TaskSpec("Copilot GA", 0, "To Do", 0, None, (), None, True, 12),
        )),
    ),
    milestones=(
        MilestoneSpec("Journey sign-off", -4, "hit"),
        MilestoneSpec("Recruiter pilot", 5),
        MilestoneSpec("Copilot GA", 12),
    ),
    components=(
        ComponentSpec("copilot-api", "service", "presentation", "high", "Chris Walker"),
        ComponentSpec("recruiter-agent", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("scheduling-agent", "service", "business", "med", "Kenji Mori"),
        ComponentSpec("calendar-service", "external", "infra", "med"),
        ComponentSpec("integration-hub", "external", "infra", "high", "Kenji Mori"),
    ),
    component_links=(
        LinkSpec("copilot-api", "recruiter-agent", "calls"),
        LinkSpec("recruiter-agent", "integration-hub", "reads_from"),
        LinkSpec("recruiter-agent", "scheduling-agent", "calls"),
        LinkSpec("scheduling-agent", "calendar-service", "calls"),
        LinkSpec("recruiter-agent", "calendar-service", "calls"),  # violates the approval ADR
    ),
    bindings=(BindingSpec("recruiter-agent", "copilot/agent/**", "northstar.copilot"),),
    adrs=(
        ADRSpec("The copilot drafts; the recruiter sends", "accepted", "one_way",
                "Priya Raman", "Daniel Reyes",
                "Recruiters must stay accountable for every candidate-facing message.",
                "Outreach and scheduling are drafted by the agent and sent only after the "
                "recruiter confirms; only the scheduling agent may write to calendars.",
                "Trust with recruiters; a confirmation step on every send.",
                components=("recruiter-agent", "scheduling-agent"),
                fitness=FitnessSpec("forbid", "recruiter-agent", "calendar-service",
                                    "Only the scheduling agent, behind recruiter confirmation, "
                                    "may write to calendars."),
                created_days_ago=28),
        ADRSpec("Where the copilot lives: ATS sidebar vs standalone app", "under_discussion",
                "two_way", "Mei Nakamura", "Mei Nakamura",
                "Recruiters resist leaving the ATS; a sidebar limits what we can show.",
                "Proposed: ATS sidebar first, with a standalone review surface for summaries.",
                components=("copilot-api",),
                stakeholders=("Mei Nakamura", "Daniel Reyes", "Chris Walker"),
                comments=(
                    ADRCommentSpec("Daniel Reyes", "Sidebar first matches the pilot "
                                   "recruiters' feedback.", "approve"),
                    ADRCommentSpec("Chris Walker", "We should scope the sidebar's data "
                                   "access carefully.", "comment"),
                ),
                created_days_ago=12),
        ADRSpec("Outreach personalisation depth", "deferred", owner="Daniel Reyes",
                context="Deeper personalisation raises response rates and compliance "
                        "questions in equal measure.",
                created_days_ago=6, decide_by_weeks=3),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "recruiter-agent writes to calendar-service",
                  ("recruiter-agent", "calendar-service"),
                  "Violates the drafts-then-sends decision.",
                  "PR #54 (quick-schedule action)"),
    ),
    specs=(
        SpecSpec("Recruiter in the loop",
                 "No candidate-facing action happens without an explicit recruiter "
                 "confirmation.",
                 "approved", "Daniel Reyes",
                 adr_title="The copilot drafts; the recruiter sends",
                 criteria=(
                     CriterionSpec("Every outbound message shows a confirmation step.", "met",
                                   "Verified in the pilot build."),
                     CriterionSpec("Calendar writes require recruiter confirmation.", "unmet",
                                   "The quick-schedule action bypasses confirmation."),
                     CriterionSpec("Drafts are attributable to the recruiter who sent them.",
                                   "open"),
                 ),
                 task_names=("Scheduling agent", "Screening summaries")),
    ),
    risks=(
        RiskSpec("Summaries omit a disqualifying detail", "quality", "medium", "high",
                 "mitigating", "Ananya Bose", "Evidence-linked summaries; eval on labelled "
                 "set."),
        RiskSpec("Pilot recruiters churn before GA", "resource", "low", "medium", "open",
                 "Daniel Reyes", "Weekly office hours with the pilot group."),
    ),
    outcomes=(
        OutcomeSpec("Summary acceptance rate", "share of summaries used as-is", "%",
                    0.0, 75.0, 52.0, "on_track", "Ananya Bose"),
    ),
    docs=(
        DocSpec("design", "Recruiter journey map (Figma)",
                "https://www.figma.com/file/recruiter-journey", "manual"),
        DocSpec("tech_design", "Copilot design doc",
                "https://northstar.atlassian.net/wiki/spaces/TP/copilot", "manual"),
    ),
    blockers=(
        BlockerSpec("Consume candidate sync", "Waiting on the candidate sync API contract.",
                    "dependency", "medium", "Kenji Mori", "Tomás Silva", False, 3, 1),
    ),
    retro=RetroSpec("Journey-mapping retrospective", "project_retro",
                    "## Went well\n- Recruiter interviews reshaped the scope early.\n\n"
                    "## Improve\n- Involve engineering in the research sessions.\n\n"
                    "## Actions\n- One engineer attends every research session.",
                    ("recruiter-agent",),
                    (RetroCommentSpec("Mei Nakamura", "Research changed the plan for the "
                                      "better."),)),
    draft=DraftSpec("Scheduling agent plan", "Proposed breakdown of the scheduling agent.",
                    "Scheduling",
                    (DraftTaskSpec("Availability lookup across calendars", "task", 3, 5.0),
                     DraftTaskSpec("Candidate-facing scheduling flow", "task", 4, 8.0),
                     DraftTaskSpec("Reschedule & cancellation handling", "task", 3, 5.0))),
    deploy_weeks=6,
)


# =========================================================================== #
# TALENT FORGE
# =========================================================================== #
_STUDIO = ProjectSpec(
    "STUDIO", "Forge Studio",
    "The visual builder customers use to compose fully customizable agent applications: "
    "templates, a flow designer, live preview and publishing.",
    "FORGE", 9, 10, True, "on_track",
    "Flow designer shipped; template library and live preview in build.",
    ("builder", "frontend", "low-code"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Studio information architecture", 4, "Done", 44, "Mei Nakamura",
                     ("design",)),
            TaskSpec("Bundle format ADR", 3, "Done", 38, "Priya Raman", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Flow designer canvas", 6, "Done", 22, "Chris Walker", ("frontend",),
                     (5, 6, 10)),
            TaskSpec("Template library", 4, "In Progress", 10, "Chris Walker", ("frontend",)),
            TaskSpec("Live preview sandbox", 5, "In Progress", 7, "Tomás Silva",
                     ("backend",), (4, 5, 9)),
            TaskSpec("Publish app bundle", 3, "To Do", 0, "Chris Walker", ("backend",)),
            TaskSpec("Theming & branding", 3, "To Do", 0, "Mei Nakamura", ("design",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Design-partner beta", 4, "To Do", 0, "Noor Abadi", ("qa",)),
            TaskSpec("Studio GA", 0, "To Do", 0, None, (), None, True, 10),
        )),
    ),
    milestones=(
        MilestoneSpec("IA sign-off", -6, "hit"),
        MilestoneSpec("Private beta", 2),
        MilestoneSpec("Studio GA", 10),
    ),
    components=(
        ComponentSpec("studio-ui", "ui", "presentation", "high", "Chris Walker"),
        ComponentSpec("designer-service", "service", "business", "high"),
        ComponentSpec("template-catalog", "datastore", "data", "med"),
        ComponentSpec("preview-sandbox", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("bundle-registry", "datastore", "data", "high"),
    ),
    component_links=(
        LinkSpec("studio-ui", "designer-service", "calls"),
        LinkSpec("designer-service", "template-catalog", "reads_from"),
        LinkSpec("designer-service", "preview-sandbox", "calls"),
        LinkSpec("designer-service", "bundle-registry", "publishes_to"),
        LinkSpec("preview-sandbox", "bundle-registry", "publishes_to"),  # violates sandbox ADR
    ),
    bindings=(BindingSpec("designer-service", "studio/designer/**", "northstar.studio"),),
    adrs=(
        ADRSpec("Previews run in an isolated sandbox and never publish", "accepted", "one_way",
                "Priya Raman", "Tomás Silva",
                "A preview that can publish is a path from an unreviewed draft to production.",
                "The preview sandbox has no production data and no write path to the bundle "
                "registry; publishing is an explicit designer action.",
                "Safe experimentation; preview and publish are two distinct steps.",
                components=("preview-sandbox", "bundle-registry"),
                fitness=FitnessSpec("forbid", "preview-sandbox", "bundle-registry",
                                    "The preview sandbox must not write to the bundle "
                                    "registry."),
                created_days_ago=36),
        ADRSpec("Canvas library: React Flow vs custom", "under_discussion", "two_way",
                "Chris Walker", "Chris Walker",
                "The designer needs custom edge semantics the off-the-shelf canvas lacks.",
                "Proposed: keep React Flow and extend with custom edge renderers.",
                components=("studio-ui",),
                stakeholders=("Chris Walker", "Mei Nakamura", "Priya Raman"),
                comments=(
                    ADRCommentSpec("Mei Nakamura", "The custom edges cover the interaction "
                                   "patterns from research.", "approve"),
                    ADRCommentSpec("Priya Raman", "Fine, provided we keep the upgrade path.",
                                   "comment"),
                ),
                created_days_ago=7),
        ADRSpec("Template marketplace", "deferred", owner="Daniel Reyes",
                context="Partners want to share templates; moderation and licensing are open "
                        "questions.",
                created_days_ago=5, decide_by_weeks=4),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "preview-sandbox publishes to bundle-registry",
                  ("preview-sandbox", "bundle-registry"),
                  "Violates the isolated-preview decision.", "PR #120 (publish from preview)"),
    ),
    specs=(
        SpecSpec("Builder usability",
                 "A non-engineer can publish a working application in under thirty minutes.",
                 "in_progress", "Mei Nakamura",
                 criteria=(
                     CriterionSpec("A new user completes the template flow unaided.", "met",
                                   "4 of 5 usability participants succeeded."),
                     CriterionSpec("Publishing takes under five clicks.", "open"),
                     CriterionSpec("Errors are explained in plain language.", "open"),
                 ),
                 task_names=("Template library", "Flow designer canvas")),
    ),
    risks=(
        RiskSpec("Preview sandbox leaks production data", "security", "low", "high",
                 "mitigating", "Yara Cohen", "Synthetic data only in previews."),
        RiskSpec("Designer performance on large flows", "technical", "medium", "medium",
                 "open", "Chris Walker", "Virtualise the canvas above 200 nodes."),
    ),
    outcomes=(
        OutcomeSpec("Time to first published app", "median minutes", "min",
                    120.0, 30.0, 55.0, "on_track", "Mei Nakamura"),
    ),
    docs=(
        DocSpec("design", "Studio design system (Figma)",
                "https://www.figma.com/file/forge-studio", "manual"),
        DocSpec("tech_design", "Bundle format specification",
                "https://github.com/northstar-ai/forge/blob/main/docs/bundle.md", "repo"),
    ),
    blockers=(
        BlockerSpec("Live preview sandbox", "Waiting on synthetic data fixtures from the data "
                    "team.", "dependency", "medium", "Olivia Grant", "Tomás Silva", False, 3,
                    1),
    ),
    retro=RetroSpec("Designer canvas retrospective", "project_retro",
                    "## Went well\n- React Flow got us to a usable canvas quickly.\n\n"
                    "## Improve\n- Performance testing on large flows came late.\n\n"
                    "## Actions\n- Add a 500-node fixture to CI.",
                    ("studio-ui",),
                    (RetroCommentSpec("Chris Walker", "Custom edges were worth it."),)),
    deploy_weeks=7,
)

_DEPLOY = ProjectSpec(
    "DEPLOY", "Forge Deploy",
    "The multi-tenant deployment pipeline for customer-built applications: isolated runtimes, "
    "versioned rollouts, rollback and custom domains.",
    "FORGE", 6, 12, True, "at_risk",
    "Deploy controller consumes bundles; tenant isolation is under security review and GA is "
    "at risk.",
    ("builder", "infra", "multi-tenant"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Deploy architecture", 3, "Done", 34, "Sam Okoro", ("architecture",)),
            TaskSpec("Tenancy model ADR", 3, "Done", 28, "Priya Raman", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Consume app bundles", 4, "In Progress", 8, "Sam Okoro", ("infra",)),
            TaskSpec("Tenant isolation", 5, "In Progress", 12, "Yara Cohen",
                     ("security", "infra"), (4, 5, 9)),
            TaskSpec("Versioned rollouts & rollback", 5, "To Do", 0, "Sam Okoro", ("infra",)),
            TaskSpec("Custom domains & TLS", 3, "To Do", 0, "Sam Okoro", ("infra",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Deploy observability", 3, "To Do", 0, "Sam Okoro", ("infra",)),
            TaskSpec("Deploy GA", 0, "To Do", 0, None, (), None, True, 12),
        )),
    ),
    milestones=(
        MilestoneSpec("Design sign-off", -3, "hit"),
        MilestoneSpec("First tenant deploy", 4, "at_risk"),
        MilestoneSpec("Deploy GA", 12),
    ),
    components=(
        ComponentSpec("deploy-api", "service", "presentation", "high", "Sam Okoro"),
        ComponentSpec("deploy-controller", "service", "business", "high", "Sam Okoro"),
        ComponentSpec("tenant-router", "service", "infra", "high"),
        ComponentSpec("app-runtime", "service", "business", "high"),
        ComponentSpec("secrets-vault", "datastore", "infra", "high", "Yara Cohen"),
    ),
    component_links=(
        LinkSpec("deploy-api", "deploy-controller", "calls"),
        LinkSpec("deploy-controller", "app-runtime", "depends_on"),
        LinkSpec("tenant-router", "app-runtime", "calls"),
        LinkSpec("deploy-controller", "secrets-vault", "reads_from"),
        LinkSpec("app-runtime", "secrets-vault", "reads_from"),  # violates the isolation ADR
    ),
    bindings=(BindingSpec("deploy-controller", "deploy/controller/**", "northstar.deploy"),),
    adrs=(
        ADRSpec("Tenant applications run isolated and never read the vault", "accepted",
                "one_way", "Priya Raman", "Yara Cohen",
                "Customer-built applications are untrusted code from the platform's point of "
                "view.",
                "Each tenant app runs in its own runtime with secrets injected by the "
                "controller; the runtime has no path to the vault.",
                "Strong isolation; a slightly slower cold start per tenant.",
                components=("app-runtime", "secrets-vault"),
                fitness=FitnessSpec("forbid", "app-runtime", "secrets-vault",
                                    "Tenant runtimes must not read the secrets vault."),
                created_days_ago=26),
        ADRSpec("Rollout strategy: blue-green vs canary", "under_discussion", "two_way",
                "Sam Okoro", "Sam Okoro",
                "Customer apps need safe upgrades without a maintenance window.",
                "Proposed: canary per tenant with automatic rollback on error rate.",
                components=("deploy-controller",),
                stakeholders=("Sam Okoro", "Priya Raman", "Noor Abadi"),
                comments=(
                    ADRCommentSpec("Noor Abadi", "Canary gives us a real signal before "
                                   "full rollout.", "approve"),
                    ADRCommentSpec("Priya Raman", "Define the rollback trigger thresholds.",
                                   "request_changes"),
                ),
                created_days_ago=8),
        ADRSpec("Bring-your-own-cloud deploys", "deferred", owner="Sam Okoro",
                context="Two enterprise prospects want apps deployed into their own cloud.",
                created_days_ago=10, decide_by_weeks=2),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "app-runtime reads secrets-vault",
                  ("app-runtime", "secrets-vault"), "Violates the tenant-isolation decision.",
                  "PR #41 (runtime fetches its own API keys)"),
    ),
    specs=(
        SpecSpec("Tenant isolation",
                 "A tenant application can never reach another tenant's data, secrets or "
                 "network.",
                 "in_progress", "Yara Cohen",
                 adr_title="Tenant applications run isolated and never read the vault",
                 criteria=(
                     CriterionSpec("Runtimes have no shared filesystem.", "met",
                                   "Verified by the isolation suite."),
                     CriterionSpec("Secrets are injected, never fetched.", "unmet",
                                   "The runtime currently fetches keys from the vault."),
                     CriterionSpec("Cross-tenant network calls are denied.", "open"),
                 ),
                 task_names=("Tenant isolation", "Consume app bundles")),
    ),
    risks=(
        RiskSpec("Deploy GA slips the Forge launch", "schedule", "high", "high", "open",
                 "Daniel Reyes", "Descope custom domains from GA.", target_weeks=-1),
        RiskSpec("Isolation review finds a blocking issue", "security", "medium", "high",
                 "mitigating", "Yara Cohen", "Review in two passes; fix as we go."),
    ),
    mitigations=(
        MitigationSpec("deadline_violations", "Proposing to descope custom domains from GA.",
                       "Daniel Reyes", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Deploy success rate", "share of deploys without rollback", "%",
                    80.0, 99.0, 91.0, "on_track", "Sam Okoro"),
    ),
    docs=(
        DocSpec("tech_design", "Deploy pipeline design",
                "https://github.com/northstar-ai/forge/blob/main/docs/deploy.md", "repo"),
        DocSpec("architecture", "Tenant isolation threat model",
                "https://drive.google.com/file/d/doc-tenant-threat/view", "drive"),
    ),
    blockers=(
        BlockerSpec("Tenant isolation", "Waiting on the second pass of the security review.",
                    "decision", "high", "Yara Cohen", "Sam Okoro", False, 6, 1),
    ),
    retro=RetroSpec("Deploy controller incident postmortem", "incident_postmortem",
                    "## Impact\n- Rollouts stalled for four hours.\n\n"
                    "## Root cause\n- The controller blocked on a vault timeout.\n\n"
                    "## Actions\n- Inject secrets at build time; time-box vault calls.",
                    ("deploy-controller",),
                    (RetroCommentSpec("Sam Okoro", "This is the same path the isolation ADR "
                                      "forbids."),)),
    incidents=(IncidentSpec("Deploy controller stalled rollouts", 9, 4, "deploy-controller"),),
    deploy_weeks=6,
)


# =========================================================================== #
# DEV AGENTS
# =========================================================================== #
_ONCALL = ProjectSpec(
    "ONCALL", "On-call & Monitoring Agents",
    "Internal agents that triage alerts, assemble incident context and execute runbooks "
    "behind a human approval.",
    "DEVAGENTS", 8, 6, True, "on_track",
    "The triage agent is live in production; incident context API and approved runbook "
    "execution in flight.",
    ("internal", "on-call", "sre"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Triage agent design", 3, "Done", 40, "Sam Okoro", ("design",)),
            TaskSpec("Remediation safety ADR", 3, "Done", 34, "Yara Cohen",
                     ("architecture", "security")),
        )),
        PhaseSpec("Build", (
            TaskSpec("Alert triage agent", 5, "Done", 20, "Sam Okoro", ("backend",),
                     (4, 5, 8)),
            TaskSpec("Incident context API", 4, "In Progress", 7, "Sam Okoro", ("backend",)),
            TaskSpec("Runbook execution with approval", 5, "In Progress", 9, "Tomás Silva",
                     ("backend", "security"), (4, 5, 9)),
            TaskSpec("Postmortem drafting agent", 3, "To Do", 0, "Olivia Grant", ("ml",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Roll out to all services", 4, "To Do", 0, "Sam Okoro", ("rollout",)),
            TaskSpec("Monitoring agents GA", 0, "To Do", 0, None, (), None, True, 6),
        )),
    ),
    milestones=(
        MilestoneSpec("Triage live", -3, "hit"),
        MilestoneSpec("Approved remediation beta", 2),
        MilestoneSpec("Monitoring agents GA", 6),
    ),
    components=(
        ComponentSpec("triage-agent", "service", "business", "high", "Sam Okoro"),
        ComponentSpec("incident-api", "service", "presentation", "high", "Sam Okoro"),
        ComponentSpec("runbook-executor", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("observability-stack", "external", "infra", "high"),
        ComponentSpec("prod-infra", "external", "infra", "high"),
    ),
    component_links=(
        LinkSpec("triage-agent", "observability-stack", "reads_from"),
        LinkSpec("incident-api", "triage-agent", "calls"),
        LinkSpec("runbook-executor", "prod-infra", "calls"),
        LinkSpec("triage-agent", "runbook-executor", "calls"),
        LinkSpec("triage-agent", "prod-infra", "calls"),  # violates the approval ADR
    ),
    bindings=(BindingSpec("triage-agent", "devagents/oncall/**", "northstar.oncall"),),
    adrs=(
        ADRSpec("Remediations require human approval before touching production",
                "accepted", "one_way", "Priya Raman", "Yara Cohen",
                "An agent acting on production without review can turn a minor alert into "
                "an outage.",
                "Only the runbook executor may change production, and only after an on-call "
                "engineer approves the proposed step.",
                "Slower remediation for trivial issues; no unreviewed production changes.",
                components=("triage-agent", "runbook-executor"),
                fitness=FitnessSpec("forbid", "triage-agent", "prod-infra",
                                    "The triage agent must not act on production directly."),
                created_days_ago=32),
        ADRSpec("Paging policy: agent-first vs human-first", "under_discussion", "two_way",
                "Sam Okoro", "Sam Okoro",
                "Should the agent attempt triage before paging a human?",
                "Proposed: agent-first for low-severity alerts, human-first for SEV1 and "
                "SEV2.",
                components=("triage-agent",),
                stakeholders=("Sam Okoro", "Jonah Fields", "Yara Cohen"),
                comments=(
                    ADRCommentSpec("Jonah Fields", "Agent-first on low severity will cut the "
                                   "night pages considerably.", "approve"),
                    ADRCommentSpec("Yara Cohen", "SEV1 must always page a human "
                                   "immediately.", "request_changes"),
                ),
                created_days_ago=9),
        ADRSpec("Cost anomaly agent", "deferred", owner="Olivia Grant",
                context="Cloud spend spikes are caught late; an agent could watch the "
                        "billing feed.",
                created_days_ago=6, decide_by_weeks=3),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "triage-agent restarts production pods directly",
                  ("triage-agent", "prod-infra"), "Violates the human-approval decision.",
                  "PR #19 (auto-restart shortcut)"),
    ),
    specs=(
        SpecSpec("Safe remediation",
                 "No production change is made by an agent without an approving engineer "
                 "on record.",
                 "in_progress", "Yara Cohen",
                 adr_title="Remediations require human approval before touching production",
                 criteria=(
                     CriterionSpec("Every executed runbook step has an approver.", "met",
                                   "Approval recorded in the incident timeline."),
                     CriterionSpec("The triage agent has no production credentials.", "unmet",
                                   "The auto-restart shortcut uses them."),
                     CriterionSpec("Approvals expire after 15 minutes.", "open"),
                 ),
                 task_names=("Runbook execution with approval", "Alert triage agent")),
    ),
    risks=(
        RiskSpec("Triage agent misclassifies a SEV1", "quality", "low", "high", "mitigating",
                 "Sam Okoro", "SEV1 signatures bypass the agent."),
        RiskSpec("Approval fatigue on-call", "resource", "medium", "medium", "open",
                 "Jonah Fields", "Batch low-risk steps into one approval."),
    ),
    outcomes=(
        OutcomeSpec("Night pages per week", "pages between 22:00 and 07:00", "pages",
                    14.0, 4.0, 8.0, "on_track", "Jonah Fields"),
    ),
    docs=(
        DocSpec("runbook", "Triage agent runbook",
                "https://github.com/northstar-ai/dev-agents/blob/main/docs/triage.md", "repo"),
    ),
    blockers=(
        BlockerSpec("Runbook execution with approval",
                    "Waiting on the paging-policy decision for approval routing.", "decision",
                    "medium", "Sam Okoro", "Tomás Silva", False, 4, 2),
    ),
    retro=RetroSpec("Triage rollout retrospective", "project_retro",
                    "## Went well\n- Night pages dropped in the first fortnight.\n\n"
                    "## Improve\n- The auto-restart shortcut should never have shipped.\n\n"
                    "## Actions\n- Fitness check on production credentials in CI.",
                    ("triage-agent",),
                    (RetroCommentSpec("Sam Okoro", "The approval gate is non-negotiable."),)),
    incidents=(IncidentSpec("Triage agent restarted a healthy service", 14, 1, "triage-agent"),),
    deploy_weeks=8,
)

_DEVPROD = ProjectSpec(
    "DEVPROD", "Developer Productivity Agents",
    "Internal agents for code review, test-gap detection, dependency upgrades and "
    "incident-aware pull-request assistance.",
    "DEVAGENTS", 6, 8, True, "on_track",
    "The review agent comments on every pull request; test-gap finder and the incident-aware "
    "assistant in build.",
    ("internal", "productivity", "developer-experience"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Productivity agent portfolio", 3, "Done", 32, "Priya Raman",
                     ("design",)),
            TaskSpec("Review agent guidelines", 2, "Done", 26, "Priya Raman", ("design",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("PR review agent", 5, "Done", 14, "Tomás Silva", ("backend",),
                     (4, 5, 8)),
            TaskSpec("Test-gap finder", 4, "In Progress", 6, "Noor Abadi", ("qa",)),
            TaskSpec("Incident-aware PR assistant", 4, "In Progress", 4, "Tomás Silva",
                     ("backend",)),
            TaskSpec("Dependency upgrade agent", 4, "To Do", 0, "Sam Okoro", ("infra",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Roll out to all repositories", 3, "To Do", 0, "Tomás Silva",
                     ("rollout",)),
            TaskSpec("Productivity GA", 0, "To Do", 0, None, (), None, True, 8),
        )),
    ),
    milestones=(
        MilestoneSpec("Review agent live", -2, "hit"),
        MilestoneSpec("Test-gap beta", 3),
        MilestoneSpec("Productivity GA", 8),
    ),
    components=(
        ComponentSpec("review-agent", "service", "business", "high", "Tomás Silva"),
        ComponentSpec("repo-indexer", "service", "data", "med"),
        ComponentSpec("ci-bridge", "module", "infra", "med"),
        ComponentSpec("source-control", "external", "infra", "high"),
        ComponentSpec("merge-gate", "external", "infra", "high"),
    ),
    component_links=(
        LinkSpec("review-agent", "repo-indexer", "reads_from"),
        LinkSpec("repo-indexer", "source-control", "reads_from"),
        LinkSpec("review-agent", "ci-bridge", "calls"),
        LinkSpec("review-agent", "merge-gate", "calls"),  # violates the human-merge ADR
    ),
    bindings=(BindingSpec("review-agent", "devagents/review/**", "northstar.review"),),
    adrs=(
        ADRSpec("Agents comment and propose; merging remains a human action", "accepted",
                "one_way", "Priya Raman", "Priya Raman",
                "Review agents are advisory; a human owns what ships.",
                "The review agent may comment, suggest and open pull requests, but it never "
                "merges.",
                "Clear accountability; dependency bumps still need a human click.",
                components=("review-agent", "merge-gate"),
                fitness=FitnessSpec("forbid", "review-agent", "merge-gate",
                                    "The review agent must not call the merge gate."),
                created_days_ago=24),
        ADRSpec("Review agent tone and scope", "under_discussion", "two_way", "Mei Nakamura",
                "Mei Nakamura",
                "Early feedback: the agent is thorough but reads as abrupt.",
                "Proposed: lead with the one blocking finding; everything else as a "
                "collapsed list.",
                components=("review-agent",),
                stakeholders=("Mei Nakamura", "Tomás Silva", "Jonah Fields"),
                comments=(
                    ADRCommentSpec("Jonah Fields", "Fewer, better comments will land "
                                   "better with the team.", "approve"),
                    ADRCommentSpec("Tomás Silva", "We can rank findings by confidence.",
                                   "comment"),
                ),
                created_days_ago=6),
        ADRSpec("IDE integration", "deferred", owner="Chris Walker",
                context="Engineers want the review agent inside the editor, not only on "
                        "pull requests.",
                created_days_ago=5, decide_by_weeks=2),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "review-agent auto-merges dependency bumps",
                  ("review-agent", "merge-gate"), "Violates the human-merge decision.",
                  "PR #77 (auto-merge for patch bumps)"),
    ),
    specs=(
        SpecSpec("Useful, humane code review",
                 "Engineers act on the agent's findings and do not mute it.",
                 "approved", "Mei Nakamura",
                 adr_title="Review agent tone and scope",
                 criteria=(
                     CriterionSpec("At least half of findings are resolved by the author.",
                                   "met", "58% over the last four weeks."),
                     CriterionSpec("No repository disables the agent.", "open"),
                     CriterionSpec("Findings link to the guideline they cite.", "open"),
                 ),
                 task_names=("PR review agent", "Test-gap finder")),
    ),
    risks=(
        RiskSpec("Noisy findings erode trust", "quality", "medium", "medium", "mitigating",
                 "Mei Nakamura", "Confidence ranking; cap comments per PR."),
    ),
    outcomes=(
        OutcomeSpec("Findings acted on", "share of findings resolved", "%",
                    30.0, 70.0, 58.0, "on_track", "Priya Raman"),
    ),
    docs=(
        DocSpec("other", "Review agent guidelines",
                "https://github.com/northstar-ai/dev-agents/blob/main/docs/review.md", "repo"),
    ),
    blockers=(
        BlockerSpec("Incident-aware PR assistant",
                    "Waiting on the incident context API.", "dependency", "medium",
                    "Sam Okoro", "Tomás Silva", False, 2, 1),
    ),
    retro=RetroSpec("Review agent rollout retrospective", "project_retro",
                    "## Went well\n- Review turnaround halved on the pilot repos.\n\n"
                    "## Improve\n- Tone and volume of comments.\n\n"
                    "## Actions\n- Rank by confidence; lead with the blocking finding.",
                    ("review-agent",),
                    (RetroCommentSpec("Tomás Silva", "The signal is there; the delivery "
                                      "needs work."),)),
    deploy_weeks=6,
)


PROJECTS: tuple[ProjectSpec, ...] = (
    _RUNTIME, _GATEWAY, _SESSION, _INTERVIEW, _ATSHUB, _COPILOT, _STUDIO, _DEPLOY, _ONCALL,
    _DEVPROD,
)

FLAGSHIP_KEY = "INTERVIEW"

# Cross-project hand-offs inside one initiative (drive the cross-project critical path).
CROSS_PROJECT_HANDOFFS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("GATEWAY", "Model routing API"), ("RUNTIME", "Integrate model gateway")),
    (("SESSION", "Turn-taking & barge-in"), ("INTERVIEW", "Wire realtime session in")),
    (("ATSHUB", "Candidate sync API"), ("COPILOT", "Consume candidate sync")),
    (("STUDIO", "Publish app bundle"), ("DEPLOY", "Consume app bundles")),
    (("ONCALL", "Incident context API"), ("DEVPROD", "Incident-aware PR assistant")),
)

SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        "INTERVIEWER", "Pair a second realtime engineer to protect the pilot",
        "The session integration is the at-risk critical path. What if Tomás joins Leila on "
        "the integration so the pilot recovers and GA pulls in two weeks?",
        "INTERVIEW", status="ready",
        added_tasks=(
            ScenarioAddedTask("Parallelise session integration", 4, "Tomás Silva",
                              after_task="Conversation flow engine"),
        ),
        duration_overrides=(("Wire realtime session in", 3),),
        allocations=(ScenarioAllocSpec("Tomás Silva", "INTERVIEW", 80, 0, 12),),
        milestone_pulls=(ScenarioMilestonePull("Interviewer GA", -2),),
        target_weeks_delta=-2,
    ),
    ScenarioSpec(
        "PILOT", "Defer Workday to land the copilot sooner",
        "What if the Workday connector moves out of this quarter and Kenji's time goes to the "
        "copilot's scheduling agent instead?",
        "ATSHUB", status="draft",
        removed_tasks=("Workday connector",),
        added_tasks=(
            ScenarioAddedTask("Harden Greenhouse & Lever sync", 3, "Kenji Mori",
                              after_task="Candidate sync API"),
        ),
        allocations=(ScenarioAllocSpec("Kenji Mori", "COPILOT", 40, 0, 10),),
        milestone_pulls=(ScenarioMilestonePull("Hub GA", -2),),
        target_weeks_delta=-2,
    ),
    ScenarioSpec(
        "FORGE", "Plan around the summer leave crunch",
        "What if Sam and Yara are both out over the summer? Model the availability dip and "
        "the buffer the rollout work needs to absorb it.",
        "DEPLOY", status="draft",
        duration_overrides=(("Versioned rollouts & rollback", 8),),
        availability=(
            ScenarioAvailSpec("Sam Okoro", 4, 6, 0.0, "Summer leave"),
            ScenarioAvailSpec("Yara Cohen", 2, 3, 0.0, "Parental leave"),
        ),
        milestone_pulls=(ScenarioMilestonePull("Deploy GA", 2),),
        target_weeks_delta=2,
    ),
    ScenarioSpec(
        "BUILDER", "Pull the eval harness forward",
        "What if QA pairs on the eval harness so every agent passes an eval gate a week "
        "earlier?",
        "GATEWAY", status="draft",
        duration_overrides=(("Eval harness runner", 3),),
        allocations=(ScenarioAllocSpec("Noor Abadi", "GATEWAY", 50, 0, 8),),
        milestone_pulls=(ScenarioMilestonePull("Gateway GA", -1),),
        target_weeks_delta=-1,
    ),
    ScenarioSpec(
        "DEVAGENTS", "Roll the productivity agents out in one wave",
        "What if the dependency-upgrade agent is deferred and repository onboarding is "
        "automated so every repo gets the review agent at once?",
        "DEVPROD", status="draft",
        removed_tasks=("Dependency upgrade agent",),
        added_tasks=(
            ScenarioAddedTask("Repository onboarding automation", 3, "Sam Okoro",
                              after_task="PR review agent"),
        ),
        milestone_pulls=(ScenarioMilestonePull("Productivity GA", -1),),
        target_weeks_delta=-1,
    ),
)


def demo_connections(flagship_project_id: int) -> list[DemoConnection]:
    return [
        DemoConnection("jira", "Jira — northstar.atlassian.net", {
            "demo": True,
            "base_url": "https://northstar.atlassian.net",
            "project_id": flagship_project_id,
            "jira_project_key": "AII",
            "email": "demo@northstar.ai",
            "board_id": 1,
            "story_point_field": "customfield_10016",
            "epic_issue_type": "Epic",
            "story_issue_type": "Story",
        }),
        DemoConnection("github", "GitHub — northstar-ai/interviewer", {
            "demo": True, "owner": "northstar-ai", "repo": "interviewer",
        }),
        DemoConnection("gdrive", "Google Drive — Northstar docs", {
            "demo": True, "folder_id": "demo-folder",
        }),
    ]


AGENTIC = Dataset(
    key="agentic",
    name="Northstar — agentic talent platform",
    description="AI Interviewer, Talent Pilot, Talent Forge, Agent Builder and Dev Agents "
                "(5 initiatives, 10 projects) run by a cross-functional core team of project "
                "leads.",
    users=USERS, team_roles=TEAM_ROLES, engineers=ENGINEERS, availability=AVAILABILITY,
    allocations=ALLOCATIONS, initiatives=INITIATIVES, projects=PROJECTS,
    cross_project_handoffs=CROSS_PROJECT_HANDOFFS, scenarios=SCENARIOS,
    flagship_key=FLAGSHIP_KEY, baseline_inflight_task="Rubric scoring service",
    github_repo="northstar-ai/interviewer", jira_project_key="AII",
    jira_epic=("920000", "AII-100"),
    jira_task_keys=(("920101", "AII-101", "Interview experience spec"),
                    ("920102", "AII-102", "Conversation flow engine"),
                    ("920103", "AII-103", "Interview flow architecture"),
                    ("920104", "AII-104", "Rubric scoring service"),
                    ("920105", "AII-105", "Wire realtime session in"),
                    ("920106", "AII-106", "Rubric & scoring ADR")),
    pull_requests=(
        PullRequestSpec(231, "Rubric scoring: transcript evidence spans", "open",
                        "ananyabose", "Rubric scoring service"),
        PullRequestSpec(228, "Wire realtime session into the orchestrator", "open",
                        "leilahaddad", "Wire realtime session in"),
        PullRequestSpec(219, "Conversation flow engine", "closed", "tomassilva",
                        "Conversation flow engine"),
    ),
    connections=demo_connections,
)
