"""Decision-impact analysis (pure): the blast radius of changing a set of components.

Given directed component links (source depends-on/calls target), `downstream_components`
returns everything that transitively *depends on* the seed components — i.e. would be
affected if the seeds change. Edges are (source_id, target_id); we walk them in reverse.
"""

from __future__ import annotations

from collections import deque


def downstream_components(seed_ids: set[int], edges: list[tuple[int, int]]) -> set[int]:
    """Components that (transitively) depend on any seed, excluding the seeds themselves."""
    dependents: dict[int, list[int]] = {}
    for source, target in edges:
        dependents.setdefault(target, []).append(source)

    seen: set[int] = set()
    queue: deque[int] = deque(seed_ids)
    while queue:
        node = queue.popleft()
        for dependent in dependents.get(node, []):
            if dependent not in seen:
                seen.add(dependent)
                queue.append(dependent)
    return seen - seed_ids
