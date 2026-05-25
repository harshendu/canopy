from pydantic import BaseModel


class DemoAccountRead(BaseModel):
    email: str
    full_name: str
    role: str
    function: str


class DemoStatus(BaseModel):
    """State of the demo dataset for the admin panel."""

    demo_mode: bool
    seeded: bool
    counts: dict[str, int]
    # Credentials are only populated in demo mode (a local/dev convenience, never in prod).
    password: str | None = None
    accounts: list[DemoAccountRead] = []


class DemoPublic(BaseModel):
    """Unauthenticated demo info for the login screen (empty unless demo mode is on)."""

    demo_mode: bool
    password: str | None = None
    accounts: list[DemoAccountRead] = []
