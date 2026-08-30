"""Ranking-pipeline tests against the real database and the latest persisted run."""
import json

import polars as pl
import pytest

from app.db import engine
from app.ranking.pipeline import (
    DRAFTABLE_ADP,
    ESTABLISHED_ROUNDS,
    POS_GAP_MIN,
    SLEEPER_GAP,
    SLEEPER_GAP_Z,
)


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
        established=pl.col("signals").map_elements(
            lambda s: (s if isinstance(s, dict) else json.loads(s)).get("established"), return_dtype=pl.Boolean),
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


def test_sleeper_means_unheralded_and_value_means_discounted(board):
    """Same evidence, different word.

    A former MVP coming off a touchdown-unlucky season is a real value opinion but he is not a secret: Dak
    Prescott and Patrick Mahomes were both flagged "sleeper" before this split.
    """
    sleepers = board.filter(pl.col("flags").list.contains("sleeper"))
    values = board.filter(pl.col("flags").list.contains("value"))
    assert sleepers.height and values.height
    assert set(sleepers["name"]) & set(values["name"]) == set(), "a player cannot be both"
    # every sleeper is genuinely unheralded, every value pick genuinely established
    assert sleepers["established"].any() is not True
    assert all(values["established"].to_list())
    # both carry the same evidentiary burden as before
    for frame in (sleepers, values):
        for row in frame.to_dicts():
            assert row["gap_z"] >= SLEEPER_GAP_Z and row["gap"] >= SLEEPER_GAP
            assert len(row["support"]) >= 2
            assert row["composite_adp"] <= DRAFTABLE_ADP


def test_established_is_market_or_production_based(board):
    """Established = an early pick, or a starter-level finish last season."""
    from app.scoring.config import load_league_config

    cfg = load_league_config()
    early = cfg.league.num_teams * ESTABLISHED_ROUNDS
    starters = {pos: cfg.league.num_teams * n for pos, n in cfg.roster.slots.items()}
    for row in board.filter(pl.col("established")).head(120).to_dicts():
        prior = json.loads(row["signals"])["prior_pos_rank"] if isinstance(row["signals"], str) \
            else row["signals"]["prior_pos_rank"]
        by_market = row["composite_adp"] is not None and row["composite_adp"] <= early
        by_production = prior is not None and prior <= starters.get(row["position"], 99)
        assert by_market or by_production, f"{row['name']} marked established by neither route"


def test_support_catalogue_is_wide_enough_to_fire(board):
    """The catalogue was too thin: 33 of 38 players clearing the value gap were blocked for want of a second
    signal (Breece Hall, D'Andre Swift and Mike Evans had none)."""
    gap_clearers = board.filter(
        (pl.col("gap_z") >= SLEEPER_GAP_Z) & (pl.col("gap") >= SLEEPER_GAP)
        & (pl.col("composite_adp") <= DRAFTABLE_ADP) & ~pl.col("is_kdst"))
    flagged = gap_clearers.filter(
        pl.col("flags").list.contains("sleeper") | pl.col("flags").list.contains("value"))
    assert gap_clearers.height >= 20
    assert flagged.height / gap_clearers.height >= 0.4, (
        f"only {flagged.height}/{gap_clearers.height} value gaps produce a flag — catalogue still too thin")
    # the new signals actually fire
    seen = {s for row in board.to_dicts() for s in row["support"]}
    for sig in ("inherits_vacated_opportunity", "our_model_sees_more_than_the_vendor",
                "underperformed_expected_points", "team_context_tailwind"):
        assert sig in seen, f"{sig} never fires"
