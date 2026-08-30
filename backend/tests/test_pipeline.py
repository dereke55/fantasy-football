"""Ranking-pipeline tests against the real database and the latest persisted run."""
import json

import polars as pl
import pytest

from app.db import engine
from app.ranking.pipeline import DRAFTABLE_ADP, POS_GAP_MIN, SLEEPER_GAP, SLEEPER_GAP_Z


def q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


LATEST = "(select run_id from ranking_runs where status='ok' order by started_at desc limit 1)"


@pytest.fixture(scope="module")
def board() -> pl.DataFrame:
    df = q(f"select k.*, p.name from rankings k join players p on p.id = k.player_id where k.run_id = {LATEST}")
    assert df.height > 300, "run `uv run ff rank run` first"
    return df.with_columns(
        support=pl.col("signals").map_elements(
            lambda s: (s if isinstance(s, dict) else json.loads(s)).get("support", []), return_dtype=pl.List(pl.Utf8)),
        risk=pl.col("signals").map_elements(
            lambda s: (s if isinstance(s, dict) else json.loads(s)).get("risk", []), return_dtype=pl.List(pl.Utf8)),
        pos_gap=pl.col("signals").map_elements(
            lambda s: (s if isinstance(s, dict) else json.loads(s)).get("pos_gap"), return_dtype=pl.Float64),
    )


def test_run_manifest_is_complete():
    r = q(f"select * from ranking_runs where run_id = {LATEST}").to_dicts()[0]
    assert r["status"] == "ok" and r["league_config_sha256"] and r["model_version"]
    assert r["seed_hashes"] and all(len(h) == 64 for h in r["seed_hashes"].values())
    assert r["weights"]["vendor"] + r["weights"]["inhouse"] == pytest.approx(1.0)
    assert r["n_players_ranked"] > 300 and r["n_why_bullets"] > 1000


def test_ranks_are_dense_and_ordered_by_value(board):
    ranks = sorted(board["overall_rank"].to_list())
    assert ranks == list(range(1, len(ranks) + 1))
    top = board.filter(pl.col("overall_rank") <= 50).sort("overall_rank")
    v = [x for x in top["vorp"].to_list() if x is not None]
    assert v == sorted(v, reverse=True), "overall rank must follow VORP"


def test_positional_rank_gap_has_no_unsigned_underflow(board):
    """rank() returns UInt32; subtracting without casting wrapped negatives to ~4.29e9."""
    pg = board["pos_gap"].drop_nulls()
    assert pg.min() < 0 < pg.max(), "both directions of positional disagreement must exist"
    assert pg.abs().max() < 1000, f"underflow: max |pos_gap| = {pg.abs().max()}"


def test_flags_respect_their_definitions(board):
    for row in board.filter(pl.col("flags").list.contains("sleeper")).to_dicts():
        assert row["gap_z"] >= SLEEPER_GAP_Z and row["gap"] >= SLEEPER_GAP
        assert len(row["support"]) >= 2
        assert row["composite_adp"] <= DRAFTABLE_ADP, "undraftable players must not be flagged"
    for row in board.filter(pl.col("flags").list.contains("bust")).to_dicts():
        assert row["gap_z"] <= -SLEEPER_GAP_Z and row["gap"] <= -SLEEPER_GAP
        assert len(row["risk"]) >= 2
        assert row["pos_gap"] <= -POS_GAP_MIN, "a bust must be player-specific, not positional"


def test_positional_reach_is_separated_from_bust(board):
    """In a 1-QB league every QB ranks below his ADP on overall value; that is scarcity, not a bust."""
    reach = board.filter(pl.col("flags").list.contains("positional_reach"))
    bust = board.filter(pl.col("flags").list.contains("bust"))
    assert reach.height and bust.height
    assert set(reach["name"]) & set(bust["name"]) == set(), "a player cannot be both"
    assert reach["pos_gap"].max() > bust["pos_gap"].max()
    qbs = board.filter((pl.col("position") == "QB") & pl.col("flags").list.contains("positional_reach"))
    assert qbs.height >= 1


def test_team_context_counts_as_one_signal_not_three(board):
    """18 of 32 teams changed play-caller and 21 have a line delta; counting them separately flagged 147 busts."""
    for row in board.head(200).to_dicts():
        team_signals = [s for s in row["risk"] if s.startswith("team_context:")]
        assert len(team_signals) <= 1


def test_every_top_100_player_has_at_least_three_why_bullets():
    thin = q(f"""select p.name, count(w.id) n from rankings k join players p on p.id = k.player_id
                 left join why_bullets w on w.run_id = k.run_id and w.player_id = k.player_id
                 where k.run_id = {LATEST} and k.overall_rank <= 100 group by p.name having count(w.id) < 3""")
    assert thin.is_empty(), f"players with < 3 bullets: {thin['name'].to_list()[:10]}"


def test_why_bullets_are_auditable():
    b = q(f"select * from why_bullets where run_id = {LATEST} limit 200").to_dicts()
    assert b
    for row in b:
        assert row["rule_id"] and row["template_version"] and row["text"]
        assert isinstance(row["inputs"], dict)
        assert row["polarity"] in (-1, 0, 1)


def test_no_vendor_points_leak_into_the_board(board):
    """Every points column must come from our own scoring of raw stat lines."""
    cols = set(board.columns)
    assert not {"pts_ppr", "pts_half_ppr", "pts_std", "fantasy_points", "fantasy_points_ppr"} & cols
