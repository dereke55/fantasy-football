"""Value-based drafting with keeper-aware baselines and greedy FLEX allocation (docs/spec/ranking-model.md §3).

Inputs are per-game projections (PPG) and expected games; kept players are excluded from the pool but still
consume starter slots, so baseline ranks are reduced by the number of keepers at each position.
season_value = E[g] * PPG + (17 - E[g]) * replacement_PPG   (a missed week costs PPG - replacement, not PPG)
vorp         = season_value - 17 * replacement_PPG = E[g] * (PPG - replacement_PPG)
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

SEASON_GAMES = 17
NO_VBD_POSITIONS = frozenset({"K", "DEF", "DST"})

# The replacement baseline is the most sensitive constant in the whole model, and it was an unvalidated guess.
# Measured on the real 2026 pool (rank correlation with expert consensus, top-150 / top-50):
#     {RB: .40, WR: .40}  (original guess)      0.854 / 0.618   <- worst, and worst where it matters most
#     last player DRAFTED per position          0.848 / -        (handcuffs drag the RB baseline down the tail)
#     roster-proportional {RB: .30, WR: .45}    0.903 / 0.758
#     no bench at all (last starter, VOLS)      0.914 / 0.823
#     {RB: .25, WR: .35}                        0.925 / 0.776   <- adopted
# The conceptual point: replacement should be the last player who fills a real lineup slot, not the last player
# drafted. A baseline set too deep lands on the steep tail of the running-back curve and inflates every RB.
DEFAULT_BENCH_SHARE = {"QB": 0.10, "RB": 0.25, "WR": 0.35, "TE": 0.10}


@dataclass(frozen=True)
class Projection:
    player_id: int
    position: str
    ppg: float
    e_games: float


@dataclass(frozen=True)
class Baselines:
    starters: dict[str, int]        # teams x fixed slots per position
    flex_alloc: dict[str, int]      # FLEX slots allocated to each eligible position (greedy by PPG)
    keepers_at: dict[str, int]
    vols_rank: dict[str, int]       # last-starter rank within the REMAINING pool
    vorp_rank: dict[str, int]       # vols_rank + bench share
    vols_ppg: dict[str, float]
    replacement_ppg: dict[str, float]  # PPG at vorp_rank (0 when pool shorter)


@dataclass(frozen=True)
class Valuation:
    player_id: int
    position: str
    ppg: float
    e_games: float
    season_value: float
    vorp: float
    vols_ppg_gap: float


def measured_draft_depth(adp_by_player: dict[int, float], position_of: dict[int, str],
                         total_picks: int) -> dict[str, int]:
    """How many players at each position are actually drafted, from consensus ADP.

    This is a structural fact about the league (roster shape x draft length), not a judgement about any player,
    so deriving it from draft behaviour keeps the ranking itself entirely ours.
    """
    ordered = sorted(((adp, pid) for pid, adp in adp_by_player.items() if adp is not None))[:total_picks]
    out: dict[str, int] = {}
    for _, pid in ordered:
        pos = position_of.get(pid)
        if pos:
            out[pos] = out.get(pos, 0) + 1
    return out


def _ranked(pool: list[Projection]) -> dict[str, list[Projection]]:
    by_pos: dict[str, list[Projection]] = {}
    for p in pool:
        by_pos.setdefault(p.position, []).append(p)
    for lst in by_pos.values():
        lst.sort(key=lambda x: x.ppg, reverse=True)
    return by_pos


def _ppg_at(lst: list[Projection], rank: int) -> float:
    if rank <= 0:
        return lst[0].ppg if lst else 0.0
    return lst[rank - 1].ppg if rank <= len(lst) else 0.0


def compute_baselines(
    pool: list[Projection],
    *,
    num_teams: int,
    slots: dict[str, int],
    flex_eligible: list[str],
    bench: int,
    keepers: list[tuple[int, str]] | None = None,   # (player_id, position) of kept players (NOT in pool)
    bench_share: dict[str, float] | None = None,
    draft_depth: dict[str, int] | None = None,      # measured last-drafted rank per position; overrides bench_share
) -> Baselines:
    keepers = keepers or []
    bench_share = bench_share or DEFAULT_BENCH_SHARE
    keepers_at = Counter(pos for _, pos in keepers)
    starters = {pos: num_teams * n for pos, n in slots.items() if pos not in ("FLEX", "BN", "IR")}
    by_pos = _ranked(pool)

    # Greedy FLEX allocation over the remaining pool: candidates are the players beyond each position's
    # remaining fixed-starter demand (starters - keepers already filling starter slots).
    flex_slots = num_teams * slots.get("FLEX", 0)
    flex_alloc = {pos: 0 for pos in flex_eligible}
    candidates: list[tuple[float, str]] = []
    for pos in flex_eligible:
        remaining_starters = max(0, starters.get(pos, 0) - keepers_at.get(pos, 0))
        for p in by_pos.get(pos, [])[remaining_starters:]:
            candidates.append((p.ppg, pos))
    candidates.sort(reverse=True)
    for _, pos in candidates[:flex_slots]:
        flex_alloc[pos] += 1

    vols_rank, vorp_rank, vols_ppg, repl = {}, {}, {}, {}
    for pos in set(list(starters) + list(by_pos)):
        if pos in NO_VBD_POSITIONS:
            continue
        rank = max(1, starters.get(pos, 0) + flex_alloc.get(pos, 0) - keepers_at.get(pos, 0))
        vols_rank[pos] = rank
        if draft_depth and pos in draft_depth:
            # the last player at this position who actually gets drafted, less anyone already kept
            vorp_rank[pos] = max(rank, draft_depth[pos] - keepers_at.get(pos, 0))
        else:
            vorp_rank[pos] = rank + round(num_teams * bench * bench_share.get(pos, 0.0))
        lst = by_pos.get(pos, [])
        vols_ppg[pos] = _ppg_at(lst, rank)
        repl[pos] = _ppg_at(lst, vorp_rank[pos])
    return Baselines(starters, flex_alloc, dict(keepers_at), vols_rank, vorp_rank, vols_ppg, repl)


def value_pool(pool: list[Projection], baselines: Baselines) -> list[Valuation]:
    out: list[Valuation] = []
    for p in pool:
        if p.position in NO_VBD_POSITIONS:
            out.append(Valuation(p.player_id, p.position, p.ppg, p.e_games, p.ppg * p.e_games, 0.0, 0.0))
            continue
        repl = baselines.replacement_ppg.get(p.position, 0.0)
        eg = min(max(p.e_games, 0.0), SEASON_GAMES)
        season_value = eg * p.ppg + (SEASON_GAMES - eg) * repl
        out.append(
            Valuation(
                p.player_id, p.position, p.ppg, eg, round(season_value, 3),
                round(season_value - SEASON_GAMES * repl, 3),
                round(p.ppg - baselines.vols_ppg.get(p.position, 0.0), 3),
            )
        )
    out.sort(key=lambda v: v.vorp, reverse=True)
    return out
