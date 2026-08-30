"""Phase 3 — production & opportunity features from nflverse weekly stats (REG only).

Two entry points:

* :func:`compute`         — one row per ``(player_id, gsis_id, season)``, per-season production/opportunity.
* :func:`compute_summary` — one row per hub ``player_id`` (QB/RB/WR/TE), the season rows pivoted wide plus the
  recency-weighted trend, the year-over-year deltas and the "same role" bookkeeping Phase 6 needs.

Hard rules honoured here (see ``CLAUDE.md``):

* **REG only.** ``season_type == 'REG'`` is a filter in the SQL; POST rows are never deleted, just excluded.
* **Explicit seasons.** ``seasons`` is always passed in; nothing defaults to "current".
* **Never surface vendor fantasy points.** Every point in the output comes from ``app.scoring.engine.score`` applied
  to ``app.scoring.adapters.from_nflverse_week`` under ``config/league.yaml``. The vendor ``fantasy_points`` /
  ``fantasy_points_ppr`` columns are not even selected by the SQL below (a test cross-checks against them, nothing else).
* **Real data only.** Every row comes from ``raw_nflverse_stats_player_week`` joined to the players hub; nothing is
  synthesised. Players without history are carried as null rows by :func:`compute_summary`, never invented.

Conventions worth knowing before reading the code:

*Position* is the player's dominant nflverse ``position_group`` for that season (so nflverse's ``FB`` rows fold into
``RB``, which is what fantasy scoring cares about), not the 2026 hub position. A player-season is kept when that
dominant group is QB/RB/WR/TE; **all** of his REG rows are then aggregated, so season totals reconcile with
``raw_nflverse_stats_player_reg`` even for the handful of players with an off-position week.

*Team* is the most-frequent REG team of that season (ties broken by the later week), and ``role_key`` is
``team || '-' || position`` — the "same team AND same position" key the weighted trend is restricted to.

*Shares* are season-level: ``targets / team targets``. For the ~60-90 players a season who change teams the share is
summed per team stint (``Σ_team player targets on team / that team's season targets``), which is exact for the ~95 %
of player-seasons spent on one team and is the closest season-level analogue for the rest. Summed over every player
in the league those shares total exactly 1.0 per team-season; summed over the rows of :func:`compute` they do not,
because a row is filed under the player's most-frequent team while his share covers all his stints (SEA 2025 totals
1.12; teams whose 2025 contributors have left the 2026 hub total under 1.0). The weekly-mean variant
``target_share_wk_mean`` (mean of nflverse's own weekly ``target_share``) is kept alongside it for comparison; it
weights every game equally regardless of team volume.
"""
from __future__ import annotations

import polars as pl

from app.db import engine
from app.scoring.adapters import from_nflverse_week
from app.scoring.config import LeagueConfig, load_league_config
from app.scoring.engine import score

#: Fantasy positions carried by the historical feature layer.
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: Minimum REG games in a season for a positional PPG rank (below it the per-game rate is noise -> null rank).
MIN_GAMES_FOR_PPG_RANK: int = 8

#: Recency weights for the weighted PPG trend, most recent season first (0.5 / 0.3 / 0.2 per the Phase 3 spec).
RECENCY_WEIGHTS: tuple[float, ...] = (0.5, 0.3, 0.2)

#: Columns pulled from the raw weekly table. Everything the scoring adapter needs plus the opportunity columns.
#: The vendor ``fantasy_points*`` columns are deliberately absent.
_WEEK_COLUMNS: tuple[str, ...] = (
    "week", "team", "position", "position_group",
    "targets", "target_share", "air_yards_share", "wopr",
    "carries", "rushing_yards", "receptions", "receiving_yards",
    "passing_yards", "passing_tds", "passing_interceptions", "passing_2pt_conversions",
    "rushing_tds", "rushing_2pt_conversions", "receiving_tds", "receiving_2pt_conversions",
    "fumbles_lost_total", "special_teams_tds",
)

COMPUTE_COLUMNS: tuple[str, ...] = (
    "player_id", "gsis_id", "season", "position", "team", "role_key",
    "games", "points", "ppg", "pos_rank_ppg", "pos_rank_points",
    "targets", "targets_pg", "target_share", "target_share_wk_mean",
    "air_yards_share", "wopr",
    "carries", "carries_pg", "carry_share",
    "receptions", "receiving_yards", "rushing_yards", "opportunities_pg",
)


def _season_list(seasons: list[int]) -> list[int]:
    """Validate and normalise the explicit season list (ints only — the values go straight into SQL)."""
    if not seasons:
        raise ValueError("seasons must be a non-empty explicit list, e.g. [2023, 2024, 2025]")
    out = sorted({int(s) for s in seasons})
    if any(s < 1999 or s > 2100 for s in out):
        raise ValueError(f"implausible seasons: {seasons}")
    return out


def _sql_in(seasons: list[int]) -> str:
    return ", ".join(str(s) for s in seasons)


def _read_weeks(seasons: list[int]) -> pl.DataFrame:
    """REG weekly rows for hub players, one row per (player, season, week)."""
    cols = ", ".join(f"w.{c}" for c in _WEEK_COLUMNS)
    sql = f"""
        SELECT p.id AS player_id, w.player_id AS gsis_id, w.season, {cols}
        FROM raw_nflverse_stats_player_week w
        JOIN players p ON p.gsis_id = w.player_id
        WHERE w.season_type = 'REG' AND w.season IN ({_sql_in(seasons)})
    """
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def _read_team_totals(seasons: list[int]) -> pl.DataFrame:
    """Team REG targets/carries per season over EVERY player (the share denominators; no hub join, no position filter)."""
    sql = f"""
        SELECT season, team,
               SUM(COALESCE(targets, 0)) AS team_targets,
               SUM(COALESCE(carries, 0)) AS team_carries
        FROM raw_nflverse_stats_player_week
        WHERE season_type = 'REG' AND season IN ({_sql_in(seasons)})
        GROUP BY season, team
    """
    df = pl.read_database(sql, connection=engine, infer_schema_length=None)
    return df.with_columns(
        pl.col("team_targets").cast(pl.Float64), pl.col("team_carries").cast(pl.Float64)
    )


def _read_hub_players() -> pl.DataFrame:
    sql = f"""
        SELECT id AS player_id, gsis_id, position, team
        FROM players
        WHERE position IN ({", ".join(f"'{p}'" for p in POSITIONS)})
    """
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def _dominant(weeks: pl.DataFrame, column: str, alias: str) -> pl.DataFrame:
    """Most-frequent value of `column` per (player_id, season); ties broken by the later week."""
    return (
        weeks.group_by(["player_id", "season", column])
        .agg(_n=pl.len(), _last_week=pl.col("week").max())
        .sort(["player_id", "season", "_n", "_last_week"], descending=[False, False, True, True])
        .group_by(["player_id", "season"], maintain_order=True)
        .first()
        .select("player_id", "season", pl.col(column).alias(alias))
    )


def _with_points(weeks: pl.DataFrame, cfg: LeagueConfig) -> pl.DataFrame:
    """Score every weekly row through app.scoring (the only place fantasy points are produced)."""
    points = [
        score(from_nflverse_week(row), cfg.scoring, row["position"])
        for row in weeks.iter_rows(named=True)
    ]
    return weeks.with_columns(pl.Series("points", points, dtype=pl.Float64))


def _season_shares(weeks: pl.DataFrame, team_totals: pl.DataFrame) -> pl.DataFrame:
    """Season target/carry share, summed over team stints so mid-season trades stay exact per stint."""
    per_stint = (
        weeks.group_by(["player_id", "season", "team"])
        .agg(
            _tgt=pl.col("targets").fill_null(0).sum().cast(pl.Float64),
            _car=pl.col("carries").fill_null(0).sum().cast(pl.Float64),
        )
        .join(team_totals, on=["season", "team"], how="left")
    )
    return (
        per_stint.with_columns(
            _tgt_share=pl.when(pl.col("team_targets") > 0).then(pl.col("_tgt") / pl.col("team_targets")).otherwise(0.0),
            _car_share=pl.when(pl.col("team_carries") > 0).then(pl.col("_car") / pl.col("team_carries")).otherwise(0.0),
        )
        .group_by(["player_id", "season"])
        .agg(target_share=pl.col("_tgt_share").sum(), carry_share=pl.col("_car_share").sum())
    )


def _positional_ranks(seasons_df: pl.DataFrame) -> pl.DataFrame:
    """pos_rank_ppg (>= MIN_GAMES_FOR_PPG_RANK games only, else null) and pos_rank_points (every player-season).

    Both are 1 = best within (season, position); ties share the lower rank ("min" method).
    """
    ppg_rank = (
        seasons_df.filter(pl.col("games") >= MIN_GAMES_FOR_PPG_RANK)
        .select(
            "player_id", "season",
            pos_rank_ppg=pl.col("ppg").rank(method="min", descending=True).over(["season", "position"]).cast(pl.Int32),
        )
    )
    points_rank = seasons_df.select(
        "player_id", "season",
        pos_rank_points=pl.col("points").rank(method="min", descending=True).over(["season", "position"]).cast(pl.Int32),
    )
    return seasons_df.join(ppg_rank, on=["player_id", "season"], how="left").join(
        points_rank, on=["player_id", "season"], how="left"
    )


def compute(seasons: list[int]) -> pl.DataFrame:
    """Per-season REG production and opportunity, one row per (player_id, gsis_id, season).

    Only players in the hub (``players.gsis_id = raw_nflverse_stats_player_week.player_id``) whose dominant
    nflverse ``position_group`` for that season is QB/RB/WR/TE, and who have at least one REG game, get a row.

    Columns: see :data:`COMPUTE_COLUMNS`.

    * ``games``  — REG weeks with a stat row (matches ``raw_nflverse_stats_player_reg.games``).
    * ``points`` — Σ ``score(from_nflverse_week(week), cfg.scoring, position)`` under ``config/league.yaml``.
    * ``pos_rank_ppg``   — rank of ``ppg`` within (season, position) restricted to players with
      >= :data:`MIN_GAMES_FOR_PPG_RANK` games; null for everyone below that bar (their rate is small-sample noise).
    * ``pos_rank_points`` — rank of season ``points`` within (season, position) over **every** player-season with
      >= 1 game; total points is a volume stat, so no games filter applies.
    * ``target_share`` / ``carry_share`` — season-level, player's share of his team's season targets/carries
      (summed per team stint for traded players). ``target_share_wk_mean`` is the mean of nflverse's weekly
      ``target_share`` column, kept for comparison only.
    * ``air_yards_share`` / ``wopr`` — mean of the weekly nflverse columns over the player's REG games.
    * ``opportunities_pg`` — (targets + carries) / games.
    """
    seasons = _season_list(seasons)
    cfg = load_league_config()
    weeks = _read_weeks(seasons)
    if weeks.is_empty():
        return pl.DataFrame(schema=dict.fromkeys(COMPUTE_COLUMNS, pl.Null))

    season_pos = _dominant(weeks, "position_group", "position").filter(pl.col("position").is_in(POSITIONS))
    season_team = _dominant(weeks, "team", "team_season")
    weeks = (
        weeks.drop("position")
        .join(season_pos, on=["player_id", "season"], how="inner")
        .join(season_team, on=["player_id", "season"], how="left")
    )
    weeks = _with_points(weeks, cfg)

    agg = (
        weeks.group_by(["player_id", "gsis_id", "season", "position", "team_season"])
        .agg(
            games=pl.len().cast(pl.Int32),
            points=pl.col("points").sum(),
            targets=pl.col("targets").fill_null(0).sum().cast(pl.Int32),
            carries=pl.col("carries").fill_null(0).sum().cast(pl.Int32),
            receptions=pl.col("receptions").fill_null(0).sum().cast(pl.Int32),
            receiving_yards=pl.col("receiving_yards").fill_null(0).sum().cast(pl.Int32),
            rushing_yards=pl.col("rushing_yards").fill_null(0).sum().cast(pl.Int32),
            target_share_wk_mean=pl.col("target_share").mean(),
            air_yards_share=pl.col("air_yards_share").mean(),
            wopr=pl.col("wopr").mean(),
        )
        .rename({"team_season": "team"})
        .with_columns(
            role_key=pl.concat_str([pl.col("team"), pl.col("position")], separator="-"),
            ppg=pl.col("points") / pl.col("games"),
            targets_pg=pl.col("targets") / pl.col("games"),
            carries_pg=pl.col("carries") / pl.col("games"),
            opportunities_pg=(pl.col("targets") + pl.col("carries")) / pl.col("games"),
        )
        .join(_season_shares(weeks, _read_team_totals(seasons)), on=["player_id", "season"], how="left")
    )
    return (
        _positional_ranks(agg)
        .select(*COMPUTE_COLUMNS)
        .sort(["season", "position", "pos_rank_points", "player_id"])
    )


def _recency_weight_map(seasons: list[int]) -> dict[int, float]:
    """Most recent season -> 0.5, then 0.3, then 0.2; any season older than the third gets weight 0.0."""
    ordered = sorted(seasons, reverse=True)
    return {
        s: (RECENCY_WEIGHTS[i] if i < len(RECENCY_WEIGHTS) else 0.0)
        for i, s in enumerate(ordered)
    }


def _wide_by_season(prod: pl.DataFrame, seasons: list[int]) -> pl.DataFrame:
    """Pivot the per-season metrics into `<metric>_<season>` columns, one row per player_id."""
    metrics = ("ppg", "games", "target_share", "carry_share", "opportunities_pg")
    out = prod.select("player_id").unique()
    for season in seasons:
        chunk = prod.filter(pl.col("season") == season).select(
            "player_id", *[pl.col(m).alias(f"{m}_{season}") for m in metrics]
        )
        out = out.join(chunk, on="player_id", how="left")
    return out


def _trend(prod: pl.DataFrame, seasons: list[int]) -> pl.DataFrame:
    """Recency-weighted PPG over same-role seasons only, plus the same-role bookkeeping columns.

    The reference role is the player's ``role_key`` in the most recent season **he actually played** among
    ``seasons`` (2025 for almost everyone; for a player with no 2025 season — retired-from-2025, missed the whole
    year, or last seen in 2023/2024 — his most recent season is used instead, and it is reported in ``ref_season``
    so a WHY bullet can say which year the trend is anchored on).

    Only seasons whose ``role_key`` equals that reference (same team AND same position) contribute; the 0.5 / 0.3 /
    0.2 weights are renormalised over the seasons actually used, so a player with a 2025+2023 match is
    ``(0.5*ppg_2025 + 0.2*ppg_2023) / 0.7``.
    """
    weights = _recency_weight_map(seasons)
    ref = (
        prod.sort(["player_id", "season"])
        .group_by("player_id", maintain_order=True)
        .last()
        .select("player_id", ref_role_key=pl.col("role_key"), ref_season=pl.col("season"))
    )
    same_role = (
        prod.join(ref, on="player_id", how="left")
        .filter(pl.col("role_key") == pl.col("ref_role_key"))
        .with_columns(_w=pl.col("season").replace_strict(weights, default=0.0, return_dtype=pl.Float64))
    )
    agg = same_role.group_by("player_id").agg(
        _wsum=pl.col("_w").sum(),
        _wppg=(pl.col("_w") * pl.col("ppg")).sum(),
        same_role_seasons=pl.len().cast(pl.Int32),
        has_8game_same_role_season=(pl.col("games") >= MIN_GAMES_FOR_PPG_RANK).any(),
    )
    return (
        ref.join(agg, on="player_id", how="left")
        .with_columns(
            ppg_trend_w=pl.when(pl.col("_wsum") > 0).then(pl.col("_wppg") / pl.col("_wsum")).otherwise(None)
        )
        .select("player_id", "ref_season", "ref_role_key", "ppg_trend_w",
                "same_role_seasons", "has_8game_same_role_season")
    )


def compute_summary(seasons: list[int]) -> pl.DataFrame:
    """One row per hub QB/RB/WR/TE player, the season features pivoted wide plus trend and YoY deltas.

    **Every** hub player at those positions gets a row: rookies and anyone else with no REG history keep null
    metrics rather than being dropped (``same_role_seasons`` is 0 and ``has_8game_same_role_season`` is false for
    them, since those two are a count and a flag, not measurements).

    Columns (for ``seasons=[2023, 2024, 2025]``): ``player_id, gsis_id, position, team,
    ppg_2023/2024/2025, games_2023/2024/2025, target_share_2023/2024/2025, carry_share_2023/2024/2025,
    opportunities_pg_2025, ppg_trend_w, yoy_ppg_delta, yoy_target_share_delta, yoy_carry_share_delta,
    same_role_seasons, has_8game_same_role_season, ref_season, ref_role_key``.

    ``opportunities_pg_<latest>`` and the ``yoy_*`` deltas use the two most recent seasons in ``seasons``
    (2025 minus 2024); a delta is null when either season is missing for that player.

    ``ppg_trend_w`` is the recency-weighted, same-role PPG described in :func:`_trend`; ``ref_season`` /
    ``ref_role_key`` record which season and role the trend was anchored on.
    """
    seasons = _season_list(seasons)
    latest = seasons[-1]
    prior = seasons[-2] if len(seasons) >= 2 else None

    base = _read_hub_players()
    prod = compute(seasons)
    out = base.join(_wide_by_season(prod, seasons), on="player_id", how="left").join(
        _trend(prod, seasons), on="player_id", how="left"
    )

    if prior is None:
        deltas = [pl.lit(None, dtype=pl.Float64).alias(n)
                  for n in ("yoy_ppg_delta", "yoy_target_share_delta", "yoy_carry_share_delta")]
    else:
        deltas = [
            (pl.col(f"{m}_{latest}") - pl.col(f"{m}_{prior}")).alias(f"yoy_{m}_delta")
            for m in ("ppg", "target_share", "carry_share")
        ]
    out = out.with_columns(
        *deltas,
        same_role_seasons=pl.col("same_role_seasons").fill_null(0).cast(pl.Int32),
        has_8game_same_role_season=pl.col("has_8game_same_role_season").fill_null(value=False),
    )

    cols = ["player_id", "gsis_id", "position", "team"]
    cols += [f"ppg_{s}" for s in seasons] + [f"games_{s}" for s in seasons]
    cols += [f"target_share_{s}" for s in seasons] + [f"carry_share_{s}" for s in seasons]
    cols += [
        f"opportunities_pg_{latest}", "ppg_trend_w",
        "yoy_ppg_delta", "yoy_target_share_delta", "yoy_carry_share_delta",
        "same_role_seasons", "has_8game_same_role_season", "ref_season", "ref_role_key",
    ]
    return out.select(cols).sort("player_id")
