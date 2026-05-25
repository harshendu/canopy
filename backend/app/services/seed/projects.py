"""The 8 demo projects (declarative). Split out of catalog.py for readability.

Each project is fully populated — a scheduled WBS, an architecture map + ADRs (incl. one
accepted with a fitness function and one in active review), specs, risks, outcomes, docs,
blockers, a retro, and activity — so every per-project tab has real content. Task names here
are referenced by specs / blockers / cross-project hand-offs, so keep them in sync.
"""

from __future__ import annotations

from app.services.seed.catalog import (
    ADRCommentSpec,
    ADRSpec,
    BindingSpec,
    BlockerSpec,
    ComponentSpec,
    CriterionSpec,
    DocSpec,
    DraftSpec,
    DraftTaskSpec,
    DriftSpec,
    FitnessSpec,
    IncidentSpec,
    LinkSpec,
    MilestoneSpec,
    MitigationSpec,
    OutcomeSpec,
    PhaseSpec,
    ProjectSpec,
    RetroCommentSpec,
    RetroSpec,
    RiskSpec,
    SpecSpec,
    TaskSpec,
)

# =========================================================================== #
# CONTROL PLANE
# =========================================================================== #
_CPORCH = ProjectSpec(
    "CPORCH", "Control Plane Orchestrator",
    "Multi-tenant orchestration & scheduling of the customer data-plane fleet.",
    "CONTROL-PLANE", 10, 10, True, "on_track",
    "Tenant-aware scheduler shipped; quotas/isolation in flight, multi-region deferred.",
    ("control-plane", "backend", "multi-tenant"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Fleet model & tenancy ADR", 3, "Done", 49, "Ravi Iyer", ("architecture",)),
            TaskSpec("Scheduler design", 4, "Done", 38, "Sofia Garcia", ("backend",), (3, 4, 7)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Tenant-aware scheduler", 6, "Done", 24, "Ravi Iyer", ("backend",),
                     (4, 6, 10)),
            TaskSpec("Per-tenant quotas & isolation", 5, "In Progress", 30, "Sofia Garcia",
                     ("backend", "security"), (4, 5, 9)),
            TaskSpec("Consume policy bundles", 4, "In Progress", 8, "Ravi Iyer", ("backend",)),
            TaskSpec("Fleet health reconciler", 4, "To Do", 0, "Sofia Garcia", ("backend",)),
        )),
        PhaseSpec("Rollout", (
            TaskSpec("Multi-region autoscaling", 5, "To Do", 0, "Ravi Iyer", ("infra",)),
            TaskSpec("Orchestrator GA", 0, "To Do", 0, None, (), None, True, 10),
        )),
    ),
    milestones=(
        MilestoneSpec("Design sign-off", -7, "hit"),
        MilestoneSpec("Orchestrator beta", 4),
        MilestoneSpec("GA", 10),
    ),
    components=(
        ComponentSpec("control-api", "service", "presentation", "high", "Sofia Garcia"),
        ComponentSpec("orchestrator", "service", "business", "high", "Ravi Iyer"),
        ComponentSpec("scheduler", "module", "business", "high"),
        ComponentSpec("tenant-registry", "datastore", "data", "high"),
    ),
    component_links=(
        LinkSpec("control-api", "orchestrator", "calls"),
        LinkSpec("orchestrator", "scheduler", "depends_on"),
        LinkSpec("orchestrator", "tenant-registry", "reads_from"),
        LinkSpec("control-api", "tenant-registry", "reads_from"),  # violates the layering ADR
    ),
    bindings=(BindingSpec("orchestrator", "control-plane/orchestrator/**", "helix.orchestrator"),),
    adrs=(
        ADRSpec("Cell-based multi-tenancy", "accepted", "one_way", "Aanya Sharma", "Ravi Iyer",
                "Shared services suffer noisy-neighbour effects at tenant scale.",
                "Partition tenants into isolated cells; the API never touches tenant storage.",
                "Strong isolation; more infrastructure to operate.",
                components=("orchestrator", "control-api"),
                fitness=FitnessSpec("forbid", "control-api", "tenant-registry",
                                    "The control API must not read tenant storage directly."),
                created_days_ago=40),
        ADRSpec("Scheduling: fair-share vs strict priority", "under_discussion", "two_way",
                "Ravi Iyer", "Sofia Garcia",
                "Fleet scheduling must balance fairness against latency-sensitive tenants.",
                "Proposed: weighted fair-share with a priority boost.",
                components=("scheduler",),
                stakeholders=("Ravi Iyer", "Sofia Garcia", "Aanya Sharma"),
                comments=(
                    ADRCommentSpec("Sofia Garcia", "Fair-share keeps small tenants healthy.",
                                   "approve"),
                    ADRCommentSpec("Aanya Sharma", "Need a priority lane for paid tiers.",
                                   "request_changes"),
                    ADRCommentSpec("Ravi Iyer", "We can add a boost factor per tier.", "comment"),
                ),
                created_days_ago=20),
        ADRSpec("Defer multi-region to Q4", "deferred", owner="Aanya Sharma",
                context="Latency for non-US tenants is high but multi-region is costly now.",
                created_days_ago=12, decide_by_weeks=-1),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "control-api reads tenant-registry directly",
                  ("control-api", "tenant-registry"),
                  "Violates the cell-based multi-tenancy layering ADR.",
                  "PR #214 (quota lookup shortcut)"),
    ),
    specs=(
        SpecSpec("Tenant isolation guarantees",
                 "A tenant must never see another tenant's jobs, data, or quota.",
                 "in_progress", "Ravi Iyer",
                 context="Underpins the cell-based multi-tenancy decision.",
                 adr_title="Cell-based multi-tenancy",
                 criteria=(
                     CriterionSpec("Jobs are scoped to a tenant cell.", "met",
                                   "Verified by the isolation test suite."),
                     CriterionSpec("Quotas are enforced per tenant.", "open"),
                     CriterionSpec("Cross-cell access is denied by default.", "unmet",
                                   "Quota lookup currently bypasses the cell boundary."),
                 ),
                 task_names=("Per-tenant quotas & isolation", "Tenant-aware scheduler")),
    ),
    risks=(
        RiskSpec("Scheduler hot-spotting under burst load", "technical", "medium", "high",
                 "mitigating", "Ravi Iyer", "Shadow-load test before GA; add backpressure."),
        RiskSpec("Cross-tenant data leakage via shared cache", "security", "low", "high",
                 "open", "Yuki Tanaka", "Namespace cache keys per tenant."),
    ),
    mitigations=(
        MitigationSpec("over_allocation", "Rebalance Sofia off the registry next sprint.",
                       "Marcus Lee", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Scheduler decision latency", "p99 schedule latency", "ms",
                    200.0, 50.0, 90.0, "on_track", "Ravi Iyer"),
    ),
    docs=(
        DocSpec("tech_design", "Orchestrator design doc",
                "https://github.com/helix-io/control-plane/blob/main/docs/orchestrator.md",
                "repo"),
    ),
    blockers=(
        BlockerSpec("Per-tenant quotas & isolation",
                    "Waiting on the security sign-off for cell isolation.", "decision", "high",
                    "Yuki Tanaka", "Ravi Iyer", False, 5, 1),
    ),
    retro=RetroSpec("Orchestrator beta retrospective", "project_retro",
                    "## Went well\n- Cell model simplified isolation reasoning.\n\n"
                    "## Improve\n- Earlier load testing.\n\n## Actions\n- Add shadow-load to CI.",
                    ("orchestrator",),
                    (RetroCommentSpec("Ravi Iyer", "Cells were the right call."),
                     RetroCommentSpec("Sofia Garcia", "Let's load-test sooner next time."))),
    deploy_weeks=8,
)

_REGISTRY = ProjectSpec(
    "REGISTRY", "Model & Policy Registry",
    "Versioned models and governance policies the control plane pushes to data planes.",
    "CONTROL-PLANE", 8, 9, True, "on_track",
    "Versioning + publish API landing; signing is the gate before GA.",
    ("control-plane", "backend", "governance"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Registry data model", 3, "Done", 40, "Sofia Garcia", ("backend",)),
            TaskSpec("Versioning & immutability ADR", 2, "Done", 30, "Aanya Sharma",
                     ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Content-addressed storage", 5, "Done", 18, "Grace Liu", ("data",),
                     (4, 5, 8)),
            TaskSpec("Policy bundle publish API", 4, "In Progress", 12, "Sofia Garcia",
                     ("backend",), (3, 4, 7)),
            TaskSpec("Artifact signing & verification", 4, "To Do", 0, "Sofia Garcia",
                     ("backend", "security")),
            TaskSpec("Rollback & pinning", 3, "To Do", 0, "Grace Liu", ("data",)),
        )),
    ),
    milestones=(MilestoneSpec("Publish API beta", 3), MilestoneSpec("Registry GA", 9)),
    components=(
        ComponentSpec("registry-api", "service", "presentation", "high", "Sofia Garcia"),
        ComponentSpec("blob-store", "datastore", "data", "high"),
        ComponentSpec("signer", "module", "business", "high"),
    ),
    component_links=(
        LinkSpec("registry-api", "blob-store", "reads_from"),
        LinkSpec("registry-api", "signer", "calls"),
    ),
    adrs=(
        ADRSpec("Content-addressed, immutable artifacts", "accepted", "one_way",
                "Aanya Sharma", "Sofia Garcia",
                "Pushed artifacts must be reproducible and tamper-evident.",
                "Store artifacts by content hash; never mutate a published version.",
                components=("blob-store",),
                fitness=FitnessSpec("require", "registry-api", "signer",
                                    "Every publish path must go through the signer."),
                created_days_ago=28),
        ADRSpec("Signing: Sigstore vs in-house KMS", "proposed", proposer="Sofia Garcia",
                context="We need artifact signatures customers can verify offline.",
                created_days_ago=6),  # overdue triage (past the 72h SLA)
    ),
    specs=(
        SpecSpec("Tamper-evident publishing",
                 "A customer must be able to verify an artifact was published by Helix, unchanged.",
                 "approved", "Sofia Garcia", adr_title="Content-addressed, immutable artifacts",
                 criteria=(
                     CriterionSpec("Artifacts are addressed by content hash.", "met"),
                     CriterionSpec("Every artifact is signed before publish.", "open"),
                     CriterionSpec("Verification works without network access.", "open"),
                 ),
                 task_names=("Artifact signing & verification", "Content-addressed storage")),
    ),
    risks=(
        RiskSpec("Key management complexity slows GA", "technical", "medium", "medium",
                 "open", "Sofia Garcia", "Spike Sigstore early to de-risk."),
    ),
    outcomes=(
        OutcomeSpec("Artifact publish reliability", "publish success rate", "%",
                    97.0, 99.9, 99.0, "on_track", "Sofia Garcia"),
    ),
    docs=(DocSpec("design", "Registry design", "https://drive.google.com/file/d/doc-reg/view",
                  "drive"),),
    blockers=(),
    retro=RetroSpec("Registry storage retro", "project_retro",
                    "## Went well\n- Content addressing simplified rollback.",
                    comments=(RetroCommentSpec("Grace Liu", "CAS made pinning trivial."),)),
    draft=DraftSpec("GA hardening plan", "Hardening work to review before creating tickets.",
                    "Registry hardening",
                    (DraftTaskSpec("Signature key rotation", "task", 3, 5.0),
                     DraftTaskSpec("Multi-region replication", "task", 5, 8.0),
                     DraftTaskSpec("Disaster-recovery drill", "task", 2, 3.0))),
    deploy_weeks=7,
)

_CONSOLE = ProjectSpec(
    "CONSOLE", "Admin Console & Dashboards",
    "The vendor + customer-admin web UI: tenants, fleet health, usage and audit.",
    "CONTROL-PLANE", 7, 12, False, "at_risk",
    "Tenant management shipped; the fleet-health dashboard is aging in review.",
    ("control-plane", "frontend"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Information architecture", 3, "Done", 35, "Lena Brooks", ("design",)),
            TaskSpec("Component library", 4, "Done", 22, "Hannah Schmidt", ("frontend",),
                     (3, 4, 6)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Tenant management screens", 5, "Done", 14, "Hannah Schmidt",
                     ("frontend",), (4, 5, 8)),
            TaskSpec("Fleet-health dashboard", 6, "In Progress", 26, "Hannah Schmidt",
                     ("frontend",), (4, 6, 11)),
            TaskSpec("Usage & billing views", 4, "To Do", 0, "Hannah Schmidt", ("frontend",)),
            TaskSpec("Audit-log viewer", 3, "To Do", 0, "Hannah Schmidt", ("frontend",)),
        )),
    ),
    milestones=(MilestoneSpec("Console beta", 5), MilestoneSpec("GA", 12)),
    components=(
        ComponentSpec("web-console", "ui", "presentation", "high", "Hannah Schmidt"),
        ComponentSpec("bff", "service", "presentation", "med", "Sofia Garcia"),
    ),
    component_links=(LinkSpec("web-console", "bff", "calls"),),
    adrs=(
        ADRSpec("Backend-for-frontend over direct control-API", "accepted", "two_way",
                "Aanya Sharma", "Hannah Schmidt",
                "The console needs aggregated, shaped reads the control API doesn't expose.",
                "Introduce a thin BFF that composes control-plane reads for the UI.",
                components=("bff", "web-console"), created_days_ago=24),
    ),
    specs=(
        SpecSpec("Fleet health at a glance",
                 "An admin must see, in one screen, which tenant fleets are unhealthy and why.",
                 "in_progress", "Lena Brooks",
                 criteria=(
                     CriterionSpec("Unhealthy fleets surface at the top.", "open"),
                     CriterionSpec("Each fleet links to its tenant + recent incidents.", "open"),
                     CriterionSpec("Loads under 1.5s with 500 fleets.", "unmet",
                                   "Currently 3.2s — needs server-side aggregation."),
                 ),
                 task_names=("Fleet-health dashboard",)),
    ),
    risks=(
        RiskSpec("Dashboard performance at fleet scale", "technical", "high", "medium",
                 "mitigating", "Hannah Schmidt", "Move aggregation into the BFF."),
        RiskSpec("Design capacity is a single point of failure", "resource", "medium", "medium",
                 "open", "Marcus Lee", "Cross-train a second engineer on the design system."),
    ),
    outcomes=(
        OutcomeSpec("Admin task completion", "time to find an unhealthy fleet", "sec",
                    90.0, 20.0, 55.0, "on_track", "Lena Brooks"),
    ),
    docs=(
        DocSpec("design", "Console design system",
                "https://figma.com/file/helix-console", "manual"),
    ),
    blockers=(
        BlockerSpec("Fleet-health dashboard",
                    "Blocked on a fleet-health aggregation endpoint from the orchestrator team.",
                    "dependency", "medium", "Ravi Iyer", "Hannah Schmidt", False, 7, 1),
    ),
    retro=RetroSpec("Console design-system retro", "project_retro",
                    "## Went well\n- Shared component library paid off.",
                    comments=(RetroCommentSpec("Hannah Schmidt", "Reuse cut build time."),)),
    deploy_weeks=6,
)

# =========================================================================== #
# DATA PLANE
# =========================================================================== #
_ENGINE = ProjectSpec(
    "ENGINE", "Intelligence Engine",
    "The customer-deployed processing engine — the intelligence suite that runs in the "
    "customer's own VPC so their data never leaves their environment.",
    "DATA-PLANE", 9, 11, True, "at_risk",
    "Pipeline shipped; the secure-gateway integration is the critical path and at risk.",
    ("data-plane", "byoc", "rust", "intelligence"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Engine architecture", 3, "Done", 52, "Aanya Sharma", ("architecture",)),
            TaskSpec("Enclave & key-handling ADR", 3, "Done", 45, "Yuki Tanaka",
                     ("architecture", "security")),
            TaskSpec("Processing contract spec", 4, "Done", 38, "Tom Becker", ("design",),
                     (3, 4, 7)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Streaming pipeline core", 6, "Done", 28, "Tom Becker", ("backend",),
                     (5, 6, 11)),
            TaskSpec("In-VPC model execution", 5, "In Progress", 34, "Tom Becker",
                     ("backend", "intelligence"), (4, 5, 9)),
            TaskSpec("Wire secure gateway in", 5, "In Progress", 10, "Yuki Tanaka",
                     ("backend", "security"), (3, 5, 9), deadline_weeks=1),
            TaskSpec("Local result cache", 4, "To Do", 0, "Grace Liu", ("data",)),
            TaskSpec("Package engine artifact", 2, "To Do", 0, "Tom Becker", ("backend",)),
        )),
        PhaseSpec("Harden & Launch", (
            TaskSpec("Soak & chaos testing", 5, "To Do", 0, "Mei Lin", ("qa",)),
            TaskSpec("Private preview", 0, "at_risk", 0, None, (), None, True, -2),
            TaskSpec("BYOC GA", 0, "To Do", 0, None, (), None, True, 11),
        )),
    ),
    milestones=(
        MilestoneSpec("Architecture sign-off", -8, "hit"),
        MilestoneSpec("Private preview", -2, "at_risk"),  # overdue → alert
        MilestoneSpec("BYOC GA", 11),
    ),
    components=(
        ComponentSpec("engine-core", "service", "business", "high", "Tom Becker"),
        ComponentSpec("model-runtime", "module", "business", "high", "Tom Becker"),
        ComponentSpec("secure-enclave", "module", "infra", "high", "Yuki Tanaka"),
        ComponentSpec("local-store", "datastore", "data", "high"),
        ComponentSpec("data-gateway", "external", "infra", "high", "Yuki Tanaka"),
    ),
    component_links=(
        LinkSpec("engine-core", "model-runtime", "depends_on"),
        LinkSpec("engine-core", "local-store", "reads_from"),
        LinkSpec("engine-core", "secure-enclave", "depends_on"),
        LinkSpec("engine-core", "data-gateway", "calls"),
    ),
    bindings=(
        BindingSpec("engine-core", "data-plane/engine/**", "helix.engine"),
        BindingSpec("secure-enclave", "data-plane/enclave/**", "helix.enclave"),
    ),
    adrs=(
        ADRSpec("Process data only inside the customer VPC", "accepted", "one_way",
                "Aanya Sharma", "Yuki Tanaka",
                "Customers require that raw data never leaves their environment.",
                "All processing runs in-VPC; only aggregates/telemetry leave via the gateway.",
                "Strong data-residency story; harder deploys and debugging.",
                components=("engine-core", "secure-enclave"),
                fitness=FitnessSpec("forbid", "engine-core", "data-gateway",
                                    "The engine must not send raw data through the gateway; "
                                    "only the enclave-approved aggregate path may."),
                created_days_ago=44),
        ADRSpec("Engine runtime: Rust vs Go", "accepted", "two_way", "Aanya Sharma",
                "Tom Becker", "The hot path needs predictable latency and memory.",
                "Use Rust for the streaming core.", alternatives=("Go", "C++"),
                components=("engine-core",), created_days_ago=40),
        ADRSpec("Key custody: customer-managed vs Helix-managed", "under_discussion", "one_way",
                "Yuki Tanaka", "Yuki Tanaka",
                "Who holds the keys that decrypt customer data in the enclave?",
                "Proposed: customer-managed keys (BYOK) with enclave attestation.",
                components=("secure-enclave",),
                stakeholders=("Yuki Tanaka", "Aanya Sharma", "Ravi Iyer"),
                comments=(
                    ADRCommentSpec("Yuki Tanaka", "BYOK is the only defensible posture.",
                                   "approve"),
                    ADRCommentSpec("Aanya Sharma", "Attestation flow needs more detail.",
                                   "request_changes"),
                    ADRCommentSpec("Ravi Iyer", "Agree on BYOK; let's spec attestation.",
                                   "comment"),
                ),
                created_days_ago=22),  # stuck (> 14d)
        ADRSpec("Telemetry sampling at the edge", "deferred", owner="Tom Becker",
                context="Full telemetry is too costly to egress; sampling needs design.",
                created_days_ago=9, decide_by_weeks=2),
    ),
    drift=(
        DriftSpec("unexpected_dependency",
                  "engine-core sends raw payloads through data-gateway",
                  ("engine-core", "data-gateway"),
                  "Violates the in-VPC processing ADR — raw data must stay in-tenant.",
                  "PR #318 (debug passthrough left enabled)"),
        DriftSpec("unimplemented_adr",
                  "BYOK key custody accepted in discussion but not wired in the enclave",
                  ("secure-enclave",), status="open"),
    ),
    specs=(
        SpecSpec("Zero raw-data egress",
                 "No raw customer record may leave the customer VPC; only enclave-approved "
                 "aggregates and telemetry may.",
                 "in_progress", "Yuki Tanaka",
                 context="The core promise of the BYOC data plane.",
                 out_of_scope="Telemetry sampling policy (separate ADR).",
                 adr_title="Process data only inside the customer VPC",
                 source_url="https://helix.atlassian.net/wiki/spaces/DP/egress",
                 criteria=(
                     CriterionSpec("Raw records never traverse the gateway.", "unmet",
                                   "A debug passthrough currently violates this (drift)."),
                     CriterionSpec("Aggregates pass enclave approval before egress.", "open"),
                     CriterionSpec("Egress volume is observable per tenant.", "met",
                                   "Gateway meters bytes per tenant."),
                     CriterionSpec("Keys are customer-managed.", "open"),
                 ),
                 task_names=("Wire secure gateway in", "In-VPC model execution")),
    ),
    risks=(
        RiskSpec("Raw-data egress via the gateway", "security", "medium", "high", "mitigating",
                 "Yuki Tanaka", "Enforce egress allow-list; block raw payloads at the enclave.",
                 "Kill-switch the gateway and notify the customer.", target_weeks=1),
        RiskSpec("Enclave attestation slips the GA date", "schedule", "high", "high", "open",
                 "Aanya Sharma", "Time-box the attestation spike to two weeks.", target_weeks=-2),
        RiskSpec("Rust expertise concentrated in one engineer", "resource", "medium", "high",
                 "open", "Marcus Lee", "Pair a second engineer on the streaming core."),
    ),
    mitigations=(
        MitigationSpec("deadline_violations",
                       "Re-sequencing gateway work to protect the GA date.", "Aanya Sharma",
                       False, 1),
        MitigationSpec("quality_signals", "Added soak testing to relieve late-stage risk.",
                       "Mei Lin", True),
    ),
    outcomes=(
        OutcomeSpec("Raw data egress", "raw bytes egressed", "MB/day",
                    120.0, 0.0, 8.0, "on_track", "Yuki Tanaka"),
        OutcomeSpec("Engine throughput", "records/sec/node", "rps",
                    5000.0, 20000.0, 14000.0, "on_track", "Tom Becker"),
    ),
    docs=(
        DocSpec("tech_design", "Engine technical design",
                "https://helix.atlassian.net/wiki/spaces/DP/engine", "manual"),
        DocSpec("architecture", "Enclave threat model",
                "https://drive.google.com/file/d/doc-threat/view", "drive"),
        DocSpec("design", "Processing contract (OpenAPI)",
                "https://helix.atlassian.net/wiki/spaces/DP/contract", "jira_epic",
                "Processing contract spec"),
    ),
    blockers=(
        BlockerSpec("Wire secure gateway in",
                    "Waiting on the key-custody decision before wiring decryption.",
                    "decision", "high", "Yuki Tanaka", "Tom Becker", False, 5, 1),
        BlockerSpec("Streaming pipeline core",
                    "Was blocked on a staging cluster (now resolved).",
                    "resource", "medium", "Noah Williams", "Tom Becker", True, 22),
    ),
    retro=RetroSpec("Engine pipeline phase-1 retrospective", "project_retro",
                    "## Went well\n- Rust core hit the latency target.\n\n"
                    "## Improve\n- Security review started too late.\n\n"
                    "## Actions\n- Pull the key-custody ADR forward.",
                    ("engine-core",),
                    (RetroCommentSpec("Tom Becker", "Contract-first really helped."),
                     RetroCommentSpec("Aanya Sharma", "Start security review a sprint earlier."))),
    draft=DraftSpec("GA hardening plan", "Proposed hardening before BYOC GA.",
                    "Hardening",
                    (DraftTaskSpec("Chaos & failure injection", "task", 5, 8.0),
                     DraftTaskSpec("Air-gapped install mode", "task", 4, 5.0),
                     DraftTaskSpec("Enclave attestation spike", "task", 3, 5.0))),
    incidents=(IncidentSpec("Latency spike after model-runtime deploy", 16, 5, "model-runtime"),),
    deploy_weeks=9,
)

_GATEWAY = ProjectSpec(
    "GATEWAY", "Secure Data Gateway",
    "The boundary that connects the data plane to the control plane without egressing "
    "customer data — meters and approves what may leave the tenant.",
    "DATA-PLANE", 8, 10, True, "on_track",
    "Handshake protocol shipped; egress allow-list under active security review.",
    ("data-plane", "security", "networking"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Trust & egress model ADR", 3, "Done", 42, "Yuki Tanaka",
                     ("architecture", "security")),
            TaskSpec("Protocol design", 3, "Done", 30, "Yuki Tanaka", ("networking",), (2, 3, 6)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Control-plane handshake protocol", 5, "Done", 20, "Yuki Tanaka",
                     ("networking", "security"), (4, 5, 8)),
            TaskSpec("Egress allow-list enforcement", 5, "In Progress", 16, "Yuki Tanaka",
                     ("security",), (4, 5, 9)),
            TaskSpec("mTLS & attestation", 4, "In Progress", 7, "Ivan Petrov",
                     ("security", "networking")),
            TaskSpec("Per-tenant metering", 3, "To Do", 0, "Grace Liu", ("data",)),
        )),
    ),
    milestones=(MilestoneSpec("Protocol frozen", -3, "hit"), MilestoneSpec("Gateway GA", 10)),
    components=(
        ComponentSpec("gateway", "service", "infra", "high", "Yuki Tanaka"),
        ComponentSpec("egress-policy", "module", "business", "high", "Yuki Tanaka"),
        ComponentSpec("meter", "module", "data", "med", "Grace Liu"),
    ),
    component_links=(
        LinkSpec("gateway", "egress-policy", "depends_on"),
        LinkSpec("gateway", "meter", "publishes_to"),
    ),
    bindings=(BindingSpec("gateway", "data-plane/gateway/**", "helix.gateway"),),
    adrs=(
        ADRSpec("Default-deny egress with an explicit allow-list", "accepted", "one_way",
                "Aanya Sharma", "Yuki Tanaka",
                "Anything leaving the tenant is a data-residency risk.",
                "Deny all egress by default; allow only declared, metered aggregate paths.",
                components=("gateway", "egress-policy"),
                fitness=FitnessSpec("require", "gateway", "egress-policy",
                                    "All egress must be evaluated by the egress policy."),
                created_days_ago=30),
        ADRSpec("Attestation: SPIFFE vs custom mTLS", "under_discussion", "two_way",
                "Yuki Tanaka", "Ivan Petrov",
                "Data-plane↔control-plane identity must be verifiable.",
                "Proposed: SPIFFE/SPIRE workload identity.",
                components=("gateway",),
                stakeholders=("Yuki Tanaka", "Ivan Petrov"),
                comments=(ADRCommentSpec("Ivan Petrov", "SPIFFE saves us building PKI.",
                                         "approve"),),
                created_days_ago=5),  # discussing (recent)
    ),
    specs=(
        SpecSpec("Metered, policy-checked egress",
                 "Every byte that leaves a tenant is policy-approved and metered.",
                 "approved", "Yuki Tanaka",
                 adr_title="Default-deny egress with an explicit allow-list",
                 criteria=(
                     CriterionSpec("Undeclared egress paths are denied.", "met"),
                     CriterionSpec("Egress bytes are metered per tenant.", "met"),
                     CriterionSpec("Policy changes are audit-logged.", "open"),
                 ),
                 task_names=("Egress allow-list enforcement", "Per-tenant metering")),
    ),
    risks=(
        RiskSpec("A policy gap allows unintended egress", "security", "low", "high",
                 "mitigating", "Yuki Tanaka", "Fuzz the policy engine; default-deny everything."),
    ),
    outcomes=(
        OutcomeSpec("Unapproved egress events", "policy violations", "count/week",
                    14.0, 0.0, 2.0, "on_track", "Yuki Tanaka"),
    ),
    docs=(
        DocSpec("runbook", "Gateway incident runbook",
                "https://github.com/helix-io/data-plane/blob/main/runbooks/gateway.md", "repo"),
    ),
    blockers=(),
    retro=RetroSpec("Egress near-miss postmortem", "incident_postmortem",
                    "## Summary\nA debug passthrough briefly allowed raw payloads toward the "
                    "gateway in staging; no customer data left a tenant.\n\n"
                    "## Timeline\n- Detected by an egress metering anomaly.\n"
                    "- Passthrough disabled.\n\n"
                    "## Root cause\nA debug flag shipped enabled.\n\n"
                    "## Corrective actions\n- Default-deny in the enclave.\n"
                    "- Block the flag in CI.",
                    ("gateway", "egress-policy"),
                    (RetroCommentSpec("Yuki Tanaka", "Metering caught it — the control worked."),
                     RetroCommentSpec("Noah Williams", "Adding a CI guard for debug flags."))),
    incidents=(IncidentSpec("Egress metering anomaly (debug passthrough)", 11, 3, "gateway"),),
    deploy_weeks=8,
)

_OPERATOR = ProjectSpec(
    "OPERATOR", "Deployment Operator",
    "The Kubernetes operator/installer that stands up and upgrades the data plane inside "
    "a customer's environment.",
    "DATA-PLANE", 6, 12, True, "on_track",
    "Install path works on reference clouds; air-gapped mode is next.",
    ("data-plane", "kubernetes", "deployment"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Operator design & CRDs", 3, "Done", 32, "Ivan Petrov", ("kubernetes",)),
            TaskSpec("Upgrade strategy ADR", 2, "Done", 20, "Aanya Sharma", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Reconcile loop & CRDs", 5, "Done", 14, "Ivan Petrov", ("kubernetes",),
                     (4, 5, 9)),
            TaskSpec("Bundle engine + gateway", 4, "In Progress", 9, "Ivan Petrov",
                     ("deployment",), (3, 4, 7)),
            TaskSpec("Air-gapped install mode", 5, "To Do", 0, "Omar Haddad", ("deployment",)),
            TaskSpec("Rolling upgrades & rollback", 4, "To Do", 0, "Ivan Petrov",
                     ("kubernetes",)),
        )),
    ),
    milestones=(MilestoneSpec("Reference-cloud install", 2), MilestoneSpec("Operator GA", 12)),
    components=(
        ComponentSpec("operator", "service", "infra", "high", "Ivan Petrov"),
        ComponentSpec("installer", "module", "infra", "med", "Omar Haddad"),
    ),
    component_links=(LinkSpec("operator", "installer", "depends_on"),),
    bindings=(BindingSpec("operator", "data-plane/operator/**", "helix.operator"),),
    adrs=(
        ADRSpec("Kubernetes operator over Helm-only", "accepted", "two_way", "Aanya Sharma",
                "Ivan Petrov",
                "Customers need lifecycle management, not just an install.",
                "Ship an operator with CRDs for install, upgrade and health.",
                components=("operator",), created_days_ago=20),
        ADRSpec("Support air-gapped environments", "under_discussion", "one_way",
                "Ivan Petrov", "Omar Haddad",
                "Some regulated customers run fully air-gapped.",
                "Proposed: a bundled, registry-mirrored install path.",
                stakeholders=("Ivan Petrov", "Omar Haddad", "Diego Santos"),
                comments=(ADRCommentSpec("Diego Santos", "Air-gap is a must for two key accounts.",
                                         "approve"),),
                created_days_ago=4),
    ),
    drift=(
        DriftSpec("dead_dependency", "installer still references the deprecated bootstrap chart",
                  ("installer",), status="open"),
    ),
    specs=(
        SpecSpec("One-hour install",
                 "A field engineer can stand up a healthy data plane on a reference cloud in "
                 "under an hour.",
                 "in_progress", "Ivan Petrov",
                 criteria=(
                     CriterionSpec("Install completes in <60 min on a reference cloud.", "open"),
                     CriterionSpec("Health is green before handing off.", "met"),
                     CriterionSpec("A failed install rolls back cleanly.", "open"),
                 ),
                 task_names=("Reconcile loop & CRDs", "Bundle engine + gateway")),
    ),
    risks=(
        RiskSpec("Customer cluster drift breaks upgrades", "external", "medium", "medium",
                 "open", "Omar Haddad", "Pin and validate cluster prerequisites."),
    ),
    outcomes=(
        OutcomeSpec("Install time", "median install time", "min",
                    240.0, 60.0, 110.0, "on_track", "Ivan Petrov"),
    ),
    docs=(
        DocSpec("runbook", "Operator install runbook",
                "https://github.com/helix-io/data-plane/blob/main/runbooks/operator.md", "repo"),
    ),
    blockers=(),
    retro=RetroSpec("Operator MVP retro", "project_retro",
                    "## Went well\n- CRD-driven model is clean.",
                    comments=(RetroCommentSpec("Ivan Petrov", "Operators were worth it."),)),
    deploy_weeks=6,
)

# =========================================================================== #
# FIELD DELIVERY
# =========================================================================== #
_PLAYBOOKS = ProjectSpec(
    "PLAYBOOKS", "Deployment Playbooks & Reference Architectures",
    "Repeatable, validated deployment patterns and reference architectures field engineers "
    "use to deploy the data plane in customer environments.",
    "FIELD-DELIVERY", 6, 8, False, "on_track",
    "Three reference architectures drafted; validation harness in progress.",
    ("field", "documentation", "reference-architecture"),
    phases=(
        PhaseSpec("Author", (
            TaskSpec("AWS reference architecture", 4, "Done", 30, "Diego Santos",
                     ("solutions",), (3, 4, 7)),
            TaskSpec("Azure reference architecture", 4, "Done", 18, "Diego Santos",
                     ("solutions",)),
            TaskSpec("GCP reference architecture", 4, "In Progress", 12, "Omar Haddad",
                     ("solutions",)),
        )),
        PhaseSpec("Validate", (
            TaskSpec("Deployment validation harness", 5, "In Progress", 9, "Omar Haddad",
                     ("deployment", "automation")),
            TaskSpec("Sizing & capacity guide", 3, "To Do", 0, "Diego Santos", ("solutions",)),
        )),
    ),
    milestones=(MilestoneSpec("Three references published", 3), MilestoneSpec("Validated set", 8)),
    components=(
        ComponentSpec("reference-archs", "external", "infra", "med", "Diego Santos"),
        ComponentSpec("validation-harness", "module", "infra", "med", "Omar Haddad"),
    ),
    component_links=(LinkSpec("validation-harness", "reference-archs", "reads_from"),),
    adrs=(
        ADRSpec("Constrain to three reference architectures", "accepted", "two_way",
                "Diego Santos", "Diego Santos",
                "Supporting arbitrary customer environments is unsustainable.",
                "Officially support AWS, Azure and GCP reference architectures only.",
                components=("reference-archs",), created_days_ago=26),
    ),
    specs=(
        SpecSpec("Validated reference architectures",
                 "Each reference architecture is proven by an automated deployment in CI.",
                 "in_progress", "Omar Haddad",
                 criteria=(
                     CriterionSpec("Each reference deploys cleanly in CI.", "open"),
                     CriterionSpec("Sizing guidance is included.", "open"),
                 ),
                 task_names=("Deployment validation harness",)),
    ),
    risks=(
        RiskSpec("Reference architectures drift from the product", "technical", "medium",
                 "medium", "open", "Diego Santos", "Re-validate references each release."),
    ),
    outcomes=(
        OutcomeSpec("Supported environments validated", "validated references", "count",
                    0.0, 3.0, 2.0, "on_track", "Diego Santos"),
    ),
    docs=(
        DocSpec("architecture", "AWS reference architecture",
                "https://drive.google.com/file/d/doc-aws-ref/view", "drive"),
    ),
    blockers=(),
    retro=RetroSpec("Reference-architecture authoring retro", "project_retro",
                    "## Went well\n- Customers adopted the AWS reference quickly.",
                    comments=(RetroCommentSpec("Diego Santos", "Constraints made support sane."),)),
    deploy_weeks=5,
)

_FIELDCON = ProjectSpec(
    "FIELDCON", "Customer Deployment Console",
    "A guided installer + health console field engineers and customers use to deploy and "
    "operate the data plane — the productized face of Helix's implementation expertise.",
    "FIELD-DELIVERY", 4, 10, False, "on_track",
    "Guided installer wireframes done; build just starting.",
    ("field", "frontend", "deployment"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Installer flow & wireframes", 3, "Done", 24, "Lena Brooks", ("design",)),
            TaskSpec("Health & diagnostics model", 3, "Done", 14, "Omar Haddad",
                     ("deployment",), (2, 3, 5)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Guided install wizard", 6, "In Progress", 10, "Hannah Schmidt",
                     ("frontend",), (5, 6, 10)),
            TaskSpec("Pre-flight environment checks", 4, "To Do", 0, "Omar Haddad",
                     ("deployment",)),
            TaskSpec("Live deployment health view", 4, "To Do", 0, "Hannah Schmidt",
                     ("frontend",)),
        )),
    ),
    milestones=(MilestoneSpec("Guided install MVP", 4), MilestoneSpec("GA", 10)),
    components=(
        ComponentSpec("deploy-console", "ui", "presentation", "med", "Hannah Schmidt"),
        ComponentSpec("preflight", "module", "business", "med", "Omar Haddad"),
    ),
    component_links=(LinkSpec("deploy-console", "preflight", "calls"),),
    adrs=(
        ADRSpec("Wizard-driven install over raw manifests", "accepted", "two_way",
                "Diego Santos", "Lena Brooks",
                "Field engineers shouldn't hand-edit manifests in customer environments.",
                "Ship a guided wizard that generates and applies validated config.",
                components=("deploy-console",), created_days_ago=12),
    ),
    specs=(
        SpecSpec("Confident first install",
                 "A field engineer can complete a first install without reading the manifests.",
                 "draft", "Diego Santos",
                 criteria=(
                     CriterionSpec("Pre-flight catches the common failures.", "open"),
                     CriterionSpec("The wizard explains each step.", "open"),
                 ),
                 task_names=("Guided install wizard", "Pre-flight environment checks")),
    ),
    risks=(
        RiskSpec("Scope creep from bespoke customer asks", "scope", "high", "medium", "open",
                 "Marcus Lee", "Hold the line on the three reference architectures."),
    ),
    outcomes=(
        OutcomeSpec("First-time install success", "success rate", "%",
                    55.0, 90.0, 72.0, "on_track", "Diego Santos"),
    ),
    docs=(
        DocSpec("prd", "Deployment console PRD",
                "https://drive.google.com/file/d/doc-fieldcon-prd/view", "drive"),
    ),
    blockers=(),
    retro=None,
    deploy_weeks=4,
)

PROJECTS: tuple[ProjectSpec, ...] = (
    _CPORCH, _REGISTRY, _CONSOLE, _ENGINE, _GATEWAY, _OPERATOR, _PLAYBOOKS, _FIELDCON,
)
