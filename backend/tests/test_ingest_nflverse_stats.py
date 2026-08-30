"""Parse the REAL nflverse fixtures (tests/fixtures/nflverse/PROVENANCE.md) with app.ingest.nflverse_stats helpers.

Expected values are hand-read from the fixture rows (Puka Nacua, LA, 2025) - no invented stat lines.
"""
from __future__ import annotations

from pathlib import Path

import polars as pl
import pytest

from app.ingest.nflverse_stats import DATASETS, player_week_line, read_snapshot, reg_weeks_by_season

FIX = Path(__file__).parent / "fixtures" / "nflverse"
NACUA = "00-0039075"


@pytest.fixture(scope="module")
def week_df():
    return read_snapshot(str(FIX / "stats_player_week_2025_nacua.parquet"))


@pytest.fixture(scope="module")
def opp_df():
    return read_snapshot(str(FIX / "ff_opportunity_weekly_2025_nacua.parquet"))


def test_stats_player_week_columns_are_verbatim(week_df):
    assert week_df.width == 150
    for col in ("targets", "target_share", "air_yards_share", "wopr", "carries", "rushing_yards", "receptions",
                "receiving_yards", "receiving_tds", "rushing_tds", "passing_tds", "fumbles_lost_total",
                "receiving_2pt_conversions", "opponent_team", "season_type"):
        assert col in week_df.columns, col


def test_nacua_week16_line(week_df):
    """2025 wk16 LA vs SEA: 16 tgt / 12 rec / 225 yds / 2 TD; target_share = 16 of 48 team targets."""
    row = player_week_line(week_df, NACUA, 2025, 16)
    assert row["player_display_name"] == "Puka Nacua"
    assert (row["team"], row["opponent_team"], row["season_type"]) == ("LA", "SEA", "REG")
    assert (row["targets"], row["receptions"], row["receiving_yards"], row["receiving_tds"]) == (16, 12, 225, 2)
    assert (row["carries"], row["rushing_yards"]) == (0, 0)
    assert row["target_share"] == pytest.approx(16 / 48, abs=1e-6)
    # wopr = 1.5 * target_share + 0.7 * air_yards_share
    assert row["wopr"] == pytest.approx(1.5 * row["target_share"] + 0.7 * row["air_yards_share"], abs=1e-6)
    assert player_week_line(week_df, NACUA, 2025, 11)["fumbles_lost_total"] == 1  # only lost fumble of the year


def test_reg_weeks_exclude_post(week_df):
    """Nacua played REG weeks 1-6 and 9-18 (LA bye wk 8, missed wk 7); POST rows exist with weeks 19-21."""
    assert reg_weeks_by_season(week_df) == {2025: [1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18]}
    post = week_df.filter(week_df["season_type"] == "POST")
    assert post["week"].to_list() == [19, 20, 21]
    with pytest.raises(ValueError):
        player_week_line(week_df, NACUA, 2025, 7)


def test_ff_opportunity_week16_expected_yards(opp_df):
    """ffopportunity ships season as a string and week as float; diff == actual - expected (225 - 125.48)."""
    assert opp_df["season"].dtype == pl.String and opp_df["week"].dtype == pl.Float64
    row = opp_df.filter((opp_df["player_id"] == NACUA) & (opp_df["week"] == 16.0)).to_dicts()
    assert len(row) == 1
    row = row[0]
    assert (row["posteam"], row["rec_attempt"], row["receptions"], row["rec_yards_gained"]) == ("LA", 16.0, 12.0, 225.0)
    assert row["rec_yards_gained_exp"] == pytest.approx(125.48)
    assert row["rec_yards_gained_diff"] == pytest.approx(225.0 - 125.48, abs=1e-6)
    assert row["receptions_exp"] == pytest.approx(9.6)


def test_dataset_specs_target_raw_tables():
    assert set(DATASETS) == {
        "stats_player_week", "stats_player_reg", "ff_opportunity_weekly", "roster_weekly", "injuries",
    }
    for name, spec in DATASETS.items():
        assert spec.table == f"raw_nflverse_{name}"
        assert spec.asset.format(season=2025).endswith("_2025.parquet")
        assert spec.endpoint(2025) == f"{name}_2025"
