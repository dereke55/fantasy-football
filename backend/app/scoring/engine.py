"""Apply league scoring to a stat line. This is the ONLY place fantasy points are computed.

A stat line is a mapping of internal stat keys (see config.STAT_KEYS) to counts/yards. Adapters in `adapters.py`
translate upstream rows (nflverse weekly stats, ff_opportunity expected stats, Sleeper projections) into stat lines.

Yahoo semantics implemented:
- uses_fractional_points=False: yardage points are awarded in whole increments (e.g. 0.04/yd == 1 pt per 25 yds -> 24 yds = 0).
- uses_negative_points=False: a player's total for the period is floored at 0.
"""
from __future__ import annotations

import math
from collections.abc import Mapping

from app.scoring.config import STAT_KEYS, YARDAGE_KEYS, Scoring


def _yardage_points(yards: float, per_yard: float, fractional: bool) -> float:
    if per_yard == 0 or yards == 0:
        return 0.0
    if fractional:
        return yards * per_yard
    yards_per_point = 1.0 / abs(per_yard)
    whole = math.floor(abs(yards) / yards_per_point + 1e-9)
    return math.copysign(whole, yards) * math.copysign(1.0, per_yard)


def score(stat_line: Mapping[str, float | None], scoring: Scoring, position: str | None = None) -> float:
    """Fantasy points for one stat line under `scoring` (position overrides applied when given)."""
    w = scoring.weights_for(position)
    total = 0.0
    for key in STAT_KEYS:
        v = stat_line.get(key)
        if v is None or v == 0:
            continue
        if key in YARDAGE_KEYS:
            total += _yardage_points(float(v), w[key], scoring.uses_fractional_points)
        else:
            total += float(v) * w[key]
    for b in scoring.bonuses:
        v = stat_line.get(b.stat)
        if v is not None and float(v) >= b.threshold:
            total += b.points
    if not scoring.uses_negative_points and total < 0:
        total = 0.0
    return round(total, 4)


def breakdown(stat_line: Mapping[str, float | None], scoring: Scoring, position: str | None = None) -> dict[str, float]:
    """Per-stat contribution (for WHY bullets and debugging); sums to score() before the negative-points floor."""
    w = scoring.weights_for(position)
    out: dict[str, float] = {}
    for key in STAT_KEYS:
        v = stat_line.get(key)
        if v is None or v == 0:
            continue
        pts = _yardage_points(float(v), w[key], scoring.uses_fractional_points) if key in YARDAGE_KEYS else float(v) * w[key]
        if pts:
            out[key] = round(pts, 4)
    for b in scoring.bonuses:
        v = stat_line.get(b.stat)
        if v is not None and float(v) >= b.threshold:
            out[f"bonus:{b.stat}>={b.threshold:g}"] = b.points
    return out
