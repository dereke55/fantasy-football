"""Phase 3 — per-team offensive tendencies, REG only, from real weekly stat lines.

Source: ``raw_nflverse_stats_player_week`` filtered to ``season_type = 'REG'`` (POST rows stay in the table
and are excluded by filter, never by deletion). One row per (team, season) — 32 teams x len(seasons).

Everything here is volume, not points: no vendor fantasy_points column is read anywhere.

Definitions
  pass_attempts / rush_attempts  Sum of ``attempts`` / ``carries`` over every player who logged a REG line for
                                 that club. A player traded mid-season contributes to each club separately,
                                 because ``team`` is carried on the weekly row.
  games                          Distinct REG weeks in which the club appears (a bye week produces no rows,
                                 so this is 17 for a healthy full season).
  pass_rate                      pass_attempts / (pass_attempts + rush_attempts). Sacks are not plays here
                                 (nflverse charges a sack to ``sacks_suffered``, not to ``attempts``), so this
                                 is dropback-excluding-sacks pass rate, which runs a little below PFF's.
  target_concentration_top2      Share of the club's targets taken by its two biggest target earners.
  rb_carry_share_top1            The club's single busiest RB (``position = 'RB'`` on the weekly row) as a
                                 share of ALL team carries, QB scrambles and WR sweeps included.
"""
from __future__ import annotations

import polars as pl

from app.config import settings
from app.db import engine

TOP_TARGET_EARNERS = 2


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def player_weeks(seasons: list[int]) -> pl.DataFrame:
    """Every REG player-week stat line needed for the team aggregates."""
    season_list = ", ".join(str(int(s)) for s in seasons)
    sql = (
        "select season, week, team, player_id, position, "
        "coalesce(attempts, 0) as attempts, coalesce(carries, 0) as carries, "
        "coalesce(targets, 0) as targets, coalesce(passing_tds, 0) as passing_tds, "
        "coalesce(rushing_tds, 0) as rushing_tds "
        "from raw_nflverse_stats_player_week "
        f"where season_type = 'REG' and season in ({season_list}) and team is not null"
    )
    return _q(sql).with_columns(
        pl.col("season").cast(pl.Int32),
        pl.col("week").cast(pl.Int32),
        pl.col("attempts").cast(pl.Int64),
        pl.col("carries").cast(pl.Int64),
        pl.col("targets").cast(pl.Int64),
        pl.col("passing_tds").cast(pl.Int64),
        pl.col("rushing_tds").cast(pl.Int64),
    )


def compute(seasons: list[int] | None = None) -> pl.DataFrame:
    """One row per (team, season).

    Columns: team, season, games, pass_attempts, rush_attempts, pass_attempts_pg, rush_attempts_pg, plays_pg,
    pass_rate, targets_total, carries_total, pass_td_total, rush_td_total, target_concentration_top2,
    rb_carry_share_top1."""
    seasons = list(seasons or settings.history_seasons)
    weeks = player_weeks(seasons)
    if weeks.is_empty():
        return weeks

    team = weeks.group_by(["team", "season"]).agg(
        games=pl.col("week").n_unique().cast(pl.Int32),
        pass_attempts=pl.col("attempts").sum(),
        rush_attempts=pl.col("carries").sum(),
        targets_total=pl.col("targets").sum(),
        carries_total=pl.col("carries").sum(),
        pass_td_total=pl.col("passing_tds").sum(),
        rush_td_total=pl.col("rushing_tds").sum(),
    )

    top2 = (
        weeks.group_by(["team", "season", "player_id"])
        .agg(targets=pl.col("targets").sum())
        .sort(["team", "season", "targets"], descending=[False, False, True])
        .group_by(["team", "season"], maintain_order=True)
        .head(TOP_TARGET_EARNERS)
        .group_by(["team", "season"])
        .agg(top2_targets=pl.col("targets").sum())
    )
    top_rb = (
        weeks.filter(pl.col("position") == "RB")
        .group_by(["team", "season", "player_id"])
        .agg(carries=pl.col("carries").sum())
        .group_by(["team", "season"])
        .agg(top_rb_carries=pl.col("carries").max())
    )

    return (
        team.join(top2, on=["team", "season"], how="left")
        .join(top_rb, on=["team", "season"], how="left")
        .with_columns(
            pass_attempts_pg=(pl.col("pass_attempts") / pl.col("games")).round(2),
            rush_attempts_pg=(pl.col("rush_attempts") / pl.col("games")).round(2),
            plays_pg=((pl.col("pass_attempts") + pl.col("rush_attempts")) / pl.col("games")).round(2),
            pass_rate=(
                pl.col("pass_attempts") / (pl.col("pass_attempts") + pl.col("rush_attempts"))
            ).round(4),
            target_concentration_top2=(pl.col("top2_targets") / pl.col("targets_total")).round(4),
            rb_carry_share_top1=(
                pl.col("top_rb_carries").fill_null(0) / pl.col("carries_total")
            ).round(4),
        )
        .select(
            "team", "season", "games", "pass_attempts", "rush_attempts", "pass_attempts_pg",
            "rush_attempts_pg", "plays_pg", "pass_rate", "targets_total", "carries_total",
            "pass_td_total", "rush_td_total", "target_concentration_top2", "rb_carry_share_top1",
        )
        .sort(["season", "team"])
    )
