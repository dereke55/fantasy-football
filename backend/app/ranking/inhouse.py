"""Phase 6 step 1 — the IN-HOUSE half of the per-game blend (docs/spec/ranking-model.md §1b/1c).

One row per player we can project. The model is deliberately an *opportunity* model: volume is taken at face
value from the player's own role history (or the slot he is listed in), efficiency is regressed hard toward the
positional mean, and touchdowns come from expected-TD rates rather than from raw TD history. Nothing here is
a vendor number: every point comes from ``app.scoring.engine.score`` under ``config/league.yaml``.

    in-house PPG (raw) = score({rec, rec_yd, rec_td, rush_yd, rush_td, pass_yd, pass_td, pass_int} per game)
    in-house PPG       = in-house PPG (raw) x age_factor(position, age at 2026-09-10)

The per-game yardage bonuses are NOT added here (``include_bonuses=False``): they are per game and the caller
adds them from :func:`app.scoring.bonuses.season_bonus_points`. E[games] is likewise the caller's job — this
module is strictly per game.

--------------------------------------------------------------------------------------------------------------
1. Team volume  (``team_plays_pass``, ``team_plays_rush``, ``team_targets_pg``)
--------------------------------------------------------------------------------------------------------------
``features.team_tendencies.compute([2025])`` for the player's **2026** team of record (``players.team``):
``pass_attempts_pg`` and ``rush_attempts_pg``, REG only. This is a **2025 baseline applied to a 2026 roster** —
it carries no 2026 scheme, coordinator or personnel change, and a club that changes identity (new OC, new QB)
will be mis-levelled until an in-season update. It is the only team-volume evidence that exists in the db.

Targets are not pass attempts: league-wide ``targets / attempts`` is 0.952 / 0.955 / 0.953 for 2023 / 2024 /
2025 (throwaways and spikes have no target). ``target_share`` is measured against team **targets**, so the
target projection multiplies by ``team_targets_pg`` (targets_total / games) and not by ``team_plays_pass``;
carries and rush attempts are the same column in nflverse, so ``team_plays_rush`` is used directly.

--------------------------------------------------------------------------------------------------------------
2. Player share  (``proj_target_share``, ``proj_carry_share``, ``proj_pass_att_share``, ``share_source``)
--------------------------------------------------------------------------------------------------------------
**Shares are PER GAME.** ``production.compute`` reports a season-total share (player season targets / team
season targets), which is deflated by every game the player missed — a WR1 who played 9 of 17 games shows 0.12,
not his 0.24 role — and the caller applies E[games] afterwards, so using the season share would charge his
injury twice (CLAUDE.md: "ONE E[games] ... no double counting of injury"). Every share here is therefore
rescaled to a per-game basis:

    share_pg = season_share x team_games / max(player_games, 8)

The 8-game floor caps the rescale at 17/8 = 2.125x, so a two-game cameo cannot be extrapolated into a full-time
role. Eight games is the spec's own veteran bar (``qualifies_vet``, ranking-model.md §2) and
``production.MIN_GAMES_FOR_PPG_RANK``.

``own_role``  — the player's own 2023-25 seasons whose ``role_key`` (team-position) equals his **2026** team and
position **and** which reach 8 REG games. Weighted 0.5 / 0.3 / 0.2 most-recent-first and renormalised over the
seasons actually used, exactly like ``production._trend``. Note this is a stricter test than
``compute_summary``'s ``ref_role_key``, which anchors on the last season the player *played*: a player who
changed clubs has a ``ref_role_key`` but no ``own_role`` share here, which is the point.

``depth_slot_baseline`` — no qualifying same-role season (changed clubs, or a veteran with no real history):
the 2025 league-average per-game share for his position at his 2026 depth-chart rank. The db holds depth charts
for **2026 only** (162 dt snapshots, no 2025 chart), so the slot table is built from the 2026 chart rank
(``features.depth.compute(2026)``, latest dt per team) paired with each player's 2025 per-game share — "what
does a player who is listed WR2 today produce" rather than "what did a 2025 WR2 produce". Players on the chart
with no 2025 REG line count as a real 0.0. Slots are forced monotone non-increasing and ranks deeper than the
last slot with >= 8 observations reuse that slot.

``rookie_draft_capital`` — a 2026 rookie (``players.is_rookie``) on the chart: the same depth-slot baseline
scaled by a draft-round factor derived at run time from real rookie seasons (:func:`rookie_round_factors`), §3.

**Role credibility.** An own-role share and today's depth chart are two estimates of the same 2026 role, so
they are combined by how much history there is:

    share = v x own_role_share + (1 - v) x slot_baseline,   v = same_role_games / (same_role_games + 8)

This is NOT the efficiency regression (nothing is pulled toward a positional mean) — it is why a WR listed 7th
today with one 9-game season two years ago (v = 0.5) lands near the WR7 slot instead of 4x it, while a
40-game incumbent (v = 0.83) keeps his own number essentially untouched. ``v`` is reported as
``role_credibility``; it is 0 for the two prior-only sources.

**Quarterbacks are different.** A QB's pass volume is the binary "is he the starter" question, and only the
2026 chart answers it: history cannot tell "was TEN's starter in 2023" from "is TEN's starter in 2026". So any
QB listed behind QB1 takes the **unconditional (season-basis) slot share** for pass attempts, not a per-game
one — his missing snaps are a depth-chart fact, not an availability one that E[games] would price. Without
this, Will Levis (TEN starter in 2023-24, now QB3) projected at 0.40 of Tennessee's attempts against Cam Ward's
0.435; with it Ward takes 0.80 and Levis 0.038. Rushing share and every other position keep the normal rule.
The spec's designated fix is Phase 5 ``qb_situations``, which this module does not read — the caller should
override QB shares from it when it lands.

A player with neither a qualifying same-role season nor a depth-chart rank cannot be projected and gets no row:
845 of the 961 hub QB/RB/WR/TEs are projected on the 2026-08-30 data (18 of the 116 dropped have no club at
all, ``team`` null or ``FA``).

**Team-level cap (required).** Within each 2026 club the projected target shares are scaled proportionally so
they sum to <= 1.0, and likewise carry shares and QB pass-attempt shares (the pass-attempt cap is an extra
guard of the same shape, not in the spec). Two things the pipeline must know:

* Only hub QB/RB/WR/TE players are in the pool, so a club total below 1.0 is normal — FB, OL and unmapped
  practice-squad targets are simply never projected.
* Per-game shares are conditional on being active, so they do **not** sum to 1.0 in reality: over the real 2025
  season the per-game (8-floored) shares of a club's own contributors sum to 1.223 on average (max 1.466) for
  targets and 1.201 for carries, because two players who split a season each hold a full-time per-game share.
  Capping at 1.0 is therefore a genuine haircut, not just a guard: 31 clubs are over the target budget and 30
  over the carry budget (32 need at least one of the two), and the scale averages 0.829 for targets
  (min 0.621, LV) and 0.813 for carries (min 0.568, NO). The uncapped values are kept as
  ``target_share_raw`` / ``carry_share_raw`` so a caller who prefers the physically-correct constraint
  (sum of share x P(active) <= 1, which E[games] supplies downstream) can use them. Because the haircut is
  close to league-uniform and the in-house component carries 0.10-0.30 of the blend, its effect on rank order
  is small; its effect on the vendor-vs-in-house gap bullet is not, and that bullet should expect the in-house
  number to sit low.

**Team codes.** Five hub rows carry vendor codes (SFO, KCC, LVR, NOS) rather than nflverse ones; they are
aliased in :func:`hub_players`, without which Deebo Samuel and Brandon Aiyuk would never match an nflverse
``role_key`` and would drop out of the projection.

--------------------------------------------------------------------------------------------------------------
3. Rookie round factors (derived, not invented)
--------------------------------------------------------------------------------------------------------------
:func:`rookie_round_factors` measures, over every 2023 / 2024 / 2025 rookie season
(``raw_nflverse_players.rookie_season`` = that season, so undrafted rookies are included), the mean per-game
share by position x draft-round bucket (R1 / R2 / R3 / R4+ / UDFA), **conditional on playing at least one REG
game**, and reports it relative to that position's R1 bucket. The conditioning matters: the depth-slot baseline
already conditions on being listed on a 2026 chart, so an unconditional factor would charge the "never sees the
field" discount twice. Anchoring at R1 = 1.0 is supported by the data — the mean R1 rookie almost exactly
matches the slot he is listed at (2023-25 R1 WR mean target share 0.191 vs the WR1 slot baseline 0.199; R1 RB
mean carry share 0.440 vs the RB1 slot baseline 0.459). Buckets are then forced monotone non-increasing
(cumulative min) because draft capital is ordinal and the per-cell samples are small (2-14 players a cell).

--------------------------------------------------------------------------------------------------------------
4. Efficiency, regressed  (``eff_ypt``, ``eff_ypc``, ``eff_ypa``, ``eff_catch_rate``, ``eff_yprr_or_none``)
--------------------------------------------------------------------------------------------------------------
Every rate is a James-Stein style shrink toward the **opportunity-weighted positional mean**:

    eff = w x own_rate + (1 - w) x positional_mean,    w = n / (n + k)

with ``n`` the player's own opportunities (targets / carries / pass attempts) over the seasons used. Volume is
never regressed — only efficiency.

``k`` was measured, not guessed. For each metric, every player-season with >= 25 opportunities (>= 100 pass
attempts for the QB metrics) was centred on its (season, position) mean — so the correlation measures
within-position stability, not the between-position spread the shrink is not trying to capture — and the
year-over-year Pearson correlation ``r`` was taken over the 2023->2024 and 2024->2025 pairs, with ``n_bar`` the
mean harmonic sample size of a pair. Under a "true talent + binomial noise" model ``r = tau^2 / (tau^2 +
sigma^2/n)``, so ``k = sigma^2/tau^2 = n_bar (1 - r) / r``. :func:`measure_stability` re-derives the table.

    metric              pairs      r     n_bar        k        used
    yards / target        314   +0.291    70.9    172.4        170
    catch rate            314   +0.307    70.9    160.3        160
    exp rec TD / target   314   +0.314    70.9    154.9        155
    yards / carry (all)   158   +0.365   121.1    210.4        800   <-- see below
    yards / carry (RB)    112   -0.015   146.5      inf
    exp rush TD / carry   158   +0.305   121.1    276.1        280
    yards / attempt (QB)   60   +0.470   405.9    458.2        460
    exp pass TD / att      60   +0.283   405.9   1030.5       1030
    exp INT / att          60   +0.629   405.9    239.7        240

Yards per carry is the outlier: for RBs alone it has **no** year-over-year signal (r = -0.015 over 112 pairs,
i.e. a 200-carry season tells you nothing about the next one), which formally implies k -> infinity and full
regression to the positional mean. ``k = 800`` is a deliberately conservative finite stand-in: it gives a
200-carry back a weight of 0.20 on his own YPC and leaves a sliver of player signal instead of flattening every
RB onto 4.38 yards a carry. The positive pooled figure (212) comes from QB scrambling, which is stable
(r = +0.627) but is not what the RB constant is for.

``eff_yprr_or_none`` is always null: no table in this db carries routes run (nflverse weekly stats, ff
opportunity, rosters and depth charts were all checked), and the rule is real data or nothing.

Efficiency is read from the player's same-role seasons. When he has none (he changed clubs), it falls back to
**all** of his seasons in the window rather than to the bare positional mean — see
:data:`EFFICIENCY_FALLBACK_TO_ALL_SEASONS`. Share is a property of a role and does not travel with a player;
yards per target is a property of the player and does.

--------------------------------------------------------------------------------------------------------------
5. Touchdowns  (``proj_td_pg``, ``proj_pass_td_pg``)
--------------------------------------------------------------------------------------------------------------
Raw TD history is never extrapolated. ``raw_nflverse_ff_opportunity_weekly`` gives, per player-week,
``rec_touchdown_exp`` / ``rush_touchdown_exp`` / ``pass_touchdown_exp`` and the matching opportunity counts;
summed over the seasons used they give an expected-TD rate per opportunity, regressed like any other rate and
multiplied by the projected opportunities. That table has no ``season_type`` column and does hold POST weeks
(19-22), so it is inner-joined to REG rows of ``raw_nflverse_stats_player_week`` — the join is what makes it
REG only, exactly as in ``features/luck.py``.

``proj_td_pg`` is receiving + rushing TDs per game (passing TDs are reported separately as
``proj_pass_td_pg``). Interceptions are included from ``pass_interception_exp`` because at -2 a point they are
worth ~1.4 PPG to a starting QB; expected fumbles are not — ff_opportunity ships ``*_fumble_lost`` but no
``*_fumble_lost_exp``, so a fumble penalty would have to be invented. Two-point conversions are dropped for the
same reason they are negligible (<0.1 PPG). Both omissions make the in-house number slightly generous for
fumble-prone players; neither is fabricated.

--------------------------------------------------------------------------------------------------------------
6. Quarterbacks
--------------------------------------------------------------------------------------------------------------
Pass attempts per game = his share of team pass attempts (own-role history, else the QB depth-slot baseline,
else the rookie prior) x ``team_plays_pass``; pass yards from the regressed yards-per-attempt, pass TDs and
INTs from the regressed expected rates. Rushing runs through exactly the same carry-share machinery as a
running back, so a rushing QB keeps his rushing points.

--------------------------------------------------------------------------------------------------------------
Known limitations to carry forward
--------------------------------------------------------------------------------------------------------------
* 2025 team volume on a 2026 roster; no coordinator/scheme change is modelled (context tables are tags only).
* The slot baseline is a 2026 chart rank paired with 2025 shares, because no 2025 depth chart is stored.
* No routes-run data anywhere, so YPRR is null.
* Rookie priors rest on 2-14 players a cell before the monotone smoothing.
* Depth-chart movement after the latest ``dt`` (2026-08-29) is invisible.
* The team cap costs every club 17-38 % of its raw per-game share budget, so the in-house number sits
  systematically below a vendor projection (mean gap -0.44 PPG against the Sleeper line, correlation 0.875).
  The gap is close to league-uniform, so it barely moves rank order, but the MARKET_VENDOR_GAP bullet must not
  read it as a per-player disagreement.
* QB rooms rest entirely on the depth chart. Phase 5 ``qb_situations`` is the spec's designated override and is
  deliberately not read here; a club whose chart QB1 is not the real 2026 starter will be wrong at QB.
"""
from __future__ import annotations

import functools

MIN_GAMES_FOR_BUDGET = 3
MIN_SHARE_FOR_BUDGET = 0.01
from datetime import date

import polars as pl

from app.config import settings
from app.db import engine
from app.features import depth, production, team_tendencies
from app.features.production import MIN_GAMES_FOR_PPG_RANK
from app.ranking.adjustments import age_factor
from app.scoring.config import LeagueConfig, load_league_config
from app.scoring.engine import score

#: Fantasy positions carried by the in-house projection.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: Age is measured at kickoff, per docs/spec/ranking-model.md §3a.
KICKOFF_2026 = date(2026, 9, 10)

#: Recency weights for the share history, most recent season first (renormalised over the seasons used).
SHARE_RECENCY_WEIGHTS: tuple[float, ...] = (0.5, 0.3, 0.2)

#: A season must reach this many REG games before its per-game share is trusted — the spec's own veteran test
#: (docs/spec/ranking-model.md §2, `qualifies_vet`) and the same bar as production.MIN_GAMES_FOR_PPG_RANK.
#: It doubles as the floor of the per-game rescale, capping it at 17/8 = 2.125x.
MIN_GAMES_FOR_SHARE: int = MIN_GAMES_FOR_PPG_RANK

#: Credibility half-weight for own-role share evidence: a player's own share is combined with the depth-slot
#: baseline as `v x own + (1 - v) x slot`, `v = same_role_games / (same_role_games + ROLE_CREDIBILITY_GAMES)`.
#: This is NOT the efficiency regression (nothing is pulled toward a positional mean): it is two estimates of
#: the same 2026 role, one from history and one from today's chart, combined by how much history there is.
ROLE_CREDIBILITY_GAMES: int = MIN_GAMES_FOR_PPG_RANK

#: Draft-round buckets, best capital first. The rookie factors are forced monotone in this order.
ROUND_BUCKETS: tuple[str, ...] = ("R1", "R2", "R3", "R4+", "UDFA")

#: Shrink constants k for `w = n / (n + k)`. Measured by :func:`measure_stability` — see the module docstring
#: for the r / n_bar each one comes from. YPC is the documented exception (RB r = -0.015 implies k -> inf).
SHRINK_K: dict[str, float] = {
    "ypt": 170.0,
    "catch_rate": 160.0,
    "rec_td_rate": 155.0,
    "ypc": 800.0,
    "rush_td_rate": 280.0,
    "ypa": 460.0,
    "pass_td_rate": 1030.0,
    "pass_int_rate": 240.0,
}

#: Minimum opportunities for a player-season to enter the stability measurement.
MIN_OPPS_FOR_STABILITY: int = 25
MIN_PASS_ATT_FOR_STABILITY: int = 100

#: A handful of hub rows carry a vendor team code instead of the nflverse one (observed 2026-08-30: SFO x2,
#: KCC, LVR, NOS — 5 players, Deebo Samuel and Brandon Aiyuk among them). Without the alias their 2026 role
#: key can never match an nflverse ``role_key`` and they fall out of the projection entirely. ``FA`` is a real
#: "no club" value and is mapped to null, which drops the player (17 rows).
TEAM_ALIASES: dict[str, str] = {"SFO": "SF", "KCC": "KC", "LVR": "LV", "NOS": "NO", "FA": ""}

#: A depth slot needs this many observations before it gets its own baseline; deeper ranks reuse the last one.
MIN_PLAYERS_PER_SLOT: int = 8

#: Efficiency (unlike share) is a property of the player, not of the role: when a player has no same-role
#: season, fall back to his own full history in the window rather than to the bare positional mean.
EFFICIENCY_FALLBACK_TO_ALL_SEASONS: bool = True

#: The exact output contract of :func:`compute_inhouse` (required columns first, audit columns after).
OUTPUT_COLUMNS: tuple[str, ...] = (
    "player_id", "name", "position", "team",
    "team_plays_pass", "team_plays_rush",
    "proj_target_share", "proj_carry_share", "share_source",
    "proj_targets_pg", "proj_carries_pg",
    "eff_ypt", "eff_ypc", "eff_yprr_or_none",
    "proj_rec_pg", "proj_rec_yd_pg", "proj_rush_yd_pg", "proj_pass_yd_pg", "proj_pass_td_pg",
    "proj_td_pg",
    "inhouse_ppg_raw", "age_factor", "inhouse_ppg",
    # ---- audit columns (inputs to the WHY bullets; not part of the blend contract) ----
    "team_targets_pg", "proj_pass_att_share", "proj_pass_att_pg", "proj_pass_int_pg",
    "proj_rec_td_pg", "proj_rush_td_pg",
    "eff_catch_rate", "eff_ypa", "eff_rec_td_rate", "eff_rush_td_rate",
    "n_targets_hist", "n_carries_hist", "n_pass_att_hist",
    "same_role_seasons", "share_seasons_used", "depth_rank", "draft_bucket",
    "is_rookie", "age", "role_credibility", "target_share_raw", "carry_share_raw",
    "target_cap_scale", "carry_cap_scale",
)


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def _seasons(seasons: list[int] | None) -> list[int]:
    out = sorted({int(s) for s in (seasons or settings.history_seasons)})
    if not out:
        raise ValueError("seasons must be a non-empty explicit list, e.g. [2023, 2024, 2025]")
    return out


def _sql_in(seasons: list[int]) -> str:
    return ", ".join(str(s) for s in seasons)


# ------------------------------------------------------------------------------------------------ raw inputs

def hub_players() -> pl.DataFrame:
    """The 2026 players hub at fantasy positions: identity, team of record, bio and draft capital."""
    return _q(
        "select id as player_id, gsis_id, name, position, team, birth_date, is_rookie, "
        "draft_round, draft_pick "
        f"from players where position in ({', '.join(chr(39) + p + chr(39) for p in POSITIONS)}) "
        "order by id"
    ).with_columns(
        team=pl.col("team").replace(TEAM_ALIASES).replace("", None),
    ).with_columns(
        role_2026=pl.concat_str([pl.col("team"), pl.col("position")], separator="-"),
    )


def player_season_volume(seasons: list[int]) -> pl.DataFrame:
    """Per (player_id, season) REG volume and yards, plus expected TDs/INTs from ff_opportunity.

    The expected columns come from ``raw_nflverse_ff_opportunity_weekly``, which has no ``season_type`` and does
    carry POST weeks; the inner join to REG rows of ``raw_nflverse_stats_player_week`` is what makes them REG.
    """
    sl = _sql_in(seasons)
    actual = _q(f"""
        select p.id as player_id, w.season,
               sum(coalesce(w.targets, 0))         as targets,
               sum(coalesce(w.receptions, 0))      as receptions,
               sum(coalesce(w.receiving_yards, 0)) as rec_yd,
               sum(coalesce(w.carries, 0))         as carries,
               sum(coalesce(w.rushing_yards, 0))   as rush_yd,
               sum(coalesce(w.attempts, 0))        as pass_att,
               sum(coalesce(w.passing_yards, 0))   as pass_yd
          from raw_nflverse_stats_player_week w
          join players p on p.gsis_id = w.player_id
         where w.season_type = 'REG' and w.season in ({sl})
         group by 1, 2
    """)
    expected = _q(f"""
        select p.id as player_id, s.season,
               sum(coalesce(o.rec_attempt, 0))          as rec_att_exp_den,
               sum(coalesce(o.rec_touchdown_exp, 0))    as rec_td_exp,
               sum(coalesce(o.rush_attempt, 0))         as rush_att_exp_den,
               sum(coalesce(o.rush_touchdown_exp, 0))   as rush_td_exp,
               sum(coalesce(o.pass_attempt, 0))         as pass_att_exp_den,
               sum(coalesce(o.pass_touchdown_exp, 0))   as pass_td_exp,
               sum(coalesce(o.pass_interception_exp, 0)) as pass_int_exp
          from raw_nflverse_stats_player_week s
          join raw_nflverse_ff_opportunity_weekly o
            on o.player_id = s.player_id and o.season::int = s.season and o.week::int = s.week
          join players p on p.gsis_id = s.player_id
         where s.season_type = 'REG' and s.season in ({sl})
         group by 1, 2
    """)
    return actual.join(expected, on=["player_id", "season"], how="left").with_columns(
        pl.col(c).cast(pl.Float64)
        for c in ("targets", "receptions", "rec_yd", "carries", "rush_yd", "pass_att", "pass_yd")
    )


# --------------------------------------------------------------------------------------- shrink constants

def measure_stability(seasons: list[int] | None = None) -> pl.DataFrame:
    """Re-derive the shrink constants: within-position-centred year-over-year correlation of each rate.

    One row per metric: ``pairs``, ``r``, ``n_bar``, ``k = n_bar (1 - r) / r``. The values baked into
    :data:`SHRINK_K` came from this function over 2023-2025; it exists so the constants stay auditable.
    """
    seasons = _seasons(seasons)
    vol = player_season_volume(seasons)
    pos = _q(f"""
        select p.id as player_id, w.season,
               mode() within group (order by w.position_group) as position
          from raw_nflverse_stats_player_week w
          join players p on p.gsis_id = w.player_id
         where w.season_type = 'REG' and w.season in ({_sql_in(seasons)})
         group by 1, 2
    """)
    df = vol.join(pos, on=["player_id", "season"], how="inner").filter(pl.col("position").is_in(POSITIONS))

    specs = (
        ("ypt", "rec_yd", "targets", MIN_OPPS_FOR_STABILITY),
        ("catch_rate", "receptions", "targets", MIN_OPPS_FOR_STABILITY),
        ("rec_td_rate", "rec_td_exp", "rec_att_exp_den", MIN_OPPS_FOR_STABILITY),
        ("ypc", "rush_yd", "carries", MIN_OPPS_FOR_STABILITY),
        ("rush_td_rate", "rush_td_exp", "rush_att_exp_den", MIN_OPPS_FOR_STABILITY),
        ("ypa", "pass_yd", "pass_att", MIN_PASS_ATT_FOR_STABILITY),
        ("pass_td_rate", "pass_td_exp", "pass_att_exp_den", MIN_PASS_ATT_FOR_STABILITY),
        ("pass_int_rate", "pass_int_exp", "pass_att_exp_den", MIN_PASS_ATT_FOR_STABILITY),
    )
    rows = []
    for metric, num, den, min_n in specs:
        d = (
            df.filter(pl.col(den).fill_null(0) >= min_n)
            .with_columns(rate=pl.col(num) / pl.col(den))
            .with_columns(c=pl.col("rate") - pl.col("rate").mean().over(["season", "position"]))
            .select("player_id", "season", "c", n=pl.col(den))
        )
        pairs = d.join(d.with_columns(season=pl.col("season") - 1), on=["player_id", "season"], suffix="_next")
        if pairs.height < 15:
            rows.append({"metric": metric, "pairs": pairs.height, "r": None, "n_bar": None, "k": None})
            continue
        r = pairs.select(pl.corr("c", "c_next")).item()
        n_bar = pairs.select((2 / (1 / pl.col("n") + 1 / pl.col("n_next"))).mean()).item()
        k = (n_bar * (1 - r) / r) if (r or 0) > 0 else None
        rows.append({"metric": metric, "pairs": pairs.height, "r": round(r, 4),
                     "n_bar": round(n_bar, 1), "k": None if k is None else round(k, 1)})
    return pl.DataFrame(rows).with_columns(
        k_used=pl.col("metric").replace_strict(SHRINK_K, return_dtype=pl.Float64)
    )


# ---------------------------------------------------------------------------------- shares and slot priors

def _per_game_shares(prod: pl.DataFrame, team_games: pl.DataFrame) -> pl.DataFrame:
    """Season shares rescaled to a per-game basis: share x team_games / player_games.

    ``production.compute`` reports the season-total share, which a missed game deflates. The blend is per game,
    so every share in this module is per game.
    """
    return (
        prod.join(team_games, on=["team", "season"], how="left")
        .with_columns(
            _scale=pl.col("team_games").cast(pl.Float64)
            / pl.col("games").cast(pl.Float64).clip(lower_bound=float(MIN_GAMES_FOR_SHARE))
        )
        .with_columns(
            target_share_pg=(pl.col("target_share") * pl.col("_scale")).clip(0.0, 1.0),
            carry_share_pg=(pl.col("carry_share") * pl.col("_scale")).clip(0.0, 1.0),
        )
        .drop("_scale")
    )


def _pass_att_shares(vol: pl.DataFrame, prod: pl.DataFrame, team_tend: pl.DataFrame) -> pl.DataFrame:
    """Per-game share of his club's pass attempts, per (player_id, season)."""
    team_att = team_tend.select("team", "season", "pass_attempts", "games").rename({"games": "team_games"})
    return (
        prod.select("player_id", "season", "team", "games")
        .join(vol.select("player_id", "season", "pass_att"), on=["player_id", "season"], how="left")
        .join(team_att, on=["team", "season"], how="left")
        .with_columns(
            pass_att_share_season=(pl.col("pass_att") / pl.col("pass_attempts")).clip(0.0, 1.0),
        )
        .with_columns(
            pass_att_share_pg=(
                pl.col("pass_att_share_season")
                * (
                    pl.col("team_games").cast(pl.Float64)
                    / pl.col("games").cast(pl.Float64).clip(lower_bound=float(MIN_GAMES_FOR_SHARE))
                )
            ).clip(0.0, 1.0)
        )
        .select("player_id", "season", "pass_att_share_pg", "pass_att_share_season")
    )


def _recency_weights(seasons: list[int]) -> dict[int, float]:
    ordered = sorted(seasons, reverse=True)
    return {
        s: (SHARE_RECENCY_WEIGHTS[i] if i < len(SHARE_RECENCY_WEIGHTS) else 0.0)
        for i, s in enumerate(ordered)
    }


def _weighted(df: pl.DataFrame, cols: tuple[str, ...], seasons: list[int]) -> pl.DataFrame:
    """Recency-weighted mean of `cols` per player, weights renormalised over the seasons present."""
    weights = _recency_weights(seasons)
    d = df.with_columns(_w=pl.col("season").replace_strict(weights, default=0.0, return_dtype=pl.Float64))
    return d.group_by("player_id").agg(
        _wsum=pl.col("_w").sum(),
        share_seasons_used=pl.len().cast(pl.Int32),
        **{c: (pl.col("_w") * pl.col(c).fill_null(0.0)).sum() for c in cols},
    ).with_columns(
        **{c: pl.when(pl.col("_wsum") > 0).then(pl.col(c) / pl.col("_wsum")).otherwise(None) for c in cols}
    ).drop("_wsum")


def depth_slot_baseline(prod: pl.DataFrame, chart: pl.DataFrame, latest_season: int,
                        pass_shares: pl.DataFrame) -> pl.DataFrame:
    """League-average per-game share by (position, depth_rank), from the latest chart x `latest_season` shares.

    Ranks are forced monotone non-increasing and clamped at the deepest rank with >= MIN_PLAYERS_PER_SLOT
    observations, so a WR7 inherits the deepest reliable slot rather than an empty cell.
    """
    latest = (
        prod.filter(pl.col("season") == latest_season)
        .select("player_id", "target_share_pg", "carry_share_pg")
        .join(
            pass_shares.filter(pl.col("season") == latest_season)
            .select("player_id", "pass_att_share_pg", "pass_att_share_season"),
            on="player_id", how="left",
        )
    )
    slots = (
        chart.filter(pl.col("appears_on_chart"))
        .select("player_id", "position", "depth_rank")
        .join(latest, on="player_id", how="left")
        .with_columns(
            pl.col("target_share_pg").fill_null(0.0),
            pl.col("carry_share_pg").fill_null(0.0),
            pl.col("pass_att_share_pg").fill_null(0.0),
            pl.col("pass_att_share_season").fill_null(0.0),
        )
    )
    agg = (
        slots.group_by(["position", "depth_rank"])
        .agg(
            n_slot=pl.len().cast(pl.Int32),
            base_target_share=pl.col("target_share_pg").mean(),
            base_carry_share=pl.col("carry_share_pg").mean(),
            base_pass_att_share=pl.col("pass_att_share_pg").mean(),
            base_pass_att_share_season=pl.col("pass_att_share_season").mean(),
        )
        .filter(pl.col("n_slot") >= MIN_PLAYERS_PER_SLOT)
        .sort(["position", "depth_rank"])
    )
    return agg.with_columns(
        pl.col(c).cum_min().over("position")
        for c in ("base_target_share", "base_carry_share", "base_pass_att_share",
                  "base_pass_att_share_season")
    )


def _bucket_expr(round_col: str = "draft_round") -> pl.Expr:
    return (
        pl.when(pl.col(round_col) == 1).then(pl.lit("R1"))
        .when(pl.col(round_col) == 2).then(pl.lit("R2"))
        .when(pl.col(round_col) == 3).then(pl.lit("R3"))
        .when(pl.col(round_col) >= 4).then(pl.lit("R4+"))
        .otherwise(pl.lit("UDFA"))
    )


def rookie_round_factors(seasons: list[int], prod: pl.DataFrame,
                         pass_shares: pl.DataFrame) -> pl.DataFrame:
    """Mean rookie-season per-game share by position x draft-round bucket, relative to that position's R1.

    Cohort: every ``raw_nflverse_players.rookie_season`` in `seasons` at a fantasy position (undrafted rookies
    included — they have a ``rookie_season`` but a null ``draft_round``), restricted to rookies who played at
    least one REG game, because the depth slot the factor multiplies already conditions on being on a chart.
    Forced monotone non-increasing over R1 > R2 > R3 > R4+ > UDFA.
    """
    cohort = _q(f"""
        select n.gsis_id, n.rookie_season as season, n.position, n.draft_round
          from raw_nflverse_players n
         where n.rookie_season in ({_sql_in(seasons)})
           and n.position in ({', '.join(chr(39) + p + chr(39) for p in POSITIONS)})
    """)
    shares = (
        prod.select("player_id", "gsis_id", "season", "games", "target_share_pg", "carry_share_pg")
        .join(pass_shares.drop("pass_att_share_season"), on=["player_id", "season"], how="left")
    )
    df = (
        cohort.join(shares, on=["gsis_id", "season"], how="inner")
        .filter(pl.col("games") >= 1)
        .with_columns(bucket=_bucket_expr())
    )
    agg = df.group_by(["position", "bucket"]).agg(
        n_rookies=pl.len().cast(pl.Int32),
        mean_target_share=pl.col("target_share_pg").fill_null(0.0).mean(),
        mean_carry_share=pl.col("carry_share_pg").fill_null(0.0).mean(),
        mean_pass_att_share=pl.col("pass_att_share_pg").fill_null(0.0).mean(),
    )
    order = pl.DataFrame({"bucket": list(ROUND_BUCKETS), "_ord": list(range(len(ROUND_BUCKETS)))})
    metrics = ("target", "carry", "pass_att")
    out = (
        agg.join(order, on="bucket", how="left")
        .sort(["position", "_ord"])
        .with_columns(
            **{
                f"f_{m}": (
                    pl.col(f"mean_{m}_share")
                    / pl.col(f"mean_{m}_share").filter(pl.col("bucket") == "R1").first().over("position")
                )
                for m in metrics
            }
        )
    )
    return out.with_columns(
        pl.col(f"f_{m}").fill_nan(None).fill_null(1.0).clip(0.0, 1.0).cum_min().over("position")
        for m in metrics
    ).select("position", "bucket", "n_rookies", "f_target", "f_carry", "f_pass_att")


# -------------------------------------------------------------------------------------- efficiency shrink

def _regressed(df: pl.DataFrame, num: str, den: str, metric: str, out: str) -> pl.DataFrame:
    """Shrink `num/den` toward the opportunity-weighted positional mean with w = n / (n + SHRINK_K[metric])."""
    k = SHRINK_K[metric]
    d = df.with_columns(
        _n=pl.col(den).fill_null(0.0),
        _num=pl.col(num).fill_null(0.0),
    ).with_columns(
        _mean=(pl.col("_num").sum().over("position") / pl.col("_n").sum().over("position")),
    )
    return d.with_columns(
        pl.when(pl.col("_n") > 0)
        .then(
            (pl.col("_n") / (pl.col("_n") + k)) * (pl.col("_num") / pl.col("_n"))
            + (k / (pl.col("_n") + k)) * pl.col("_mean")
        )
        .otherwise(pl.col("_mean"))
        .alias(out)
    ).drop("_n", "_num", "_mean")


# ------------------------------------------------------------------------------------------- team caps

def _credible(own: str, base: str) -> pl.Expr:
    """Combine an own-role share with the depth-slot baseline by `role_credibility` (module docstring, §2)."""
    return (
        pl.col("role_credibility") * pl.col(own)
        + (1 - pl.col("role_credibility")) * pl.col(base).fill_null(pl.col(own))
    )


@functools.lru_cache(maxsize=4)
def measured_share_budget(seasons: tuple[int, ...], kind: str) -> float:
    """The per-game share budget a real roster actually spends.

    Per-game shares are conditional on the player being active, so a club's contributors do NOT sum to 1.0: someone
    always misses time and his share is redistributed. Measured over real 2025 rosters the sum is ~1.2, so capping
    at 1.0 is a 17-38% haircut applied to every skill player rather than a guard against impossible projections.
    This measures the budget from the same data the shares come from and caps at that instead.
    """
    col = {"target": "targets", "carry": "carries", "pass_att": "attempts"}[kind]
    df = pl.read_database(
        f"select team, player_id, sum({col}) tot, count(*) g from raw_nflverse_stats_player_week "
        f"where season_type = 'REG' and season = {max(seasons)} and {col} is not null group by team, player_id",
        connection=engine, infer_schema_length=None)
    if df.is_empty():
        return 1.0
    team_tot = df.group_by("team").agg(pl.col("tot").sum().alias("team_tot"))
    # Restrict to real contributors. The 17/games rescaling amplifies tiny samples, so including every fringe
    # player who touched the ball once (66 per team) inflates the budget to 1.39; the ~12 players per team who
    # account for 98% of the volume - the same population we actually project - measure 1.24.
    per_game = (
        df.join(team_tot, on="team")
        .with_columns(share=pl.col("tot") / pl.col("team_tot"))
        .filter((pl.col("g") >= MIN_GAMES_FOR_BUDGET) & (pl.col("share") >= MIN_SHARE_FOR_BUDGET))
        .with_columns(share_pg=pl.col("share") * (17.0 / pl.col("g")))
        .group_by("team").agg(pl.col("share_pg").sum().alias("s"))
    )
    return float(per_game["s"].median())


def _apply_team_cap(df: pl.DataFrame, share_col: str, scale_col: str, budget: float = 1.0) -> pl.DataFrame:
    """Scale each club's shares proportionally so they sum to <= `budget` (see measured_share_budget)."""
    total = pl.col(share_col).fill_null(0.0).sum().over("team")
    return df.with_columns(
        pl.when(total > budget).then(budget / total).otherwise(1.0).alias(scale_col)
    ).with_columns((pl.col(share_col).fill_null(0.0) * pl.col(scale_col)).alias(share_col))


def cap_report(df: pl.DataFrame) -> pl.DataFrame:
    """One row per club that needed scaling: which cap fired and by how much."""
    return (
        df.group_by("team")
        .agg(
            target_cap_scale=pl.col("target_cap_scale").min(),
            carry_cap_scale=pl.col("carry_cap_scale").min(),
            target_share_sum_raw=pl.col("target_share_raw").sum(),
            carry_share_sum_raw=pl.col("carry_share_raw").sum(),
        )
        .filter((pl.col("target_cap_scale") < 1.0) | (pl.col("carry_cap_scale") < 1.0))
        .sort("target_cap_scale")
    )


# ------------------------------------------------------------------------------------------------- main

def _age_years(birth: date | None) -> float | None:
    if birth is None:
        return None
    return round((KICKOFF_2026 - birth).days / 365.25, 2)


def _share_history(prod_pg: pl.DataFrame, pass_shares: pl.DataFrame, hub: pl.DataFrame,
                   seasons: list[int]) -> pl.DataFrame:
    """Recency-weighted own-role shares: only seasons whose role_key equals the player's 2026 team-position."""
    same_role = (
        prod_pg.join(hub.select("player_id", "role_2026"), on="player_id", how="inner")
        .filter(
            (pl.col("role_key") == pl.col("role_2026"))
            & (pl.col("games") >= MIN_GAMES_FOR_SHARE)
        )
        .join(pass_shares.drop("pass_att_share_season"), on=["player_id", "season"], how="left")
    )
    weighted = _weighted(
        same_role, ("target_share_pg", "carry_share_pg", "pass_att_share_pg"), seasons
    ).rename({
        "target_share_pg": "own_target_share",
        "carry_share_pg": "own_carry_share",
        "pass_att_share_pg": "own_pass_att_share",
    })
    counts = same_role.group_by("player_id").agg(
        same_role_seasons=pl.len().cast(pl.Int32),
        same_role_games=pl.col("games").sum().cast(pl.Int32),
    )
    return weighted.join(counts, on="player_id", how="left")


def _efficiency_history(vol: pl.DataFrame, prod_pg: pl.DataFrame, hub: pl.DataFrame) -> pl.DataFrame:
    """Per-player opportunity and yard/expected-TD totals over the seasons used for efficiency.

    Same-role seasons when the player has any; otherwise (a club change) his full history in the window, since
    efficiency travels with the player while share does not (:data:`EFFICIENCY_FALLBACK_TO_ALL_SEASONS`).
    """
    roles = prod_pg.select("player_id", "season", "role_key").join(
        hub.select("player_id", "role_2026"), on="player_id", how="inner"
    )
    same = roles.filter(pl.col("role_key") == pl.col("role_2026")).select("player_id", "season")
    has_same = same.select("player_id").unique().with_columns(_has_same=pl.lit(value=True))

    if EFFICIENCY_FALLBACK_TO_ALL_SEASONS:
        allsz = roles.select("player_id", "season")
        keep = pl.concat([
            same.join(has_same, on="player_id", how="inner").select("player_id", "season"),
            allsz.join(has_same, on="player_id", how="left")
            .filter(pl.col("_has_same").is_null())
            .select("player_id", "season"),
        ])
    else:
        keep = same

    totals = (
        vol.join(keep, on=["player_id", "season"], how="inner")
        .group_by("player_id")
        .agg(pl.col(c).fill_null(0.0).sum() for c in (
            "targets", "receptions", "rec_yd", "carries", "rush_yd", "pass_att", "pass_yd",
            "rec_att_exp_den", "rec_td_exp", "rush_att_exp_den", "rush_td_exp",
            "pass_att_exp_den", "pass_td_exp", "pass_int_exp",
        ))
    )
    return totals.join(has_same, on="player_id", how="left").with_columns(
        pl.col("_has_same").fill_null(value=False).alias("eff_same_role")
    ).drop("_has_same")


def compute_inhouse(cfg: LeagueConfig | None = None, seasons: list[int] | None = None) -> pl.DataFrame:
    """The in-house per-game projection, one row per projectable QB/RB/WR/TE (see the module docstring).

    Columns: :data:`OUTPUT_COLUMNS`. ``inhouse_ppg_raw`` is before the age step, ``inhouse_ppg`` after it;
    the per-game yardage bonuses and E[games] are the caller's to add.
    """
    cfg = cfg or load_league_config()
    seasons = _seasons(seasons)
    latest = seasons[-1]

    hub = hub_players()
    prod = production.compute(seasons)
    tend = team_tendencies.compute(seasons)
    chart = depth.compute(settings.current_season)
    vol = player_season_volume(seasons)

    team_games = tend.select("team", "season", team_games=pl.col("games"))
    prod_pg = _per_game_shares(prod, team_games)
    pass_shares = _pass_att_shares(vol, prod, tend)

    # ---- opportunity ------------------------------------------------------------------------------------
    own = _share_history(prod_pg, pass_shares, hub, seasons)
    baseline = depth_slot_baseline(prod_pg, chart, latest, pass_shares)
    factors = rookie_round_factors(seasons, prod_pg, pass_shares)

    max_slot = baseline.group_by("position").agg(_max_rank=pl.col("depth_rank").max())
    slots = (
        chart.select("player_id", "depth_rank", "appears_on_chart")
        .join(hub.select("player_id", "position"), on="player_id", how="inner")
        .join(max_slot, on="position", how="left")
        .with_columns(_slot=pl.min_horizontal(pl.col("depth_rank"), pl.col("_max_rank")).cast(pl.Int32))
        .join(baseline, left_on=["position", "_slot"], right_on=["position", "depth_rank"], how="left")
        .select("player_id", "depth_rank", "appears_on_chart", "base_target_share", "base_carry_share",
                "base_pass_att_share", "base_pass_att_share_season")
    )

    df = (
        hub.join(own, on="player_id", how="left")
        .join(slots, on="player_id", how="left")
        .with_columns(draft_bucket=_bucket_expr())
        .join(
            factors.drop("n_rookies").rename({"bucket": "draft_bucket"}),
            on=["position", "draft_bucket"], how="left",
        )
    )
    # a rookie whose (position, bucket) cell had no history keeps the neutral factor
    df = df.with_columns(
        pl.col("f_target").fill_null(1.0), pl.col("f_carry").fill_null(1.0),
        pl.col("f_pass_att").fill_null(1.0),
        same_role_seasons=pl.col("same_role_seasons").fill_null(0).cast(pl.Int32),
        same_role_games=pl.col("same_role_games").fill_null(0).cast(pl.Int32),
        share_seasons_used=pl.col("share_seasons_used").fill_null(0).cast(pl.Int32),
    ).with_columns(
        role_credibility=pl.when(pl.col("base_target_share").is_null())
        .then(1.0)
        .otherwise(
            pl.col("same_role_games").cast(pl.Float64)
            / (pl.col("same_role_games") + ROLE_CREDIBILITY_GAMES)
        )
    )

    has_own = pl.col("same_role_seasons") > 0
    # A QB's pass volume is the binary "is he the starter" question, which only the 2026 chart answers: a QB
    # listed behind QB1 takes the UNCONDITIONAL (season-basis) slot share, because his missing snaps are a
    # depth-chart fact, not an availability one that E[games] would price. See the module docstring, §6.
    backup_qb = (
        (pl.col("position") == "QB")
        & pl.col("appears_on_chart").fill_null(value=False)
        & (pl.col("depth_rank") > 1)
    )
    is_rookie_prior = ~has_own & pl.col("is_rookie") & pl.col("appears_on_chart").fill_null(value=False)
    has_slot = ~has_own & pl.col("appears_on_chart").fill_null(value=False)

    df = df.with_columns(
        share_source=pl.when(has_own).then(pl.lit("own_role"))
        .when(is_rookie_prior).then(pl.lit("rookie_draft_capital"))
        .when(has_slot).then(pl.lit("depth_slot_baseline"))
        .otherwise(pl.lit(None, dtype=pl.String)),
        target_share_raw=pl.when(has_own).then(_credible("own_target_share", "base_target_share"))
        .when(is_rookie_prior).then(pl.col("base_target_share") * pl.col("f_target"))
        .otherwise(pl.col("base_target_share")),
        carry_share_raw=pl.when(has_own).then(_credible("own_carry_share", "base_carry_share"))
        .when(is_rookie_prior).then(pl.col("base_carry_share") * pl.col("f_carry"))
        .otherwise(pl.col("base_carry_share")),
        pass_att_share_raw=pl.when(backup_qb).then(
            pl.col("base_pass_att_share_season")
            * pl.when(is_rookie_prior).then(pl.col("f_pass_att")).otherwise(1.0)
        )
        .when(has_own).then(_credible("own_pass_att_share", "base_pass_att_share"))
        .when(is_rookie_prior).then(pl.col("base_pass_att_share") * pl.col("f_pass_att"))
        .otherwise(pl.col("base_pass_att_share")),
    ).filter(pl.col("share_source").is_not_null() & pl.col("team").is_not_null())

    df = df.with_columns(
        pl.col("target_share_raw").fill_null(0.0),
        pl.col("carry_share_raw").fill_null(0.0),
        pl.col("pass_att_share_raw").fill_null(0.0),
    )

    # ---- team-level caps --------------------------------------------------------------------------------
    df = df.with_columns(
        proj_target_share=pl.col("target_share_raw"),
        proj_carry_share=pl.col("carry_share_raw"),
        proj_pass_att_share=pl.col("pass_att_share_raw"),
    )
    seasons_t = tuple(seasons)
    df = _apply_team_cap(df, "proj_target_share", "target_cap_scale",
                         measured_share_budget(seasons_t, "target"))
    df = _apply_team_cap(df, "proj_carry_share", "carry_cap_scale",
                         measured_share_budget(seasons_t, "carry"))
    df = _apply_team_cap(df, "proj_pass_att_share", "pass_att_cap_scale",
                         measured_share_budget(seasons_t, "pass_att"))

    # ---- team volume ------------------------------------------------------------------------------------
    team_vol = (
        tend.filter(pl.col("season") == latest)
        .select(
            "team",
            team_plays_pass=pl.col("pass_attempts_pg"),
            team_plays_rush=pl.col("rush_attempts_pg"),
            team_targets_pg=(pl.col("targets_total") / pl.col("games")).round(2),
        )
    )
    df = df.join(team_vol, on="team", how="inner").with_columns(
        proj_targets_pg=pl.col("proj_target_share") * pl.col("team_targets_pg"),
        proj_carries_pg=pl.col("proj_carry_share") * pl.col("team_plays_rush"),
        proj_pass_att_pg=pl.col("proj_pass_att_share") * pl.col("team_plays_pass"),
    )

    # ---- efficiency, regressed --------------------------------------------------------------------------
    eff = _efficiency_history(vol, prod_pg, hub).join(
        hub.select("player_id", "position"), on="player_id", how="inner"
    )
    eff = _regressed(eff, "rec_yd", "targets", "ypt", "eff_ypt")
    eff = _regressed(eff, "receptions", "targets", "catch_rate", "eff_catch_rate")
    eff = _regressed(eff, "rec_td_exp", "rec_att_exp_den", "rec_td_rate", "eff_rec_td_rate")
    eff = _regressed(eff, "rush_yd", "carries", "ypc", "eff_ypc")
    eff = _regressed(eff, "rush_td_exp", "rush_att_exp_den", "rush_td_rate", "eff_rush_td_rate")
    eff = _regressed(eff, "pass_yd", "pass_att", "ypa", "eff_ypa")
    eff = _regressed(eff, "pass_td_exp", "pass_att_exp_den", "pass_td_rate", "eff_pass_td_rate")
    eff = _regressed(eff, "pass_int_exp", "pass_att_exp_den", "pass_int_rate", "eff_pass_int_rate")
    eff = eff.select(
        "player_id", "eff_ypt", "eff_catch_rate", "eff_rec_td_rate", "eff_ypc", "eff_rush_td_rate",
        "eff_ypa", "eff_pass_td_rate", "eff_pass_int_rate",
        n_targets_hist=pl.col("targets"), n_carries_hist=pl.col("carries"),
        n_pass_att_hist=pl.col("pass_att"),
    )

    # players with no history at all sit exactly on the positional mean
    pos_means = eff.join(hub.select("player_id", "position"), on="player_id", how="inner").group_by(
        "position"
    ).agg(
        pl.col(c).mean().alias(f"_m_{c}") for c in (
            "eff_ypt", "eff_catch_rate", "eff_rec_td_rate", "eff_ypc", "eff_rush_td_rate",
            "eff_ypa", "eff_pass_td_rate", "eff_pass_int_rate",
        )
    )
    df = df.join(eff, on="player_id", how="left").join(pos_means, on="position", how="left")
    for c in ("eff_ypt", "eff_catch_rate", "eff_rec_td_rate", "eff_ypc", "eff_rush_td_rate",
              "eff_ypa", "eff_pass_td_rate", "eff_pass_int_rate"):
        df = df.with_columns(pl.col(c).fill_null(pl.col(f"_m_{c}")).fill_null(0.0))
    df = df.with_columns(
        pl.col("n_targets_hist").fill_null(0.0),
        pl.col("n_carries_hist").fill_null(0.0),
        pl.col("n_pass_att_hist").fill_null(0.0),
    )

    # ---- projected stat line ----------------------------------------------------------------------------
    df = df.with_columns(
        eff_yprr_or_none=pl.lit(None, dtype=pl.Float64),
        proj_rec_pg=pl.col("proj_targets_pg") * pl.col("eff_catch_rate"),
        proj_rec_yd_pg=pl.col("proj_targets_pg") * pl.col("eff_ypt"),
        proj_rush_yd_pg=pl.col("proj_carries_pg") * pl.col("eff_ypc"),
        proj_pass_yd_pg=pl.col("proj_pass_att_pg") * pl.col("eff_ypa"),
        proj_pass_td_pg=pl.col("proj_pass_att_pg") * pl.col("eff_pass_td_rate"),
        proj_pass_int_pg=pl.col("proj_pass_att_pg") * pl.col("eff_pass_int_rate"),
        proj_rec_td_pg=pl.col("proj_targets_pg") * pl.col("eff_rec_td_rate"),
        proj_rush_td_pg=pl.col("proj_carries_pg") * pl.col("eff_rush_td_rate"),
    ).with_columns(proj_td_pg=pl.col("proj_rec_td_pg") + pl.col("proj_rush_td_pg"))

    # ---- scoring and the age step -----------------------------------------------------------------------
    ppg_raw: list[float] = []
    ages: list[float | None] = []
    factors_age: list[float] = []
    for r in df.iter_rows(named=True):
        line = {
            "rec": r["proj_rec_pg"], "rec_yd": r["proj_rec_yd_pg"], "rec_td": r["proj_rec_td_pg"],
            "rush_yd": r["proj_rush_yd_pg"], "rush_td": r["proj_rush_td_pg"],
            "pass_yd": r["proj_pass_yd_pg"], "pass_td": r["proj_pass_td_pg"],
            "pass_int": r["proj_pass_int_pg"],
        }
        ppg_raw.append(score(line, cfg.scoring, r["position"], include_bonuses=False))
        age = _age_years(r["birth_date"])
        ages.append(age)
        factors_age.append(age_factor(r["position"], age))

    df = df.with_columns(
        pl.Series("inhouse_ppg_raw", ppg_raw, dtype=pl.Float64),
        pl.Series("age", ages, dtype=pl.Float64),
        pl.Series("age_factor", factors_age, dtype=pl.Float64),
    ).with_columns(
        inhouse_ppg=(pl.col("inhouse_ppg_raw") * pl.col("age_factor")).clip(lower_bound=0.0).round(4)
    )

    rounded = {
        c: pl.col(c).round(4) for c in (
            "proj_targets_pg", "proj_carries_pg",
            "eff_ypt", "eff_ypc", "proj_rec_pg", "proj_rec_yd_pg", "proj_rush_yd_pg",
            "proj_pass_yd_pg", "proj_pass_td_pg", "proj_td_pg", "inhouse_ppg_raw",
            "proj_pass_att_pg", "proj_pass_int_pg", "proj_rec_td_pg",
            "proj_rush_td_pg", "eff_catch_rate", "eff_ypa", "eff_rec_td_rate", "eff_rush_td_rate",
            "target_share_raw", "carry_share_raw", "target_cap_scale", "carry_cap_scale",
            "role_credibility",
        )
    }
    rounded.update({
        c: pl.col(c).round(6)
        for c in ("proj_target_share", "proj_carry_share", "proj_pass_att_share")
    })
    return (
        df.with_columns(**rounded)
        .select(OUTPUT_COLUMNS)
        .sort("inhouse_ppg", descending=True)
    )
