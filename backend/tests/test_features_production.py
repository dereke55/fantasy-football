"""Phase 3 production features against the REAL Postgres data (read-only, no fixtures, no mock rows).

Every expected value is derived independently of `app.features.production`:

* season totals come from `raw_nflverse_stats_player_reg` (nflverse's own REG aggregate, `recent_team` + `games`,
  no week column) — a different table from the weekly one the feature module reads;
* target/carry shares are recomputed with SQL straight off `raw_nflverse_stats_player_week`;
* league points are rebuilt from the REG season totals times the `config/league.yaml` weights;
* the vendor `fantasy_points` column is touched in exactly one place, as a cross-check that our points are NOT it.

Kept to one or two seasons so the module stays fast (~2 s of DB work in total).
"""
from __future__ import annotations

import polars as pl
import pytest

from app.db import engine
from app.features.production import (
    COMPUTE_COLUMNS,
    MIN_GAMES_FOR_PPG_RANK,
    POSITIONS,
    RECENCY_WEIGHTS,
    compute,
    compute_summary,
)
from app.scoring.config import load_league_config

SEASON = 2025
PRIOR = 2024
# Named players verified against nflverse REG totals; Bijan's 2025 line (287 att / 1478 yds / 103 tgt / 820 rec yds)
# also matches ESPN's independent figures recorded in docs/phases/03-features.md.
NAMED = ("Bijan Robinson", "Puka Nacua", "Ja'Marr Chase")
# 2026 rookie, ARI R1 — no NFL history at all, must still appear in compute_summary with nulls.
ROOKIE_GSIS = "00-0041027"
# Traded 2025: PIT-WR in 2023/2024 -> DAL-WR in 2025, so only 2025 counts toward the same-role trend.
TRADED_NAME = "George Pickens"


def _sql(query: str) -> pl.DataFrame:
    return pl.read_database(query, connection=engine, infer_schema_length=None)


def _quote(name: str) -> str:
    return "'" + name.replace("'", "''") + "'"


@pytest.fixture(scope="module")
def prod() -> pl.DataFrame:
    return compute([SEASON])


@pytest.fixture(scope="module")
def named_rows(prod: pl.DataFrame) -> pl.DataFrame:
    names = _sql("SELECT id AS player_id, name FROM players")
    rows = prod.join(names, on="player_id").filter(pl.col("name").is_in(NAMED))
    assert rows.height == len(NAMED), f"named players missing from compute(): {rows['name'].to_list()}"
    return rows


@pytest.fixture(scope="module")
def reg_totals() -> pl.DataFrame:
    """nflverse's own REG season aggregate for the named players (independent of the weekly table)."""
    return _sql(f"""
        SELECT player_display_name AS name, recent_team, games, carries, rushing_yards, targets, receptions,
               receiving_yards, passing_yards, passing_tds, passing_interceptions, passing_2pt_conversions,
               rushing_tds, rushing_2pt_conversions, receiving_tds, receiving_2pt_conversions,
               fumbles_lost_total, special_teams_tds, fantasy_points
        FROM raw_nflverse_stats_player_reg
        WHERE season = {SEASON} AND season_type = 'REG'
          AND player_display_name IN ({", ".join(_quote(n) for n in NAMED)})
    """)


def test_compute_shape_and_columns(prod: pl.DataFrame) -> None:
    assert prod.columns == list(COMPUTE_COLUMNS)
    assert prod.height > 400  # 2025 had 574 hub QB/RB/WR/TE player-seasons on 2026-08-30
    assert set(prod["position"].unique()) <= set(POSITIONS)
    assert prod["season"].unique().to_list() == [SEASON]
    assert prod["games"].min() >= 1
    assert prod["games"].max() <= 18  # REG only; POST weeks 19-22 must not leak in
    assert prod.select(pl.struct("player_id", "season").n_unique()).item() == prod.height
    assert prod["gsis_id"].null_count() == 0
    for col in ("points", "fantasy_points", "fantasy_points_ppr"):
        assert (col in prod.columns) == (col == "points")  # vendor points are never surfaced


def test_season_totals_match_nflverse_reg_table(named_rows: pl.DataFrame, reg_totals: pl.DataFrame) -> None:
    """games / receiving_yards / carries / rushing_yards / targets / receptions == raw_nflverse_stats_player_reg."""
    merged = named_rows.join(reg_totals, on="name", suffix="_reg")
    assert merged.height == len(NAMED)
    for row in merged.iter_rows(named=True):
        who = f"{row['name']} {SEASON}"
        assert row["games"] == row["games_reg"], who
        assert row["team"] == row["recent_team"], who
        for col in ("carries", "rushing_yards", "targets", "receptions", "receiving_yards"):
            assert row[col] == row[f"{col}_reg"], f"{who}: {col}"
    bijan = merged.filter(pl.col("name") == "Bijan Robinson").to_dicts()[0]
    assert (bijan["games"], bijan["carries"], bijan["rushing_yards"]) == (17, 287, 1478)
    assert (bijan["targets"], bijan["receiving_yards"]) == (103, 820)


def test_points_are_league_scored_and_not_vendor(named_rows: pl.DataFrame, reg_totals: pl.DataFrame) -> None:
    """Σ score(week) equals the league weights applied to the independent REG season totals — and is not the vendor column."""
    s = load_league_config().scoring
    if s.bonuses or s.position_overrides or not s.uses_fractional_points:
        pytest.skip("reconstruction below assumes linear, bonus-free scoring")
    merged = named_rows.join(reg_totals, on="name", suffix="_reg")
    for row in merged.iter_rows(named=True):
        expected = (
            s.pass_yd * row["passing_yards"] + s.pass_td * row["passing_tds"]
            + s.pass_int * row["passing_interceptions"] + s.pass_2pt * row["passing_2pt_conversions"]
            + s.rush_yd * row["rushing_yards_reg"] + s.rush_td * row["rushing_tds"]
            + s.rush_2pt * row["rushing_2pt_conversions"]
            + s.rec * row["receptions_reg"] + s.rec_yd * row["receiving_yards_reg"]
            + s.rec_td * row["receiving_tds"] + s.rec_2pt * row["receiving_2pt_conversions"]
            + s.fum_lost * row["fumbles_lost_total"] + s.ret_td * row["special_teams_tds"]
        )
        assert row["points"] == pytest.approx(expected, abs=0.02), row["name"]
        assert row["ppg"] == pytest.approx(row["points"] / row["games"])
        if s.rec != 0.0:  # half/full PPR: our total must differ from nflverse's standard-scoring column
            assert row["points"] != pytest.approx(row["fantasy_points"], abs=0.02), row["name"]


def test_target_and_carry_shares_match_sql_denominators(named_rows: pl.DataFrame) -> None:
    shares = _sql(f"""
        WITH team AS (
            SELECT team, SUM(COALESCE(targets, 0))::float AS tt, SUM(COALESCE(carries, 0))::float AS tc
            FROM raw_nflverse_stats_player_week WHERE season = {SEASON} AND season_type = 'REG' GROUP BY team
        ), pl AS (
            SELECT player_display_name AS name, team,
                   SUM(COALESCE(targets, 0))::float AS t, SUM(COALESCE(carries, 0))::float AS c
            FROM raw_nflverse_stats_player_week
            WHERE season = {SEASON} AND season_type = 'REG'
              AND player_display_name IN ({", ".join(_quote(n) for n in NAMED)})
            GROUP BY 1, 2
        )
        SELECT pl.name, SUM(pl.t / team.tt) AS sql_target_share, SUM(pl.c / team.tc) AS sql_carry_share
        FROM pl JOIN team USING (team) GROUP BY pl.name
    """)
    merged = named_rows.join(shares, on="name")
    assert merged.height == len(NAMED)
    for row in merged.iter_rows(named=True):
        assert row["target_share"] == pytest.approx(row["sql_target_share"], abs=1e-9), row["name"]
        assert row["carry_share"] == pytest.approx(row["sql_carry_share"], abs=1e-9), row["name"]
        # the weekly-mean variant is a different statistic, but must land in the same neighbourhood
        assert row["target_share_wk_mean"] == pytest.approx(row["target_share"], abs=0.05), row["name"]


def test_weekly_target_shares_sum_to_one_per_team_week_and_season_shares_do_not_exceed_one(
    prod: pl.DataFrame,
) -> None:
    """Shares are true shares: Σ = 1.0 per team-week upstream and Σ = 1.0 per team-season for our denominator."""
    week_sums = _sql(f"""
        SELECT team, week, SUM(target_share) AS s
        FROM raw_nflverse_stats_player_week WHERE season = {SEASON} AND season_type = 'REG'
        GROUP BY team, week
    """)
    assert week_sums.height == 32 * 17  # 32 teams x 17 played weeks (each team has one bye in an 18-week REG season)
    assert week_sums["s"].min() == pytest.approx(1.0, abs=1e-6)
    assert week_sums["s"].max() == pytest.approx(1.0, abs=1e-6)

    # the exact season-level formula compute() uses, run over EVERY player in SQL: Σ per team-season == 1.0
    stint_sums = _sql(f"""
        WITH team AS (
            SELECT team, SUM(COALESCE(targets, 0))::float AS tt, SUM(COALESCE(carries, 0))::float AS tc
            FROM raw_nflverse_stats_player_week WHERE season = {SEASON} AND season_type = 'REG' GROUP BY team
        ), pl AS (
            SELECT player_id, team, SUM(COALESCE(targets, 0))::float AS t, SUM(COALESCE(carries, 0))::float AS c
            FROM raw_nflverse_stats_player_week WHERE season = {SEASON} AND season_type = 'REG' GROUP BY 1, 2
        )
        SELECT team, SUM(pl.t / team.tt) AS ts, SUM(pl.c / team.tc) AS cs FROM pl JOIN team USING (team) GROUP BY team
    """)
    assert stint_sums.height == 32
    for col in ("ts", "cs"):
        assert stint_sums[col].min() == pytest.approx(1.0, abs=1e-9)
        assert stint_sums[col].max() == pytest.approx(1.0, abs=1e-9)

    # In compute() a row is filed under the player's MOST-FREQUENT team, but his share covers every stint, so a
    # team that acquired a player mid-season can total slightly over 1.0 (SEA 2025: 1.12) while a team whose
    # 2025 contributors have left the 2026 hub totals under 1.0. Both stay in a tight band.
    per_team = prod.group_by("team").agg(t=pl.col("target_share").sum(), c=pl.col("carry_share").sum())
    assert per_team.height == 32
    assert 0.6 < per_team["t"].min() and per_team["t"].max() < 1.25
    assert 0.6 < per_team["c"].min() and per_team["c"].max() < 1.25
    assert prod["target_share"].min() >= 0.0
    assert prod["carry_share"].min() >= 0.0
    assert prod["target_share"].max() <= 1.0
    assert prod["carry_share"].max() <= 1.0


def test_positional_ranks(prod: pl.DataFrame) -> None:
    short = prod.filter(pl.col("games") < MIN_GAMES_FOR_PPG_RANK)
    assert short.height > 0
    assert short["pos_rank_ppg"].null_count() == short.height  # small-sample rates get no rank
    long = prod.filter(pl.col("games") >= MIN_GAMES_FOR_PPG_RANK)
    assert long["pos_rank_ppg"].null_count() == 0
    assert prod["pos_rank_points"].null_count() == 0  # volume rank covers every player-season
    for pos in POSITIONS:
        block = long.filter(pl.col("position") == pos)
        best = block.filter(pl.col("pos_rank_ppg") == 1)
        assert best.height >= 1
        assert best["ppg"].max() == pytest.approx(block["ppg"].max())
        assert block["pos_rank_ppg"].max() <= block.height
        pts_block = prod.filter(pl.col("position") == pos)
        top = pts_block.filter(pl.col("pos_rank_points") == 1)
        assert top["points"].max() == pytest.approx(pts_block["points"].max())


def test_summary_covers_every_hub_player_and_keeps_no_history_players_as_nulls() -> None:
    summary = compute_summary([SEASON])
    hub = _sql(f"SELECT id AS player_id FROM players WHERE position IN ({', '.join(_quote(p) for p in POSITIONS)})")
    assert summary.height == hub.height
    assert sorted(summary["player_id"].to_list()) == sorted(hub["player_id"].to_list())
    assert summary.select(pl.col("player_id").n_unique()).item() == summary.height

    rookie = summary.filter(pl.col("gsis_id") == ROOKIE_GSIS)
    assert rookie.height == 1, "a player with no history must be kept as a null row, not dropped"
    row = rookie.to_dicts()[0]
    played = _sql(f"""
        SELECT COUNT(*) AS n FROM raw_nflverse_stats_player_week WHERE player_id = {_quote(ROOKIE_GSIS)}
    """)["n"].item()
    assert played == 0, "fixture assumption: this player has no nflverse rows at all"
    for col in ("ppg_2025", "games_2025", "target_share_2025", "carry_share_2025",
                "opportunities_pg_2025", "ppg_trend_w", "ref_season", "ref_role_key"):
        assert row[col] is None, col
    assert row["same_role_seasons"] == 0
    assert row["has_8game_same_role_season"] is False


def test_summary_trend_uses_same_role_seasons_only_with_renormalised_weights() -> None:
    seasons = [PRIOR, SEASON]
    prod2 = compute(seasons)
    summary = compute_summary(seasons)
    weights = dict(zip(sorted(seasons, reverse=True), RECENCY_WEIGHTS, strict=False))

    joined = summary.join(prod2, on="player_id", how="inner")
    assert joined.height > 0
    for row in joined.filter(pl.col("role_key") != pl.col("ref_role_key")).iter_rows(named=True):
        assert row["season"] != row["ref_season"]  # the reference season always matches its own role

    # re-derive the trend from the per-season rows, independently of _trend()
    expected = (
        prod2.join(summary.select("player_id", "ref_role_key"), on="player_id")
        .filter(pl.col("role_key") == pl.col("ref_role_key"))
        .with_columns(w=pl.col("season").replace_strict(weights, return_dtype=pl.Float64))
        .group_by("player_id")
        .agg(
            exp_trend=(pl.col("w") * pl.col("ppg")).sum() / pl.col("w").sum(),
            exp_n=pl.len().cast(pl.Int32),
            exp_8=(pl.col("games") >= MIN_GAMES_FOR_PPG_RANK).any(),
        )
    )
    check = summary.join(expected, on="player_id", how="inner")
    assert check.height > 300
    assert check.select(((pl.col("ppg_trend_w") - pl.col("exp_trend")).abs() > 1e-9).sum()).item() == 0
    assert check.select((pl.col("same_role_seasons") != pl.col("exp_n")).sum()).item() == 0
    assert check.select((pl.col("has_8game_same_role_season") != pl.col("exp_8")).sum()).item() == 0

    # a real role change: PIT-WR in 2024 -> DAL-WR in 2025, so only 2025 feeds the trend
    pid = _sql(f"SELECT id AS player_id FROM players WHERE name = {_quote(TRADED_NAME)}")["player_id"].item()
    moved = summary.filter(pl.col("player_id") == pid).to_dicts()[0]
    roles = prod2.filter(pl.col("player_id") == pid).sort("season")["role_key"].to_list()
    assert roles == ["PIT-WR", "DAL-WR"]
    assert moved["ref_role_key"] == "DAL-WR" and moved["ref_season"] == SEASON
    assert moved["same_role_seasons"] == 1
    assert moved["ppg_trend_w"] == pytest.approx(moved[f"ppg_{SEASON}"])
    assert moved["yoy_ppg_delta"] == pytest.approx(moved[f"ppg_{SEASON}"] - moved[f"ppg_{PRIOR}"])


def test_summary_yoy_deltas_are_null_when_a_season_is_missing() -> None:
    summary = compute_summary([PRIOR, SEASON])
    one_sided = summary.filter(pl.col(f"ppg_{SEASON}").is_null() ^ pl.col(f"ppg_{PRIOR}").is_null())
    assert one_sided.height > 0
    assert one_sided["yoy_ppg_delta"].null_count() == one_sided.height
    both = summary.filter(pl.col(f"ppg_{SEASON}").is_not_null() & pl.col(f"ppg_{PRIOR}").is_not_null())
    assert both["yoy_ppg_delta"].null_count() == 0
    assert both["yoy_target_share_delta"].null_count() == 0
