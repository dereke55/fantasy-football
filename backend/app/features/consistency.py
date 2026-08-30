"""Consistency features (DISPLAY ONLY) — week-to-week distribution of league-scored points, REG only.

Per `docs/phases/03-features.md` (Consistency): over REG weeks excluding weeks with < 3 opportunities
(opportunities = targets + carries + pass attempts), the mean / sd / floor (p25) / ceiling (p90) of weekly
`score()` points, plus how often the player cleared a startable weekly score.

Starter threshold for a position in a week = the weekly points of the (`league.num_teams` x `roster.slots[pos]`)-th
best player at that position that week, computed over EVERY nflverse REG row at that position (not just the players
in the hub) so the replacement level is the real one. FLEX is ignored, per spec.

`pct_weeks_above_starter` counts used weeks with points >= that threshold and `bust_rate` counts used weeks with
points < it, so the two are exact complements by construction. `boom_rate` is the share of used weeks in that
position's weekly top 12 (QB/TE) or top 24 (RB/WR), using the same ">= the N-th best score" tie rule.

These columns are display-only: they are never inputs to ranking, value or flags.
"""
from __future__ import annotations

from collections.abc import Sequence

import polars as pl

from app.config import settings
from app.db import engine
from app.scoring.adapters import from_nflverse_week
from app.scoring.config import LeagueConfig, load_league_config
from app.scoring.engine import score

# Positions that have a weekly startable baseline. K/DEF have no target/carry/attempt opportunity concept.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")
# "boom" = a weekly finish inside the positional starter pool everybody streams for.
BOOM_TOP_N: dict[str, int] = {"QB": 12, "TE": 12, "RB": 24, "WR": 24}
MIN_OPPORTUNITIES = 3
FLOOR_Q = 0.25
CEILING_Q = 0.90

# Stat columns consumed by app.scoring.adapters.NFLVERSE_WEEK (vendor fantasy_points columns excluded on purpose).
_STAT_COLS = (
    "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions",
    "rushing_yards", "rushing_tds", "rushing_2pt_conversions",
    "receptions", "receiving_yards", "receiving_tds", "receiving_2pt_conversions",
    "fumbles_lost_total", "special_teams_tds",
)

OUTPUT_COLUMNS = (
    "player_id", "gsis_id", "season", "position", "weeks_used",
    "weekly_mean", "weekly_sd", "cv", "floor_p25", "ceiling_p90",
    "pct_weeks_above_starter", "boom_rate", "bust_rate",
)


def _sql(seasons: Sequence[int]) -> str:
    season_list = ", ".join(str(int(s)) for s in seasons)
    pos_list = ", ".join(f"'{p}'" for p in POSITIONS)
    cols = ",\n               ".join(f"s.{c}" for c in _STAT_COLS)
    return f"""
        SELECT s.player_id AS gsis_id,
               s.season     AS season,
               s.week       AS week,
               s.position   AS position,
               COALESCE(s.targets, 0) + COALESCE(s.carries, 0) + COALESCE(s.attempts, 0) AS opportunities,
               {cols}
          FROM raw_nflverse_stats_player_week s
         WHERE s.season_type = 'REG'
           AND s.season IN ({season_list})
           AND s.position IN ({pos_list})
    """


def load_weeks(seasons: Sequence[int] | None = None) -> pl.DataFrame:
    """Every REG QB/RB/WR/TE player-week in the requested seasons (the full population, hub or not)."""
    seasons = list(seasons or settings.history_seasons)
    return pl.read_database(_sql(seasons), connection=engine, infer_schema_length=None)


def _with_points(weeks: pl.DataFrame, cfg: LeagueConfig) -> pl.DataFrame:
    rows = weeks.to_dicts()
    scoring = cfg.scoring
    pts = [score(from_nflverse_week(r), scoring, r.get("position")) for r in rows]
    return weeks.with_columns(pl.Series("points", pts, dtype=pl.Float64))


def weekly_thresholds(weeks: pl.DataFrame, cfg: LeagueConfig) -> pl.DataFrame:
    """One row per (season, week, position): `starter_threshold` and `boom_threshold` weekly point values."""
    starter_k = {p: cfg.league.num_teams * int(cfg.roster.slots.get(p, 0)) for p in POSITIONS}
    missing = [p for p, k in starter_k.items() if k <= 0]
    if missing:
        raise ValueError(f"roster.slots has no starter slot for {missing}; cannot build a starter threshold")
    return (
        weeks.group_by("season", "week", "position")
        .agg(pl.col("points").sort(descending=True).alias("_pts"))
        .with_columns(
            pl.col("position").replace_strict(starter_k, return_dtype=pl.Int64).alias("_k"),
            pl.col("position").replace_strict(BOOM_TOP_N, return_dtype=pl.Int64).alias("_boom_n"),
            pl.col("_pts").list.len().cast(pl.Int64).alias("_n"),
        )
        .with_columns(
            pl.col("_pts").list.get(pl.min_horizontal(pl.col("_k"), pl.col("_n")) - 1).alias("starter_threshold"),
            pl.col("_pts").list.get(
                pl.min_horizontal(pl.col("_boom_n"), pl.col("_n")) - 1
            ).alias("boom_threshold"),
        )
        .select("season", "week", "position", "starter_threshold", "boom_threshold")
    )


def compute(seasons: Sequence[int] | None = None, cfg: LeagueConfig | None = None) -> pl.DataFrame:
    """One row per (player_id, gsis_id, season) for hub players with at least one REG QB/RB/WR/TE week.

    A player whose every week had < 3 opportunities keeps his row with `weeks_used = 0` and null distribution
    metrics (no exception). `weekly_sd` / `cv` are also null when only one week qualifies.
    """
    seasons = list(seasons or settings.history_seasons)
    cfg = cfg or load_league_config()
    weeks = _with_points(load_weeks(seasons), cfg)
    weeks = weeks.join(weekly_thresholds(weeks, cfg), on=["season", "week", "position"], how="left")

    hub = pl.read_database(
        "SELECT id AS player_id, gsis_id FROM players WHERE gsis_id IS NOT NULL",
        connection=engine,
        infer_schema_length=None,
    )
    weeks = weeks.join(hub, on="gsis_id", how="inner")

    base = (
        weeks.group_by("player_id", "gsis_id", "season")
        .agg(pl.col("position").drop_nulls().mode().first().alias("position"))
    )
    used = weeks.filter(pl.col("opportunities") >= MIN_OPPORTUNITIES)
    agg = used.group_by("player_id", "gsis_id", "season").agg(
        pl.len().alias("weeks_used"),
        pl.col("points").mean().alias("weekly_mean"),
        pl.col("points").std().alias("weekly_sd"),
        pl.col("points").quantile(FLOOR_Q, interpolation="linear").alias("floor_p25"),
        pl.col("points").quantile(CEILING_Q, interpolation="linear").alias("ceiling_p90"),
        (pl.col("points") >= pl.col("starter_threshold")).mean().alias("pct_weeks_above_starter"),
        (pl.col("points") >= pl.col("boom_threshold")).mean().alias("boom_rate"),
        (pl.col("points") < pl.col("starter_threshold")).mean().alias("bust_rate"),
    )
    return (
        base.join(agg, on=["player_id", "gsis_id", "season"], how="left")
        .with_columns(pl.col("weeks_used").fill_null(0).cast(pl.Int64))
        .with_columns(
            pl.when((pl.col("weekly_mean").is_not_null()) & (pl.col("weekly_mean") > 0))
            .then(pl.col("weekly_sd") / pl.col("weekly_mean"))
            .otherwise(None)
            .alias("cv")
        )
        .select(OUTPUT_COLUMNS)
        .sort("season", "player_id")
    )


def compute_summary(
    seasons: Sequence[int] | None = None,
    cfg: LeagueConfig | None = None,
    per_season: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """One row per player_id, flattened onto the latest requested season.

    Column names carry the real season number, so with `settings.history_seasons == [2023, 2024, 2025]` this is
    `weekly_sd_2025, cv_2025, floor_p25_2025, ceiling_p90_2025, pct_weeks_above_starter_2025, boom_rate_2025,
    bust_rate_2025, weeks_used_2025`.
    """
    seasons = sorted({int(s) for s in (seasons or settings.history_seasons)})
    df = per_season if per_season is not None else compute(seasons, cfg)
    latest = seasons[-1]
    metrics = ("weekly_sd", "cv", "floor_p25", "ceiling_p90",
               "pct_weeks_above_starter", "boom_rate", "bust_rate", "weeks_used")
    cur = df.filter(pl.col("season") == latest).select(
        "player_id", *[pl.col(m).alias(f"{m}_{latest}") for m in metrics]
    )
    return (
        df.select("player_id").unique()
        .join(cur, on="player_id", how="left")
        .select("player_id", *[f"{m}_{latest}" for m in metrics])
        .sort("player_id")
    )
