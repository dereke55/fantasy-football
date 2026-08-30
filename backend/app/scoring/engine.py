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


def bonus_points(stat_line: Mapping[str, float | None], scoring: Scoring) -> float:
    """Yardage-threshold bonus for ONE GAME.

    Yahoo models each threshold as its own stat category, so a 425-yard passing game fires the 350, 400 and 425
    bonuses (1 + 2 + 3). Set `bonus_mode: highest` in league.yaml if the league awards only the top tier reached.
    """
    if not scoring.bonuses:
        return 0.0
    if scoring.bonus_mode == "highest":
        best: dict[str, tuple[float, float]] = {}
        for b in scoring.bonuses:
            v = stat_line.get(b.stat)
            if v is not None and float(v) >= b.threshold:
                cur = best.get(b.stat)
                if cur is None or b.threshold > cur[0]:
                    best[b.stat] = (b.threshold, b.points)
        return sum(p for _, p in best.values())
    return sum(b.points for b in scoring.bonuses
               if (v := stat_line.get(b.stat)) is not None and float(v) >= b.threshold)


def score(stat_line: Mapping[str, float | None], scoring: Scoring, position: str | None = None,
          *, include_bonuses: bool = True) -> float:
    """Fantasy points for one stat line under `scoring` (position overrides applied when given).

    IMPORTANT: the yardage bonuses are PER GAME. Pass `include_bonuses=False` when scoring a season-total stat
    line (a projection), otherwise a 1,200-yard rushing season would collect the 200-yard game bonus once.
    `app.scoring.bonuses.season_bonus_points` estimates the season bonus from real weekly history instead.
    """
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
    if include_bonuses:
        total += bonus_points(stat_line, scoring)
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
    if scoring.bonus_mode == "highest":
        keep = {}
        for k, v in out.items():
            if not k.startswith("bonus:"):
                keep[k] = v
        for b_stat in {b.stat for b in scoring.bonuses}:
            fired = {k: v for k, v in out.items() if k.startswith(f"bonus:{b_stat}>=")}
            if fired:
                top = max(fired.items(), key=lambda kv: float(kv[0].split(">=")[1]))
                keep[top[0]] = top[1]
        return keep
    return out
