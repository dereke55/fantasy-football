"""Phase 3 — 2026 depth-chart position for every hub QB/RB/WR/TE.

Source: ``raw_nflverse_depth_charts`` (season 2026 only — nflverse's daily ESPN scrape; 162 distinct ``dt``
snapshots from 2026-03-22T06:38:42Z to 2026-08-29T12:56:08Z, all 32 teams present at the latest ``dt``).

``dt`` is stored as an ISO-8601 UTC string ("2026-08-29T12:56:08Z"), which sorts lexicographically, but it is
parsed to a real datetime here so the 30-day lookback is arithmetic rather than string surgery.

Rows are restricted to the player's HUB position (``pos_abb == players.position``): the same player also shows
up under KR/PR and, for a few teams, in more than one receiver slot, and those rows carry their own pos_rank.
"""
from __future__ import annotations

from datetime import timedelta

import polars as pl

from app.config import settings
from app.db import engine
from app.features.durability import FANTASY_POSITIONS, hub_players

DT_FORMAT = "%Y-%m-%dT%H:%M:%SZ"
LOOKBACK_DAYS = 30


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def depth_chart_rows(season: int) -> pl.DataFrame:
    """(dt, team, gsis_id, pos_abb, pos_rank) for one season, restricted to fantasy positions."""
    positions = ", ".join(f"'{p}'" for p in FANTASY_POSITIONS)
    df = _q(
        "select dt, team, gsis_id, pos_abb, pos_rank from raw_nflverse_depth_charts "
        f"where season = {int(season)} and gsis_id is not null and pos_rank is not null "
        f"and pos_abb in ({positions})"
    )
    if df.is_empty():
        return df
    return df.with_columns(
        dt=pl.col("dt").str.strptime(pl.Datetime, DT_FORMAT),
        pos_rank=pl.col("pos_rank").cast(pl.Int32),
    )


def _rank_at(rows: pl.DataFrame, target: pl.DataFrame) -> pl.DataFrame:
    """Best (lowest) pos_rank per (gsis_id, team, pos_abb) at each team's target dt."""
    return (
        rows.join(target, on="team", how="inner")
        .filter(pl.col("dt") == pl.col("target_dt"))
        .group_by(["gsis_id", "team", "pos_abb"])
        .agg(pos_rank=pl.col("pos_rank").min())
    )


def compute(season: int | None = None) -> pl.DataFrame:
    """One row per hub QB/RB/WR/TE (players absent from every chart get nulls, never missing rows).

    Columns: player_id, gsis_id, name, position, team, depth_pos, depth_rank, depth_dt,
    depth_rank_30d_ago, depth_rank_change_30d, appears_on_chart.

    ``depth_rank``           best pos_rank at that team's LATEST dt, within the player's hub position.
    ``depth_dt``             the dt that rank was read at (per team, so a stale club cannot poison the rest).
    ``depth_rank_30d_ago``   rank at the latest dt <= (team's latest dt - 30 days); null when the player was
                             not on the chart then (a rookie who first appears in August, say).
    ``depth_rank_change_30d`` current - 30-days-ago. NEGATIVE means the player moved UP the chart.
    """
    season = int(season or settings.current_season)
    hub = hub_players()
    rows = depth_chart_rows(season)

    empty = hub.select("player_id", "gsis_id", "name", "position", "team").with_columns(
        depth_pos=pl.lit(None, dtype=pl.String),
        depth_rank=pl.lit(None, dtype=pl.Int32),
        depth_dt=pl.lit(None, dtype=pl.Datetime),
        depth_rank_30d_ago=pl.lit(None, dtype=pl.Int32),
        depth_rank_change_30d=pl.lit(None, dtype=pl.Int32),
        appears_on_chart=pl.lit(value=False),
    )
    if rows.is_empty():
        return empty

    # the per-team snapshot clock comes from the WHOLE chart, but a rank is only ever read from the row that
    # matches the player's hub position (a handful of fringe players are listed under a different pos_abb
    # than the hub gives them — 5 on the 2026-08-29 chart — and those are reported as not on the chart)
    latest = rows.group_by("team").agg(target_dt=pl.col("dt").max())
    prior_target = (
        rows.join(latest, on="team", how="inner")
        .filter(pl.col("dt") <= (pl.col("target_dt") - pl.duration(days=LOOKBACK_DAYS)))
        .group_by("team")
        .agg(target_dt=pl.col("dt").max())
    )
    mine = rows.join(
        hub.select("gsis_id", "position"),
        left_on=["gsis_id", "pos_abb"],
        right_on=["gsis_id", "position"],
        how="inner",
    )

    current = _rank_at(mine, latest).join(latest.rename({"target_dt": "depth_dt"}), on="team", how="left")
    prior = _rank_at(mine, prior_target).rename({"pos_rank": "depth_rank_30d_ago"})

    # a player on two clubs' charts (mid-camp move) keeps the row from the most recently refreshed chart
    current = current.sort(["gsis_id", "depth_dt", "pos_rank"], descending=[False, True, False]).unique(
        subset=["gsis_id"], keep="first", maintain_order=True
    )

    joined = (
        hub.select("player_id", "gsis_id", "name", "position")
        .join(
            current.rename({"team": "chart_team", "pos_abb": "depth_pos", "pos_rank": "depth_rank"}),
            on="gsis_id",
            how="left",
        )
        .join(
            prior.rename({"team": "chart_team", "pos_abb": "depth_pos"}),
            on=["gsis_id", "chart_team", "depth_pos"],
            how="left",
        )
    )
    return (
        joined.join(hub.select("player_id", hub_team="team"), on="player_id", how="left")
        .with_columns(
            team=pl.coalesce(pl.col("chart_team"), pl.col("hub_team")),
            appears_on_chart=pl.col("depth_rank").is_not_null(),
            depth_rank_change_30d=(pl.col("depth_rank") - pl.col("depth_rank_30d_ago")).cast(pl.Int32),
        )
        .select(
            "player_id", "gsis_id", "name", "position", "team", "depth_pos", "depth_rank", "depth_dt",
            "depth_rank_30d_ago", "depth_rank_change_30d", "appears_on_chart",
        )
        .sort("player_id")
    )
