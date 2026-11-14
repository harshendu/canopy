"""Proposal plan preview: the plan as a whole, **before vs after** a staged proposal.

The review queue used to show a proposal only as a list of field diffs — the reviewer had to
imagine what "duration 5 → 8" does to everything downstream. This module answers the
question they actually have: *what does my plan look like if I apply this?*

It is a **pure simulation** — nothing is written. The staged items (minus the ones the
reviewer excluded, with their inline overrides layered on) are replayed onto an in-memory
copy of the live tasks / dependencies / milestones, then both graphs go through the *same*
scheduler a real apply uses (`planner.compute_schedule` + `rollup_summaries`). So:

- `current` is the live plan **recomputed** — what a replan would give right now. Every
  difference from `proposed` is therefore the proposal's doing, never a stale saved schedule
  (when the saved schedule *was* stale, the project says so: `live_schedule_stale`).
- `proposed` is what apply + auto-replan will produce. A task the proposal creates has no id
  yet, so it carries a synthetic negative one (`-item_id`).

Each task that differs is classified `added` (the proposal creates it), `edited` (an item
targets it) or `shifted` (it only moves as a knock-on effect) — the three things a reviewer
needs to tell apart at a glance.

Layout: dataclasses + pure functions first (unit-tested without a database), then the
single async loader `build_proposal_preview` the API calls.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col, select

from app.models.base import (
    DependencyType,
    ProposalAction,
    ProposalEntity,
    ProposalScope,
    TaskType,
)
from app.models.project import Dependency, Holiday, Milestone, Project, Task
from app.models.proposal import Proposal
from app.models.team import Engineer
from app.schemas.entities import GanttLink, GanttResponse, GanttTask
from app.schemas.proposal import (
    MilestoneChangeKind,
    PreviewCounts,
    PreviewDeadlineMiss,
    PreviewIssue,
    PreviewMilestone,
    PreviewTaskChange,
    ProjectPlanPreview,
    ProposalPreview,
    TaskChangeKind,
)
from app.services import proposals as proposal_svc
from app.services.planner import (
    RollupNode,
    SchedInput,
    compute_schedule,
    effective_duration,
    infer_project_start,
    rollup_summaries,
    schedule_outcome,
)
from app.services.scheduling import CycleError, SchedDep, WorkingCalendar

# --------------------------------------------------------------------------- #
# Inputs (decoupled from the ORM so the simulation is pure)
# --------------------------------------------------------------------------- #


@dataclass
class SimTask:
    id: int  # live id; a staged create gets a synthetic negative id (-item_id)
    project_id: int
    name: str
    type: TaskType
    parent_id: int | None
    duration: int
    # The last *saved* schedule. Seeds project-start inference and is what a childless
    # summary keeps showing — the simulation recomputes everything else.
    start: date | None
    end: date | None
    constraint_start: date | None
    deadline: date | None
    percent_complete: float
    assignee_engineer_id: int | None


@dataclass
class SimDep:
    id: int  # synthetic negative id for a staged dependency
    predecessor_id: int
    successor_id: int
    type: DependencyType
    lag: int


@dataclass
class SimMilestone:
    id: int  # synthetic negative id for a staged milestone
    project_id: int
    name: str
    target_date: date | None
    status: str


@dataclass
class SimItem:
    """The slice of a proposal item the simulation needs. `fields` is the *effective* payload
    (reviewer overrides applied), validated and type-coerced."""

    id: int
    entity_type: ProposalEntity
    action: ProposalAction
    entity_id: int | None
    ref: str | None
    fields: dict[str, Any]


@dataclass
class SimProject:
    id: int
    key: str
    name: str
    start_date: date | None
    calendar: WorkingCalendar


@dataclass
class StagedPlan:
    """The plan after replaying the items, plus what each item touched."""

    tasks: list[SimTask]
    deps: list[SimDep]
    milestones: list[SimMilestone]
    added_tasks: set[int] = field(default_factory=set)
    edited_tasks: set[int] = field(default_factory=set)
    added_milestones: set[int] = field(default_factory=set)
    edited_milestones: set[int] = field(default_factory=set)
    task_items: dict[int, list[int]] = field(default_factory=dict)
    milestone_items: dict[int, list[int]] = field(default_factory=dict)
    touched_projects: set[int] = field(default_factory=set)
    counts: PreviewCounts = field(default_factory=PreviewCounts)


@dataclass
class _Row:
    """One task's computed place in a schedule."""

    start: date | None
    end: date | None
    is_critical: bool = False
    total_float: int = 0


# The task fields a staged update can move in the simulation (the rest — description, tags,
# estimates, spec — don't change the picture the reviewer is looking at). The second group
# may be explicitly cleared with null (unassign, drop a deadline, lift a pin).
_TASK_SET_FIELDS = ("name", "percent_complete", "duration")
_TASK_CLEARABLE_FIELDS = (
    "parent_id",
    "start",
    "constraint_start",
    "deadline",
    "assignee_engineer_id",
)


# --------------------------------------------------------------------------- #
# Replaying the staged items (pure)
# --------------------------------------------------------------------------- #


def _resolve(fields: dict[str, Any], ref_key: str, id_key: str, refs: dict[str, int]) -> int | None:
    """A link expressed either as a live id or as a handle to something created earlier."""
    handle = fields.get(ref_key)
    if handle is not None:
        return refs.get(str(handle))
    value = fields.get(id_key)
    return int(value) if value is not None else None


def stage_items(
    tasks: list[SimTask],
    deps: list[SimDep],
    milestones: list[SimMilestone],
    items: list[SimItem],
) -> StagedPlan:
    """Replay `items` in order onto copies of the live plan. Never raises on bad data: an
    item whose target or ref can't be resolved is skipped (validation reports it elsewhere),
    so a half-broken proposal still previews everything that *is* coherent."""
    plan = StagedPlan(
        tasks=[replace(t) for t in tasks],
        deps=list(deps),
        milestones=[replace(m) for m in milestones],
    )
    task_by_id = {t.id: t for t in plan.tasks}
    milestone_by_id = {m.id: m for m in plan.milestones}
    refs: dict[str, int] = {}
    counts: Counter[str] = Counter()

    def touch_task(task_id: int, item_id: int) -> None:
        plan.task_items.setdefault(task_id, []).append(item_id)

    for item in items:
        entity, action, f = item.entity_type, item.action, item.fields
        create = action == ProposalAction.create

        if entity == ProposalEntity.task and create:
            parent_id = _resolve(f, "parent_ref", "parent_id", refs)
            if f.get("parent_ref") is not None and parent_id is None:
                continue
            project_id = f.get("project_id")
            if project_id is None:
                continue
            new = SimTask(
                id=-item.id,
                project_id=int(project_id),
                name=str(f.get("name") or ""),
                type=TaskType(str(f.get("type") or TaskType.task.value)),
                parent_id=parent_id,
                duration=int(f.get("duration") or 0),
                start=f.get("start"),
                end=f.get("end"),
                constraint_start=f.get("constraint_start"),
                deadline=f.get("deadline"),
                percent_complete=float(f.get("percent_complete") or 0.0),
                assignee_engineer_id=f.get("assignee_engineer_id"),
            )
            plan.tasks.append(new)
            task_by_id[new.id] = new
            plan.added_tasks.add(new.id)
            plan.touched_projects.add(new.project_id)
            touch_task(new.id, item.id)
            if item.ref:
                refs[item.ref] = new.id
            counts["tasks_added"] += 1

        elif entity == ProposalEntity.task:
            target = task_by_id.get(item.entity_id or 0)
            if target is None:
                continue
            for key in _TASK_SET_FIELDS:
                if f.get(key) is not None:
                    setattr(target, key, f[key])
            for key in _TASK_CLEARABLE_FIELDS:
                if key in f:
                    setattr(target, key, f[key])
            plan.edited_tasks.add(target.id)
            plan.touched_projects.add(target.project_id)
            touch_task(target.id, item.id)
            counts["tasks_edited"] += 1

        elif entity == ProposalEntity.dependency:
            pred = _resolve(f, "predecessor_ref", "predecessor_id", refs)
            succ = _resolve(f, "successor_ref", "successor_id", refs)
            if pred is None or succ is None or pred not in task_by_id or succ not in task_by_id:
                continue
            plan.deps.append(
                SimDep(
                    id=-item.id,
                    predecessor_id=pred,
                    successor_id=succ,
                    type=DependencyType(str(f.get("type") or DependencyType.FS.value)),
                    lag=int(f.get("lag") or 0),
                )
            )
            # The successor is the task a new dependency moves — link the item to its row.
            touch_task(succ, item.id)
            plan.touched_projects.update(
                {task_by_id[pred].project_id, task_by_id[succ].project_id}
            )
            counts["dependencies_added"] += 1

        elif entity == ProposalEntity.milestone and create:
            project_id = f.get("project_id")
            if project_id is None:
                continue
            staged = SimMilestone(
                id=-item.id,
                project_id=int(project_id),
                name=str(f.get("name") or ""),
                target_date=f.get("target_date"),
                status=str(f.get("status") or "planned"),
            )
            plan.milestones.append(staged)
            milestone_by_id[staged.id] = staged
            plan.added_milestones.add(staged.id)
            plan.milestone_items.setdefault(staged.id, []).append(item.id)
            plan.touched_projects.add(staged.project_id)
            counts["milestones_added"] += 1

        elif entity == ProposalEntity.milestone:
            milestone = milestone_by_id.get(item.entity_id or 0)
            if milestone is None:
                continue
            if "name" in f and f["name"] is not None:
                milestone.name = str(f["name"])
            if "target_date" in f:
                milestone.target_date = f["target_date"]
            if "status" in f and f["status"] is not None:
                milestone.status = str(f["status"])
            plan.edited_milestones.add(milestone.id)
            plan.milestone_items.setdefault(milestone.id, []).append(item.id)
            plan.touched_projects.add(milestone.project_id)
            counts["milestones_edited"] += 1

        elif entity == ProposalEntity.blocker and create:
            task_id = _resolve(f, "task_ref", "task_id", refs)
            if task_id is not None and task_id in task_by_id:
                touch_task(task_id, item.id)
            counts["blockers_raised"] += 1

        elif entity == ProposalEntity.blocker:
            counts["blockers_resolved"] += 1
        elif entity == ProposalEntity.risk:
            counts["risks_added" if create else "risks_edited"] += 1
        elif entity == ProposalEntity.outcome:
            counts["outcomes_added" if create else "outcomes_edited"] += 1
        elif entity == ProposalEntity.decision:
            counts["decisions_added"] += 1
        elif entity == ProposalEntity.doc_reference:
            counts["docs_added"] += 1

    plan.counts = PreviewCounts(**counts)
    return plan


# --------------------------------------------------------------------------- #
# Scheduling one project's graph (pure)
# --------------------------------------------------------------------------- #


def schedule_graph(
    project: SimProject, tasks: list[SimTask], deps: list[SimDep]
) -> tuple[dict[int, _Row], date | None, list[int]]:
    """Run the real scheduler over one project's tasks (project-local, exactly like
    `reschedule_project`: cross-project edges are ignored). Returns the per-task rows, the
    project finish, and the ids whose finish overruns their deadline. Raises CycleError."""
    ids = {t.id for t in tasks}
    inputs = [
        SchedInput(
            task_id=t.id,
            duration=effective_duration(t.type, t.duration),
            type=t.type,
            parent_id=t.parent_id,
            pinned_start=t.constraint_start,
            deadline=t.deadline,
        )
        for t in tasks
    ]
    sched_deps = [
        SchedDep(d.predecessor_id, d.successor_id, d.type.value, d.lag)
        for d in deps
        if d.predecessor_id in ids and d.successor_id in ids
    ]
    start_ref = infer_project_start(project.start_date, [t.start for t in tasks if t.start])
    results = compute_schedule(
        inputs, sched_deps, project_start=start_ref, calendar=project.calendar
    )
    project_end, violations = schedule_outcome(inputs, results)

    rows: dict[int, _Row] = {}
    for t in tasks:
        res = results.get(t.id)
        if res is not None:
            rows[t.id] = _Row(res.start, res.end, res.is_critical, res.total_float)
        else:  # a summary: spans its children (below); childless keeps its saved dates
            rows[t.id] = _Row(t.start, t.end)
    rolled = rollup_summaries(
        [
            RollupNode(
                id=t.id,
                parent_id=t.parent_id,
                is_summary=t.type == TaskType.summary,
                start=rows[t.id].start,
                end=rows[t.id].end,
            )
            for t in tasks
        ]
    )
    for task_id, (start, end) in rolled.items():
        rows[task_id] = _Row(start, end)
    return rows, project_end, violations


def wbs_order(tasks: list[SimTask]) -> list[SimTask]:
    """Depth-first WBS order: each phase followed by its children. Live tasks keep their id
    order and staged ones follow in staging order — so a new task appears under its phase
    and a row never jumps when the reviewer toggles current ↔ proposed."""
    ids = {t.id for t in tasks}

    def rank(t: SimTask) -> tuple[int, int]:
        return (0, t.id) if t.id > 0 else (1, -t.id)

    children: dict[int | None, list[SimTask]] = {}
    for t in tasks:
        parent = t.parent_id if t.parent_id in ids else None
        children.setdefault(parent, []).append(t)
    ordered: list[SimTask] = []
    seen: set[int] = set()

    def walk(parent: int | None) -> None:
        for t in sorted(children.get(parent, []), key=rank):
            if t.id in seen:
                continue
            seen.add(t.id)
            ordered.append(t)
            walk(t.id)

    walk(None)
    # Anything unreachable from a root (a parent cycle) still gets a row.
    ordered.extend(t for t in sorted(tasks, key=rank) if t.id not in seen)
    return ordered


def _gantt(
    project_id: int,
    tasks: list[SimTask],
    deps: list[SimDep],
    rows: dict[int, _Row],
    engineer_names: dict[int, str],
) -> GanttResponse:
    ids = {t.id for t in tasks}
    gantt_tasks = []
    for t in wbs_order(tasks):
        row = rows[t.id]
        # A phase's duration is its span, as the planner persists it.
        duration = t.duration
        if t.type == TaskType.summary and row.start and row.end:
            duration = (row.end - row.start).days
        gantt_tasks.append(
            GanttTask(
                id=t.id,
                text=t.name,
                start_date=row.start,
                end_date=row.end,
                baseline_start=None,
                baseline_end=None,
                deadline=t.deadline,
                duration=duration,
                progress=round(t.percent_complete / 100.0, 4),
                parent=t.parent_id or 0,
                type=t.type,
                is_critical=row.is_critical,
                total_float=row.total_float,
                assignee_engineer_id=t.assignee_engineer_id,
                assignee_name=(
                    engineer_names.get(t.assignee_engineer_id)
                    if t.assignee_engineer_id is not None
                    else None
                ),
            )
        )
    links = [
        GanttLink(id=d.id, source=d.predecessor_id, target=d.successor_id, type=d.type, lag=d.lag)
        for d in deps
        if d.predecessor_id in ids and d.successor_id in ids
    ]
    return GanttResponse(project_id=project_id, tasks=gantt_tasks, links=links)


def _days(before: date | None, after: date | None) -> int | None:
    return (after - before).days if before and after else None


def _milestone_rows(
    project_id: int, live: list[SimMilestone], plan: StagedPlan
) -> list[PreviewMilestone]:
    before = {m.id: m for m in live if m.project_id == project_id}
    out: list[PreviewMilestone] = []
    for m in plan.milestones:
        if m.project_id != project_id:
            continue
        was = before.get(m.id)
        kind: MilestoneChangeKind
        if m.id in plan.added_milestones:
            kind = "added"
        elif was is not None and (
            was.target_date != m.target_date or was.status != m.status or was.name != m.name
        ):
            kind = "edited"
        else:
            kind = "unchanged"
        out.append(
            PreviewMilestone(
                milestone_id=m.id,
                name=m.name,
                kind=kind,
                item_ids=plan.milestone_items.get(m.id, []),
                target_before=was.target_date if was else None,
                target_after=m.target_date,
                status_before=was.status if was else None,
                status_after=m.status,
            )
        )
    out.sort(key=lambda r: (r.target_after or date.max, r.name))
    return out


def preview_project(
    project: SimProject,
    live_tasks: list[SimTask],
    live_deps: list[SimDep],
    live_milestones: list[SimMilestone],
    plan: StagedPlan,
    engineer_names: dict[int, str],
) -> ProjectPlanPreview:
    """Schedule one project's live graph and its staged graph, and diff them. Pure."""
    now_tasks = [t for t in live_tasks if t.project_id == project.id]
    next_tasks = [t for t in plan.tasks if t.project_id == project.id]

    # A cycle in the *live* graph is the plan's own problem, not the proposal's — fall back
    # to the saved dates so the reviewer still sees something.
    try:
        now_rows, end_now, miss_now = schedule_graph(project, now_tasks, live_deps)
    except CycleError:
        now_rows = {t.id: _Row(t.start, t.end) for t in now_tasks}
        end_now, miss_now = None, []
    current = _gantt(project.id, now_tasks, live_deps, now_rows, engineer_names)

    stale = any(
        (now_rows[t.id].start, now_rows[t.id].end) != (t.start, t.end)
        for t in now_tasks
        if t.type != TaskType.summary
    )
    result = ProjectPlanPreview(
        project_id=project.id,
        key=project.key,
        name=project.name,
        current=current,
        end_current=end_now,
        critical_current=sum(1 for r in now_rows.values() if r.is_critical),
        milestones=_milestone_rows(project.id, live_milestones, plan),
        live_schedule_stale=stale,
    )

    try:
        next_rows, end_next, miss_next = schedule_graph(project, next_tasks, plan.deps)
    except CycleError:
        result.cycle = True
        return result

    result.proposed = _gantt(project.id, next_tasks, plan.deps, next_rows, engineer_names)
    result.end_proposed = end_next
    result.end_delta_days = _days(end_now, end_next)
    result.critical_proposed = sum(1 for r in next_rows.values() if r.is_critical)

    for t in wbs_order(next_tasks):
        was, will = now_rows.get(t.id), next_rows[t.id]
        kind: TaskChangeKind
        if t.id in plan.added_tasks:
            kind = "added"
        elif t.id in plan.edited_tasks:
            kind = "edited"
        elif was is not None and (was.start, was.end) != (will.start, will.end):
            kind = "shifted"
        else:
            continue
        result.task_changes.append(
            PreviewTaskChange(
                task_id=t.id,
                name=t.name,
                kind=kind,
                is_summary=t.type == TaskType.summary,
                item_ids=plan.task_items.get(t.id, []),
                start_before=was.start if was else None,
                start_after=will.start,
                end_before=was.end if was else None,
                end_after=will.end,
                end_delta_days=_days(was.end if was else None, will.end),
                critical_before=was.is_critical if was else False,
                critical_after=will.is_critical,
            )
        )

    already_missed = set(miss_now)
    by_id = {t.id: t for t in next_tasks}
    for task_id in miss_next:
        task, row = by_id[task_id], next_rows[task_id]
        if task_id not in already_missed and task.deadline and row.end:
            result.new_deadline_misses.append(
                PreviewDeadlineMiss(
                    task_id=task_id, name=task.name, deadline=task.deadline, end=row.end
                )
            )
    return result


# --------------------------------------------------------------------------- #
# Loader (the one impure function)
# --------------------------------------------------------------------------- #


async def build_proposal_preview(session: AsyncSession, proposal: Proposal) -> ProposalPreview:
    """Simulate applying the proposal's included items and report the plan before vs after,
    together with whether an apply would currently succeed (and why not). Read-only."""
    assert proposal.id is not None
    all_items = await proposal_svc.load_items(session, proposal)
    included = [i for i in all_items if not i.excluded]

    issues: list[PreviewIssue] = []
    invalid: set[int] = set()
    # `check_items` normalises each payload in place (scope defaults — a no-op for a staged
    # item); keep that from being flushed by the reads below.
    with session.no_autoflush:
        found = await proposal_svc.check_items(
            session, proposal.scope_level, proposal.scope_id, included
        )
    for issue in found:
        item = included[issue.index]
        if item.id is not None:
            invalid.add(item.id)
        issues.append(PreviewIssue(item_id=item.id, error=issue.error))

    sim_items: list[SimItem] = []
    for item in included:
        if item.id is None or item.id in invalid:
            continue
        try:
            fields = proposal_svc.coerced_fields(item)
        except ValueError:
            continue
        sim_items.append(
            SimItem(
                id=item.id,
                entity_type=item.entity_type,
                action=item.action,
                entity_id=item.entity_id,
                ref=item.ref,
                fields=fields,
            )
        )

    if proposal.scope_level == ProposalScope.project:
        project_rows = [await session.get(Project, proposal.scope_id)]
    else:
        project_rows = list(
            (
                await session.execute(
                    select(Project)
                    .where(Project.initiative_id == proposal.scope_id)
                    .order_by(col(Project.id))
                )
            )
            .scalars()
            .all()
        )
    projects = [p for p in project_rows if p is not None and p.id is not None]
    project_ids = [p.id for p in projects if p.id is not None]

    with session.no_autoflush:
        task_rows = (
            (await session.execute(select(Task).where(col(Task.project_id).in_(project_ids))))
            .scalars()
            .all()
        )
        task_ids = [t.id for t in task_rows if t.id is not None]
        dep_rows = (
            (
                await session.execute(
                    select(Dependency).where(col(Dependency.successor_id).in_(task_ids))
                )
            )
            .scalars()
            .all()
        )
        holiday_rows = (
            (await session.execute(select(Holiday).where(col(Holiday.project_id).in_(project_ids))))
            .scalars()
            .all()
        )
        milestone_rows = (
            (
                await session.execute(
                    select(Milestone).where(col(Milestone.project_id).in_(project_ids))
                )
            )
            .scalars()
            .all()
        )
        engineer_names = {
            e.id: e.name
            for e in (await session.execute(select(Engineer))).scalars().all()
            if e.id is not None
        }

    live_tasks = [
        SimTask(
            id=t.id,
            project_id=t.project_id,
            name=t.name,
            type=t.type,
            parent_id=t.parent_id,
            duration=t.duration,
            start=t.start,
            end=t.end,
            constraint_start=t.constraint_start,
            deadline=t.deadline,
            percent_complete=t.percent_complete,
            assignee_engineer_id=t.assignee_engineer_id,
        )
        for t in task_rows
        if t.id is not None
    ]
    known = set(task_ids)
    live_deps = [
        SimDep(d.id, d.predecessor_id, d.successor_id, d.type, d.lag)
        for d in dep_rows
        if d.id is not None and d.predecessor_id in known
    ]
    live_milestones = [
        SimMilestone(m.id, m.project_id, m.name, m.target_date, m.status)
        for m in milestone_rows
        if m.id is not None
    ]
    holidays: dict[int, set[date]] = {}
    for h in holiday_rows:
        holidays.setdefault(h.project_id, set()).add(h.day)

    plan = stage_items(live_tasks, live_deps, live_milestones, sim_items)

    previews: list[ProjectPlanPreview] = []
    shifted = 0
    for p in projects:
        assert p.id is not None
        # An initiative-wide proposal previews only the projects it actually reaches.
        if proposal.scope_level == ProposalScope.initiative and p.id not in plan.touched_projects:
            continue
        sim_project = SimProject(
            id=p.id,
            key=p.key,
            name=p.name,
            start_date=p.start_date,
            calendar=WorkingCalendar(
                weekend=frozenset({5, 6}) if p.skip_weekends else frozenset(),
                holidays=frozenset(holidays.get(p.id, set())),
            ),
        )
        view = preview_project(
            sim_project, live_tasks, live_deps, live_milestones, plan, engineer_names
        )
        if view.cycle:
            issues.append(
                PreviewIssue(
                    project_id=p.id,
                    error=f"These changes would create a dependency cycle in {p.key}.",
                )
            )
        shifted += sum(1 for c in view.task_changes if c.kind == "shifted" and not c.is_summary)
        previews.append(view)

    counts = plan.counts.model_copy(update={"tasks_shifted": shifted})
    return ProposalPreview(
        proposal_id=proposal.id,
        revision=proposal.revision,
        included=len(included),
        excluded=len(all_items) - len(included),
        can_apply=bool(included) and not issues,
        issues=issues,
        counts=counts,
        projects=previews,
    )
