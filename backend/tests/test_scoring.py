"""Scoring engine tests on REAL nflverse rows (Puka Nacua 2025 weekly fixture; see tests/fixtures/nflverse/PROVENANCE.md).

Vendor fantasy_points columns are used ONLY as a cross-check of our adapters, never surfaced by the app.
nflverse fantasy_points = 0.04 pass yd, 4 pass TD, -2 INT, 0.1 rush/rec yd, 6 TD, -2 fumbles lost, 2 per 2pt, 6 ST TD;
fantasy_points_ppr adds 1.0 per reception.
"""
from pathlib import Path

import polars as pl
import pytest

from app.scoring.adapters import from_ff_opportunity_expected, from_nflverse_week
from app.scoring.config import Scoring
from app.scoring.engine import breakdown, score

FIX = Path(__file__).parent / "fixtures" / "nflverse"

NFLVERSE_STD = Scoring(pass_yd=0.04, pass_td=4, pass_int=-2, pass_2pt=2, rush_yd=0.1, rush_td=6, rush_2pt=2,
                       rec=0.0, rec_yd=0.1, rec_td=6, rec_2pt=2, fum_lost=-2, ret_td=6)
NFLVERSE_PPR = NFLVERSE_STD.model_copy(update={"rec": 1.0})
YAHOO_DEFAULT = Scoring(pass_yd=0.04, pass_td=4, pass_int=-1, pass_2pt=2, rush_yd=0.1, rush_td=6, rush_2pt=2,
                        rec=0.5, rec_yd=0.1, rec_td=6, rec_2pt=2, fum_lost=-2, ret_td=6)


@pytest.fixture(scope="module")
def nacua_weeks() -> list[dict]:
    df = pl.read_parquet(FIX / "stats_player_week_2025_nacua.parquet").filter(pl.col("season_type") == "REG")
    assert df.height >= 10
    return df.to_dicts()


def test_adapter_reproduces_nflverse_points_every_week(nacua_weeks):
    for row in nacua_weeks:
        line = from_nflverse_week(row)
        assert score(line, NFLVERSE_STD) == pytest.approx(row["fantasy_points"], abs=0.011), row["week"]
        assert score(line, NFLVERSE_PPR) == pytest.approx(row["fantasy_points_ppr"], abs=0.011), row["week"]


def test_yahoo_default_half_ppr_on_a_real_week(nacua_weeks):
    row = max(nacua_weeks, key=lambda r: r["receiving_yards"])  # his biggest receiving week of 2025
    line = from_nflverse_week(row)
    expected = (0.1 * row["receiving_yards"] + 0.5 * row["receptions"] + 6 * row["receiving_tds"]
                + 0.1 * row["rushing_yards"] + 6 * row["rushing_tds"] - 2 * line["fum_lost"] + 2 * line["rec_2pt"]
                + 2 * line["rush_2pt"] + 6 * line["ret_td"])
    assert score(line, YAHOO_DEFAULT) == pytest.approx(expected, abs=1e-6)
    bd = breakdown(line, YAHOO_DEFAULT)
    assert bd["rec_yd"] == pytest.approx(0.1 * row["receiving_yards"]) and bd["rec"] == pytest.approx(0.5 * row["receptions"])


def test_whole_increment_yardage_and_negative_floor(nacua_weeks):
    row = max(nacua_weeks, key=lambda r: r["receiving_yards"])
    line = from_nflverse_week(row)
    whole = YAHOO_DEFAULT.model_copy(update={"uses_fractional_points": False})
    # 0.1/yd == 1 pt per 10 yards -> whole increments floor the yardage points
    frac_pts = score(line, YAHOO_DEFAULT)
    whole_pts = score(line, whole)
    assert whole_pts <= frac_pts
    assert (row["receiving_yards"] // 10) * 1.0 == breakdown(line, whole)["rec_yd"]
    no_neg = YAHOO_DEFAULT.model_copy(update={"uses_negative_points": False})
    assert score({"fum_lost": 2}, no_neg) == 0.0 and score({"fum_lost": 2}, YAHOO_DEFAULT) == -4.0


def test_expected_stats_adapter_scores_under_league_scoring():
    ex = pl.read_parquet(FIX / "ff_opportunity_weekly_2025_nacua.parquet").to_dicts()
    assert ex
    total_exp = sum(score(from_ff_opportunity_expected(r), YAHOO_DEFAULT) for r in ex)
    total_act = sum(score(from_nflverse_week(r), YAHOO_DEFAULT) for r in
                    pl.read_parquet(FIX / "stats_player_week_2025_nacua.parquet").filter(pl.col("season_type") == "REG").to_dicts())
    assert total_exp > 0 and total_act > 0
    # a 2025 WR1's actual and expected season totals should be the same order of magnitude (sanity, not a model claim)
    assert 0.5 < total_exp / total_act < 2.0
