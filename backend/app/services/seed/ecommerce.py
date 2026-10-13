"""The demo dataset — a fictional **online retailer** (generic e-commerce; no real brand).

Five initiatives anyone who has shopped online will recognise:

  * **Checkout Modernization** — a one-page checkout on top of a payments-platform migration
    (tokenized cards, 3-D Secure) that has to land before the peak code freeze.
  * **Search & Discovery** — search relevance (typo tolerance, facets, learning-to-rank) and
    personalized recommendations.
  * **Delivery Promise** — real-time inventory and a delivery date shoppers can trust, with one
    tracking page for every carrier.
  * **Marketplace Launch** — self-serve onboarding and payouts for third-party sellers.
  * **Holiday Peak Readiness** — load tests, a checkout waiting room and storefront
    performance before the busiest weeks of the year.

Two teams own the work — **Shopping Experience** and **Commerce Operations** — each with pods,
a director and a manager. Every initiative has a lead team (technical / product / design, plus
a manager seat on the peak programme) and every project one owner; a CTO and a CPO sit above.
Ten projects (two per initiative, defined in ``ecommerce_projects.py``) are fully populated,
with cross-project hand-offs, over-allocations, a baseline with variance on the flagship, a
what-if scenario per initiative and leadership notes. Every login, link and repository is
fictional (``example.com`` domains). Pure data; the generic loader turns it into rows.
"""

from __future__ import annotations

from app.models.base import UserFunction, UserRole
from app.services.seed.catalog import (
    Dataset,
    DemoAvailability,
    DemoConnection,
    DemoEngineer,
    DemoUser,
    DocSpec,
    InitiativeSpec,
    LeadershipNoteSpec,
    OutcomeSpec,
    PullRequestSpec,
    RiskSpec,
    ScenarioAddedTask,
    ScenarioAllocSpec,
    ScenarioAvailSpec,
    ScenarioMilestonePull,
    ScenarioSpec,
    TeamSpec,
)
from app.services.seed.ecommerce_projects import PROJECTS

_DOMAIN = "shop.example.com"
_WIKI = "https://wiki.example.com"
_DRIVE = "https://drive.google.com/file/d"


def _email(local: str) -> str:
    return f"{local}@{_DOMAIN}"


# --------------------------------------------------------------------------- #
# People — one login per role and per function (the shared password is DEMO_PASSWORD)
# --------------------------------------------------------------------------- #
USERS: tuple[DemoUser, ...] = (
    DemoUser(_email("admin"), "Dana Whitfield", UserRole.admin, UserFunction.management),
    # Executives (read-only logins with the leadership function).
    DemoUser(_email("elena"), "Elena Rossi", UserRole.viewer, UserFunction.leadership),
    DemoUser(_email("kwame"), "Kwame Mensah", UserRole.viewer, UserFunction.leadership),
    # Directors and engineering managers.
    DemoUser(_email("arjun"), "Arjun Mehta", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser(_email("claire"), "Claire Dubois", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser(_email("ben"), "Ben Ortiz", UserRole.engineering_manager, UserFunction.management),
    DemoUser(_email("hana"), "Hana Sato", UserRole.engineering_manager,
             UserFunction.management),
    DemoUser(_email("ingrid"), "Ingrid Larsen", UserRole.architect, UserFunction.architecture),
    # Initiative leads: technical, product and design (planner logins).
    DemoUser(_email("rahul"), "Rahul Verma", UserRole.architect, UserFunction.engineering),
    DemoUser(_email("tobias"), "Tobias Klein", UserRole.architect, UserFunction.engineering),
    DemoUser(_email("amina"), "Amina Diallo", UserRole.architect, UserFunction.engineering),
    DemoUser(_email("jakub"), "Jakub Novak", UserRole.architect, UserFunction.engineering),
    DemoUser(_email("sarah"), "Sarah Chen", UserRole.architect, UserFunction.product),
    DemoUser(_email("oliver"), "Oliver Grant", UserRole.architect, UserFunction.product),
    DemoUser(_email("lucia"), "Lucia Ferreira", UserRole.architect, UserFunction.design),
    DemoUser(_email("mira"), "Mira Patel", UserRole.architect, UserFunction.design),
    # Engineers.
    DemoUser(_email("priya"), "Priya Shah", UserRole.engineer, UserFunction.engineering),
    DemoUser(_email("leo"), "Leo Martins", UserRole.engineer, UserFunction.engineering),
    DemoUser(_email("nina"), "Nina Kowalski", UserRole.engineer, UserFunction.engineering),
    DemoUser(_email("sam"), "Sam Adeyemi", UserRole.engineer, UserFunction.engineering),
    DemoUser(_email("yara"), "Yara Haddad", UserRole.engineer, UserFunction.engineering),
    DemoUser(_email("victor"), "Victor Lindgren", UserRole.member, UserFunction.engineering),
    DemoUser(_email("felix"), "Felix Wagner", UserRole.viewer, UserFunction.product),
)

TEAM_ROLES: tuple[str, ...] = (
    "Architecture", "Management", "Product", "Design", "Backend", "Frontend", "Mobile",
    "Search & ML", "Data", "Platform / SRE", "Security", "QA", "Support",
)

ENGINEERS: tuple[DemoEngineer, ...] = (
    DemoEngineer("Arjun Mehta", "Director of Engineering, Shopping Experience",
                 ("management", "web"), "Asia/Kolkata", 20, "arjunmehta", "Management",
                 _email("arjun")),
    DemoEngineer("Claire Dubois", "Director of Engineering, Commerce Operations",
                 ("management", "operations"), "Europe/Paris", 20, "clairedubois",
                 "Management", _email("claire")),
    DemoEngineer("Ben Ortiz", "Engineering Manager, Checkout & Discovery",
                 ("management", "backend"), "America/Chicago", 20, "benortiz", "Management",
                 _email("ben")),
    DemoEngineer("Hana Sato", "Engineering Manager, Fulfilment & Platform",
                 ("management", "infra"), "Asia/Tokyo", 20, "hanasato", "Management",
                 _email("hana")),
    DemoEngineer("Ingrid Larsen", "Principal Architect",
                 ("architecture", "security", "distributed-systems"), "Europe/Oslo", 30,
                 "ingridlarsen", "Architecture", _email("ingrid")),
    DemoEngineer("Rahul Verma", "Staff Engineer, Checkout",
                 ("backend", "java", "payments"), "Asia/Kolkata", 36, "rahulverma", "Backend",
                 _email("rahul")),
    DemoEngineer("Tobias Klein", "Staff Engineer, Search & Discovery",
                 ("search", "backend", "relevance"), "Europe/Berlin", 36, "tobiasklein",
                 "Search & ML", _email("tobias")),
    DemoEngineer("Amina Diallo", "Staff Engineer, Fulfilment",
                 ("backend", "events", "logistics"), "Africa/Dakar", 36, "aminadiallo",
                 "Backend", _email("amina")),
    DemoEngineer("Jakub Novak", "Principal Engineer, Platform & Marketplace",
                 ("infra", "kubernetes", "go"), "Europe/Prague", 36, "jakubnovak",
                 "Platform / SRE", _email("jakub")),
    DemoEngineer("Sarah Chen", "Group Product Manager, Shopping Experience",
                 ("product", "analytics", "experimentation"), "America/Los_Angeles", 30,
                 "sarahchen", "Product", _email("sarah")),
    DemoEngineer("Oliver Grant", "Group Product Manager, Commerce Operations",
                 ("product", "marketplace", "logistics"), "Europe/London", 30, "olivergrant",
                 "Product", _email("oliver")),
    DemoEngineer("Lucia Ferreira", "Design Lead, Shopping Experience",
                 ("design", "research", "prototyping"), "Europe/Lisbon", 30, "luciaferreira",
                 "Design", _email("lucia")),
    DemoEngineer("Mira Patel", "Design Lead, Sellers & Operations",
                 ("design", "research", "service-design"), "Asia/Kolkata", 30, "mirapatel",
                 "Design", _email("mira")),
    DemoEngineer("Priya Shah", "Senior Backend Engineer, Payments",
                 ("backend", "payments", "pci"), "Europe/London", 40, "priyashah", "Backend",
                 _email("priya")),
    DemoEngineer("Leo Martins", "Frontend Engineer, Checkout",
                 ("frontend", "react", "typescript"), "America/Sao_Paulo", 40, "leomartins",
                 "Frontend", _email("leo")),
    DemoEngineer("Nina Kowalski", "Machine Learning Engineer",
                 ("ml", "python", "recommendations"), "Europe/Warsaw", 40, "ninakowalski",
                 "Search & ML", _email("nina")),
    DemoEngineer("Sam Adeyemi", "Site Reliability Engineer",
                 ("infra", "observability", "load-testing"), "Africa/Lagos", 40,
                 "samadeyemi", "Platform / SRE", _email("sam")),
    DemoEngineer("Yara Haddad", "Backend Engineer, Inventory",
                 ("backend", "events", "kafka"), "Asia/Dubai", 40, "yarahaddad", "Backend",
                 _email("yara")),
    DemoEngineer("Victor Lindgren", "Seller Support Engineer",
                 ("support", "sellers", "tooling"), "Europe/Stockholm", 32, "victorlindgren",
                 "Support", _email("victor")),
    # Team members without a demo login.
    DemoEngineer("Gabriel Silva", "Backend Engineer, Payments & Payouts",
                 ("backend", "payments", "ledger"), "America/Sao_Paulo", 40, "gabrielsilva",
                 "Backend"),
    DemoEngineer("Isabel Moreno", "Security Engineer",
                 ("security", "fraud", "compliance"), "Europe/Madrid", 40, "isabelmoreno",
                 "Security"),
    DemoEngineer("Ethan Wu", "Data Engineer",
                 ("data", "sql", "streaming"), "America/New_York", 40, "ethanwu", "Data"),
    DemoEngineer("Diego Ramos", "Senior Frontend Engineer, Storefront",
                 ("frontend", "performance", "react"), "America/Mexico_City", 40,
                 "diegoramos", "Frontend"),
    DemoEngineer("Chloe Martin", "Mobile Engineer",
                 ("mobile", "ios", "android"), "Europe/Paris", 40, "chloemartin", "Mobile"),
    DemoEngineer("Marco Bellini", "Backend Engineer, Delivery",
                 ("backend", "integrations", "logistics"), "Europe/Rome", 40,
                 "marcobellini", "Backend"),
    DemoEngineer("Kofi Boateng", "Senior Backend Engineer, Marketplace",
                 ("backend", "marketplace", "python"), "Africa/Accra", 40, "kofiboateng",
                 "Backend"),
    DemoEngineer("Ava Thompson", "Frontend Engineer, Marketplace",
                 ("frontend", "react", "accessibility"), "America/Toronto", 40,
                 "avathompson", "Frontend"),
    DemoEngineer("Fatou Ndiaye", "QA Engineer",
                 ("qa", "automation", "load-testing"), "Europe/Paris", 40, "fatoundiaye",
                 "QA"),
)

AVAILABILITY: tuple[DemoAvailability, ...] = (
    DemoAvailability("Priya Shah", 3, 4, 0.0, "Vacation"),
    DemoAvailability("Leo Martins", 5, 6, 0.0, "Vacation"),
    DemoAvailability("Sam Adeyemi", 2, 3, 0.6, "On-call rotation"),
    DemoAvailability("Yara Haddad", 5, 6, 0.0, "Vacation"),
    DemoAvailability("Isabel Moreno", 2, 3, 0.0, "Security conference"),
    DemoAvailability("Nina Kowalski", 4, 6, 0.5, "Conference and workshop"),
    DemoAvailability("Kofi Boateng", 1, 2, 0.5, "Seller onboarding workshops"),
    DemoAvailability("Marco Bellini", 0, 1, 0.5, "Carrier site visit"),
    DemoAvailability("Ben Ortiz", -4, 16, 0.5, "Split between management and delivery"),
    DemoAvailability("Hana Sato", -2, 12, 0.5, "Split between management and peak readiness"),
)

# Engineer-to-project allocations. Ethan (payments + inventory + payouts) and Diego
# (performance + tracking + search) are spread too thin → cross-project over-allocation alerts.
ALLOCATIONS: tuple[tuple[str, str, float], ...] = (
    ("Rahul Verma", "ONEPAGE", 60), ("Leo Martins", "ONEPAGE", 80),
    ("Priya Shah", "ONEPAGE", 40), ("Lucia Ferreira", "ONEPAGE", 20),
    ("Sarah Chen", "ONEPAGE", 20), ("Fatou Ndiaye", "ONEPAGE", 30),
    ("Priya Shah", "PAYMENTS", 60), ("Gabriel Silva", "PAYMENTS", 50),
    ("Ethan Wu", "PAYMENTS", 50), ("Isabel Moreno", "PAYMENTS", 20),
    ("Tobias Klein", "SEARCH", 60), ("Nina Kowalski", "SEARCH", 40),
    ("Diego Ramos", "SEARCH", 20),
    ("Nina Kowalski", "RECS", 60), ("Tobias Klein", "RECS", 30),
    ("Chloe Martin", "RECS", 50),
    ("Yara Haddad", "INVENTORY", 80), ("Ethan Wu", "INVENTORY", 40),
    ("Amina Diallo", "INVENTORY", 30),
    ("Marco Bellini", "TRACKING", 100), ("Amina Diallo", "TRACKING", 50),
    ("Diego Ramos", "TRACKING", 30), ("Chloe Martin", "TRACKING", 30),
    ("Kofi Boateng", "SELLERS", 80), ("Ava Thompson", "SELLERS", 70),
    ("Victor Lindgren", "SELLERS", 50), ("Mira Patel", "SELLERS", 20),
    ("Gabriel Silva", "PAYOUTS", 50), ("Ethan Wu", "PAYOUTS", 30),
    ("Sam Adeyemi", "PEAKSCALE", 60), ("Jakub Novak", "PEAKSCALE", 50),
    ("Fatou Ndiaye", "PEAKSCALE", 40), ("Hana Sato", "PEAKSCALE", 20),
    ("Diego Ramos", "PERF", 60), ("Sam Adeyemi", "PERF", 30), ("Ava Thompson", "PERF", 30),
)


# --------------------------------------------------------------------------- #
# Org — two teams, each owning a slice of the business, with pods and seats
# --------------------------------------------------------------------------- #
TEAMS: tuple[TeamSpec, ...] = (
    TeamSpec(
        "SHOP", "Shopping Experience",
        "Owns the shopper-facing journey: the storefront, search and recommendations, "
        "checkout and payments.",
        ("Storefront", "Checkout & Payments", "Search & Discovery"),
        directors=("Arjun Mehta",), managers=("Ben Ortiz",),
    ),
    TeamSpec(
        "OPS", "Commerce Operations",
        "Owns everything after the order and the platform underneath: inventory, delivery, "
        "the marketplace and site reliability.",
        ("Orders & Inventory", "Delivery", "Marketplace", "Platform"),
        directors=("Claire Dubois",), managers=("Hana Sato",),
    ),
)


# --------------------------------------------------------------------------- #
# Initiatives
# --------------------------------------------------------------------------- #
INITIATIVES: tuple[InitiativeSpec, ...] = (
    InitiativeSpec(
        "CHECKOUT", "Checkout Modernization",
        "Make checkout fast and forgiving: lift conversion to 3.5% and halve abandonment, on a "
        "payments platform we can grow with.",
        8, "Rahul Verma", ("checkout", "payments", "conversion"), "at_risk",
        "One-page checkout is in beta; the payments migration is the critical path and now "
        "lands after the peak code freeze.",
        outcomes=(
            OutcomeSpec("Lift checkout conversion", "checkout conversion rate", "%",
                        2.8, 3.5, 3.0, "on_track", "Sarah Chen"),
            OutcomeSpec("Halve checkout abandonment", "checkout abandonment rate", "%",
                        68.0, 34.0, 55.0, "at_risk", "Lucia Ferreira"),
        ),
        risks=(
            RiskSpec("Payment provider migration slips past the peak code freeze", "schedule",
                     "high", "high", "open", "Priya Shah",
                     "Pair a second engineer on tokenization; ship full refunds only.",
                     "Keep the current provider live through peak and cut over afterwards.",
                     target_weeks=2),
        ),
        docs=(
            DocSpec("prd", "Checkout Modernization — PRD", f"{_DRIVE}/doc-prd-checkout/view",
                    "drive"),
        ),
        leads=(("Rahul Verma", "technical"), ("Sarah Chen", "product"),
               ("Lucia Ferreira", "design")),
        team_key="SHOP",
    ),
    InitiativeSpec(
        "DISCOVERY", "Search & Discovery",
        "Help shoppers find what they want: raise search conversion to 5% and personalize the "
        "home page and product pages.",
        8, "Tobias Klein", ("search", "recommendations", "ml"), "on_track",
        "Typo tolerance validated; the ranking and recommendation models are in training.",
        outcomes=(
            OutcomeSpec("Raise search conversion", "search-to-purchase conversion", "%",
                        4.1, 5.0, 4.5, "on_track", "Sarah Chen"),
            OutcomeSpec("More revenue from recommendations",
                        "revenue share from recommendation clicks", "%",
                        3.0, 8.0, 4.0, "on_track", "Nina Kowalski"),
        ),
        risks=(
            RiskSpec("Relevance tuning regresses long-tail queries", "quality", "medium",
                     "medium", "mitigating", "Tobias Klein",
                     "Track long-tail queries as their own metric in every A/B test."),
        ),
        docs=(
            DocSpec("prd", "Search & Discovery strategy", f"{_WIKI}/discovery/strategy"),
        ),
        leads=(("Tobias Klein", "technical"), ("Sarah Chen", "product"),
               ("Lucia Ferreira", "design")),
        team_key="SHOP",
    ),
    InitiativeSpec(
        "DELIVERY", "Delivery Promise",
        "Show a delivery date shoppers can trust — met for 95% of orders — and cut 'where is "
        "my order' contacts by 40%.",
        6, "Amina Diallo", ("delivery", "inventory", "customer-experience"), "at_risk",
        "Real-time inventory is on track; carrier integrations missed their milestone and the "
        "delivery-date estimator waits on them.",
        outcomes=(
            OutcomeSpec("Accurate delivery promise", "promised delivery dates met", "%",
                        88.0, 95.0, 89.0, "at_risk", "Oliver Grant"),
            OutcomeSpec("Fewer 'where is my order' contacts",
                        "contacts per 1,000 orders", "contacts",
                        42.0, 25.0, 38.0, "on_track", "Victor Lindgren"),
        ),
        risks=(
            RiskSpec("Carrier tracking feeds are unreliable", "external", "high", "high",
                     "open", "Marco Bellini",
                     "Agree webhook feeds with the three largest carriers.",
                     "Fall back to carrier-reported estimates for the long tail.",
                     target_weeks=-1),  # overdue resolution
        ),
        docs=(
            DocSpec("architecture", "Fulfilment architecture overview",
                    f"{_WIKI}/operations/fulfilment-architecture"),
        ),
        leads=(("Amina Diallo", "technical"), ("Oliver Grant", "product"),
               ("Mira Patel", "design")),
        team_key="OPS",
    ),
    InitiativeSpec(
        "MARKETPLACE", "Marketplace Launch",
        "Open the catalog to third-party sellers: 200 sellers live and 10% of GMV from the "
        "marketplace within two quarters.",
        8, "Jakub Novak", ("marketplace", "sellers", "growth"), "on_track",
        "Seller beta complete; bulk upload and the first seller payout are next.",
        outcomes=(
            OutcomeSpec("Onboard marketplace sellers", "live sellers", "sellers",
                        0.0, 200.0, 35.0, "on_track", "Oliver Grant"),
            OutcomeSpec("Grow marketplace share of GMV", "marketplace share of GMV", "%",
                        0.0, 10.0, 1.5, "pending", "Oliver Grant", target_weeks=26),
        ),
        risks=(
            RiskSpec("Seller fraud and counterfeit listings", "security", "medium", "high",
                     "mitigating", "Isabel Moreno",
                     "Identity checks for every seller and a review queue for flagged "
                     "listings."),
        ),
        docs=(
            DocSpec("prd", "Marketplace business case", f"{_WIKI}/marketplace/business-case"),
        ),
        leads=(("Jakub Novak", "technical"), ("Oliver Grant", "product"),
               ("Mira Patel", "design")),
        team_key="OPS",
    ),
    InitiativeSpec(
        "PEAK", "Holiday Peak Readiness",
        "Get through the holiday peak with zero checkout downtime and fast pages at five times "
        "normal traffic.",
        5, "Jakub Novak", ("platform", "reliability", "peak"), "at_risk",
        "3x load test passed; the waiting room and the 5x test are tight against the code "
        "freeze.",
        outcomes=(
            OutcomeSpec("Zero checkout downtime during peak", "checkout downtime in peak week",
                        "min", 95.0, 0.0, 95.0, "pending", "Jakub Novak", target_weeks=7),
            OutcomeSpec("Fast pages under peak load", "p95 page load at 5x traffic", "s",
                        3.2, 1.5, 2.4, "at_risk", "Diego Ramos", target_weeks=6),
        ),
        risks=(
            RiskSpec("Peak traffic exceeds load-tested capacity", "technical", "medium",
                     "high", "mitigating", "Sam Adeyemi",
                     "Load test at 5x and keep the waiting room in reserve.",
                     "Lower the waiting-room threshold and pause marketing emails.",
                     target_weeks=4),
        ),
        docs=(
            DocSpec("runbook", "Peak readiness checklist", f"{_DRIVE}/doc-peak-checklist/view",
                    "drive"),
        ),
        leads=(("Jakub Novak", "technical"), ("Hana Sato", "manager")),
        team_key="OPS",
    ),
)


# Cross-project hand-offs inside one initiative (drive the cross-project critical path).
CROSS_PROJECT_HANDOFFS: tuple[tuple[tuple[str, str], tuple[str, str]], ...] = (
    (("PAYMENTS", "Card tokenization API"), ("ONEPAGE", "Integrate tokenized payments")),
    (("SEARCH", "Learning-to-rank model"), ("RECS", "Recommendations API")),
    (("INVENTORY", "Availability API"), ("TRACKING", "Delivery-date estimator")),
    (("SELLERS", "Seller KYC verification"), ("PAYOUTS", "Payout account setup")),
    (("PERF", "Edge caching for product pages"), ("PEAKSCALE", "Load test at 5x")),
)

# Each scenario is a faithful clone of its initiative's live plan with a coherent set of edits
# layered on, so Compare / Capacity / Gantt / Milestones all show a real delta against live.
SCENARIOS: tuple[ScenarioSpec, ...] = (
    ScenarioSpec(
        "CHECKOUT", "Pair Rahul on tokenization to make the code freeze",
        "The payments cut-over currently lands after the peak code freeze. What if Rahul pairs "
        "with Priya on the tokenization API, refunds ship as full refunds only and the dual "
        "run is cut to one week, so the cut-over lands before the freeze?",
        "PAYMENTS", status="ready",
        added_tasks=(
            ScenarioAddedTask("Pair on tokenization edge cases", 3, "Rahul Verma",
                              after_task="Card tokenization API"),
        ),
        duration_overrides=(("Card tokenization API", 7), ("Refunds & partial captures", 3),
                            ("Dual-run reconciliation", 5)),
        allocations=(ScenarioAllocSpec("Rahul Verma", "PAYMENTS", 50, 0, 6),),
        target_weeks_delta=-2,
    ),
    ScenarioSpec(
        "DELIVERY", "Ship tracking first, dates on product pages later",
        "What if delivery dates on product pages move to next quarter and the team launches "
        "the tracking page for the top carriers first?",
        "TRACKING", status="draft",
        removed_tasks=("Show delivery date on product pages",),
        added_tasks=(
            ScenarioAddedTask("Tracking page for the top carriers", 3, "Marco Bellini",
                              after_task="Carrier tracking integrations"),
        ),
        milestone_pulls=(ScenarioMilestonePull("Tracking page live", -1),),
    ),
    ScenarioSpec(
        "PEAK", "Pre-scale for peak instead of tuning autoscaling",
        "What if we pre-scale to the traffic forecast for peak week instead of tuning "
        "autoscaling policies, and Sam's on-call week moves out of the run-up?",
        "PEAKSCALE", status="draft",
        removed_tasks=("Autoscaling policies",),
        added_tasks=(
            ScenarioAddedTask("Pre-scale for peak week", 2, "Sam Adeyemi",
                              after_task="Checkout waiting room"),
        ),
        availability=(
            ScenarioAvailSpec("Sam Adeyemi", 2, 3, 1.0, "On-call week moved after peak"),
        ),
        milestone_pulls=(ScenarioMilestonePull("5x load test passed", -1),),
        target_weeks_delta=-1,
    ),
    ScenarioSpec(
        "MARKETPLACE", "Plan around the seller team's holiday leave",
        "What if Kofi and Victor are both out in the run-up to the holidays? Model the dip and "
        "the buffer bulk upload needs to absorb it.",
        "SELLERS", status="draft",
        duration_overrides=(("Bulk listing upload", 16),),
        availability=(
            ScenarioAvailSpec("Kofi Boateng", 3, 5, 0.0, "Holiday leave"),
            ScenarioAvailSpec("Victor Lindgren", 4, 6, 0.3, "Reduced hours"),
        ),
        milestone_pulls=(ScenarioMilestonePull("100 sellers onboarded", 2),),
        target_weeks_delta=2,
    ),
    ScenarioSpec(
        "DISCOVERY", "Launch the home feed with a popular-items fallback",
        "What if the personalized home feed launches with a popular-items fallback for new "
        "shoppers, and Tobias spends more of his time on the recommendations API?",
        "RECS", status="draft",
        added_tasks=(
            ScenarioAddedTask("Popular-items fallback", 2, "Diego Ramos",
                              after_task="Recommendations API"),
        ),
        duration_overrides=(("Personalized home feed", 5),),
        allocations=(ScenarioAllocSpec("Tobias Klein", "RECS", 50, 0, 8),),
        milestone_pulls=(ScenarioMilestonePull("Home feed beta", -1),),
        target_weeks_delta=-1,
    ),
)


# Executive feedback left on specific views (USER_FLOWS §BR). Open ones roll up into the
# business review; the lead teams answer them where the work is.
LEADERSHIP_NOTES: tuple[LeadershipNoteSpec, ...] = (
    LeadershipNoteSpec(
        "CHECKOUT", "initiative", _email("elena"), "priority",
        "The payments cut-over landing after the code freeze is the biggest risk to peak. "
        "Please bring options this week, including keeping the current provider through peak.",
        priority=1, target_kind="risk",
        target_title="Payment provider migration slips past the peak code freeze",
        created_days_ago=2,
    ),
    LeadershipNoteSpec(
        "CHECKOUT", "initiative", _email("kwame"), "watch",
        "Watching the checkout GA date; the spring campaign plan builds on it.",
        target_kind="milestone", target_title="Checkout GA", created_days_ago=4,
    ),
    LeadershipNoteSpec(
        "DELIVERY", "initiative", _email("kwame"), "feedback",
        "I lean towards the conservative promise date: a date we keep beats a date that sells. "
        "Happy to look at the conversion numbers together.",
        target_kind="decision", target_title="Promise dates: conservative vs optimistic",
        created_days_ago=6, status="acknowledged",
        response="Thanks. The conversion analysis lands Thursday and we'll bring both options "
                 "to the review.",
        responder_email=_email("oliver"),
    ),
    LeadershipNoteSpec(
        "PEAK", "initiative", _email("elena"), "priority",
        "Zero checkout downtime is the one goal for peak this year. Anything that puts it at "
        "risk comes to me directly.",
        priority=1, target_kind="outcome", target_title="Zero checkout downtime during peak",
        created_days_ago=3,
    ),
    LeadershipNoteSpec(
        "DISCOVERY", "initiative", _email("kwame"), "feedback",
        "Halving zero-result searches is a great result; let's show it in the quarterly "
        "business review.",
        created_days_ago=9, status="resolved",
        response="Added to the review deck with the before and after numbers.",
        responder_email=_email("tobias"),
    ),
    LeadershipNoteSpec(
        "MARKETPLACE", "initiative", _email("kwame"), "priority",
        "Sellers keep asking about fees. Please settle the commission model before we onboard "
        "the next hundred sellers.",
        priority=2, target_kind="decision",
        target_title="Commission model: flat vs category-based", created_days_ago=2,
    ),
    LeadershipNoteSpec(
        "PAYOUTS", "project", _email("elena"), "watch",
        "Watching the first seller payout; finance wants a dry run before real money moves.",
        target_kind="milestone", target_title="First seller payout", created_days_ago=1,
    ),
    LeadershipNoteSpec(
        "TRACKING", "project", _email("claire"), "watch",
        "Keeping an eye on the carrier integrations. I can escalate with the two regional "
        "carriers if that helps.",
        created_days_ago=2,
    ),
)


def demo_connections(flagship_project_id: int) -> list[DemoConnection]:
    return [
        DemoConnection("jira", "Jira — jira.example.com", {
            "demo": True,
            "base_url": "https://jira.example.com",
            "project_id": flagship_project_id,
            "jira_project_key": "SHOP",
            "email": _email("demo"),
            "board_id": 1,
            "story_point_field": "customfield_10016",
            "epic_issue_type": "Epic",
            "story_issue_type": "Story",
        }),
        DemoConnection("github", "GitHub — example-shop/checkout", {
            "demo": True, "owner": "example-shop", "repo": "checkout",
        }),
        DemoConnection("gdrive", "Google Drive — Shop docs", {
            "demo": True, "folder_id": "demo-folder",
        }),
    ]


ECOMMERCE = Dataset(
    key="ecommerce",
    name="Online retail — e-commerce",
    description="A fictional online retailer: checkout, search, delivery, a marketplace and "
                "holiday-peak readiness (5 initiatives, 10 projects, 2 teams).",
    users=USERS, team_roles=TEAM_ROLES, engineers=ENGINEERS, availability=AVAILABILITY,
    allocations=ALLOCATIONS, initiatives=INITIATIVES, projects=PROJECTS,
    cross_project_handoffs=CROSS_PROJECT_HANDOFFS, scenarios=SCENARIOS,
    flagship_key="ONEPAGE", baseline_inflight_task="Integrate tokenized payments",
    github_repo="example-shop/checkout", jira_project_key="SHOP",
    jira_epic=("930000", "SHOP-100"),
    jira_task_keys=(("930101", "SHOP-101", "Checkout funnel analysis"),
                    ("930102", "SHOP-102", "One-page checkout UX"),
                    ("930103", "SHOP-103", "Checkout session service"),
                    ("930104", "SHOP-104", "Address & delivery step"),
                    ("930105", "SHOP-105", "Integrate tokenized payments"),
                    ("930106", "SHOP-106", "Guest checkout")),
    pull_requests=(
        PullRequestSpec(412, "Integrate tokenized card payments", "open", "priyashah",
                        "Integrate tokenized payments"),
        PullRequestSpec(415, "Handle 3-D Secure challenges in checkout", "open",
                        "gabrielsilva", "Integrate tokenized payments"),
        PullRequestSpec(398, "Checkout session service", "closed", "rahulverma",
                        "Checkout session service"),
    ),
    connections=demo_connections,
    leadership_notes=LEADERSHIP_NOTES,
    teams=TEAMS,
)
