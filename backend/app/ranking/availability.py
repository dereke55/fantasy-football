"""Closed-form availability and VONA (docs/spec/ranking-model.md, Phase 8a).

P(available at pick m) = 1 - Phi((m - room_adp) / sd_adp), using LIVE pick numbering (keeper slots excluded).
Expected best value at my next pick (same position) = sum_i v_i * P_i * prod_{j<i}(1 - P_j) over candidates sorted by value.
VONA = value_now - expected_best_at_next_pick, weighted by my open slots (open starter -> 1.0, bench only -> 0.5).
"""
from __future__ import annotations

from dataclasses import dataclass

from scipy.stats import norm


@dataclass(frozen=True)
class Candidate:
    player_id: int
    position: str
    value: float
    room_adp: float | None   # live pick number equivalent; None = undrafted/unknown
    sd_adp: float


def p_available(room_adp: float | None, sd_adp: float, at_pick: int) -> float:
    if room_adp is None:
        return 1.0
    sd = max(sd_adp, 1.0)
    return float(1.0 - norm.cdf((at_pick - room_adp) / sd))


def expected_best_value(cands: list[Candidate], at_pick: int) -> float:
    """Expected value of the best candidate still available at `at_pick` (independence assumption)."""
    best = 0.0
    p_none_better = 1.0
    for c in sorted(cands, key=lambda x: x.value, reverse=True):
        p = p_available(c.room_adp, c.sd_adp, at_pick)
        best += c.value * p * p_none_better
        p_none_better *= 1.0 - p
        if p_none_better < 1e-6:
            break
    return best


def vona(
    player: Candidate,
    same_position_pool: list[Candidate],
    *,
    my_next_pick: int,
    slot_weight: float = 1.0,
) -> tuple[float, float, float]:
    """Returns (vona, p_available_at_next_pick, expected_best_at_next_pick)."""
    others = [c for c in same_position_pool if c.player_id != player.player_id]
    exp_best = expected_best_value(others, my_next_pick)
    p_av = p_available(player.room_adp, player.sd_adp, my_next_pick)
    return round(slot_weight * (player.value - exp_best), 3), round(p_av, 4), round(exp_best, 3)
