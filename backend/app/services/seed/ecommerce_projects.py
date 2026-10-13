"""The 10 demo projects of the e-commerce dataset (declarative). Split out of ``ecommerce.py``
for readability.

Two projects per initiative, each fully populated — a scheduled WBS, an architecture map +
ADRs (an accepted one with a fitness function, one in active review, plus proposed / deferred /
rejected ones), drift, a spec, risks, outcomes, docs, blockers, retros, draft plans and activity
— so every per-project tab has real content. Task, milestone, ADR and risk names here are
referenced by hand-offs, scenarios, leadership notes and the flagship's Jira/PR links in
``ecommerce.py``; ``tests/test_demo_seed.py`` checks every reference resolves.
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

_REPO = "https://github.com/example-shop/checkout/blob/main"
_WIKI = "https://wiki.example.com"
_DRIVE = "https://drive.google.com/file/d"

# =========================================================================== #
# CHECKOUT MODERNIZATION
# =========================================================================== #
_ONEPAGE = ProjectSpec(
    "ONEPAGE", "One-Page Checkout",
    "Replace the five-step checkout with a single page: cart review, address, delivery and "
    "payment in one place, for guests and signed-in shoppers alike.",
    "CHECKOUT", 9, 8, True, "at_risk",
    "Session service and address step shipped; tokenized payments is the critical path and "
    "waits on the payments platform.",
    ("checkout", "web", "conversion"),
    phases=(
        PhaseSpec("Discovery & design", (
            TaskSpec("Checkout funnel analysis", 5, "Done", 54, "Sarah Chen",
                     ("product", "analytics")),
            TaskSpec("One-page checkout UX", 8, "Done", 44, "Lucia Ferreira", ("design",),
                     (6, 8, 12)),
            TaskSpec("Checkout architecture", 4, "Done", 38, "Rahul Verma", ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Checkout session service", 8, "Done", 27, "Rahul Verma", ("backend",),
                     (6, 8, 12)),
            TaskSpec("Address & delivery step", 7, "Done", 17, "Leo Martins", ("frontend",),
                     (5, 7, 10)),
            TaskSpec("Guest checkout", 6, "In Review", 5, "Leo Martins",
                     ("frontend", "backend"), (4, 6, 9)),
            TaskSpec("Integrate tokenized payments", 8, "In Progress", 9, "Priya Shah",
                     ("backend", "payments"), (6, 8, 14), deadline_weeks=-1),
            TaskSpec("Digital wallet buttons", 5, "To Do", 0, "Leo Martins",
                     ("frontend", "payments")),
            TaskSpec("Order review & place order", 5, "To Do", 0, "Rahul Verma",
                     ("backend", "frontend")),
        )),
        PhaseSpec("Launch", (
            TaskSpec("A/B test vs legacy checkout", 10, "To Do", 0, "Fatou Ndiaye",
                     ("qa", "experiment"), (8, 10, 15)),
            TaskSpec("Ramp to all traffic", 5, "To Do", 0, "Sam Adeyemi", ("release",)),
            TaskSpec("One-page checkout GA", 0, milestone=True, deadline_weeks=8),
        )),
    ),
    milestones=(
        MilestoneSpec("Design sign-off", -6, "hit"),
        MilestoneSpec("Beta behind a flag", -1, "at_risk"),  # overdue → alert
        MilestoneSpec("Checkout GA", 8),
    ),
    components=(
        ComponentSpec("web-checkout", "ui", "presentation", "high", "Leo Martins"),
        ComponentSpec("checkout-api", "service", "business", "high", "Rahul Verma"),
        ComponentSpec("cart-service", "service", "business", "high"),
        ComponentSpec("orders-db", "datastore", "data", "high"),
        ComponentSpec("payment-gateway", "external", "infra", "high", "Priya Shah"),
        ComponentSpec("address-lookup", "external", "infra", "med"),
    ),
    component_links=(
        LinkSpec("web-checkout", "checkout-api", "calls"),
        LinkSpec("checkout-api", "cart-service", "calls"),
        LinkSpec("checkout-api", "orders-db", "reads_from"),
        LinkSpec("checkout-api", "payment-gateway", "calls"),
        LinkSpec("web-checkout", "address-lookup", "calls"),
        LinkSpec("web-checkout", "orders-db", "reads_from"),  # violates the session ADR
    ),
    bindings=(
        BindingSpec("checkout-api", "services/checkout/**", "shop.checkout"),
        BindingSpec("web-checkout", "web/checkout/**"),
    ),
    adrs=(
        ADRSpec("Server-side checkout session as the source of truth", "accepted", "one_way",
                "Ingrid Larsen", "Rahul Verma",
                "Cart, address and payment state drifted between the browser and the order "
                "service, so a refresh mid-checkout could lose the cart or fail the order.",
                "Keep one server-side checkout session per cart. The web client renders it "
                "and never reads order storage directly.",
                "Refresh-safe, resumable checkout; one more service on the critical path.",
                alternatives=("Client-side state with periodic sync",),
                components=("checkout-api", "web-checkout"),
                fitness=FitnessSpec("forbid", "web-checkout", "orders-db",
                                    "The checkout UI must not read order storage directly; "
                                    "it goes through the checkout API."),
                created_days_ago=40),
        ADRSpec("Guest checkout without account creation", "under_discussion", "two_way",
                "Sarah Chen", "Lucia Ferreira",
                "Forced sign-up is the largest single drop-off in the funnel analysis.",
                "Proposed: shoppers check out with an email address only and are offered an "
                "account after the order is placed.",
                components=("web-checkout", "checkout-api"),
                stakeholders=("Sarah Chen", "Lucia Ferreira", "Rahul Verma", "Isabel Moreno"),
                comments=(
                    ADRCommentSpec("Lucia Ferreira", "Post-purchase sign-up tested far better "
                                   "in the prototype sessions.", "approve"),
                    ADRCommentSpec("Isabel Moreno", "Guest orders need rate limits and a fraud "
                                   "check before we ship this.", "request_changes"),
                    ADRCommentSpec("Rahul Verma", "The session already supports anonymous "
                                   "carts; the fraud hook is a small change.", "comment"),
                ),
                created_days_ago=18),  # stuck in review (> 14 days)
        ADRSpec("Address autocomplete provider", "proposed", proposer="Leo Martins",
                context="Typos in delivery addresses cause failed deliveries; autocomplete "
                        "needs a provider decision before the address step is final.",
                created_days_ago=5),  # overdue triage (past the 72h SLA)
        ADRSpec("Save cards for returning shoppers", "deferred", owner="Sarah Chen",
                context="Saved cards lift repeat conversion but widen PCI scope; revisit once "
                        "tokenization is live.",
                created_days_ago=12, decide_by_weeks=-1),  # overdue in the queue
    ),
    drift=(
        DriftSpec("unexpected_dependency", "web-checkout reads orders-db directly",
                  ("web-checkout", "orders-db"),
                  "Violates the server-side checkout session ADR — the UI must go through the "
                  "checkout API.",
                  "PR #405 (order-status shortcut on the confirmation page)"),
    ),
    specs=(
        SpecSpec("One-page checkout",
                 "Shoppers abandon a five-step checkout. They should be able to review, pay "
                 "and place an order on a single page.",
                 "in_progress", "Rahul Verma",
                 context="The flagship bet of the Checkout Modernization initiative.",
                 out_of_scope="Saved cards (a deferred decision) and loyalty points.",
                 adr_title="Server-side checkout session as the source of truth",
                 source_url=f"{_WIKI}/checkout/one-page-spec",
                 criteria=(
                     CriterionSpec("Checkout completes on one page without a full reload.",
                                   "met", "Verified in the beta behind the flag."),
                     CriterionSpec("A refresh or back-navigation never loses the cart or "
                                   "address.", "met", "Covered by the checkout e2e suite."),
                     CriterionSpec("Cards are tokenized; raw card numbers never touch our "
                                   "servers.", "open"),
                     CriterionSpec("Guests can check out without creating an account.",
                                   "unmet", "Waiting on the guest-checkout decision."),
                     CriterionSpec("Median time to place an order is under 90 seconds.",
                                   "open"),
                 ),
                 task_names=("Checkout session service", "Guest checkout",
                             "Integrate tokenized payments", "Order review & place order")),
    ),
    risks=(
        RiskSpec("Tokenization API lands late from the payments team", "schedule", "high",
                 "high", "open", "Rahul Verma",
                 "Build against the sandbox contract and stub the vault in tests.",
                 "Launch with the legacy payment form embedded in the new page.",
                 target_weeks=1),
        RiskSpec("Conversion dips during the A/B test", "scope", "medium", "medium",
                 "mitigating", "Sarah Chen",
                 "Start at 5% of traffic with automatic rollback on a conversion drop."),
        RiskSpec("Guest orders attract card-testing fraud", "security", "medium", "high",
                 "open", "Isabel Moreno",
                 "Rate-limit guest sessions and score orders for fraud before payment."),
    ),
    mitigations=(
        MitigationSpec("deadline_violations",
                       "Sequencing wallet buttons after tokenized payments to protect GA.",
                       "Rahul Verma", False, 1),
        MitigationSpec("quality_signals", "Added the checkout e2e suite to the merge gate.",
                       "Fatou Ndiaye", True),
    ),
    outcomes=(
        OutcomeSpec("Faster checkout", "median time to place an order", "s",
                    210.0, 90.0, 140.0, "on_track", "Rahul Verma"),
        OutcomeSpec("Fewer failed payments", "payment failure rate", "%",
                    4.2, 2.0, 3.6, "at_risk", "Priya Shah"),
    ),
    docs=(
        DocSpec("prd", "One-page checkout PRD", f"{_WIKI}/checkout/one-page-prd"),
        DocSpec("design", "Checkout flow designs", f"{_DRIVE}/doc-checkout-ux/view", "drive"),
        DocSpec("architecture", "Checkout ADR log (repo)", f"{_REPO}/docs/adr/README.md",
                "repo"),
        DocSpec("design", "Checkout funnel analysis", f"{_WIKI}/checkout/funnel-analysis",
                "jira_epic", "Checkout funnel analysis"),
        DocSpec("runbook", "Tokenized payments integration notes", f"{_REPO}/docs/payments.md",
                "repo", "Integrate tokenized payments"),
        DocSpec("tech_design", "Checkout session design",
                f"{_DRIVE}/doc-checkout-session/view", "drive", "Checkout session service"),
    ),
    blockers=(
        BlockerSpec("Integrate tokenized payments",
                    "Waiting on the card tokenization API from the payments platform team.",
                    "dependency", "high", "Priya Shah", "Rahul Verma", False, 4, 1),
        BlockerSpec("Guest checkout",
                    "Needs the guest-checkout decision and a fraud-check sign-off.",
                    "decision", "medium", "Sarah Chen", "Leo Martins", False, 3, 1),
        BlockerSpec("Address & delivery step",
                    "Was blocked on an address-lookup API key (now resolved).",
                    "external", "low", "Ben Ortiz", "Leo Martins", True, 24),
    ),
    retro=RetroSpec("Checkout beta retrospective", "project_retro",
                    "## Went well\n- The server-side session made refresh bugs disappear.\n"
                    "- Design and engineering paired on every step.\n\n"
                    "## Improve\n- We found the payments dependency too late.\n\n"
                    "## Actions\n- Bring the payments team into checkout planning.\n"
                    "- Track cross-team hand-offs on the initiative plan.",
                    ("checkout-api",),
                    (RetroCommentSpec("Rahul Verma",
                                      "The session service paid for itself in week one."),
                     RetroCommentSpec("Lucia Ferreira", "Testing the prototype with real "
                                      "shoppers saved us two redesigns."))),
    draft=DraftSpec("Checkout fast-follows",
                    "Post-GA improvements to review before creating Jira tickets.",
                    "Checkout fast-follows",
                    (DraftTaskSpec("Saved addresses for signed-in shoppers", "task", 3, 5.0),
                     DraftTaskSpec("Gift messages and gift wrap", "task", 2, 3.0),
                     DraftTaskSpec("Edit an order within 30 minutes", "task", 5, 8.0))),
    incidents=(
        IncidentSpec("Checkout errors spiked after the address-step deploy", 15, 3,
                     "web-checkout"),
    ),
    deploy_weeks=9,
    pod="Checkout & Payments",
    owner="Rahul Verma",
)

_PAYMENTS = ProjectSpec(
    "PAYMENTS", "Payments Platform Migration",
    "Move card payments to a new provider with tokenization, 3-D Secure, refunds and a "
    "dual-run reconciliation before the peak code freeze.",
    "CHECKOUT", 12, 6, True, "at_risk",
    "Provider signed and the vault works in the sandbox; the tokenization API is aging and the "
    "cut-over now lands after the code freeze.",
    ("payments", "backend", "pci"),
    phases=(
        PhaseSpec("Evaluate", (
            TaskSpec("Provider evaluation", 12, "Done", 66, "Priya Shah", ("payments",),
                     (10, 12, 18)),
            TaskSpec("Provider contract & onboarding", 10, "Done", 52, "Oliver Grant",
                     ("payments",)),
            TaskSpec("Payments architecture & PCI scope", 8, "Done", 41, "Ingrid Larsen",
                     ("architecture", "security")),
        )),
        PhaseSpec("Build", (
            TaskSpec("Sandbox integration spike", 6, "Done", 33, "Gabriel Silva",
                     ("backend", "payments")),
            TaskSpec("Ledger & idempotency keys", 8, "Done", 23, "Priya Shah", ("backend",),
                     (6, 8, 12)),
            TaskSpec("Card tokenization API", 12, "In Progress", 22, "Priya Shah",
                     ("backend", "payments"), (8, 12, 18)),
            TaskSpec("3-D Secure challenge flow", 8, "In Progress", 6, "Gabriel Silva",
                     ("backend", "payments"), (5, 8, 12)),
            TaskSpec("Refunds & partial captures", 6, "To Do", 0, "Gabriel Silva",
                     ("backend",)),
            TaskSpec("Payment webhooks & retries", 4, "To Do", 0, "Priya Shah", ("backend",)),
        )),
        PhaseSpec("Cut-over", (
            TaskSpec("Dual-run reconciliation", 8, "To Do", 0, "Ethan Wu",
                     ("data", "payments")),
            TaskSpec("PCI scope review", 3, "To Do", 0, "Isabel Moreno", ("security",)),
            TaskSpec("Cut over remaining traffic", 3, "To Do", 0, "Sam Adeyemi",
                     ("release",)),
            # The code freeze is the hard deadline; the plan currently lands after it.
            TaskSpec("Payments cut-over complete", 0, milestone=True, deadline_weeks=4),
        )),
    ),
    milestones=(
        MilestoneSpec("Provider contract signed", -8, "hit"),
        MilestoneSpec("Tokenization live in sandbox", -1, "at_risk"),  # overdue → alert
        MilestoneSpec("Payments cut-over", 4, "at_risk"),
    ),
    components=(
        ComponentSpec("payments-service", "service", "business", "high", "Priya Shah"),
        ComponentSpec("token-vault", "external", "infra", "high"),
        ComponentSpec("payment-provider", "external", "infra", "high"),
        ComponentSpec("fraud-screening", "service", "business", "med"),
        ComponentSpec("payments-ledger", "datastore", "data", "high", "Gabriel Silva"),
    ),
    component_links=(
        LinkSpec("payments-service", "token-vault", "calls"),
        LinkSpec("payments-service", "payment-provider", "calls"),
        LinkSpec("payments-service", "payments-ledger", "depends_on"),
        LinkSpec("payments-service", "fraud-screening", "calls"),
    ),
    bindings=(BindingSpec("payments-service", "services/payments/**", "shop.payments"),),
    adrs=(
        ADRSpec("Tokenize cards through the provider vault", "accepted", "one_way",
                "Ingrid Larsen", "Priya Shah",
                "Storing card numbers would put every service that touches checkout in PCI "
                "scope.",
                "Cards are tokenized in the provider's vault straight from the browser; our "
                "services only ever see tokens.",
                "PCI scope shrinks to a few services; we depend on the provider's vault for "
                "retries and any future migration.",
                alternatives=("Run our own vault",),
                components=("payments-service", "token-vault"),
                fitness=FitnessSpec("require", "payments-service", "token-vault",
                                    "Every card charge must go through the vault token path."),
                created_days_ago=50),
        ADRSpec("Single provider vs payment orchestration layer", "under_discussion",
                "two_way", "Priya Shah", "Gabriel Silva",
                "One provider is simpler to run; an orchestration layer could route by cost "
                "and fail over during peak.",
                "Proposed: start with one provider behind a thin internal interface and keep "
                "the option to add a second.",
                components=("payments-service", "payment-provider"),
                stakeholders=("Priya Shah", "Gabriel Silva", "Ingrid Larsen", "Jakub Novak"),
                comments=(
                    ADRCommentSpec("Jakub Novak", "We need a failover story before peak; one "
                                   "provider is a single point of failure.", "request_changes"),
                    ADRCommentSpec("Gabriel Silva", "With a thin interface a second provider "
                                   "is a few weeks of work.", "comment"),
                    ADRCommentSpec("Ingrid Larsen", "Agree on the thin interface; revisit "
                                   "routing after peak.", "approve"),
                ),
                created_days_ago=16),  # stuck in review (> 14 days)
        ADRSpec("Store payment data in the shared orders database", "rejected", "one_way",
                "Ingrid Larsen", "Gabriel Silva",
                "Reusing the orders database would avoid running a new datastore.",
                "Rejected: payment records live in a separate ledger so the orders database "
                "stays out of PCI scope.",
                alternatives=("A separate payments ledger",),
                components=("payments-ledger",), created_days_ago=45),
    ),
    drift=(
        DriftSpec("dead_dependency", "payments-service no longer calls fraud-screening",
                  ("payments-service", "fraud-screening"),
                  "The declared dependency was not observed in the last scan.",
                  "Provider-side risk scoring replaced the in-house call"),
    ),
    specs=(
        SpecSpec("Tokenized card payments",
                 "Shoppers pay by card without card numbers ever reaching our systems, with "
                 "3-D Secure where the bank asks for it.",
                 "in_progress", "Priya Shah",
                 context="Prerequisite for the one-page checkout and for saved cards later.",
                 out_of_scope="Wallets and buy-now-pay-later (separate projects).",
                 adr_title="Tokenize cards through the provider vault",
                 criteria=(
                     CriterionSpec("Card data is tokenized in the browser.", "met",
                                   "Verified in the sandbox."),
                     CriterionSpec("3-D Secure challenges complete inside checkout.", "open"),
                     CriterionSpec("Refunds and partial captures work on tokens.", "open"),
                     CriterionSpec("Dual-run shows matching totals for 7 days.", "open"),
                 ),
                 task_names=("Card tokenization API", "3-D Secure challenge flow",
                             "Refunds & partial captures", "Dual-run reconciliation")),
    ),
    risks=(
        RiskSpec("Card tokenization API slips again", "schedule", "high", "high", "open",
                 "Priya Shah", "Pair Gabriel on the API; cut refunds to full refunds only.",
                 "Run the old and new providers in parallel through peak.", target_weeks=1),
        RiskSpec("PCI scope creeps into the checkout services", "security", "low", "high",
                 "mitigating", "Isabel Moreno",
                 "Keep raw card data in the vault; scan checkout logs for card numbers."),
    ),
    mitigations=(
        MitigationSpec("deadline_violations",
                       "Moving the PCI review earlier so cut-over can start the day the "
                       "dual-run passes.", "Priya Shah", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Lower payment processing cost", "processing cost per order", "%",
                    2.1, 1.6, 2.1, "pending", "Oliver Grant"),
    ),
    docs=(
        DocSpec("architecture", "Payments reference architecture",
                f"{_DRIVE}/doc-payments-arch/view", "drive"),
        DocSpec("tech_design", "Tokenization API design", f"{_REPO}/docs/tokenization.md",
                "repo", "Card tokenization API"),
    ),
    blockers=(
        BlockerSpec("Card tokenization API",
                    "The provider's sandbox rate-limits our integration tests.",
                    "external", "high", "Priya Shah", "Gabriel Silva", False, 8, 1),
    ),
    retro=RetroSpec("Sandbox outage postmortem", "incident_postmortem",
                    "## What happened\n- The provider sandbox was unavailable for two days.\n\n"
                    "## Impact\n- Integration tests blocked; tokenization slipped a week.\n\n"
                    "## Actions\n- Contract tests against a local provider stub.",
                    ("payment-provider",),
                    (RetroCommentSpec("Priya Shah", "A local stub would have kept us moving."),
                     RetroCommentSpec("Gabriel Silva", "Asking the provider for a status "
                                      "feed for their sandbox."))),
    incidents=(
        IncidentSpec("Payment provider sandbox outage", 19, 30, "payment-provider"),
        IncidentSpec("Duplicate charge retries in staging", 7, 4, "payments-service"),
    ),
    deploy_weeks=6,
    pod="Checkout & Payments",
    owner="Priya Shah",
)

# =========================================================================== #
# SEARCH & DISCOVERY
# =========================================================================== #
_SEARCH = ProjectSpec(
    "SEARCH", "Search Relevance Revamp",
    "Fresher, more forgiving and better-ranked search: an index fed by catalog events, typo "
    "tolerance, facets and a learning-to-rank model.",
    "DISCOVERY", 10, 6, True, "on_track",
    "Typo tolerance shipped and zero-result searches halved; ranking model in training.",
    ("search", "relevance", "ml"),
    phases=(
        PhaseSpec("Discovery", (
            TaskSpec("Search analytics baseline", 5, "Done", 62, "Tobias Klein",
                     ("analytics",)),
            TaskSpec("Relevance test set", 6, "Done", 54, "Nina Kowalski", ("ml", "data")),
        )),
        PhaseSpec("Build", (
            TaskSpec("Catalog change-event indexer", 10, "Done", 40, "Tobias Klein",
                     ("backend",), (8, 10, 15)),
            TaskSpec("Typo tolerance & synonyms", 8, "Done", 29, "Tobias Klein",
                     ("backend", "relevance"), (6, 8, 12)),
            TaskSpec("Faceted filters", 8, "In Review", 21, "Diego Ramos",
                     ("frontend", "backend"), (6, 8, 12)),  # aging in review
            TaskSpec("Learning-to-rank model", 15, "In Progress", 10, "Nina Kowalski",
                     ("ml", "relevance"), (10, 15, 22)),
            TaskSpec("Search results page redesign", 6, "To Do", 0, "Diego Ramos",
                     ("frontend", "design")),
            TaskSpec("Autocomplete suggestions", 5, "To Do", 0, "Diego Ramos",
                     ("frontend",)),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Relevance A/B test", 8, "To Do", 0, "Fatou Ndiaye",
                     ("qa", "experiment")),
            TaskSpec("Search relevance GA", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Index on catalog events", -6, "hit"),
        MilestoneSpec("Ranking beta", 2),
        MilestoneSpec("Search GA", 5),
    ),
    components=(
        ComponentSpec("search-api", "service", "business", "high", "Tobias Klein"),
        ComponentSpec("search-index", "datastore", "data", "high"),
        ComponentSpec("catalog-service", "service", "business", "high"),
        ComponentSpec("ranking-model", "module", "business", "med", "Nina Kowalski"),
        ComponentSpec("spellcheck-api", "external", "infra", "low"),
    ),
    component_links=(
        LinkSpec("search-api", "search-index", "reads_from"),
        LinkSpec("catalog-service", "search-index", "publishes_to"),
        LinkSpec("search-api", "ranking-model", "calls"),
        LinkSpec("search-api", "spellcheck-api", "calls"),  # no ADR covers it (drift)
    ),
    bindings=(BindingSpec("search-api", "services/search/**", "shop.search"),),
    adrs=(
        ADRSpec("Search index fed by catalog change events", "accepted", "two_way",
                "Tobias Klein", "Tobias Klein",
                "Nightly full re-indexes left prices and stock in search results stale for up "
                "to a day.",
                "The catalog publishes change events; the indexer applies them within a "
                "minute.",
                "Fresh results; event ordering and replay become our problem.",
                alternatives=("Hourly incremental re-index",),
                components=("catalog-service", "search-index"),
                fitness=FitnessSpec("require", "catalog-service", "search-index",
                                    "Catalog changes must reach the index through the "
                                    "change-event path."),
                created_days_ago=55),
        ADRSpec("Ranking: learning-to-rank vs hand-tuned boosts", "under_discussion",
                "two_way", "Tobias Klein", "Nina Kowalski",
                "Hand-tuned boosts are easy to reason about but have plateaued; a learned "
                "model needs labelled data and monitoring.",
                "Proposed: a learning-to-rank model on top of the boosts, behind an A/B test.",
                components=("ranking-model", "search-api"),
                stakeholders=("Tobias Klein", "Nina Kowalski", "Sarah Chen"),
                comments=(
                    ADRCommentSpec("Nina Kowalski", "Offline NDCG is up 9% on the relevance "
                                   "test set.", "approve"),
                    ADRCommentSpec("Sarah Chen", "Merchandisers still need to pin products "
                                   "for campaigns.", "request_changes"),
                    ADRCommentSpec("Tobias Klein", "Pinning can stay as a post-ranking rule.",
                                   "comment"),
                ),
                created_days_ago=9),
        ADRSpec("Adopt a managed vector database for semantic search", "proposed",
                proposer="Nina Kowalski",
                context="Semantic retrieval for long-tail queries needs vector search; we "
                        "could extend the current engine or adopt a managed service.",
                created_days_ago=4),  # overdue triage
    ),
    drift=(
        DriftSpec("implicit_decision", "search-api calls a third-party spell-check API",
                  ("search-api", "spellcheck-api"),
                  "A new external dependency appeared without a recorded decision.",
                  "PR #388 (typo tolerance)"),
    ),
    specs=(
        SpecSpec("Typo-tolerant search",
                 "Shoppers who misspell a product name get zero results and leave.",
                 "verified", "Tobias Klein",
                 context="The first relevance win of the Search & Discovery initiative.",
                 criteria=(
                     CriterionSpec("Queries within two typos of a product name return it.",
                                   "met", "Relevance test set: 96% recall."),
                     CriterionSpec("Zero-result searches drop below 4%.", "met",
                                   "Search dashboard after rollout: 3.1%."),
                     CriterionSpec("Brand names are never corrected into other brands.",
                                   "met"),
                     CriterionSpec("Works in every storefront language.", "waived",
                                   "Two languages move to next quarter."),
                 ),
                 task_names=("Typo tolerance & synonyms",)),
    ),
    risks=(
        RiskSpec("Ranking model favours bestsellers over relevance", "quality", "medium",
                 "medium", "open", "Nina Kowalski",
                 "Track long-tail query metrics separately in the A/B test."),
    ),
    outcomes=(
        OutcomeSpec("Fewer zero-result searches", "zero-result rate", "%",
                    8.0, 3.0, 3.1, "validated", "Tobias Klein"),
    ),
    docs=(
        DocSpec("tech_design", "Search indexing design", f"{_WIKI}/discovery/search-indexing"),
        DocSpec("qa", "Relevance test set", f"{_DRIVE}/doc-relevance-set/view", "drive",
                "Relevance test set"),
    ),
    retro=RetroSpec("Typo tolerance rollout retro", "project_retro",
                    "## Went well\n- The relevance test set caught two regressions early.\n\n"
                    "## Improve\n- The spell-check dependency was added without a decision.\n\n"
                    "## Actions\n- Record an ADR for the spell-check service.",
                    ("search-api",),
                    (RetroCommentSpec("Tobias Klein", "Event-fed indexing made this easy."),
                     RetroCommentSpec("Nina Kowalski", "Let's grow the test set to 5,000 "
                                      "queries."))),
    draft=DraftSpec("Search UX improvements",
                    "Ideas from the latest usability study to review before ticketing.",
                    "Search UX",
                    (DraftTaskSpec("Recent searches", "task", 2, 3.0),
                     DraftTaskSpec("Visual filters for colour and size", "task", 4, 5.0),
                     DraftTaskSpec("Search within a category", "task", 3, 5.0))),
    deploy_weeks=10,
    pod="Search & Discovery",
    owner="Tobias Klein",
)

_RECS = ProjectSpec(
    "RECS", "Personalized Recommendations",
    "Recommendations on the home page, product pages and in the app — built on a feature "
    "store, ranked by the search team's model and respectful of consent.",
    "DISCOVERY", 8, 8, True, "on_track",
    "Feature store live; candidate generation in progress; consent check still to wire in.",
    ("recommendations", "ml", "personalization"),
    phases=(
        PhaseSpec("Foundations", (
            TaskSpec("Recommendation use cases", 4, "Done", 49, "Sarah Chen", ("product",)),
            TaskSpec("Event collection & consent", 8, "Done", 42, "Ethan Wu",
                     ("data", "privacy")),
            TaskSpec("Feature store", 12, "Done", 25, "Ethan Wu", ("data",), (8, 12, 16)),
            TaskSpec("Offline evaluation harness", 6, "Done", 15, "Nina Kowalski", ("ml",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Candidate generation", 14, "In Progress", 12, "Nina Kowalski",
                     ("ml",), (10, 14, 20)),
            TaskSpec("Recommendations API", 6, "To Do", 0, "Tobias Klein", ("backend",)),
            TaskSpec("Personalized home feed", 8, "To Do", 0, "Diego Ramos", ("frontend",)),
            TaskSpec("'Because you viewed' carousel", 5, "To Do", 0, "Chloe Martin",
                     ("mobile",)),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Holdout experiment", 8, "To Do", 0, "Nina Kowalski",
                     ("ml", "experiment")),
            TaskSpec("Recommendations GA", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Feature store live", -4, "hit"),
        MilestoneSpec("Home feed beta", 4),
        MilestoneSpec("Recommendations GA", 7),
    ),
    components=(
        ComponentSpec("recs-api", "service", "business", "high", "Nina Kowalski"),
        ComponentSpec("feature-store", "datastore", "data", "high", "Ethan Wu"),
        ComponentSpec("event-collector", "service", "data", "med"),
        ComponentSpec("web-storefront", "ui", "presentation", "high"),
        ComponentSpec("consent-service", "service", "business", "high"),
    ),
    component_links=(
        LinkSpec("web-storefront", "recs-api", "calls"),
        LinkSpec("recs-api", "feature-store", "reads_from"),
        LinkSpec("event-collector", "feature-store", "publishes_to"),
        LinkSpec("event-collector", "consent-service", "calls"),
    ),
    bindings=(BindingSpec("recs-api", "services/recs/**", "shop.recs"),),
    adrs=(
        ADRSpec("Batch features with a real-time session layer", "accepted", "two_way",
                "Tobias Klein", "Nina Kowalski",
                "Fully real-time features are expensive; nightly batch features miss what the "
                "shopper is doing right now.",
                "Compute long-term features nightly and blend in a small real-time session "
                "layer inside recs-api.",
                "Cheap and fresh enough; two feature paths to keep consistent.",
                components=("recs-api", "feature-store"),
                fitness=FitnessSpec("forbid", "web-storefront", "feature-store",
                                    "The storefront reads recommendations through recs-api, "
                                    "never the feature store."),
                created_days_ago=38),
        ADRSpec("Respect consent for personalization", "accepted", "one_way",
                "Ingrid Larsen", "Isabel Moreno",
                "Shoppers who opt out of personalization must get non-personalized results "
                "everywhere.",
                "recs-api checks the consent service on every request and falls back to "
                "popular items.",
                "A consent lookup on the hot path; cache it for a minute.",
                components=("recs-api", "consent-service"), created_days_ago=30),
        ADRSpec("Show 'because you viewed' explanations", "under_discussion", "two_way",
                "Sarah Chen", "Lucia Ferreira",
                "Explanations build trust but take space on small screens.",
                "Proposed: a one-line reason on desktop and in the app; none on small mobile "
                "web screens.",
                components=("web-storefront",),
                stakeholders=("Sarah Chen", "Lucia Ferreira", "Nina Kowalski"),
                comments=(
                    ADRCommentSpec("Lucia Ferreira", "Shoppers in testing trusted explained "
                                   "picks more.", "approve"),
                    ADRCommentSpec("Nina Kowalski", "The reasons come for free from candidate "
                                   "generation.", "comment"),
                ),
                created_days_ago=6),
    ),
    drift=(
        DriftSpec("unimplemented_adr",
                  "Consent check is accepted but recs-api does not call the consent service",
                  ("recs-api", "consent-service"),
                  "An accepted decision with no matching dependency in the code."),
    ),
    specs=(
        SpecSpec("Consent-aware recommendations",
                 "Personalization must never use data from shoppers who opted out.",
                 "approved", "Nina Kowalski",
                 adr_title="Respect consent for personalization",
                 criteria=(
                     CriterionSpec("Opted-out shoppers get non-personalized results on every "
                                   "surface.", "open"),
                     CriterionSpec("Consent changes apply within one minute.", "open"),
                     CriterionSpec("Events from opted-out shoppers never reach the feature "
                                   "store.", "met", "The collector drops them at ingest."),
                 ),
                 task_names=("Event collection & consent", "Recommendations API")),
    ),
    risks=(
        RiskSpec("Cold start for new shoppers", "technical", "medium", "medium", "open",
                 "Nina Kowalski",
                 "Fall back to popular-in-category for shoppers with no history."),
    ),
    outcomes=(
        OutcomeSpec("Recommendation click-through", "CTR on recommendation slots", "%",
                    1.8, 3.0, 2.1, "on_track", "Nina Kowalski"),
    ),
    docs=(
        DocSpec("prd", "Recommendations PRD", f"{_WIKI}/discovery/recs-prd", "jira_epic"),
        DocSpec("tech_design", "Feature store design", f"{_DRIVE}/doc-feature-store/view",
                "drive", "Feature store"),
    ),
    blockers=(
        BlockerSpec("Feature store",
                    "Waited on a data-platform quota increase (resolved).",
                    "resource", "medium", "Ethan Wu", "Nina Kowalski", True, 30),
    ),
    deploy_weeks=7,
    pod="Search & Discovery",
    owner="Nina Kowalski",
)

# =========================================================================== #
# DELIVERY PROMISE
# =========================================================================== #
_INVENTORY = ProjectSpec(
    "INVENTORY", "Real-Time Inventory",
    "Stock events from warehouses and stores instead of nightly files, reservations at "
    "checkout and an availability API the site and delivery promise can trust.",
    "DELIVERY", 10, 6, True, "on_track",
    "Stock event stream in production; reservations in review; availability API in build.",
    ("inventory", "events", "backend"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Inventory event model", 5, "Done", 62, "Amina Diallo",
                     ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Stock event stream", 12, "Done", 46, "Yara Haddad",
                     ("backend", "events"), (10, 12, 16)),
            TaskSpec("Warehouse adapter", 10, "Done", 32, "Yara Haddad", ("backend",)),
            TaskSpec("Reservation service", 10, "In Review", 4, "Yara Haddad",
                     ("backend",), (8, 10, 14)),
            TaskSpec("Availability API", 14, "In Progress", 8, "Ethan Wu",
                     ("backend", "data"), (10, 14, 18)),
            TaskSpec("Store inventory sync", 8, "To Do", 0, "Ethan Wu", ("data",)),
            TaskSpec("Retire the legacy nightly import", 3, "To Do", 0, "Yara Haddad",
                     ("backend", "cleanup")),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Oversell alerts", 4, "To Do", 0, "Sam Adeyemi", ("observability",)),
            TaskSpec("Inventory accuracy audit", 5, "To Do", 0, "Fatou Ndiaye", ("qa",)),
            TaskSpec("Real-time inventory GA", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Stock events in production", -5, "hit"),
        MilestoneSpec("Reservations live", 2),
        MilestoneSpec("Real-time inventory GA", 6),
    ),
    components=(
        ComponentSpec("inventory-service", "service", "business", "high", "Yara Haddad"),
        ComponentSpec("inventory-db", "datastore", "data", "high"),
        ComponentSpec("stock-events", "datastore", "data", "high"),
        ComponentSpec("warehouse-system", "external", "infra", "high"),
        ComponentSpec("availability-api", "service", "business", "high", "Ethan Wu"),
    ),
    component_links=(
        LinkSpec("warehouse-system", "stock-events", "publishes_to"),
        LinkSpec("inventory-service", "stock-events", "reads_from"),
        LinkSpec("inventory-service", "inventory-db", "depends_on"),
        LinkSpec("availability-api", "inventory-db", "reads_from"),
        LinkSpec("warehouse-system", "inventory-db", "depends_on"),  # legacy import (drift)
    ),
    bindings=(BindingSpec("inventory-service", "services/inventory/**", "shop.inventory"),),
    adrs=(
        ADRSpec("Inventory as an event stream", "accepted", "one_way",
                "Amina Diallo", "Yara Haddad",
                "Nightly stock files from the warehouses left the site selling items that "
                "were already gone.",
                "Warehouses and stores publish stock events; only the inventory service writes "
                "inventory state.",
                "Near-real-time stock; we own replay, ordering and idempotency.",
                alternatives=("Hourly stock files",),
                components=("inventory-service", "stock-events"),
                fitness=FitnessSpec("forbid", "warehouse-system", "inventory-db",
                                    "Warehouse adapters publish events; they never write "
                                    "inventory state directly."),
                created_days_ago=48),
        ADRSpec("Reserve stock at add-to-cart or at payment", "under_discussion", "two_way",
                "Oliver Grant", "Yara Haddad",
                "Reserving at add-to-cart prevents oversells but strands stock in abandoned "
                "carts.",
                "Proposed: soft-reserve for 15 minutes when checkout starts, hard-reserve at "
                "payment.",
                components=("inventory-service",),
                stakeholders=("Oliver Grant", "Yara Haddad", "Rahul Verma", "Amina Diallo"),
                comments=(
                    ADRCommentSpec("Rahul Verma", "Checkout start is the right moment; carts "
                                   "are too noisy.", "approve"),
                    ADRCommentSpec("Oliver Grant", "Need oversell numbers by category before "
                                   "we pick a timeout.", "request_changes"),
                    ADRCommentSpec("Yara Haddad", "Pulling the oversell report from last "
                                   "peak.", "comment"),
                ),
                created_days_ago=15),  # stuck in review (> 14 days)
        ADRSpec("Store inventory accuracy threshold", "deferred", owner="Oliver Grant",
                context="Showing in-store availability needs store counts we trust; accuracy "
                        "is about 92% today.",
                created_days_ago=10, decide_by_weeks=3),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "warehouse-system writes inventory-db directly",
                  ("warehouse-system", "inventory-db"),
                  "Violates the event-stream ADR; the legacy nightly import still writes "
                  "stock rows.",
                  "Legacy nightly import job", "rejected"),
    ),
    specs=(
        SpecSpec("Accurate availability",
                 "Shoppers buy items that are already out of stock, and 1.8% of orders are "
                 "cancelled for it.",
                 "approved", "Yara Haddad",
                 adr_title="Inventory as an event stream",
                 criteria=(
                     CriterionSpec("Stock changes reach the site within 60 seconds.", "met",
                                   "p95 of 38 seconds in staging."),
                     CriterionSpec("No oversells for items with live stock events.", "open"),
                     CriterionSpec("The availability API answers in under 50 ms at p99.",
                                   "open"),
                     CriterionSpec("Store stock is shown only above the accuracy threshold.",
                                   "waived", "Deferred along with its ADR."),
                 ),
                 task_names=("Stock event stream", "Reservation service", "Availability API")),
    ),
    risks=(
        RiskSpec("Event replay double-reserves stock", "technical", "low", "high",
                 "mitigating", "Yara Haddad", "Idempotency keys on every stock event."),
    ),
    mitigations=(
        MitigationSpec("over_allocation",
                       "Yara's vacation overlaps the availability API; Ethan pairs with her on "
                       "it beforehand.", "Hana Sato", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Fewer out-of-stock cancellations", "orders cancelled for stock", "%",
                    1.8, 0.3, 0.9, "on_track", "Yara Haddad"),
    ),
    docs=(
        DocSpec("architecture", "Inventory event model", f"{_WIKI}/operations/inventory-events"),
    ),
    retro=RetroSpec("Stock event stream retro", "project_retro",
                    "## Went well\n- Stock now reaches the site in under a minute.\n\n"
                    "## Improve\n- The legacy import was left running in parallel.\n\n"
                    "## Actions\n- Retire the nightly import before peak.",
                    ("stock-events",),
                    (RetroCommentSpec("Yara Haddad", "Idempotency keys saved us twice."),)),
    draft=DraftSpec("Store inventory rollout",
                    "Bring store stock online once accuracy is trusted; review before "
                    "ticketing.",
                    "Store inventory",
                    (DraftTaskSpec("Store stock counts integration", "task", 5, 8.0),
                     DraftTaskSpec("Pick up in store availability badge", "task", 3, 5.0),
                     DraftTaskSpec("Cycle-count accuracy dashboard", "task", 2, 3.0))),
    deploy_weeks=8,
    pod="Orders & Inventory",
    owner="Yara Haddad",
)

_TRACKING = ProjectSpec(
    "TRACKING", "Delivery Promise & Tracking",
    "A delivery date shoppers can trust on every product page, one tracking page for every "
    "carrier, and proactive delay alerts.",
    "DELIVERY", 9, 4, True, "at_risk",
    "Carrier integrations missed their milestone; two regional carriers still have no API "
    "access.",
    ("delivery", "tracking", "carriers"),
    phases=(
        PhaseSpec("Discovery", (
            TaskSpec("Delivery promise research", 5, "Done", 57, "Oliver Grant",
                     ("product", "research")),
            TaskSpec("Tracking page designs", 6, "Done", 48, "Mira Patel", ("design",)),
            TaskSpec("Tracking event model", 5, "Done", 41, "Amina Diallo",
                     ("architecture",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Carrier API contracts", 8, "Done", 30, "Marco Bellini", ("backend",)),
            TaskSpec("Tracking notifications service", 8, "Done", 19, "Marco Bellini",
                     ("backend",)),
            TaskSpec("Carrier tracking integrations", 15, "In Progress", 24, "Marco Bellini",
                     ("backend", "integrations"), (10, 15, 24)),  # aging
            TaskSpec("Delivery-date estimator", 10, "To Do", 0, "Amina Diallo",
                     ("backend", "data")),
            TaskSpec("Show delivery date on product pages", 5, "To Do", 0, "Diego Ramos",
                     ("frontend",)),
            TaskSpec("Delay alerts", 5, "To Do", 0, "Chloe Martin", ("mobile", "backend")),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Delivery promise GA", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Carrier integrations complete", -2, "missed"),
        MilestoneSpec("Tracking page live", 2),
        MilestoneSpec("Delivery promise GA", 4),
    ),
    components=(
        ComponentSpec("tracking-service", "service", "business", "high", "Marco Bellini"),
        ComponentSpec("carrier-apis", "external", "infra", "high"),
        ComponentSpec("tracking-page", "ui", "presentation", "med"),
        ComponentSpec("notification-service", "service", "business", "med"),
        ComponentSpec("promise-engine", "module", "business", "high", "Amina Diallo"),
    ),
    component_links=(
        LinkSpec("tracking-page", "tracking-service", "calls"),
        LinkSpec("tracking-service", "carrier-apis", "calls"),
        LinkSpec("tracking-service", "notification-service", "publishes_to"),
        LinkSpec("promise-engine", "tracking-service", "reads_from"),
    ),
    # Bound to code but never scanned → the Drift tab shows the scan as due.
    bindings=(
        BindingSpec("tracking-service", "services/tracking/**", "shop.tracking"),
        BindingSpec("promise-engine", "services/promise/**", "shop.promise"),
    ),
    adrs=(
        ADRSpec("Normalize carrier events into one tracking model", "accepted", "two_way",
                "Amina Diallo", "Marco Bellini",
                "Each carrier reports statuses differently; the page and emails were full of "
                "carrier-specific branches.",
                "Map every carrier status to one internal event model in tracking-service; "
                "clients only see normalized events.",
                "One model for the page, emails and support; mapping tables need upkeep for "
                "each carrier.",
                components=("tracking-service", "carrier-apis"),
                fitness=FitnessSpec("forbid", "tracking-page", "carrier-apis",
                                    "The tracking page reads normalized events; it never "
                                    "calls carrier APIs directly."),
                created_days_ago=42),
        ADRSpec("Promise dates: conservative vs optimistic", "under_discussion", "two_way",
                "Oliver Grant", "Amina Diallo",
                "An optimistic date sells more, but every miss costs a support contact and "
                "trust.",
                "Proposed: show the date we hit 80% of the time, and an earlier 'could arrive' "
                "date only for in-stock items near a warehouse.",
                components=("promise-engine",),
                stakeholders=("Oliver Grant", "Amina Diallo", "Mira Patel", "Victor Lindgren"),
                comments=(
                    ADRCommentSpec("Mira Patel", "Shoppers in testing preferred one honest "
                                   "date over a range.", "approve"),
                    ADRCommentSpec("Victor Lindgren", "Most 'where is my order' contacts come "
                                   "the day after a missed promise.", "comment"),
                    ADRCommentSpec("Oliver Grant", "Need the conversion impact of the "
                                   "conservative date before deciding.", "request_changes"),
                ),
                created_days_ago=12),
        ADRSpec("Push notifications vs SMS for delay alerts", "proposed",
                proposer="Chloe Martin",
                context="Delay alerts cut support contacts. Push is free but needs the app; "
                        "SMS reaches everyone but costs per message.",
                created_days_ago=4),  # overdue triage
    ),
    specs=(
        SpecSpec("Trustworthy delivery promise",
                 "Shoppers don't trust our delivery dates, and 'where is my order' is the top "
                 "reason they contact support.",
                 "in_progress", "Amina Diallo",
                 adr_title="Normalize carrier events into one tracking model",
                 criteria=(
                     CriterionSpec("The promised date is met for 95% of orders.", "unmet",
                                   "88% today; carrier delays dominate."),
                     CriterionSpec("Shoppers hear about a delay before the promised date "
                                   "passes.", "open"),
                     CriterionSpec("One tracking page works for every carrier.", "open"),
                 ),
                 task_names=("Carrier tracking integrations", "Delivery-date estimator",
                             "Delay alerts")),
    ),
    risks=(
        RiskSpec("Carrier APIs rate-limit tracking polls", "external", "high", "medium",
                 "open", "Marco Bellini", "Prefer carrier webhooks; poll with backoff.",
                 "Poll low-volume carriers hourly.", target_weeks=-2),  # overdue
    ),
    outcomes=(
        OutcomeSpec("Promised date met", "orders delivered by the promised date", "%",
                    88.0, 95.0, 89.0, "at_risk", "Amina Diallo"),
    ),
    docs=(
        DocSpec("design", "Tracking page designs", f"{_DRIVE}/doc-tracking-ux/view", "drive"),
        DocSpec("runbook", "Carrier onboarding runbook", f"{_WIKI}/delivery/carrier-onboarding",
                "manual", "Carrier tracking integrations"),
    ),
    blockers=(
        BlockerSpec("Carrier tracking integrations",
                    "Two regional carriers have not issued API credentials.",
                    "external", "high", "Oliver Grant", "Marco Bellini", False, 9, 1),
        BlockerSpec("Delivery-date estimator",
                    "Needs the availability API from the inventory team.",
                    "dependency", "medium", "Yara Haddad", "Amina Diallo", False, 3, 2),
    ),
    incidents=(
        IncidentSpec("Tracking page showed stale statuses for one carrier", 11, 8,
                     "tracking-service"),
    ),
    deploy_weeks=6,
    pod="Delivery",
    owner="Amina Diallo",
)

# =========================================================================== #
# MARKETPLACE LAUNCH
# =========================================================================== #
_SELLERS = ProjectSpec(
    "SELLERS", "Seller Portal & Onboarding",
    "Self-serve onboarding for third-party sellers: business accounts, identity checks, a "
    "listing editor, bulk upload and a review queue.",
    "MARKETPLACE", 11, 6, True, "on_track",
    "Twelve beta sellers live; bulk upload in build; the review queue is the next bottleneck.",
    ("marketplace", "sellers", "web"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Seller journey mapping", 6, "Done", 68, "Mira Patel",
                     ("design", "research")),
        )),
        PhaseSpec("Build", (
            TaskSpec("Seller accounts & roles", 10, "Done", 56, "Kofi Boateng",
                     ("backend",)),
            TaskSpec("Seller KYC verification", 10, "Done", 42, "Kofi Boateng",
                     ("backend", "compliance"), (8, 10, 15)),
            TaskSpec("Seller portal shell", 8, "Done", 30, "Ava Thompson", ("frontend",)),
            TaskSpec("Listing editor", 10, "Done", 16, "Ava Thompson", ("frontend",),
                     (8, 10, 14)),
            TaskSpec("Bulk listing upload", 12, "In Progress", 9, "Kofi Boateng",
                     ("backend",), (8, 12, 18)),
            TaskSpec("Listing review queue", 6, "To Do", 0, "Kofi Boateng", ("backend",)),
            TaskSpec("Seller onboarding emails", 4, "To Do", 0, "Ava Thompson",
                     ("frontend",)),
            TaskSpec("Seller help center", 5, "To Do", 0, "Victor Lindgren", ("support",)),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Marketplace open to sellers", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Seller beta", -3, "hit"),
        MilestoneSpec("100 sellers onboarded", 3),
        MilestoneSpec("Marketplace launch", 6),
    ),
    components=(
        ComponentSpec("seller-portal", "ui", "presentation", "high", "Ava Thompson"),
        ComponentSpec("seller-api", "service", "business", "high", "Kofi Boateng"),
        ComponentSpec("listing-review", "service", "business", "med"),
        ComponentSpec("catalog-service", "service", "business", "high"),
        ComponentSpec("kyc-provider", "external", "infra", "high"),
        ComponentSpec("seller-db", "datastore", "data", "high"),
    ),
    component_links=(
        LinkSpec("seller-portal", "seller-api", "calls"),
        LinkSpec("seller-api", "listing-review", "publishes_to"),
        LinkSpec("listing-review", "catalog-service", "publishes_to"),
        LinkSpec("seller-api", "kyc-provider", "calls"),
        LinkSpec("seller-api", "seller-db", "depends_on"),
    ),
    bindings=(BindingSpec("seller-api", "services/sellers/**", "shop.sellers"),),
    adrs=(
        ADRSpec("Seller listings go through a review queue", "accepted", "two_way",
                "Jakub Novak", "Kofi Boateng",
                "Counterfeit and prohibited items damage shopper trust in the whole "
                "marketplace.",
                "New and changed listings pass automated checks and, when flagged, a human "
                "review before they reach the catalog.",
                "A safer catalog; sellers wait longer for flagged listings.",
                components=("listing-review", "catalog-service"),
                fitness=FitnessSpec("forbid", "seller-portal", "catalog-service",
                                    "Seller changes reach the catalog only through the review "
                                    "queue."),
                created_days_ago=46),
        ADRSpec("Separate seller identity from shopper accounts", "accepted", "one_way",
                "Ingrid Larsen", "Kofi Boateng",
                "Sellers are businesses with several staff; shopper accounts are personal.",
                "Sellers get organisation accounts with roles, separate from shopper login.",
                "Clean permissions and audit; a second login system to run.",
                components=("seller-api", "seller-db"), created_days_ago=60),
        ADRSpec("Commission model: flat vs category-based", "under_discussion", "two_way",
                "Oliver Grant", "Jakub Novak",
                "A flat rate is simple to explain; category-based rates match our margins and "
                "the market.",
                "Proposed: category-based rates, with a flat launch rate for the first 90 "
                "days.",
                stakeholders=("Oliver Grant", "Jakub Novak", "Gabriel Silva", "Mira Patel"),
                comments=(
                    ADRCommentSpec("Gabriel Silva", "The ledger handles either; category "
                                   "rates need a rates table.", "comment"),
                    ADRCommentSpec("Mira Patel", "A launch rate keeps the onboarding story "
                                   "simple.", "approve"),
                    ADRCommentSpec("Oliver Grant", "Finance wants to see the margin model "
                                   "first.", "request_changes"),
                ),
                created_days_ago=11),
    ),
    drift=(
        DriftSpec("implicit_decision", "seller-api caches KYC results for 30 days",
                  ("seller-api", "kyc-provider"),
                  "A retention choice for identity data was made in code without an ADR.",
                  "PR #377 (KYC result cache)", "accepted"),
    ),
    specs=(
        SpecSpec("Self-serve seller onboarding",
                 "Onboarding a seller takes three weeks of emails; sellers should be able to "
                 "list within two days.",
                 "in_progress", "Kofi Boateng",
                 adr_title="Seller listings go through a review queue",
                 criteria=(
                     CriterionSpec("A seller can sign up, verify and list without talking to "
                                   "us.", "met"),
                     CriterionSpec("Identity checks return within one business day.", "met",
                                   "Provider turnaround verified in the beta."),
                     CriterionSpec("Bulk upload handles 10,000 listings per file.", "open"),
                     CriterionSpec("Flagged listings get a decision within 24 hours.",
                                   "unmet", "The review backlog is three days."),
                 ),
                 task_names=("Seller KYC verification", "Bulk listing upload",
                             "Listing review queue")),
    ),
    risks=(
        RiskSpec("Review queue backlog delays seller launches", "resource", "medium",
                 "medium", "open", "Victor Lindgren",
                 "Auto-approve rules for trusted categories."),
    ),
    outcomes=(
        OutcomeSpec("Faster seller onboarding", "days from sign-up to first listing", "days",
                    21.0, 2.0, 6.0, "on_track", "Kofi Boateng"),
    ),
    docs=(
        DocSpec("prd", "Seller portal PRD", f"{_WIKI}/marketplace/seller-portal-prd"),
        DocSpec("qa", "Bulk upload test plan", f"{_WIKI}/marketplace/bulk-upload-tests",
                "manual", "Bulk listing upload"),
    ),
    blockers=(
        BlockerSpec("Bulk listing upload",
                    "The file format for variants (sizes and colours) is still undecided.",
                    "decision", "medium", "Oliver Grant", "Kofi Boateng", False, 4, 1),
    ),
    retro=RetroSpec("Seller beta retrospective", "project_retro",
                    "## Went well\n- Twelve beta sellers listed within two days.\n\n"
                    "## Improve\n- The review queue was understaffed from day one.\n\n"
                    "## Actions\n- Auto-approve rules for trusted categories.",
                    ("listing-review",),
                    (RetroCommentSpec("Kofi Boateng", "Identity checks through the provider "
                                      "were painless."),
                     RetroCommentSpec("Victor Lindgren", "Sellers need a status page for "
                                      "their listings."))),
    draft=DraftSpec("Seller analytics",
                    "A first seller dashboard to review before creating tickets.",
                    "Seller analytics",
                    (DraftTaskSpec("Sales and traffic dashboard", "task", 5, 8.0),
                     DraftTaskSpec("Returns and ratings view", "task", 3, 5.0),
                     DraftTaskSpec("Payout forecast widget", "task", 2, 3.0))),
    deploy_weeks=9,
    pod="Marketplace",
    owner="Kofi Boateng",
)

_PAYOUTS = ProjectSpec(
    "PAYOUTS", "Seller Payouts & Commissions",
    "Pay marketplace sellers correctly and on time: a double-entry ledger, commission "
    "calculation, payout scheduling and seller statements.",
    "MARKETPLACE", 7, 7, True, "on_track",
    "Ledger and commission engine done; payout accounts in build ahead of the first payout.",
    ("marketplace", "payments", "finance"),
    phases=(
        PhaseSpec("Design", (
            TaskSpec("Payout flows & ledger design", 6, "Done", 40, "Gabriel Silva",
                     ("architecture",)),
            TaskSpec("Commission rules", 5, "Done", 33, "Oliver Grant", ("product",)),
        )),
        PhaseSpec("Build", (
            TaskSpec("Double-entry ledger", 12, "Done", 16, "Gabriel Silva",
                     ("backend", "finance"), (10, 12, 16)),
            TaskSpec("Commission calculation", 8, "Done", 5, "Gabriel Silva", ("backend",)),
            TaskSpec("Payout account setup", 8, "In Progress", 4, "Gabriel Silva",
                     ("backend",)),
            TaskSpec("Payout scheduling", 6, "To Do", 0, "Gabriel Silva", ("backend",)),
            TaskSpec("Seller statements & reports", 6, "To Do", 0, "Ethan Wu", ("data",)),
            TaskSpec("Tax reporting thresholds", 5, "To Do", 0, "Ethan Wu",
                     ("data", "compliance")),
        )),
        PhaseSpec("Launch", (
            TaskSpec("First payout sent", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Ledger in production", -2, "hit"),
        MilestoneSpec("First seller payout", 4),
        MilestoneSpec("Payouts GA", 7),
    ),
    components=(
        ComponentSpec("payout-service", "service", "business", "high", "Gabriel Silva"),
        ComponentSpec("ledger-db", "datastore", "data", "high"),
        ComponentSpec("commission-engine", "module", "business", "high"),
        ComponentSpec("payout-provider", "external", "infra", "high"),
        ComponentSpec("seller-statements", "service", "presentation", "med", "Ethan Wu"),
    ),
    component_links=(
        LinkSpec("payout-service", "ledger-db", "depends_on"),
        LinkSpec("payout-service", "payout-provider", "calls"),
        LinkSpec("commission-engine", "ledger-db", "depends_on"),
        LinkSpec("seller-statements", "ledger-db", "reads_from"),
    ),
    adrs=(
        ADRSpec("Double-entry ledger for seller balances", "accepted", "one_way",
                "Ingrid Larsen", "Gabriel Silva",
                "Seller balances must be auditable to the cent; mutable balance columns cannot "
                "be reconciled.",
                "Every money movement is a pair of immutable ledger entries; balances are "
                "derived.",
                "Auditable and reversible; reports need materialized views.",
                components=("payout-service", "ledger-db"),
                fitness=FitnessSpec("require", "payout-service", "ledger-db",
                                    "Every payout must post through the ledger."),
                created_days_ago=35),
        ADRSpec("Payout frequency: weekly vs on-demand", "proposed", proposer="Oliver Grant",
                context="Sellers want their money sooner; on-demand payouts cost more and "
                        "raise fraud risk.",
                created_days_ago=5),  # overdue triage
    ),
    specs=(
        SpecSpec("Correct seller payouts",
                 "Sellers must be paid the right amount, on time, with a statement they can "
                 "check.",
                 "approved", "Gabriel Silva",
                 adr_title="Double-entry ledger for seller balances",
                 criteria=(
                     CriterionSpec("Every payout reconciles to ledger entries.", "met",
                                   "The reconciliation job passes on staging."),
                     CriterionSpec("Commission is calculated per order line and category.",
                                   "open"),
                     CriterionSpec("Sellers can download a statement for every payout.",
                                   "open"),
                 ),
                 task_names=("Double-entry ledger", "Commission calculation",
                             "Payout scheduling", "Seller statements & reports")),
    ),
    risks=(
        RiskSpec("Tax reporting rules differ by region", "external", "medium", "high",
                 "open", "Oliver Grant",
                 "Launch payouts in two regions first; add the rest behind a flag."),
    ),
    outcomes=(
        OutcomeSpec("On-time seller payouts", "payouts sent on schedule", "%",
                    0.0, 99.5, 0.0, "pending", "Gabriel Silva"),
    ),
    docs=(
        DocSpec("release", "Payouts launch checklist", f"{_WIKI}/marketplace/payouts-launch"),
        DocSpec("tech_design", "Ledger design", f"{_DRIVE}/doc-ledger/view", "drive",
                "Double-entry ledger"),
    ),
    blockers=(
        BlockerSpec("Payout account setup",
                    "Was waiting on payout-provider sandbox credentials (resolved).",
                    "external", "low", "Gabriel Silva", "Gabriel Silva", True, 12),
    ),
    deploy_weeks=5,
    pod="Marketplace",
    owner="Gabriel Silva",
)

# =========================================================================== #
# HOLIDAY PEAK READINESS
# =========================================================================== #
_PEAKSCALE = ProjectSpec(
    "PEAKSCALE", "Peak Scale & Resilience",
    "Keep the site and checkout up at five times normal traffic: connection pooling, a "
    "checkout waiting room, autoscaling, load tests and game days before the code freeze.",
    "PEAK", 8, 5, True, "at_risk",
    "3x load test passed; the waiting room is aging on a CDN change and the plan lands after "
    "the code freeze.",
    ("platform", "reliability", "peak"),
    phases=(
        PhaseSpec("Prepare", (
            TaskSpec("Peak capacity model", 5, "Done", 50, "Sam Adeyemi", ("capacity",)),
            TaskSpec("Database connection pooling", 8, "Done", 40, "Jakub Novak",
                     ("backend", "database")),
            TaskSpec("Cache warm-up for peak", 6, "Done", 31, "Sam Adeyemi", ("infra",)),
            TaskSpec("Load test at 3x", 5, "Done", 24, "Fatou Ndiaye", ("qa", "load")),
            TaskSpec("Read replicas for the catalog", 6, "Done", 16, "Sam Adeyemi",
                     ("database",)),
        )),
        PhaseSpec("Harden", (
            TaskSpec("Checkout waiting room", 12, "In Progress", 18, "Jakub Novak",
                     ("infra", "checkout"), (8, 12, 18)),  # aging
            TaskSpec("Autoscaling policies", 8, "To Do", 0, "Sam Adeyemi", ("infra",)),
            TaskSpec("Load test at 5x", 5, "To Do", 0, "Fatou Ndiaye", ("qa", "load")),
            TaskSpec("Peak runbooks & on-call rota", 5, "To Do", 0, "Hana Sato",
                     ("operations",)),
            TaskSpec("Game day", 4, "To Do", 0, "Sam Adeyemi", ("operations",)),
            TaskSpec("Peak ready", 0, milestone=True, deadline_weeks=4),  # the code freeze
        )),
    ),
    milestones=(
        MilestoneSpec("3x load test passed", -3, "hit"),
        MilestoneSpec("5x load test passed", 2, "at_risk"),
        MilestoneSpec("Code freeze", 4),
    ),
    components=(
        ComponentSpec("api-gateway", "service", "infra", "high", "Jakub Novak"),
        ComponentSpec("waiting-room", "service", "infra", "high", "Jakub Novak"),
        ComponentSpec("web-storefront", "ui", "presentation", "high"),
        ComponentSpec("checkout-api", "service", "business", "high"),
        ComponentSpec("orders-db", "datastore", "data", "high"),
        ComponentSpec("cache-cluster", "datastore", "data", "high", "Sam Adeyemi"),
    ),
    component_links=(
        LinkSpec("web-storefront", "api-gateway", "calls"),
        LinkSpec("api-gateway", "waiting-room", "depends_on"),
        LinkSpec("api-gateway", "checkout-api", "calls"),
        LinkSpec("checkout-api", "orders-db", "depends_on"),
        LinkSpec("web-storefront", "cache-cluster", "reads_from"),
    ),
    bindings=(BindingSpec("waiting-room", "platform/waiting-room/**", "shop.waitingroom"),),
    adrs=(
        ADRSpec("Queue shoppers instead of failing under overload", "accepted", "two_way",
                "Jakub Novak", "Sam Adeyemi",
                "At last year's peak, checkout errors cascaded once traffic passed capacity.",
                "Above a load threshold the gateway admits shoppers to checkout through a "
                "waiting room instead of returning errors.",
                "Graceful degradation; some shoppers wait a few minutes at the busiest "
                "moments.",
                components=("api-gateway", "waiting-room"),
                fitness=FitnessSpec("require", "api-gateway", "waiting-room",
                                    "Checkout traffic must pass the waiting-room admission "
                                    "check."),
                created_days_ago=33),
        ADRSpec("Peak code freeze window", "accepted", "two_way", "Hana Sato", "Jakub Novak",
                "Most of last year's peak incidents followed late deploys.",
                "Freeze non-critical deploys from two weeks before peak week until the week "
                "after; fixes go through an exception review.",
                "Fewer incidents; feature work has to land before the freeze.",
                created_days_ago=25),
        ADRSpec("Pre-scale vs reactive autoscaling for peak", "under_discussion", "two_way",
                "Jakub Novak", "Sam Adeyemi",
                "Reactive autoscaling lagged the traffic spikes at the start of last year's "
                "sale.",
                "Proposed: pre-scale to the forecast for peak days and keep autoscaling as a "
                "safety net.",
                components=("api-gateway",),
                stakeholders=("Jakub Novak", "Sam Adeyemi", "Hana Sato", "Claire Dubois"),
                comments=(
                    ADRCommentSpec("Sam Adeyemi", "Pre-scaling would have avoided last year's "
                                   "first-hour incident.", "approve"),
                    ADRCommentSpec("Claire Dubois", "I need the cost of a week of pre-scaled "
                                   "capacity before we commit.", "request_changes"),
                    ADRCommentSpec("Jakub Novak", "Costing it with finance this week.",
                                   "comment"),
                ),
                created_days_ago=13),
    ),
    drift=(
        DriftSpec("unexpected_dependency", "web-storefront calls orders-db during load tests",
                  ("web-storefront", "orders-db"),
                  "The traffic was the load-test harness seeding orders, not the storefront.",
                  "Load-test data seeding", "false_positive"),
    ),
    specs=(
        SpecSpec("Survive 5x peak traffic",
                 "Checkout must stay up at five times normal traffic during the peak sale.",
                 "in_progress", "Sam Adeyemi",
                 adr_title="Queue shoppers instead of failing under overload",
                 criteria=(
                     CriterionSpec("Checkout errors stay under 0.5% at 5x load.", "open"),
                     CriterionSpec("Product pages stay under 800 ms at p95 at 5x load.",
                                   "unmet", "1.1 s in the 3x test."),
                     CriterionSpec("Overload degrades to the waiting room, never to errors.",
                                   "met", "Verified in the 3x test."),
                 ),
                 task_names=("Checkout waiting room", "Autoscaling policies",
                             "Load test at 5x")),
    ),
    risks=(
        RiskSpec("5x load test finds a new bottleneck late", "schedule", "high", "high",
                 "open", "Sam Adeyemi", "Run partial 4x tests weekly until the full test.",
                 "Lower the waiting-room threshold for peak week.", target_weeks=2),
    ),
    mitigations=(
        MitigationSpec("deadline_violations",
                       "Moving game day earlier to land before the code freeze.",
                       "Jakub Novak", False, 1),
    ),
    outcomes=(
        OutcomeSpec("Peak capacity proven", "sustained load tested", "x normal",
                    3.0, 5.0, 3.0, "at_risk", "Sam Adeyemi"),
    ),
    docs=(
        DocSpec("runbook", "Peak week runbook", f"{_WIKI}/platform/peak-runbook"),
        DocSpec("qa", "Load test plan", f"{_DRIVE}/doc-load-test/view", "drive",
                "Load test at 5x"),
    ),
    blockers=(
        BlockerSpec("Checkout waiting room",
                    "Needs a CDN configuration change from the vendor.",
                    "external", "high", "Jakub Novak", "Sam Adeyemi", False, 7, 1),
    ),
    retro=RetroSpec("Last year's peak postmortem", "incident_postmortem",
                    "## What happened\n- Checkout errors reached 12% in the first hour of "
                    "the sale.\n\n## Root cause\n- Connection pools on the orders database "
                    "were exhausted.\n\n## Actions\n- Connection pooling, a waiting room and "
                    "a 5x load test before peak.",
                    ("checkout-api", "orders-db"),
                    (RetroCommentSpec("Sam Adeyemi", "Autoscaling reacted ten minutes too "
                                      "late."),
                     RetroCommentSpec("Jakub Novak", "A waiting room would have kept "
                                      "checkout up."))),
    draft=DraftSpec("Post-peak hardening",
                    "Follow-ups from peak readiness to review after peak week.",
                    "Post-peak hardening",
                    (DraftTaskSpec("Multi-region failover drill", "task", 5, 8.0),
                     DraftTaskSpec("Automate the capacity model", "task", 4, 5.0),
                     DraftTaskSpec("Chaos testing in staging", "task", 3, 5.0))),
    incidents=(
        IncidentSpec("Cache cluster failover during the 3x load test", 20, 2,
                     "cache-cluster"),
    ),
    deploy_weeks=8,
    pod="Platform",
    owner="Sam Adeyemi",
)

_PERF = ProjectSpec(
    "PERF", "Storefront Performance",
    "Fast product and category pages on mobile, at peak: server-side rendering, edge "
    "caching, an image CDN and performance budgets in CI.",
    "PEAK", 6, 5, False, "on_track",
    "Server rendering shipped; edge caching in progress; LCP down from 4.0 s to 3.1 s.",
    ("storefront", "performance", "web"),
    phases=(
        PhaseSpec("Measure", (
            TaskSpec("Core Web Vitals audit", 5, "Done", 38, "Diego Ramos",
                     ("frontend", "performance")),
        )),
        PhaseSpec("Build", (
            TaskSpec("Image CDN & responsive images", 8, "Done", 30, "Diego Ramos",
                     ("frontend",)),
            TaskSpec("Server-render product pages", 12, "Done", 18, "Diego Ramos",
                     ("frontend", "backend"), (8, 12, 16)),
            TaskSpec("Critical CSS & font loading", 7, "Done", 11, "Ava Thompson",
                     ("frontend",)),
            TaskSpec("Edge caching for product pages", 14, "In Progress", 10, "Sam Adeyemi",
                     ("infra", "performance"), (10, 14, 20)),
            TaskSpec("JavaScript bundle diet", 10, "To Do", 0, "Diego Ramos", ("frontend",)),
            TaskSpec("Performance budgets in CI", 5, "To Do", 0, "Fatou Ndiaye",
                     ("qa", "performance")),
        )),
        PhaseSpec("Launch", (
            TaskSpec("Fast pages for peak", 0, milestone=True),
        )),
    ),
    milestones=(
        MilestoneSpec("Vitals baseline", -5, "hit"),
        MilestoneSpec("Product pages under 2.5 s LCP", 3),
    ),
    components=(
        ComponentSpec("web-storefront", "ui", "presentation", "high", "Diego Ramos"),
        ComponentSpec("ssr-renderer", "service", "presentation", "high", "Diego Ramos"),
        ComponentSpec("edge-cache", "external", "infra", "high", "Sam Adeyemi"),
        ComponentSpec("image-cdn", "external", "infra", "med"),
        ComponentSpec("catalog-api", "service", "business", "high"),
    ),
    component_links=(
        LinkSpec("edge-cache", "ssr-renderer", "calls"),
        LinkSpec("web-storefront", "ssr-renderer", "depends_on"),
        LinkSpec("ssr-renderer", "catalog-api", "calls"),
        LinkSpec("web-storefront", "image-cdn", "reads_from"),
    ),
    adrs=(
        ADRSpec("Server-side rendering for product pages", "accepted", "two_way",
                "Diego Ramos", "Diego Ramos",
                "Client-rendered product pages took four seconds to show content on "
                "mid-range phones.",
                "Render product and category pages on the server and cache them at the edge; "
                "the browser hydrates only the interactive parts.",
                "Fast first paint and better SEO; cache invalidation becomes critical.",
                components=("ssr-renderer", "web-storefront"),
                fitness=FitnessSpec("forbid", "web-storefront", "catalog-api",
                                    "Product pages get catalog data through the renderer, "
                                    "never from the browser."),
                created_days_ago=30),
        ADRSpec("Rewrite the storefront as a native app shell", "rejected", "one_way",
                "Ingrid Larsen", "Chloe Martin",
                "An app-shell rewrite promised speed but would freeze feature work for two "
                "quarters.",
                "Rejected: improve the existing storefront step by step with server rendering "
                "and a bundle budget.",
                alternatives=("Incremental server rendering + budgets",
                              "An app shell for checkout only"),
                components=("web-storefront",), created_days_ago=40),
    ),
    specs=(
        SpecSpec("Fast product pages",
                 "Slow product pages lose shoppers on mobile, and it gets worse at peak.",
                 "approved", "Diego Ramos",
                 adr_title="Server-side rendering for product pages",
                 criteria=(
                     CriterionSpec("LCP under 2.5 s at p75 on mobile.", "unmet",
                                   "3.1 s today."),
                     CriterionSpec("Under 170 KB of JavaScript on product pages.", "open"),
                     CriterionSpec("The build fails when a page exceeds its budget.", "open"),
                 ),
                 task_names=("Server-render product pages", "JavaScript bundle diet",
                             "Performance budgets in CI")),
    ),
    risks=(
        RiskSpec("Edge cache serves stale prices", "quality", "medium", "high", "mitigating",
                 "Diego Ramos", "Purge product pages on price-change events."),
    ),
    outcomes=(
        OutcomeSpec("Faster product pages", "p75 LCP on mobile", "s",
                    4.0, 2.5, 3.1, "on_track", "Diego Ramos"),
    ),
    docs=(
        DocSpec("tech_design", "Rendering strategy", f"{_WIKI}/storefront/rendering"),
    ),
    incidents=(
        IncidentSpec("Stale prices served from the edge cache", 9, 4, "edge-cache"),
    ),
    deploy_weeks=12,
    pod="Storefront",
    owner="Diego Ramos",
)


PROJECTS: tuple[ProjectSpec, ...] = (
    _ONEPAGE, _PAYMENTS, _SEARCH, _RECS, _INVENTORY, _TRACKING, _SELLERS, _PAYOUTS,
    _PEAKSCALE, _PERF,
)
