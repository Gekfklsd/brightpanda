"""Overconfidence guards. Pure functions, tested in tests/test_guards.py."""

from __future__ import annotations

from . import config


def clamp_binary(p: float, floor: float = config.BINARY_FLOOR, ceiling: float = config.BINARY_CEILING) -> float:
    """Keep a probability inside [floor, ceiling]. Rejects nonsense."""
    p = float(p)
    if p != p:  # NaN
        raise ValueError("probability is NaN")
    return max(floor, min(ceiling, p))


def floor_options(probs: dict[str, float], floor: float = config.OPTION_FLOOR) -> dict[str, float]:
    """Give every option at least `floor`, then make them sum to 1.

    Done by mixing with the uniform spread, so the order of options never changes
    and no option can fall below the floor after normalising.
    """
    if not probs:
        raise ValueError("no options")
    n = len(probs)
    if floor * n >= 1:
        raise ValueError("floor too high for this many options")
    total = sum(max(0.0, float(v)) for v in probs.values())
    if total <= 0:
        return {k: 1.0 / n for k in probs}
    norm = {k: max(0.0, float(v)) / total for k, v in probs.items()}
    low = min(norm.values())
    if low >= floor:
        return norm
    # smallest mix with uniform that lifts the lowest option to the floor
    w = (floor - low) / (1.0 / n - low)
    return {k: (1 - w) * v + w / n for k, v in norm.items()}
