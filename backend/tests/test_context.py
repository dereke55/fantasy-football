"""Curated team-context tests — the seeds are hand-maintained, so these guard the things that would
silently corrupt a WHY bullet: coverage, provenance, enum validity and the known 2026 facts."""
import polars as pl
import pytest

from app.context.build import build_rows, validate
from app.db import engine


@pytest.fixture(scope="module")
def rows() -> list[dict]:
    return build_rows()


@pytest.fixture(scope="module")
def loaded() -> pl.DataFrame:
    return pl.read_database("select * from team_context", connection=engine, infer_schema_length=None)


def test_seeds_validate_clean():
    assert validate() == []


def test_every_team_present_once_and_sourced(rows):
    assert len(rows) == 32
    assert len({r["team"] for r in rows}) == 32
    for r in rows:
        assert set(r["sources"]) == {"coaching_changes", "qb_situations", "ol_changes"}
        for seed, prov in r["sources"].items():
            assert prov["source_url"], f"{r['team']}/{seed} has no source_url"
            assert prov["confidence"] in {"high", "medium", "low"}


def test_known_2026_facts_are_encoded(loaded):
    by_team = {r["team"]: r for r in loaded.to_dicts()}
    # ten new head coaches, verified against Wikipedia's 2026 season page during research
    new_hc = {t for t, r in by_team.items() if r["hc_new"]}
    assert new_hc == {"ARI", "ATL", "BAL", "BUF", "CLE", "LV", "MIA", "NYG", "PIT", "TEN"}
    assert by_team["ATL"]["hc"] == "Kevin Stefanski"
    assert by_team["CLE"]["hc"] == "Todd Monken"
    # teams that kept their head coach but changed play-caller
    assert by_team["DEN"]["play_caller_new"] and not by_team["DEN"]["hc_new"]
    assert by_team["DEN"]["play_caller"] == "Davis Webb"
    # unsettled QB rooms as of the seed date
    unsettled = {t for t, r in by_team.items() if r["qb_status"] != "settled"}
    assert {"ATL", "LV"} <= unsettled


def test_flags_are_the_only_thing_context_drives(loaded):
    """Phase 5 contributes tags, never a projection multiplier (docs/decisions.md 2026-08-29)."""
    cols = set(loaded.columns)
    assert not any("multiplier" in c or "factor" in c or "adjust" in c for c in cols)
    assert loaded["ol_delta"].min() >= -2 and loaded["ol_delta"].max() <= 2


def test_provenance_survives_the_load(loaded):
    r = loaded.filter(pl.col("team") == "DEN").to_dicts()[0]
    assert r["sources"]["coaching_changes"]["source_url"].startswith("http")
    assert set(r["seed_hashes"]) == {"coaching_changes", "qb_situations", "ol_changes"}
    assert all(len(h) == 64 for h in r["seed_hashes"].values())
