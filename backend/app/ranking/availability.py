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


def expected_best_excluding(cands: list[Candidate], at_pick: int) -> dict[int, float]:
    """E[value of the best OTHER candidate available at `at_pick`], for every candidate, in one pass.

    Calling expected_best_value() once per player is O(n^2) and the board needs this for every row. Removing one
    candidate only drops one factor from the running product, so define the tail expectation recursively --
    E_from[i] = v_i*p_i + (1-p_i)*E_from[i+1] -- and the answer for candidate k is the head sum up to k plus
    Q_k * E_from[k+1], where Q_k is the product of (1-p_j) below k. That is O(n) and, unlike dividing the factor
    back out, stays stable when a candidate is certain to be available (p -> 1 makes the divisor 0).
    """
    ordered = sorted(cands, key=lambda c: c.value, reverse=True)
    ps = [p_available(c.room_adp, c.sd_adp, at_pick) for c in ordered]
    n = len(ordered)
    e_from = [0.0] * (n + 1)
    for i in range(n - 1, -1, -1):
        e_from[i] = ordered[i].value * ps[i] + (1.0 - ps[i]) * e_from[i + 1]
    out: dict[int, float] = {}
    head, q = 0.0, 1.0
    for k in range(n):
        out[ordered[k].player_id] = head + q * e_from[k + 1]
        head += ordered[k].value * ps[k] * q
        q *= 1.0 - ps[k]
    return out


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
