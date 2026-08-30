"""Parsing/derivation functions of app.ingest.nflverse_ref on REAL snapshot extracts (tests/fixtures/nflverse/PROVENANCE.md).

Expected values were hand-read from the fixture rows (see PROVENANCE.md for the snapshot each extract came from).
"""
from __future__ import annotations

from pathlib import Path

import polars as pl

from app.ingest.nflverse_ref import (
    bye_map,
    depth_chart_dt_summary,
    derive_team_bye,
    draft_pick_id_styles,
    id_columns,
    id_coverage,
    rankings_summary,
)

FIX = Path(__file__).parent / "fixtures" / "nflverse"


def _csv(name: str) -> pl.DataFrame:
    return pl.read_csv(FIX / name, infer_schema_length=None)


def test_derive_team_bye_2026_sea_det():
    # 34 REG games involving SEA or DET: SEA plays weeks 1-10 and 12-18, DET plays every week except 6.
    games = _csv("schedules_2026_SEA_DET.csv")
    byes = derive_team_bye(games, 2026)
    assert set(byes.columns) == {"season", "team", "bye_week"}
    m = bye_map(byes.filter(pl.col("team").is_in(["SEA", "DET"])))
    assert m == {"DET": [6], "SEA": [11]}
    # a REG-only derivation: the same frame with game_type flipped must yield no byes at all for those teams
    assert derive_team_bye(games.with_columns(pl.lit("POST").alias("game_type")), 2026).height == 0


def test_rankings_summary_overall_redraft_top5():
    df = _csv("ff_rankings_draft_sample.csv")
    s = rankings_summary(df, top=5)
    assert s["page_types"] == ["dynasty-overall", "redraft-overall", "redraft-qb"]
    assert s["ecr_types"] == ["do", "ro", "rp"]
    assert s["overall_page_types"] == ["redraft-overall"]
    assert s["overall_rows"] == 40  # dynasty/qb pages excluded
    top = s["top"]
    assert [(t["player"], t["ecr"]) for t in top] == [
        ("Ja'Marr Chase", 1.55),
        ("Jahmyr Gibbs", 2.48),
        ("Puka Nacua", 3.19),
        ("Bijan Robinson", 4.1),
        ("Jaxon Smith-Njigba", 4.67),
    ]
    assert top[0]["id"] == 19788 and top[0]["team"] == "CIN" and top[0]["bye"] == 6
    assert s["scrape_date_max"] == "2026-08-28"


def test_ff_playerids_id_columns_and_coverage():
    df = _csv("ff_playerids_sample.csv")
    cols = id_columns(df)
    for c in ("gsis_id", "sleeper_id", "espn_id", "yahoo_id", "stats_id", "fantasypros_id", "pfr_id", "mfl_id"):
        assert c in cols
    # 33 rows: only the 3 veterans carry yahoo_id; 8 rows lack stats_id; 12 rows lack gsis_id
    cov = id_coverage(df, ["yahoo_id", "stats_id", "gsis_id", "missing_col"])
    assert cov == {"yahoo_id": 3, "stats_id": 25, "gsis_id": 21, "missing_col": 0}
    chase = df.filter(pl.col("name") == "Ja'Marr Chase").row(0, named=True)
    assert chase["gsis_id"] == "00-0036900"
    assert int(chase["yahoo_id"]) == 33393 and int(chase["stats_id"]) == 33393
    assert chase["sleeper_id"] == 7564 and chase["espn_id"] == 4362628


def test_draft_pick_id_styles_2026_esb_vs_2025_gsis():
    df = _csv("draft_picks_2026_r1_2025_top3.csv")
    assert draft_pick_id_styles(df, 2026) == {"rows": 32, "gsis_id_non_null": 27, "gsis_style": 0, "esb_style": 27}
    assert draft_pick_id_styles(df, 2025) == {"rows": 3, "gsis_id_non_null": 3, "gsis_style": 3, "esb_style": 0}
    first = df.filter((pl.col("season") == 2026) & (pl.col("pick") == 1)).row(0, named=True)
    assert first["pfr_player_name"] == "Fernando Mendoza" and first["gsis_id"] == "MEN516487"


def test_depth_chart_dt_summary_sea_qb():
    df = _csv("depth_charts_2026_SEA_QB_first_last_dt.csv")
    s = depth_chart_dt_summary(df)
    assert s["n_dt"] == 2
    assert s["min_dt"] == "2026-03-22T06:38:42Z" and s["max_dt"] == "2026-08-29T12:56:08Z"
    latest = df.filter(pl.col("dt") == s["max_dt"]).sort("pos_rank")
    assert latest.get_column("player_name").to_list() == ["Sam Darnold", "Drew Lock", "Jalen Milroe"]
    assert latest.get_column("gsis_id").to_list() == ["00-0034869", "00-0035704", "00-0040673"]
