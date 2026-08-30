"""Phase 3 feature tests — `app.features.luck` and `app.features.consistency`, on the real Postgres db (read-only).

Real data only: every expectation below comes from the live `fantasy_football` tables, never a fabricated row.
Vendor point columns appear exactly once, in `test_expected_adapter_matches_vendor_ppr_cross_check`, as a
cross-check that the adapter reads the right `*_exp` columns — they are never a feature value.

The Jahmyr Gibbs 2025 numbers were hand-run in psql before the module existed:

    docker exec postgres psql -U local-master -d fantasy_football -c "
    WITH j AS (
      SELECT s.passing_tds, s.receiving_tds, s.rushing_tds,
             o.pass_touchdown_exp, o.rec_touchdown_exp, o.rush_touchdown_exp,
             s.passing_yards+s.receiving_yards+s.rushing_yards AS ya,
             o.pass_yards_gained_exp+o.rec_yards_gained_exp+o.rush_yards_gained_exp AS ye
      FROM raw_nflverse_stats_player_week s
      JOIN raw_nflverse_ff_opportunity_weekly o
        ON o.player_id=s.player_id AND o.season::int=s.season AND o.week::int=s.week
      WHERE s.season_type='REG' AND s.season=2025
        AND s.player_id=(SELECT gsis_id FROM players WHERE name='Jahmyr Gibbs'))
    SELECT count(*), sum(passing_tds+receiving_tds+rushing_tds),
           sum(pass_touchdown_exp+rec_touchdown_exp+rush_touchdown_exp), sum(ya), sum(ye) FROM j;"

    games_both | td_act | td_exp  | td_diff | yards_act | yards_exp
             17 |     18 | 10.6800 |  7.3200 |      1839 |   1670.95
"""
from __future__ import annotations

import polars as pl
import pytest

from app.db import engine
from app.features import consistency, luck
from app.scoring.adapters import from_ff_opportunity_expected, from_nflverse_week
from app.scoring.config import Scoring, load_league_config
from app.scoring.engine import score

SEASONS = [2023, 2024, 2025]

# Hand-run SQL results (see the module docstring for the exact query).
GIBBS_2025 = {
    "games_both": 17,
    "td_act": 18.0,
    "td_exp": 10.68,
    "td_diff": 7.32,
    "yards_act": 1839.0,
    "yards_exp": 1670.95,
}
# A 2025 WR with a REG row every week and never 3+ opportunities (targets + carries + attempts) in any of them.
NO_OPPORTUNITY_PLAYER = "Skyy Moore"
# ffopportunity's own `total_fantasy_points_exp` is PPR-scored; reproducing it validates the expected adapter.
VENDOR_PPR = Scoring(pass_yd=0.04, pass_td=4, pass_int=-2, pass_2pt=2, rush_yd=0.1, rush_td=6, rush_2pt=2,
                     rec=1.0, rec_yd=0.1, rec_td=6, rec_2pt=2)


@pytest.fixture(scope="module")
def cfg():
    return load_league_config()


@pytest.fixture(scope="module")
def luck_df(cfg):
    return luck.compute(SEASONS, cfg)


@pytest.fixture(scope="module")
def cons_df(cfg):
    return consistency.compute(SEASONS, cfg)


@pytest.fixture(scope="module")
def hub():
    return pl.read_database("SELECT id AS player_id, gsis_id, name, position FROM players WHERE gsis_id IS NOT NULL",
                            connection=engine, infer_schema_length=None)


def _one(df: pl.DataFrame, **eq) -> dict:
    out = df.filter([pl.col(k) == v for k, v in eq.items()])
    assert out.height == 1, f"expected exactly 1 row for {eq}, got {out.height}"
    return out.row(0, named=True)


def _gsis(hub: pl.DataFrame, name: str) -> str:
    return _one(hub, name=name)["gsis_id"]


# --------------------------------------------------------------------------------------- luck


def test_luck_td_diff_matches_hand_run_sql(luck_df, hub):
    row = _one(luck_df, gsis_id=_gsis(hub, "Jahmyr Gibbs"), season=2025)
    assert row["games_both"] == GIBBS_2025["games_both"]
    assert row["td_act"] == pytest.approx(GIBBS_2025["td_act"])
    assert row["td_exp"] == pytest.approx(GIBBS_2025["td_exp"], abs=5e-3)
    assert row["td_diff"] == pytest.approx(GIBBS_2025["td_diff"], abs=5e-3)
    assert row["td_diff"] == pytest.approx(row["td_act"] - row["td_exp"], abs=1e-9)


def test_luck_yards_match_hand_run_sql(luck_df, hub):
    row = _one(luck_df, gsis_id=_gsis(hub, "Jahmyr Gibbs"), season=2025)
    assert row["yards_act"] == pytest.approx(GIBBS_2025["yards_act"])
    assert row["yards_exp"] == pytest.approx(GIBBS_2025["yards_exp"], abs=5e-3)
    assert row["yards_diff"] == pytest.approx(row["yards_act"] - row["yards_exp"], abs=1e-9)


def test_luck_td_diff_still_matches_live_sql(luck_df, hub):
    """Guard against upstream drift: re-run the hand SQL and compare it to the module's row."""
    gsis = _gsis(hub, "Jahmyr Gibbs")
    sql = f"""
        SELECT count(*) AS games_both,
               sum(s.passing_tds + s.receiving_tds + s.rushing_tds) AS td_act,
               sum(o.pass_touchdown_exp + o.rec_touchdown_exp + o.rush_touchdown_exp) AS td_exp
          FROM raw_nflverse_stats_player_week s
          JOIN raw_nflverse_ff_opportunity_weekly o
            ON o.player_id = s.player_id AND o.season::int = s.season AND o.week::int = s.week
         WHERE s.season_type = 'REG' AND s.season = 2025 AND s.player_id = '{gsis}'
    """
    hand = pl.read_database(sql, connection=engine, infer_schema_length=None).row(0, named=True)
    row = _one(luck_df, gsis_id=gsis, season=2025)
    assert row["games_both"] == hand["games_both"]
    assert row["td_act"] == pytest.approx(float(hand["td_act"]))
    assert row["td_exp"] == pytest.approx(float(hand["td_exp"]), abs=1e-6)
    assert row["td_diff"] == pytest.approx(float(hand["td_act"]) - float(hand["td_exp"]), abs=1e-6)


def test_luck_ppg_diff_finite_for_high_volume_players(luck_df):
    assert luck_df.height > 1000
    assert (luck_df["games_both"] > 0).all(), "every luck row is an inner join, so it has >= 1 shared week"
    hv = luck_df.filter(pl.col("games_both") >= 12)
    assert hv.height > 300
    assert hv["ppg_diff"].is_finite().all()
    assert hv["act_points"].min() > 0
    identity = (hv["ppg_diff"] * hv["games_both"] - hv["points_diff"]).abs().max()
    assert identity < 1e-9
    # Luck is roughly zero-sum across the league; a broken join would blow this up.
    assert abs(hv["ppg_diff"].mean()) < 1.0


def test_luck_seasons_and_key_are_clean(luck_df):
    assert sorted(luck_df["season"].unique().to_list()) == SEASONS
    assert luck_df.select("player_id", "season").n_unique() == luck_df.height
    assert luck_df["gsis_id"].null_count() == 0


def test_expected_adapter_matches_vendor_ppr_cross_check():
    """Cross-check ONLY: our `*_exp` stat line under PPR reproduces ffopportunity's own expected points."""
    cols = ("pass_yards_gained_exp, pass_touchdown_exp, pass_interception_exp, pass_two_point_conv_exp, "
            "rush_yards_gained_exp, rush_touchdown_exp, rush_two_point_conv_exp, receptions_exp, "
            "rec_yards_gained_exp, rec_touchdown_exp, rec_two_point_conv_exp, total_fantasy_points_exp")
    df = pl.read_database(
        f"SELECT {cols} FROM raw_nflverse_ff_opportunity_weekly "
        "WHERE season = '2025' AND week = 1.0 AND player_id IS NOT NULL",
        connection=engine, infer_schema_length=None)
    assert df.height > 100
    for row in df.to_dicts():
        ours = score(from_ff_opportunity_expected(row), VENDOR_PPR)
        assert ours == pytest.approx(row["total_fantasy_points_exp"], abs=0.25)


def test_luck_points_are_league_scored_not_vendor(luck_df, hub, cfg):
    """`exp_points` must be league scoring (half PPR here), not the vendor PPR column."""
    gsis = _gsis(hub, "Jahmyr Gibbs")
    vendor = pl.read_database(
        "SELECT sum(o.total_fantasy_points_exp) AS v FROM raw_nflverse_ff_opportunity_weekly o "
        "JOIN raw_nflverse_stats_player_week s ON s.player_id = o.player_id "
        " AND s.season = o.season::int AND s.week = o.week::int AND s.season_type = 'REG' "
        f"WHERE s.season = 2025 AND o.player_id = '{gsis}'",
        connection=engine, infer_schema_length=None).row(0, named=True)["v"]
    row = _one(luck_df, gsis_id=gsis, season=2025)
    assert cfg.scoring.rec == 0.5, "league.yaml is half-PPR; update this test if the scoring changes"
    assert abs(row["exp_points"] - float(vendor)) > 1.0


def test_luck_summary_is_one_row_per_player(luck_df):
    summary = luck.compute_summary(SEASONS, per_season=luck_df)
    assert summary.columns == ["player_id", "ppg_diff_2025", "td_diff_2025", "td_diff_2024",
                               "exp_points_2025", "act_points_2025"]
    assert summary["player_id"].n_unique() == summary.height
    assert summary.height == luck_df["player_id"].n_unique()
    pid = luck_df.filter(pl.col("season") == 2025).sort("act_points", descending=True).row(0, named=True)["player_id"]
    src = _one(luck_df, player_id=pid, season=2025)
    got = _one(summary, player_id=pid)
    assert got["ppg_diff_2025"] == pytest.approx(src["ppg_diff"])
    assert got["td_diff_2025"] == pytest.approx(src["td_diff"])
    assert got["act_points_2025"] == pytest.approx(src["act_points"])


# -------------------------------------------------------------------------------- consistency


def test_consistency_player_with_no_qualifying_weeks_is_null_not_a_crash(cons_df, hub):
    gsis = _gsis(hub, NO_OPPORTUNITY_PLAYER)
    raw = pl.read_database(
        "SELECT count(*) AS weeks, max(COALESCE(targets,0)+COALESCE(carries,0)+COALESCE(attempts,0)) AS max_opp "
        f"FROM raw_nflverse_stats_player_week WHERE season_type='REG' AND season=2025 AND player_id='{gsis}'",
        connection=engine, infer_schema_length=None).row(0, named=True)
    assert raw["weeks"] > 5 and raw["max_opp"] < consistency.MIN_OPPORTUNITIES
    row = _one(cons_df, gsis_id=gsis, season=2025)
    assert row["weeks_used"] == 0
    for col in ("weekly_mean", "weekly_sd", "cv", "floor_p25", "ceiling_p90",
                "pct_weeks_above_starter", "boom_rate", "bust_rate"):
        assert row[col] is None, col


def test_consistency_weeks_used_matches_the_opportunity_filter(cons_df, hub):
    gsis = _gsis(hub, "Bijan Robinson")
    used = pl.read_database(
        "SELECT count(*) AS used FROM raw_nflverse_stats_player_week "
        "WHERE season_type='REG' AND season=2025 AND COALESCE(targets,0)+COALESCE(carries,0)+COALESCE(attempts,0) >= "
        f"{consistency.MIN_OPPORTUNITIES} AND player_id='{gsis}'",
        connection=engine, infer_schema_length=None).row(0, named=True)["used"]
    row = _one(cons_df, gsis_id=gsis, season=2025)
    assert row["weeks_used"] == used > 0
    assert row["weekly_mean"] > 0 and row["weekly_sd"] > 0


def test_consistency_rates_are_within_unit_interval(cons_df):
    rated = cons_df.filter(pl.col("weeks_used") > 0)
    assert rated.height > 800
    for col in ("boom_rate", "bust_rate", "pct_weeks_above_starter"):
        assert rated[col].null_count() == 0, col
        assert rated[col].min() >= 0.0 and rated[col].max() <= 1.0, col
    # above-starter and bust are complements by definition (>= threshold vs < threshold)
    assert (rated["pct_weeks_above_starter"] + rated["bust_rate"] - 1.0).abs().max() < 1e-12


def test_consistency_distribution_columns_are_coherent(cons_df):
    multi = cons_df.filter(pl.col("weeks_used") >= 2)
    assert multi.height > 500
    assert multi["weekly_sd"].null_count() == 0
    assert multi["weekly_sd"].min() >= 0.0
    assert (multi["ceiling_p90"] - multi["floor_p25"]).min() >= -1e-9
    pos = multi.filter(pl.col("weekly_mean") > 0)
    assert (pos["cv"] - pos["weekly_sd"] / pos["weekly_mean"]).abs().max() < 1e-12
    # a single qualifying week cannot have a standard deviation
    single = cons_df.filter(pl.col("weeks_used") == 1)
    assert single["weekly_sd"].null_count() == single.height


def test_starter_threshold_is_the_kth_best_score_that_week(cfg):
    """Independently re-score every 2025 week-1 row and check the (teams x starters)-th best value."""
    weeks = consistency.load_weeks([2025])
    weeks = weeks.with_columns(
        pl.Series("points", [score(from_nflverse_week(r), cfg.scoring, r["position"]) for r in weeks.to_dicts()],
                  dtype=pl.Float64))
    thresholds = consistency.weekly_thresholds(weeks, cfg)
    for pos in consistency.POSITIONS:
        pts = sorted(weeks.filter((pl.col("week") == 1) & (pl.col("position") == pos))["points"].to_list(),
                     reverse=True)
        k = cfg.league.num_teams * cfg.roster.slots[pos]
        row = _one(thresholds, season=2025, week=1, position=pos)
        assert row["starter_threshold"] == pytest.approx(pts[k - 1]), pos
        assert row["boom_threshold"] == pytest.approx(pts[consistency.BOOM_TOP_N[pos] - 1]), pos


def test_consistency_summary_is_one_row_per_player(cons_df):
    summary = consistency.compute_summary(SEASONS, per_season=cons_df)
    assert summary.columns == ["player_id", "weekly_sd_2025", "cv_2025", "floor_p25_2025", "ceiling_p90_2025",
                               "pct_weeks_above_starter_2025", "boom_rate_2025", "bust_rate_2025", "weeks_used_2025"]
    assert summary["player_id"].n_unique() == summary.height
    assert summary.height == cons_df["player_id"].n_unique()
    pid = (cons_df.filter(pl.col("season") == 2025)
           .sort("weekly_mean", descending=True, nulls_last=True).row(0, named=True)["player_id"])
    src = _one(cons_df, player_id=pid, season=2025)
    got = _one(summary, player_id=pid)
    assert got["weeks_used_2025"] == src["weeks_used"]
    assert got["boom_rate_2025"] == pytest.approx(src["boom_rate"])
    assert 0.0 <= got["bust_rate_2025"] <= 1.0
