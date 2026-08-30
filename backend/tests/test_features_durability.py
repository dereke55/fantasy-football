"""Phase 3 feature-layer tests — durability, depth chart and team tendencies.

Real data only, read-only: every assertion runs against the live `fantasy_football` Postgres, and the
hand-computed expectations below were derived from these SQL runs (2026-08-30):

  select gsis_id, string_agg(week::text||':'||status||'/'||status_description_abbr, ' ' order by week)
  from raw_nflverse_roster_weekly where game_type='REG' and ... group by 1;

    Christian McCaffrey 00-0033280 2024  wk 1 INA/A01, wk 2-8 RES/R01, wk 10-13 ACT/A01, wk 14-18 RES/R01
                                         (SF bye = wk 9, absent from the file)              -> 17 eligible
    Zach Ertz           00-0030061 2025  wk 1-11 + 13-14 ACT/A01, wk 15-18 RES/R01
                                         (WAS bye = wk 12)                                  -> 17 eligible
    Malik Nabers        00-0039337 2025  wk 1-4 ACT/A01, wk 5-18 RES/R01
                                         (NYG bye = wk 14)                                  -> 17 eligible

  select player_id, string_agg(week::text, ',' order by week) from raw_nflverse_stats_player_week
  where season_type='REG' and (targets+carries+attempts) >= 1 and ... group by 1;

    McCaffrey 2024 -> 10,11,12,13                      (4 played, 13 missed)
    Ertz      2025 -> 1..11,13,14                      (13 played, 4 missed)
    Nabers    2025 -> 1,2,3,4                          (4 played, 13 missed)

Every one of the three is a genuine injured-reserve stint, not a healthy scratch.
"""
from __future__ import annotations

import polars as pl
import pytest
from sqlalchemy import text

from app.db import engine
from app.features import depth, durability, team_tendencies

SEASONS = [2023, 2024, 2025]
DEPTH_SEASON = 2026

# (name, gsis_id, season, eligible_games, games_played, games_missed) — hand-computed, see module docstring.
MISSED_TIME_PLAYERS = [
    ("Christian McCaffrey", "00-0033280", 2024, 17, 4, 13),
    ("Zach Ertz", "00-0030061", 2025, 17, 13, 4),
    ("Malik Nabers", "00-0039337", 2025, 17, 4, 13),
]

# 2026 first-round rookie: ARI RB, pick 3 overall, RB1 on the 2026-08-29 depth chart. No 2023-25 history.
ROOKIE_GSIS = "00-0041027"
ROOKIE_NAME = "Jeremiyah Love"


@pytest.fixture(scope="module")
def per_season() -> pl.DataFrame:
    return durability.compute(SEASONS)


@pytest.fixture(scope="module")
def summary() -> pl.DataFrame:
    return durability.compute_summary(SEASONS)


@pytest.fixture(scope="module")
def depth_rows() -> pl.DataFrame:
    return depth.compute(DEPTH_SEASON)


@pytest.fixture(scope="module")
def tendencies() -> pl.DataFrame:
    return team_tendencies.compute(SEASONS)


def _sql_games_missed(gsis_id: str, season: int) -> tuple[int, int]:
    """Independent hand-written SQL for (eligible_games, games_played) — deliberately NOT the module's query."""
    sql = text(
        """
        with eligible as (
            select distinct week
            from raw_nflverse_roster_weekly
            where gsis_id = :gsis and season = :season and game_type = 'REG'
              and status in ('ACT', 'INA', 'RES', 'PUP')
              and left(status_description_abbr, 1) not in ('P', 'W', 'E', 'F')
              and status_description_abbr not in ('R02', 'R03', 'R06', 'R09', 'R30', 'R33', 'R40')
        ),
        played as (
            select distinct week
            from raw_nflverse_stats_player_week
            where player_id = :gsis and season = :season and season_type = 'REG'
              and (coalesce(targets, 0) + coalesce(carries, 0) + coalesce(attempts, 0)) >= 1
        )
        select (select count(*) from eligible),
               (select count(*) from eligible e join played p on p.week = e.week)
        """
    )
    with engine.connect() as conn:
        row = conn.execute(sql, {"gsis": gsis_id, "season": season}).one()
    return int(row[0]), int(row[1])


# --------------------------------------------------------------------------- durability


@pytest.mark.parametrize(("name", "gsis_id", "season", "eligible", "played", "missed"), MISSED_TIME_PLAYERS)
def test_games_missed_matches_hand_run_sql(
    per_season: pl.DataFrame, name: str, gsis_id: str, season: int, eligible: int, played: int, missed: int
) -> None:
    row = per_season.filter((pl.col("gsis_id") == gsis_id) & (pl.col("season") == season))
    assert row.height == 1, f"{name} {season} should have exactly one durability row"
    got = row.to_dicts()[0]
    assert got["name"] == name
    assert (got["eligible_games"], got["games_played"], got["games_missed"]) == (eligible, played, missed)
    assert got["games_missed"] == max(0, got["eligible_games"] - got["games_played"])
    assert _sql_games_missed(gsis_id, season) == (eligible, played)


def test_per_season_keys_are_unique_and_bye_weeks_excluded(per_season: pl.DataFrame) -> None:
    assert per_season.height > 0
    assert per_season.select("player_id", "gsis_id", "season").is_duplicated().sum() == 0
    # nflverse omits the bye from roster_weekly, so 17 is the normal ceiling; 18 is only reachable by a
    # player traded across two different bye weeks (6 such rows in 2023-2025, e.g. Rashid Shaheed 2025)
    assert per_season["eligible_games"].max() <= 18
    assert per_season.filter(pl.col("eligible_games") > 17).height <= 10
    assert per_season["games_missed"].min() >= 0
    assert per_season["season"].unique().sort().to_list() == SEASONS


def test_summary_has_one_row_per_hub_player_and_nulls_for_no_history(summary: pl.DataFrame) -> None:
    hub = durability.hub_players()
    assert summary.height == hub.height
    assert summary.select("player_id").is_duplicated().sum() == 0
    no_history = summary.filter(pl.col("games_eligible_3yr").is_null())
    assert no_history.height > 0
    # a player with no history still gets a row, an e_games and bio — only the history columns are null
    assert no_history["miss_rate_3yr"].null_count() == no_history.height
    assert no_history["e_games"].null_count() == 0


def test_injury_prone_is_a_bool_for_every_row(summary: pl.DataFrame) -> None:
    assert summary.schema["injury_prone"] == pl.Boolean
    assert summary["injury_prone"].null_count() == 0
    assert all(isinstance(v, bool) for v in summary["injury_prone"].to_list())
    assert summary.schema["structural_injury_return"] == pl.Boolean
    assert summary["structural_injury_return"].null_count() == 0


def test_injury_prone_rule_holds_on_the_real_rows(summary: pl.DataFrame) -> None:
    flagged = summary.filter(pl.col("injury_prone"))
    assert flagged.height > 0
    ok = flagged.filter(
        (
            (pl.col("miss_rate_3yr") >= durability.INJURY_PRONE_MISS_RATE)
            & (pl.col("injury_events_3yr") >= durability.INJURY_PRONE_MIN_EVENTS)
            & (pl.col("seasons_with_injury_events") >= durability.INJURY_PRONE_MIN_SEASONS)
        )
        | (pl.col("seasons_with_soft_tissue") >= durability.INJURY_PRONE_MIN_SEASONS)
    )
    assert ok.height == flagged.height
    # nobody without history can be flagged
    assert summary.filter(pl.col("injury_prone") & pl.col("games_eligible_3yr").is_null()).height == 0


def test_e_games_bounds_and_known_missed_weeks(summary: pl.DataFrame) -> None:
    assert summary["e_games"].min() >= 0.0
    assert summary["e_games"].max() <= 17.0
    assert summary["known_missed_weeks"].null_count() == 0
    seed = durability.known_missed_weeks()
    assert len(seed) == 43  # backend/seeds/known_missed_weeks.yaml
    seeded = summary.filter(pl.col("known_missed_weeks") > 0)
    assert seeded.height > 0
    for row in seeded.iter_rows(named=True):
        assert row["known_missed_weeks"] == seed[row["gsis_id"]]
        assert row["e_games"] <= 17 - row["known_missed_weeks"] + 1e-9
    assert summary.filter(~pl.col("gsis_id").is_in(list(seed)))["known_missed_weeks"].max() == 0


# --------------------------------------------------------------------------- rookie


def test_2026_rookie_has_null_history_but_real_depth_and_bio(
    summary: pl.DataFrame, depth_rows: pl.DataFrame, per_season: pl.DataFrame
) -> None:
    srow = summary.filter(pl.col("gsis_id") == ROOKIE_GSIS)
    assert srow.height == 1, f"{ROOKIE_NAME} must still get a summary row"
    s = srow.to_dicts()[0]
    assert s["name"] == ROOKIE_NAME
    assert s["is_rookie"] is True
    for col in (
        "games_missed_3yr", "games_eligible_3yr", "miss_rate_3yr", "injury_events_3yr",
        "injury_causes", "structural_cause", "structural_season",
    ):
        assert s[col] is None, f"{col} should be null for a 2026 rookie, got {s[col]!r}"
    assert s["injury_prone"] is False
    assert s["structural_injury_return"] is False
    # bio + E[games] are populated
    assert s["draft_round"] == 1
    assert s["draft_pick"] == 3
    assert s["age_2026"] is not None and 20 < s["age_2026"] < 26
    assert s["e_games"] > 0
    # no per-season history rows at all
    assert per_season.filter(pl.col("gsis_id") == ROOKIE_GSIS).height == 0
    # ... but a real 2026 depth-chart slot
    drow = depth_rows.filter(pl.col("gsis_id") == ROOKIE_GSIS).to_dicts()[0]
    assert drow["appears_on_chart"] is True
    assert drow["team"] == "ARI"
    assert drow["depth_pos"] == "RB"
    assert drow["depth_rank"] == 1
    assert drow["depth_dt"] is not None


# --------------------------------------------------------------------------- depth chart


def test_depth_has_one_row_per_hub_player(depth_rows: pl.DataFrame) -> None:
    assert depth_rows.height == durability.hub_players().height
    assert depth_rows.select("player_id").is_duplicated().sum() == 0
    on_chart = depth_rows.filter(pl.col("appears_on_chart"))
    assert on_chart.height > 500
    assert on_chart["depth_rank"].min() == 1
    # the position we read the rank from is always the player's hub position
    assert on_chart.filter(pl.col("depth_pos") != pl.col("position")).height == 0
    # a 30-day-ago rank only ever comes with a change, and vice versa
    assert depth_rows.filter(
        pl.col("depth_rank_30d_ago").is_not_null() & pl.col("depth_rank_change_30d").is_null()
    ).height == 0


def test_qb_depth_ranks_are_1_to_n_at_the_latest_dt() -> None:
    rows = depth.depth_chart_rows(DEPTH_SEASON).filter(pl.col("pos_abb") == "QB")
    latest = rows.group_by("team").agg(dt=pl.col("dt").max())
    current = rows.join(latest, on=["team", "dt"], how="inner")
    assert current["team"].n_unique() == 32
    for team, group in current.group_by("team"):
        ranks = sorted(group["pos_rank"].to_list())
        assert ranks == list(range(1, len(ranks) + 1)), f"{team[0]} QB ranks are not 1..N: {ranks}"


# --------------------------------------------------------------------------- team tendencies


def test_team_tendencies_shape_and_pass_rate_range(tendencies: pl.DataFrame) -> None:
    assert tendencies.height == 32 * len(SEASONS)
    assert tendencies.select("team", "season").is_duplicated().sum() == 0
    t2025 = tendencies.filter(pl.col("season") == 2025)
    assert t2025.height == 32
    assert t2025["pass_rate"].min() >= 0.30
    assert t2025["pass_rate"].max() <= 0.80
    assert t2025["games"].unique().to_list() == [17]


def test_team_tendencies_internal_consistency(tendencies: pl.DataFrame) -> None:
    df = tendencies.with_columns(
        plays=pl.col("pass_attempts") + pl.col("rush_attempts"),
        recomputed_rate=pl.col("pass_attempts") / (pl.col("pass_attempts") + pl.col("rush_attempts")),
    )
    assert ((df["pass_rate"] - df["recomputed_rate"]).abs() < 1e-3).all()
    assert ((df["plays_pg"] - df["plays"] / df["games"]).abs() < 1e-2).all()
    assert df["carries_total"].equals(df["rush_attempts"])
    for col in ("target_concentration_top2", "rb_carry_share_top1"):
        assert df[col].min() > 0.0
        assert df[col].max() <= 1.0
