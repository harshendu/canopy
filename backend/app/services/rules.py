"""Team and project rules (working agreements, Definition of Done) — docs/AGENT_EXECUTION.md §10.

Rules are stored from Phase 2; until then no Definition-of-Done item applies to a hand-off.
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Task
from app.services.stage_policy import StageDef


async def required_attestations(session: AsyncSession, task: Task, stage: StageDef) -> list[str]:
    """The Definition-of-Done rule keys a hand-off from `stage` must attest."""
    return []


async def rules_for_brief(
    session: AsyncSession, task: Task, stage: StageDef | None, role: str | None
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """(guidance, attestations) for a brief — the rules that apply to this role and task."""
    return [], []
