"""Market layer tests — real database and real snapshot data (no mocks, per CLAUDE.md).

The market layer is pure aggregation over already-ingested raw tables, so these assert the invariants the
Phase 6 ranking model depends on: per-source coverage, the composite, the disagreement residual and sd_adp.
"""
import polars as pl
import pytest

from app.ingest.players_hub import norm_name
from app.market.build import (
    GATE_ONE_SOURCE_DEPTH,
    GATE_TWO_SOURCE_DEPTH,
    collect,
    compute_market,
    fit_sd_adp,
)


@pytest.fixture(scope="module")
def snaps() -> pl.DataFrame:
    return collect()


@pytest.fixture(scope="module")
def market(snaps) -> pl.DataFrame:
    return compute_market(snaps)


def test_all_four_sources_present_and_resolved(snaps):
    per_source = dict(snaps.group_by("source").len().iter_rows())
    assert set(per_source) == {"fantasypros_mirror", "yahoo_pub", "ffc", "sleeper"}
    assert per_source["fantasypros_mirror"] > 400 and per_source["sleeper"] > 400
    assert per_source["ffc"] >= 232, "every FFC row must resolve to a player (defenses match on team)"
    assert snaps["player_id"].null_count() == 0


def test_no_sentinel_adp_leaks_through(snaps):
    adp = snaps.filter(pl.col("source") == "sleeper")["adp"]
    assert adp.max() < 999, "Sleeper 999/1000 sentinels must be nulled, not treated as picks"
    assert snaps.filter(pl.col("adp") <= 0).height == 0


def test_composite_and_source_counts(market):
    top = market.head(50)
    assert top["n_sources"].min() >= 3, "the top 50 should appear in at least 3 of the 4 sources"
    # composite_rank is the mean of the available per-source ranks
    row = top.head(1).to_dicts()[0]
    ranks = [row[c] for c in ("ecr_rank", "yahoo_rank", "ffc_rank", "sleeper_rank") if row[c] is not None]
    assert row["composite_rank"] == pytest.approx(sum(ranks) / len(ranks), abs=0.01)
    assert row["n_sources"] == len(ranks)


def test_sd_adp_prefers_ffc_and_falls_back_to_the_fit(market, snaps):
    a, b = fit_sd_adp(snaps)
    assert 0.5 < a < 3.0 and 0.05 < b < 0.20, f"sd fit {a=} {b=} should be near the plan's 1 + 0.10*ADP"
    ffc_backed = market.filter(pl.col("sd_adp_source") == "ffc")
    assert ffc_backed.height >= 200
    assert (ffc_backed["sd_adp"] == ffc_backed["ffc_sd"]).all()
    fitted = market.filter((pl.col("sd_adp_source") == "fit") & pl.col("composite_adp").is_not_null())
    assert fitted["sd_adp"].min() >= 1.0, "the fallback is max(1, a + b*adp)"


def test_sd_adp_is_much_tighter_than_the_naive_adp_over_4_rule(market):
    """The plan replaced sd = ADP/4 with the FFC fit; confirm the two really differ on real data."""
    sub = market.filter(pl.col("ffc_adp").is_not_null() & (pl.col("ffc_adp") > 30))
    assert (sub["sd_adp"] < sub["ffc_adp"] / 4).mean() > 0.9


def test_disagreement_is_a_residual_around_zero(market):
    d = market.filter(pl.col("disagreement").is_not_null())["disagreement"]
    assert d.len() > 300
    assert abs(d.mean()) < 1.0, "a residual from an OLS fit should centre near zero"
    assert d.min() < 0 < d.max()


def test_gate_coverage_depths_hold(market):
    ecr = market.filter(pl.col("ecr_rank").is_not_null()).sort("ecr_rank")
    assert ecr.head(GATE_TWO_SOURCE_DEPTH)["n_adp_sources"].min() >= 2
    assert ecr.head(GATE_ONE_SOURCE_DEPTH)["n_adp_sources"].min() >= 1
    assert market.head(300).height == 300


def test_name_normalization_handles_accents_and_suffixes():
    assert norm_name("Eddy Piñeiro") == "eddy pineiro"
    assert norm_name("Michael Pittman Jr.") == "michael pittman"
    assert norm_name("James Cook III") == "james cook"
    assert norm_name("Ja'Marr Chase") == "jamarr chase"
