"""Season-level estimate of the per-game yardage bonuses.

The league awards yardage bonuses per game (100/150/200 rushing and receiving, 350/400/425 passing). A season
projection is a season TOTAL, so the bonuses cannot be read off it — they have to be estimated from how often the
player actually clears the thresholds. This module measures that rate from real weekly history (2023-2025 REG) and
scales it by expected games.

Players without history get 0. That is a deliberate under-estimate rather than an invented rate: it costs a
projected rookie a few points, and it never inflates anyone.
"""
from __future__ import annotations

import polars as pl

from app.db import engine
from app.scoring.adapters import from_nflverse_week
from app.scoring.config import LeagueConfig
from app.scoring.engine import bonus_points


def weekly_bonus_rate(cfg: LeagueConfig, seasons: list[int]) -> pl.DataFrame:
    """Per player: mean per-game bonus points over their REG weeks, weighted toward recent seasons."""
    if not cfg.scoring.bonuses:
        return pl.DataFrame({"player_id": [], "bonus_pg": []},
                            schema={"player_id": pl.Int64, "bonus_pg": pl.Float64})
    seasons_sql = ", ".join(str(s) for s in seasons)
    df = pl.read_database(
        "select p.id as player_id, w.season, w.passing_yards, w.rushing_yards, w.receiving_yards "
        "from raw_nflverse_stats_player_week w join players p on p.gsis_id = w.player_id "
        f"where w.season_type = 'REG' and w.season in ({seasons_sql})",
        connection=engine, infer_schema_length=None,
    )
    if df.is_empty():
        return pl.DataFrame({"player_id": [], "bonus_pg": []},
                            schema={"player_id": pl.Int64, "bonus_pg": pl.Float64})
    weights = {s: w for s, w in zip(sorted(seasons, reverse=True), (0.5, 0.3, 0.2), strict=False)}
    rows = []
    for r in df.to_dicts():
        line = from_nflverse_week(r, strict=False)
        rows.append({"player_id": r["player_id"], "season": r["season"],
                     "bonus": bonus_points(line, cfg.scoring)})
    per_season = (
        pl.DataFrame(rows)
        .group_by(["player_id", "season"])
        .agg(pl.col("bonus").mean().alias("bonus_pg"), pl.len().alias("weeks"))
    )
    per_season = per_season.with_columns(
        w=pl.col("season").replace_strict(weights, default=0.0) * pl.col("weeks").clip(upper_bound=17) / 17
    )
    return (
        per_season.group_by("player_id")
        .agg(((pl.col("bonus_pg") * pl.col("w")).sum() / pl.col("w").sum()).alias("bonus_pg"))
        .with_columns(pl.col("bonus_pg").fill_nan(0.0))
    )


def season_bonus_points(cfg: LeagueConfig, seasons: list[int]) -> dict[int, float]:
    """player_id -> expected bonus points per game (multiply by E[games] for the season contribution)."""
    df = weekly_bonus_rate(cfg, seasons)
    return {r["player_id"]: float(r["bonus_pg"] or 0.0) for r in df.to_dicts()}
