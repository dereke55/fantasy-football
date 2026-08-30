"""Parse the real Yahoo pub-api-ro fixtures (tests/fixtures/yahoo_pub, see PROVENANCE.md) and check hand-read values."""
from __future__ import annotations

import json
from pathlib import Path

import polars as pl

from app.ingest.yahoo_pub import (
    COLUMNS,
    DRAFT_ANALYSIS_FIELDS,
    YAHOO_TEAM_TO_NFLVERSE,
    endpoint_name,
    normalize_team_abbr,
    page_url,
    parse_players_page,
    rows_to_frame,
    to_float,
)

FIXTURES = Path(__file__).parent / "fixtures" / "yahoo_pub"


def _load(name: str) -> list[dict]:
    with (FIXTURES / name).open(encoding="utf-8") as f:
        return parse_players_page(json.load(f))


def test_da_ap_page_gibbs_row_and_injury_fields() -> None:
    rows = _load("players_DA_AP_p0.json")
    assert len(rows) == 40
    assert [r["page_index"] for r in rows] == list(range(40))

    gibbs = rows[0]
    assert gibbs["player_key"] == "470.p.40059"
    assert gibbs["player_id"] == "40059"
    assert (gibbs["name_full"], gibbs["name_first"], gibbs["name_last"]) == ("Jahmyr Gibbs", "Jahmyr", "Gibbs")
    assert gibbs["editorial_team_abbr"] == "Det"
    assert gibbs["team_abbr_nflverse"] == "DET"
    assert gibbs["display_position"] == "RB"
    assert gibbs["position_type"] == "O"
    assert gibbs["bye_weeks_week"] == 6
    assert gibbs["uniform_number"] == "0"
    assert gibbs["eligible_positions"] == ["RB"]
    assert gibbs["status"] is None and gibbs["injury_note"] is None
    assert gibbs["average_pick"] == 1.4
    assert gibbs["average_round"] == 1.0
    assert gibbs["average_cost"] == 73.6
    assert gibbs["percent_drafted"] == 1.0
    assert gibbs["preseason_average_pick"] == 1.4
    assert gibbs["preseason_average_cost"] == 73.7
    assert gibbs["preseason_percent_drafted"] == 1.0

    nacua = rows[3]
    assert nacua["name_full"] == "Puka Nacua"
    assert nacua["editorial_team_abbr"] == "LAR"
    assert nacua["team_abbr_nflverse"] == "LA"  # nflverse uses LA for the Rams
    assert (nacua["status"], nacua["status_full"], nacua["injury_note"]) == ("Q", "Questionable", "Groin")
    assert nacua["average_pick"] == 4.8
    assert nacua["bye_weeks_week"] == 11

    love = rows[26]  # 2026 rookie present with a Yahoo player_id
    assert (love["name_full"], love["player_key"], love["player_id"]) == ("Jeremiyah Love", "470.p.42625", "42625")
    assert love["team_abbr_nflverse"] == "ARI"
    assert love["average_pick"] == 29.1


def test_kicker_page_dash_means_null() -> None:
    rows = _load("players_AR_K_p0.json")
    assert len(rows) == 30
    aubrey = rows[0]
    assert aubrey["name_full"] == "Brandon Aubrey"
    assert (aubrey["display_position"], aubrey["position_type"]) == ("K", "K")
    assert (aubrey["average_pick"], aubrey["average_round"], aubrey["average_cost"]) == (85.9, 9.2, 4.5)

    smyth = rows[17]
    assert smyth["name_full"] == "Charlie Smyth"
    assert smyth["player_key"] == "470.p.40873"
    assert all(smyth[f] is None for f in DRAFT_ANALYSIS_FIELDS)  # every field is "-" upstream
    assert sum(r["average_pick"] is None for r in rows) == 10


def test_def_page_team_defense_rows() -> None:
    rows = _load("players_AR_DEF_p0.json")
    assert len(rows) == 8
    texans = rows[0]
    assert texans["player_key"] == "470.p.100034"
    assert texans["player_id"] == "100034"
    assert (texans["name_full"], texans["name_first"], texans["name_last"]) == ("Texans", "Texans", "")
    assert texans["editorial_team_abbr"] == "Hou" and texans["team_abbr_nflverse"] == "HOU"
    assert (texans["display_position"], texans["position_type"]) == ("DEF", "DT")
    assert texans["eligible_positions"] == ["DEF"]
    assert texans["uniform_number"] is None  # JSON false upstream
    assert texans["bye_weeks_week"] == 8
    assert texans["average_pick"] == 93.1

    rams = rows[1]
    assert (rams["name_full"], rams["player_key"], rams["team_abbr_nflverse"]) == ("Rams", "470.p.100014", "LA")
    assert rams["average_pick"] == 88.9

    jags = rows[7]
    assert (jags["name_full"], jags["team_abbr_nflverse"]) == ("Jaguars", "JAX")
    assert (jags["percent_drafted"], jags["preseason_percent_drafted"]) == (0.87, 0.9)
    assert all(r["player_key"].startswith("470.p.1000") for r in rows)


def test_rows_to_frame_schema_and_nulls() -> None:
    rows = _load("players_AR_DEF_p0.json") + _load("players_AR_K_p0.json")
    for r in rows:
        r["query_sort"], r["query_position"], r["page_start"] = "AR", r["display_position"], 0
    df = rows_to_frame(rows)
    assert df.height == 38
    assert list(df.columns) == list(COLUMNS)
    assert df.schema["eligible_positions"] == pl.List(pl.Utf8)
    assert df.schema["average_pick"] == pl.Float64
    assert df.filter(pl.col("display_position") == "DEF")["uniform_number"].null_count() == 8
    assert df["average_pick"].null_count() == 10
    assert df["player_key"].n_unique() == 38


def test_helpers() -> None:
    assert to_float("-") is None and to_float("") is None and to_float(None) is None
    assert to_float("1.00") == 1.0 and to_float("73.6") == 73.6
    assert normalize_team_abbr("LAR") == "LA" and normalize_team_abbr("LV") == "LV"
    assert normalize_team_abbr("Was") == "WAS" and normalize_team_abbr("Jax") == "JAX"
    assert normalize_team_abbr(None) is None
    assert len(YAHOO_TEAM_TO_NFLVERSE) == 32 and len(set(YAHOO_TEAM_TO_NFLVERSE.values())) == 32
    assert page_url(0) == (
        "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players"
        ";sort=AR;start=0;count=100;out=draft_analysis?format=json"
    )
    assert ";sort=DA_AP;start=200;" in page_url(200, sort="DA_AP")
    assert ";sort=AR;position=DEF;start=0;" in page_url(0, "DEF")
    assert endpoint_name(100) == "players_AR_p100"
    assert endpoint_name(0, "K") == "players_AR_K_p0"
    assert endpoint_name(0, sort="DA_AP") == "players_DA_AP_p0"
