"""Outcome progress — pure logic for 'outcomes over output'.

Progress toward the target on the baseline→target scale. Can be negative (moving the wrong way)
or >1 (overshot); the raw ratio is more honest than a clamp.
"""


def progress(
    baseline: float | None, target: float | None, current: float | None
) -> float | None:
    """(current - baseline) / (target - baseline). None when target/current are unset or the
    target equals the baseline (no movement to measure)."""
    if target is None or current is None:
        return None
    base = baseline if baseline is not None else 0.0
    denom = target - base
    if denom == 0:
        return None
    return round((current - base) / denom, 3)
