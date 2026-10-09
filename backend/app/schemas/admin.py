from pydantic import BaseModel


class FeatureGateRead(BaseModel):
    """One feature gate for the admin panel: catalog metadata + stored + effective state."""

    key: str
    label: str
    description: str
    group: str | None = None
    enabled: bool  # the stored/own toggle (default True when no row exists)
    effective: bool  # own AND group — what the app actually enforces


class FeatureGateUpdate(BaseModel):
    enabled: bool


class FeatureMap(BaseModel):
    """The effective feature map every client (React, MCP) reads to adapt its surface."""

    features: dict[str, bool]


class DemoAccountRead(BaseModel):
    email: str
    full_name: str
    role: str
    function: str


class DemoDatasetRead(BaseModel):
    """One selectable seed narrative."""

    key: str
    name: str
    description: str


class DemoStatus(BaseModel):
    """State of the demo dataset for the admin panel."""

    demo_mode: bool
    seeded: bool
    counts: dict[str, int]
    dataset: str | None = None  # the default dataset key (DEMO_DATASET) in demo mode
    datasets: list[DemoDatasetRead] = []
    # Credentials are only populated in demo mode (a local/dev convenience, never in prod).
    password: str | None = None
    accounts: list[DemoAccountRead] = []


class DemoPublic(BaseModel):
    """Unauthenticated demo info for the login screen (empty unless demo mode is on)."""

    demo_mode: bool
    password: str | None = None
    accounts: list[DemoAccountRead] = []
