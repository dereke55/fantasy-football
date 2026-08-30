"""Adjustments that apply ONLY to the in-house projection component, plus expected games (docs/spec/ranking-model.md §2, Phase 3)."""
from __future__ import annotations

SEASON_GAMES = 17

# Age year-over-year step factors (age at 2026-09-10)
AGE_STEPS = {
    "RB": [(27, 1.00), (28, 0.97), (29, 0.92), (30, 0.85), (200, 0.78)],
    "WR": [(23, 1.05), (29, 1.00), (31, 0.96), (200, 0.88)],
    "TE": [(25, 1.03), (31, 1.00), (200, 0.93)],
    "QB": [(35, 1.00), (200, 0.95)],
}
AGE_CLIFF = {"RB": 29, "WR": 31, "TE": 32}

# Expected games MISSED per season by position and ADP band (rounds 1-2 / 3-5 / 6-8+). RB/WR from the plan's
# verified base rates (Rotobanter 2021-2025); QB/TE are documented assumptions (docs/decisions.md).
BASE_MISSED = {
    "RB": (2.4, 3.3, 3.8),
    "WR": (2.2, 2.8, 3.3),
    "TE": (2.0, 2.6, 3.2),
    "QB": (1.5, 2.0, 2.5),
}


def age_factor(position: str, age: float | None) -> float:
    if age is None or position not in AGE_STEPS:
        return 1.0
    for max_age, f in AGE_STEPS[position]:
        if age <= max_age:
            return f
    return 1.0


def age_cliff(position: str, age: float | None) -> bool:
    return age is not None and position in AGE_CLIFF and age >= AGE_CLIFF[position]


def adp_band(adp_round: float | None) -> int:
    if adp_round is None:
        return 2
    if adp_round <= 2:
        return 0
    if adp_round <= 5:
        return 1
    return 2


def expected_games(
    position: str,
    *,
    adp_round: float | None,
    hist_missed: int | None,
    hist_eligible: int | None,
    known_missed_weeks: int = 0,
) -> tuple[float, dict]:
    """E[games] = min(17 - known_missed, 17 - (base_missed + 1.0 per 20% of historical miss rate above base)).
    Returns (e_games, details) where details feed the WHY bullet."""
    base = BASE_MISSED.get(position, BASE_MISSED["WR"])[adp_band(adp_round)]
    hist_rate = None
    extra = 0.0
    if hist_missed is not None and hist_eligible:
        hist_rate = hist_missed / hist_eligible
        base_rate = base / SEASON_GAMES
        if hist_rate > base_rate:
            extra = (hist_rate - base_rate) / 0.20 * 1.0
    expected_missed = base + extra
    e_games = min(SEASON_GAMES - known_missed_weeks, SEASON_GAMES - expected_missed)
    e_games = max(0.0, min(float(SEASON_GAMES), e_games))
    return round(e_games, 2), {
        "base_missed": base, "hist_rate": None if hist_rate is None else round(hist_rate, 3),
        "extra_missed": round(extra, 2), "known_missed_weeks": known_missed_weeks,
    }
