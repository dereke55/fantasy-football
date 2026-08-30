"""Luck features — expected vs. actual production, REG only, re-scored under `config/league.yaml`.

Per `docs/phases/03-features.md` (Luck):
  `points_expected` = Σ score(ffopportunity `*_exp` stat line), `points_actual` = Σ score(nflverse actual stat line),
  both over the SAME weeks (inner join on gsis_id + season + week), never the vendor `total_fantasy_points_exp` /
  `fantasy_points` columns.

Data quirks handled here (verified against the live db):
- `raw_nflverse_ff_opportunity_weekly.season` is TEXT ('2025') and `.week` is DOUBLE PRECISION (1.0) -> cast on join.
- That table has no `season_type`; POST weeks (19-22) are present. Restricting the join to REG rows of
  `raw_nflverse_stats_player_week` is what makes this REG-only.
- It also holds 1,280 rows with a NULL `player_id` (team-level residue); the join drops them.
- ffopportunity ships `rec_fumble_lost` / `rush_fumble_lost` but NO `*_fumble_lost_exp` columns, so the adapter's
  `fum_lost` candidate is absent and expected fumbles score 0. `exp_points` therefore carries no fumble penalty
  while `act_points` does; a fumble-prone season shows up as (correctly) negative luck.

Point values are per-week `score()` calls (not a season-total stat line) so non-fractional yardage and any
`bonuses` in the league config apply with weekly Yahoo semantics.
"""
from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from app.config import settings
from app.db import engine
from app.scoring.adapters import from_ff_opportunity_expected, from_nflverse_week
from app.scoring.config import LeagueConfig, load_league_config
from app.scoring.engine import score

# Actual stat columns consumed by app.scoring.adapters.NFLVERSE_WEEK, plus the TD/yard components reported here.
_ACTUAL_COLS = (
    "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "fumbles_lost_total", "special_teams_tds",
)
# Expected stat columns consumed by app.scoring.adapters.FF_OPPORTUNITY_EXP (vendor points columns excluded on purpose).
_EXPECTED_COLS = (
    "pass_yards_gained_exp", "pass_touchdown_exp", "pass_interception_exp", "pass_two_point_conv_exp",
    "rush_yards_gained_exp", "rush_touchdown_exp", "rush_two_point_conv_exp",
    "receptions_exp", "rec_yards_gained_exp", "rec_touchdown_exp", "rec_two_point_conv_exp",
)

OUTPUT_COLUMNS = (
    "player_id", "gsis_id", "season", "position", "games_both",
    "exp_points", "act_points", "points_diff", "ppg_diff",
    "td_exp", "td_act", "td_diff", "yards_exp", "yards_act", "yards_diff",
)


def _sql(seasons: Sequence[int]) -> str:
    season_list = ", ".join(str(int(s)) for s in seasons)
    cols = ",\n           ".join(
        [f"s.{c}" for c in _ACTUAL_COLS] + [f"o.{c}" for c in _EXPECTED_COLS]
    )
    return f"""
        SELECT p.id          AS player_id,
               s.player_id   AS gsis_id,
               s.season      AS season,
               s.week        AS week,
               s.position    AS position,
               {cols}
          FROM raw_nflverse_stats_player_week s
          JOIN raw_nflverse_ff_opportunity_weekly o
            ON o.player_id = s.player_id
           AND o.season::int = s.season
           AND o.week::int = s.week
          JOIN players p
            ON p.gsis_id = s.player_id
         WHERE s.season_type = 'REG'
           AND s.season IN ({season_list})
    """


def load_weeks(seasons: Sequence[int] | None = None) -> pl.DataFrame:
    """REG player-weeks that exist in BOTH the actual stats and the expected (ffopportunity) table."""
    seasons = list(seasons or settings.history_seasons)
    return pl.read_database(_sql(seasons), connection=engine, infer_schema_length=None)


def _weekly_points(weeks: pl.DataFrame, cfg: LeagueConfig) -> pl.DataFrame:
    """Add per-week `exp_points` / `act_points`, each from app.scoring applied to one adapted stat line."""
    rows = weeks.to_dicts()
    scoring = cfg.scoring
    act = [score(from_nflverse_week(r), scoring, r.get("position")) for r in rows]
    exp = [score(from_ff_opportunity_expected(r), scoring, r.get("position")) for r in rows]
    return weeks.with_columns(
        pl.Series("act_points", act, dtype=pl.Float64),
        pl.Series("exp_points", exp, dtype=pl.Float64),
    )


def compute(seasons: Sequence[int] | None = None, cfg: LeagueConfig | None = None) -> pl.DataFrame:
    """One row per (player_id, gsis_id, season): expected vs. actual points, TDs and yards over REG weeks.

    `games_both` is the number of weeks with both an actual and an expected row; every sum is over those weeks
    only, so `ppg_diff = (act_points - exp_points) / games_both` is an apples-to-apples per-game number.
    """
    seasons = list(seasons or settings.history_seasons)
    cfg = cfg or load_league_config()
    weeks = _weekly_points(load_weeks(seasons), cfg)
    out = (
        weeks.group_by("player_id", "gsis_id", "season")
        .agg(
            pl.col("position").drop_nulls().mode().first().alias("position"),
            pl.len().alias("games_both"),
            pl.col("exp_points").sum().alias("exp_points"),
            pl.col("act_points").sum().alias("act_points"),
            (pl.col("pass_touchdown_exp").fill_null(0)
             + pl.col("rec_touchdown_exp").fill_null(0)
             + pl.col("rush_touchdown_exp").fill_null(0)).sum().alias("td_exp"),
            (pl.col("passing_tds").fill_null(0)
             + pl.col("receiving_tds").fill_null(0)
             + pl.col("rushing_tds").fill_null(0)).sum().cast(pl.Float64).alias("td_act"),
            (pl.col("pass_yards_gained_exp").fill_null(0)
             + pl.col("rec_yards_gained_exp").fill_null(0)
             + pl.col("rush_yards_gained_exp").fill_null(0)).sum().alias("yards_exp"),
            (pl.col("passing_yards").fill_null(0)
             + pl.col("receiving_yards").fill_null(0)
             + pl.col("rushing_yards").fill_null(0)).sum().cast(pl.Float64).alias("yards_act"),
        )
        .with_columns(
            (pl.col("act_points") - pl.col("exp_points")).alias("points_diff"),
            (pl.col("td_act") - pl.col("td_exp")).alias("td_diff"),
            (pl.col("yards_act") - pl.col("yards_exp")).alias("yards_diff"),
        )
        .with_columns(
            pl.when(pl.col("games_both") > 0)
            .then(pl.col("points_diff") / pl.col("games_both"))
            .otherwise(None)
            .alias("ppg_diff"),
        )
        .select(OUTPUT_COLUMNS)
        .sort("season", "player_id")
    )
    return out


def compute_summary(
    seasons: Sequence[int] | None = None,
    cfg: LeagueConfig | None = None,
    per_season: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """One row per player_id, flattened onto the latest season (and the previous one for `td_diff`).

    Column names carry the real season numbers, so with `settings.history_seasons == [2023, 2024, 2025]` this is
    `ppg_diff_2025, td_diff_2025, td_diff_2024, exp_points_2025, act_points_2025`. Players with no REG week in
    any requested season are absent (the Phase 3 assembler left-joins, so rookies stay null).
    """
    seasons = sorted({int(s) for s in (seasons or settings.history_seasons)})
    df = per_season if per_season is not None else compute(seasons, cfg)
    latest = seasons[-1]
    prev = seasons[-2] if len(seasons) > 1 else None

    out = df.select("player_id").unique()
    cur = df.filter(pl.col("season") == latest).select(
        "player_id",
        pl.col("ppg_diff").alias(f"ppg_diff_{latest}"),
        pl.col("td_diff").alias(f"td_diff_{latest}"),
        pl.col("exp_points").alias(f"exp_points_{latest}"),
        pl.col("act_points").alias(f"act_points_{latest}"),
    )
    out = out.join(cur, on="player_id", how="left")
    order = ["player_id", f"ppg_diff_{latest}", f"td_diff_{latest}"]
    if prev is not None:
        back = df.filter(pl.col("season") == prev).select(
            "player_id", pl.col("td_diff").alias(f"td_diff_{prev}")
        )
        out = out.join(back, on="player_id", how="left")
        order.append(f"td_diff_{prev}")
    order += [f"exp_points_{latest}", f"act_points_{latest}"]
    return out.select(order).sort("player_id")
