"""Sleeper parsers against real snapshot extracts (see tests/fixtures/sleeper/PROVENANCE.md).

Expected values are hand-read from the fixture records; no mock data.
"""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from app.ingest.sleeper import (
    FANTASY_POSITIONS,
    assert_projection_shape,
    parse_players,
    parse_projections,
)

FIXTURES = Path(__file__).parent / "fixtures" / "sleeper"


@pytest.fixture(scope="module")
def projection_records() -> list[dict]:
    return json.loads((FIXTURES / "projections_2026_regular_sample.json").read_text())


@pytest.fixture(scope="module")
def players_payload() -> dict[str, dict]:
    return json.loads((FIXTURES / "players_nfl_sample.json").read_text())


def _row(df: pl.DataFrame, player_id: str) -> dict:
    rows = df.filter(pl.col("player_id") == player_id).to_dicts()
    assert len(rows) == 1, f"{player_id}: expected exactly one row, got {len(rows)}"
    return rows[0]


# ------------------------------------------------------------------------------------------- projections
def test_projection_shape_is_season_total(projection_records):
    assert len(projection_records) == 21
    assert_projection_shape(projection_records)  # every fixture record has week == null
    broken = [dict(projection_records[0], week=1)]
    with pytest.raises(ValueError, match="week != null"):
        assert_projection_shape(broken)


def test_parse_projections_flattens_gibbs(projection_records):
    df = parse_projections(projection_records, season=2026)
    # 21 records: LB (1000) and position-null (2901) are excluded -> 19 fantasy-position rows
    assert df.height == 19
    assert set(df["position"].unique().to_list()) <= set(FANTASY_POSITIONS)

    gibbs = _row(df, "9221")
    assert (gibbs["first_name"], gibbs["last_name"], gibbs["position"], gibbs["team"]) == ("Jahmyr", "Gibbs", "RB", "DET")
    assert gibbs["season"] == 2026 and gibbs["week"] is None and gibbs["company"] == "rotowire"
    assert gibbs["last_modified"] == 1787989847468
    assert gibbs["has_projection"] is True
    # ADP kept as-is (no prefix), sentinel 999 -> null
    assert gibbs["adp_half_ppr"] == 1.4 and gibbs["adp_ppr"] == 1.9 and gibbs["adp_std"] == 2.7 and gibbs["adp_2qb"] == 1.8
    assert gibbs["adp_rookie"] is None and gibbs["adp_dynasty"] is None
    # counting stats get the stat_ prefix
    assert gibbs["stat_rush_att"] == 255.0 and gibbs["stat_rush_yd"] == 1251.0 and gibbs["stat_rush_td"] == 12.0
    assert gibbs["stat_rec"] == 63.0 and gibbs["stat_rec_yd"] == 533.0 and gibbs["stat_rec_td"] == 3.0
    assert gibbs["stat_fum_lost"] == 1.0
    assert gibbs["stat_pass_yd"] is None  # key absent for an RB -> null column
    # the untouched dict is preserved (sentinel still 999 there)
    raw = json.loads(gibbs["stats_json"])
    assert raw["adp_rookie"] == 999.0 and raw["rush_yd"] == 1251.0 and raw["gp"] == 18.0


def test_parse_projections_qb_kicker_def_and_edges(projection_records):
    df = parse_projections(projection_records, season=2026)

    allen = _row(df, "4984")
    assert allen["position"] == "QB" and allen["team"] == "BUF"
    assert allen["stat_pass_yd"] == 3650.0 and allen["stat_pass_td"] == 27.0 and allen["stat_pass_int"] == 10.0
    assert allen["stat_rush_yd"] == 535.0 and allen["adp_2qb"] == 3.5 and allen["adp_half_ppr"] == 20.0

    aubrey = _row(df, "11533")
    assert aubrey["position"] == "K" and aubrey["stat_xpm"] == 42.0 and aubrey["stat_fgm_50p"] == 8.0
    assert aubrey["adp_ppr"] == 93.1

    det = _row(df, "DET")
    assert det["position"] == "DEF" and det["team"] == "DET"
    assert (det["first_name"], det["last_name"]) == ("Detroit", "Lions")
    assert det["stat_sack"] == 42.0 and det["stat_int"] == 13.0 and det["adp_half_ppr"] == 174.5

    # projected player with no NFL team: kept, team null
    hill = _row(df, "3321")
    assert hill["team"] is None and hill["player_team"] is None and hill["has_projection"] is True
    assert hill["stat_rec"] == 33.0 and hill["adp_half_ppr"] == 216.9

    # ADP-only record (no counting stat): parsed, but has_projection False so the loader drops it
    higgins = _row(df, "12484")
    assert higgins["has_projection"] is False and higgins["adp_half_ppr"] == 200.1
    assert higgins["stat_rec"] is None

    # non-fantasy / null positions never appear
    assert df.filter(pl.col("player_id").is_in(["1000", "2901"])).height == 0
    assert df.filter(pl.col("has_projection")).height == 18


# ------------------------------------------------------------------------------------------- players
def test_parse_players_filters_and_types(players_payload):
    assert len(players_payload) == 17
    df = parse_players(players_payload)
    kept = set(df["player_id"].to_list())
    # dropped: Inactive + no team (13175, 2881); non-fantasy positions (13940 OL, 8733 LB)
    assert {"13175", "2881", "13940", "8733"}.isdisjoint(kept)
    # kept: teamed players, DEF, Active/IR/PUP without a team, Inactive-but-teamed
    assert {"9221", "11564", "4034", "DET", "3321", "2196", "7593", "6462", "11533", "4046", "4219", "11651", "14034"} <= kept
    assert df.height == 13

    cmc = _row(df, "4034")
    assert cmc["full_name"] == "Christian McCaffrey" and cmc["team"] == "SF" and cmc["status"] == "Active"
    assert cmc["injury_status"] == "Questionable" and cmc["injury_body_part"] == "Undisclosed"
    # ids are text regardless of upstream int/str typing
    assert (cmc["espn_id"], cmc["yahoo_id"], cmc["gsis_id"], cmc["rotowire_id"]) == (
        "3117251", "30121", "00-0033280", "11690",
    )
    assert cmc["sportradar_id"] == "f96db0af-5e25-42d1-a07a-49b4e065b364"
    assert cmc["depth_chart_position"] == "RB" and cmc["depth_chart_order"] == 1 and cmc["search_rank"] == 5
    assert cmc["age"] == 30 and cmc["years_exp"] == 9 and cmc["birth_date"] == "1996-06-07" and cmc["number"] == 23
    assert cmc["college"] == "Stanford" and cmc["active"] is True
    assert cmc["fantasy_positions"] == ["RB"]
    assert json.loads(cmc["metadata"])["rookie_year"] == "2017"

    gibbs = _row(df, "9221")
    assert gibbs["search_rank"] == 1 and gibbs["depth_chart_order"] == 1
    assert gibbs["espn_id"] is None and gibbs["yahoo_id"] is None and gibbs["gsis_id"] is None  # real gap upstream

    det = _row(df, "DET")
    assert det["position"] == "DEF" and det["team"] == "DET" and det["fantasy_positions"] == ["DEF"]
    assert det["status"] is None and det["metadata"] is None

    hill = _row(df, "3321")
    assert hill["team"] is None and hill["status"] == "Active" and hill["injury_status"] == "Out"
    assert hill["injury_body_part"] == "Knee - ACL"

    richardson = _row(df, "6462")
    assert richardson["gsis_id"] == "00-0035057"  # upstream value is ' 00-0035057' (leading space stripped)

    assert _row(df, "11651")["injury_status"] == "PUP"
    assert _row(df, "14034")["injury_status"] == "Sus"
    assert _row(df, "7593")["status"] == "Inactive" and _row(df, "7593")["team"] == "ATL"
