"""Keeper-helper tests on the real projection pool and real market data (no mocks)."""
import polars as pl
import pytest

from app.ranking.availability import Candidate, expected_best_value
from app.ranking.keeper_value import expected_best_by_round, keeper_table, round_pick_numbers
from app.scoring.config import load_league_config


@pytest.fixture(scope="module")
def cfg():
    return load_league_config()


@pytest.fixture(scope="module")
def table() -> pl.DataFrame:
    return keeper_table()


def test_round_pick_numbers_cover_every_pick(cfg):
    per_round = round_pick_numbers(cfg, slot=None)
    assert len(per_round) == cfg.roster.rounds
    all_picks = sorted(p for picks in per_round.values() for p in picks)
    assert all_picks == list(range(1, cfg.league.num_teams * cfg.roster.rounds + 1))
    # a single slot gets exactly one pick per round, and the snake alternates ends
    s1 = round_pick_numbers(cfg, slot=1)
    assert all(len(v) == 1 for v in s1.values())
    assert s1[1][0] == 1 and s1[2][0] == cfg.league.num_teams * 2


def test_later_picks_are_worth_less(cfg):
    ebr = expected_best_by_round().sort("round")
    vals = ebr["expected_best_vorp"].to_list()
    assert vals == sorted(vals, reverse=True), "the expected best available must fall as the draft goes on"
    assert vals[0] > vals[-1] * 2


def test_surplus_is_vorp_minus_the_pick_it_costs(table):
    ebr = {r["round"]: r["expected_best_vorp"] for r in expected_best_by_round().to_dicts()}
    row = table.head(1).to_dicts()[0]
    for rnd, exp_best in ebr.items():
        assert row[f"surplus_r{rnd}"] == pytest.approx(row["vorp"] - exp_best, abs=0.2)


def test_break_even_round_is_the_first_positive_round(table):
    for row in table.head(60).to_dicts():
        be = row["break_even_round"]
        if be is None:
            assert all(row[f"surplus_r{r}"] <= 0 for r in (1, 8, 16))
            continue
        assert row[f"surplus_r{be}"] > 0
        if be > 1:
            assert row[f"surplus_r{be - 1}"] <= 0


def test_elite_players_are_keepable_late_and_replacement_players_are_not(table):
    best = table.head(3).to_dicts()
    assert all(r["break_even_round"] is not None and r["break_even_round"] <= 3 for r in best)
    tail = table.filter(pl.col("vorp") <= 0)
    assert tail.height > 0
    assert tail["break_even_round"].null_count() == tail.height, "a replacement-level player is never worth a pick"


def test_expected_best_value_respects_availability():
    """A player certain to be gone contributes nothing; a certain survivor caps the expectation."""
    gone = Candidate(1, "RB", 100.0, 1.0, 1.0)
    survivor = Candidate(2, "RB", 40.0, 200.0, 5.0)
    assert expected_best_value([gone], at_pick=60) < 1.0
    assert expected_best_value([survivor], at_pick=60) == pytest.approx(40.0, abs=0.5)
    assert expected_best_value([gone, survivor], at_pick=60) == pytest.approx(40.0, abs=1.0)
