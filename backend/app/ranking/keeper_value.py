"""Keeper-value helper (plan: Phase 9 "keeper value"; pulled forward to day 2 for the Aug 31 deadline).

    keeper_surplus(player, cost_round) = VORP(player) - E[VORP of the best player still available at that pick]

The alternative use of a keeper slot is the pick it consumes, so the comparison is against the best player expected
to survive to that pick under room ADP (availability model from app.ranking.availability, closed form).

Because a keeper is removed from the pool before anyone drafts, the pick it costs is a real pick: in Yahoo the
team is skipped in that round (app.ranking.pick_schedule marks the hole). The draft slot may be unknown, in which
case every slot is evaluated and the mean/min/max reported.

`break_even_round` is the earliest round at which keeping the player is still worth more than the pick it costs:
keep the player if his cost round is >= break_even_round.
"""
from __future__ import annotations

import polars as pl

from app.config import settings
from app.ranking.availability import Candidate, expected_best_value
from app.ranking.pick_schedule import build_pick_schedule
from app.ranking.projections import projection_pool
from app.ranking.room_adp import room_adp
from app.ranking.vbd import Projection, compute_baselines, value_pool
from app.scoring.config import LeagueConfig, load_league_config


def _pool_with_values(cfg: LeagueConfig, kept: set[int] | None = None) -> pl.DataFrame:
    """Projection pool + VBD values, with kept players excluded from the pool but counted against the baselines."""
    kept = kept or set()
    pool_df = projection_pool(cfg)
    kept_rows = pool_df.filter(pl.col("player_id").is_in(list(kept)))
    open_df = pool_df.filter(~pl.col("player_id").is_in(list(kept)))
    projections = [
        Projection(r["player_id"], r["position"], r["vendor_ppg"], r["e_games"])
        for r in open_df.to_dicts()
    ]
    baselines = compute_baselines(
        projections,
        num_teams=cfg.league.num_teams,
        slots=cfg.roster.slots,
        flex_eligible=cfg.roster.flex_eligible,
        bench=cfg.roster.bench,
        keepers=[(r["player_id"], r["position"]) for r in kept_rows.to_dicts()],
    )
    vals = {v.player_id: v for v in value_pool(projections, baselines)}
    # value the kept players against the same baselines so their VORP is comparable
    for r in kept_rows.to_dicts():
        for v in value_pool([Projection(r["player_id"], r["position"], r["vendor_ppg"], r["e_games"])], baselines):
            vals[v.player_id] = v
    return pool_df.with_columns(
        vorp=pl.col("player_id").map_elements(lambda i: vals[i].vorp if i in vals else None, return_dtype=pl.Float64),
        season_value=pl.col("player_id").map_elements(
            lambda i: vals[i].season_value if i in vals else None, return_dtype=pl.Float64),
    )


def _room_candidates(pool: pl.DataFrame, kept: set[int]) -> list[Candidate]:
    adp = {r["player_id"]: r["composite_adp"] for r in pool.to_dicts() if r["composite_adp"] is not None}
    room = room_adp(adp, kept)
    out = []
    for r in pool.to_dicts():
        if r["player_id"] in kept or r["vorp"] is None:
            continue
        out.append(Candidate(r["player_id"], r["position"], max(0.0, r["vorp"]),
                             room.get(r["player_id"]), r["sd_adp"] or 10.0))
    return out


def round_pick_numbers(cfg: LeagueConfig, slot: int | None) -> dict[int, list[int]]:
    """round -> the live pick number(s) that round costs, for the given slot or for every slot."""
    slots = [slot] if slot else list(range(1, cfg.league.num_teams + 1))
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds)
    out: dict[int, list[int]] = {}
    for s in sched:
        if s.team_slot in slots and s.live_pick_no is not None:
            out.setdefault(s.round, []).append(s.live_pick_no)
    return out


def _signals(cfg: LeagueConfig) -> pl.DataFrame:
    """Phase 3 context that a keeper decision turns on: last year's production and TD/points luck.

    A high positive `td_diff_2025` means the player scored more touchdowns than his opportunity implied — the
    single most regression-prone input to a projection, and worth seeing before spending a keeper on him.
    """
    from app.features import luck, production

    seasons = settings.history_seasons
    try:
        prod = production.compute_summary(seasons).select(
            "player_id", "ppg_2025", "ppg_2024", "target_share_2025", "carry_share_2025",
            "yoy_ppg_delta", "same_role_seasons")
    except Exception:  # noqa: BLE001 - signals are additive; the keeper maths must still run
        prod = pl.DataFrame({"player_id": []}, schema={"player_id": pl.Int64})
    try:
        lk = luck.compute_summary(seasons).select("player_id", "td_diff_2025", "ppg_diff_2025")
    except Exception:  # noqa: BLE001
        lk = pl.DataFrame({"player_id": []}, schema={"player_id": pl.Int64})
    return prod.join(lk, on="player_id", how="full", coalesce=True)


def keeper_table(cfg: LeagueConfig | None = None, *, slot: int | None = None,
                 kept: set[int] | None = None, with_signals: bool = True) -> pl.DataFrame:
    """For every projected player, the surplus of keeping him in each round, and his break-even round."""
    cfg = cfg or load_league_config()
    kept = kept or set()
    pool = _pool_with_values(cfg, kept)
    cands = _room_candidates(pool, kept)
    picks_by_round = round_pick_numbers(cfg, slot)

    # expected best available VORP at each round's pick (averaged over slots when the slot is unknown)
    exp_best: dict[int, float] = {}
    for rnd, picks in picks_by_round.items():
        exp_best[rnd] = sum(expected_best_value(cands, p) for p in picks) / len(picks)

    rows = []
    for r in pool.to_dicts():
        if r["vorp"] is None:
            continue
        surplus = {rnd: round(r["vorp"] - eb, 2) for rnd, eb in exp_best.items()}
        positive = [rnd for rnd in sorted(surplus) if surplus[rnd] > 0]
        rows.append({
            "player_id": r["player_id"], "name": r["name"], "position": r["position"], "team": r["team"],
            "vendor_ppg": r["vendor_ppg"], "e_games": r["e_games"], "vorp": round(r["vorp"], 1),
            "composite_adp": r["composite_adp"], "adp_round": r["adp_round"],
            "break_even_round": positive[0] if positive else None,
            **{f"surplus_r{rnd}": surplus[rnd] for rnd in sorted(surplus)},
        })
    out = pl.DataFrame(rows).sort("vorp", descending=True)
    if with_signals:
        sig = _signals(cfg)
        if sig.height:
            out = out.join(sig, on="player_id", how="left")
    return out


def expected_best_by_round(cfg: LeagueConfig | None = None, *, slot: int | None = None,
                           kept: set[int] | None = None) -> pl.DataFrame:
    """What VORP you can expect from the pick each round costs — the bar a keeper has to clear."""
    cfg = cfg or load_league_config()
    kept = kept or set()
    pool = _pool_with_values(cfg, kept)
    cands = _room_candidates(pool, kept)
    rows = []
    for rnd, picks in sorted(round_pick_numbers(cfg, slot).items()):
        vals = [expected_best_value(cands, p) for p in picks]
        rows.append({"round": rnd, "picks": picks if slot else [min(picks), max(picks)],
                     "expected_best_vorp": round(sum(vals) / len(vals), 1),
                     "min": round(min(vals), 1), "max": round(max(vals), 1)})
    return pl.DataFrame(rows)
