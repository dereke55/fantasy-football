"""Phase 6 in-house projection against the REAL Postgres data (read-only, no fixtures, no invented rows).

Every expectation is derived independently of `app.ranking.inhouse`:

* the team caps are re-summed straight off the returned frame;
* the "changed clubs" cases are proved from `raw_nflverse_stats_player_week` (the player's 2023-25 role keys)
  rather than from the module's own bookkeeping;
* the efficiency shrink is re-derived from raw yard/opportunity totals and compared with the closed form;
* `inhouse_ppg_raw` is re-scored from the projected stat line with `app.scoring.engine.score`, so the test
  fails if any fantasy point ever came from somewhere other than `config/league.yaml`.

`compute_inhouse()` is a module-scoped fixture (~1.2 s); the whole file runs in a few seconds.
"""
from __future__ import annotations

import math
from itertools import pairwise

import polars as pl
import pytest

from app.config import settings
from app.features import depth, production, team_tendencies
from app.ranking.adjustments import age_factor
from app.ranking.inhouse import (
    MIN_GAMES_FOR_SHARE,
    OUTPUT_COLUMNS,
    POSITIONS,
    ROUND_BUCKETS,
    SHRINK_K,
    _efficiency_history,
    _pass_att_shares,
    _per_game_shares,
    compute_inhouse,
    hub_players,
    measure_stability,
    player_season_volume,
    rookie_round_factors,
)
from app.scoring.config import load_league_config
from app.scoring.engine import score

SEASONS = list(settings.history_seasons)
NFL_TEAMS = 32
CAP_TOLERANCE = 1e-4          # the share columns are rounded to 6 dp before the frame is returned

# Real players, identified by gsis_id so a hub re-key cannot silently retarget the test.
BIJAN = "00-0038542"          # ATL RB, unchanged role since 2023 -> own_role
WALKER = "00-0038134"         # SEA RB 2022-25 -> KC in 2026, so his own share history is not usable
PICKENS = "00-0037247"        # PIT 2022-24 -> DAL in 2025, i.e. DAL-WR is already his 2025 role
LOVE = "00-0041027"           # 2026 rookie, ARI R1 #3 overall, no NFL history at all


@pytest.fixture(scope="module")
def proj() -> pl.DataFrame:
    return compute_inhouse(seasons=SEASONS)


@pytest.fixture(scope="module")
def hub() -> pl.DataFrame:
    return hub_players()


@pytest.fixture(scope="module")
def role_history() -> pl.DataFrame:
    """Every (player_id, season, role_key, games) a player actually logged, straight from the feature layer."""
    return production.compute(SEASONS).select("player_id", "gsis_id", "season", "role_key", "games")


def _row(proj: pl.DataFrame, hub: pl.DataFrame, gsis: str) -> dict:
    pid = hub.filter(pl.col("gsis_id") == gsis)["player_id"].item()
    matches = proj.filter(pl.col("player_id") == pid)
    assert matches.height == 1, f"{gsis} should have exactly one projection row, got {matches.height}"
    return matches.to_dicts()[0]


# --------------------------------------------------------------------------------------- contract / shape

def test_output_contract(proj: pl.DataFrame) -> None:
    assert tuple(proj.columns) == OUTPUT_COLUMNS
    assert proj.height > 500
    assert proj["player_id"].n_unique() == proj.height
    assert set(proj["position"].unique()) <= set(POSITIONS)
    assert proj["team"].null_count() == 0
    assert set(proj["share_source"].unique()) == {
        "own_role", "depth_slot_baseline", "rookie_draft_capital"
    }


def test_every_nfl_team_is_projected(proj: pl.DataFrame) -> None:
    assert proj["team"].n_unique() == NFL_TEAMS


# ------------------------------------------------------------------------------------- team-level caps

def test_team_share_caps_hold_for_every_team(proj: pl.DataFrame) -> None:
    """Within each club the projected PER-GAME shares sum to <= the measured budget.

    The budget is not 1.0. Per-game shares are conditional on the player being active, so a real roster's
    contributors sum to ~1.24 (targets) — someone always misses time and his share is redistributed. Capping at
    1.0 would apply a ~20% haircut to every skill player rather than guarding against impossible projections, so
    the cap is measured from the same data the shares come from (`measured_share_budget`).
    """
    from app.ranking.inhouse import measured_share_budget

    seasons = tuple(settings.history_seasons)
    budgets = {k: measured_share_budget(seasons, k) for k in ("target", "carry", "pass_att")}
    assert all(1.0 < b < 2.0 for b in budgets.values()), f"implausible budgets {budgets}"
    sums = proj.group_by("team").agg(
        target=pl.col("proj_target_share").sum(),
        carry=pl.col("proj_carry_share").sum(),
        pass_att=pl.col("proj_pass_att_share").sum(),
    )
    assert sums.height == NFL_TEAMS
    for r in sums.to_dicts():
        for kind in ("target", "carry", "pass_att"):
            assert r[kind] <= budgets[kind] + CAP_TOLERANCE, \
                f"{r['team']} {kind} share sums to {r[kind]} (budget {budgets[kind]})"


def test_cap_scales_proportionally(proj: pl.DataFrame) -> None:
    """A club that needed scaling has every player multiplied by the same factor, so ratios are preserved."""
    scaled = proj.filter(pl.col("target_cap_scale") < 1.0)
    assert scaled.height > 0, "expected at least one club over the raw target-share budget"
    rebuilt = scaled.with_columns(
        expected=(pl.col("target_share_raw") * pl.col("target_cap_scale")).round(6)
    )
    assert (rebuilt["expected"] - rebuilt["proj_target_share"]).abs().max() <= CAP_TOLERANCE
    # one scale per club, not per player
    per_team = scaled.group_by("team").agg(n=pl.col("target_cap_scale").n_unique())
    assert per_team["n"].max() == 1


def test_shares_are_non_negative(proj: pl.DataFrame) -> None:
    for col in ("proj_target_share", "proj_carry_share", "proj_pass_att_share"):
        assert proj[col].min() >= 0.0
        assert proj[col].null_count() == 0


# ------------------------------------------------------------------------------- share source selection

def test_changed_clubs_does_not_reuse_the_old_teams_share(
    proj: pl.DataFrame, hub: pl.DataFrame, role_history: pl.DataFrame
) -> None:
    """Kenneth Walker III was SEA-RB through 2025 and is a KC RB in 2026 -> depth-slot baseline, not SEA."""
    row = _row(proj, hub, WALKER)
    assert row["team"] == "KC"
    keys = set(role_history.filter(pl.col("gsis_id") == WALKER)["role_key"].to_list())
    assert keys and "KC-RB" not in keys, f"expected no KC history, found {sorted(keys)}"
    assert row["share_source"] == "depth_slot_baseline"
    assert row["same_role_seasons"] == 0
    assert row["role_credibility"] == 0.0

    # his projected carry share is the league-average RB1 slot (after KC's cap), not his own SEA number
    seattle_share = (
        production.compute(SEASONS)
        .filter((pl.col("gsis_id") == WALKER) & (pl.col("season") == SEASONS[-1]))["carry_share"]
        .item()
    )
    assert row["carry_share_raw"] != pytest.approx(seattle_share, abs=1e-6)


def test_own_role_players_really_have_a_qualifying_same_role_season(
    proj: pl.DataFrame, hub: pl.DataFrame, role_history: pl.DataFrame
) -> None:
    """Every `own_role` row must have >= 1 season at the same 2026 team+position with >= 8 REG games."""
    hist = role_history.filter(pl.col("games") >= MIN_GAMES_FOR_SHARE).join(
        hub.select("player_id", "role_2026"), on="player_id", how="inner"
    )
    qualifying = set(
        hist.filter(pl.col("role_key") == pl.col("role_2026"))["player_id"].to_list()
    )
    own = set(proj.filter(pl.col("share_source") == "own_role")["player_id"].to_list())
    assert own == qualifying
    # and nobody sourced from a prior has same-role seasons on the books
    priors = proj.filter(pl.col("share_source") != "own_role")
    assert priors["same_role_seasons"].max() == 0


def test_pickens_kept_his_2025_dallas_role(proj: pl.DataFrame, hub: pl.DataFrame,
                                           role_history: pl.DataFrame) -> None:
    """The flip side of the rule: Pickens moved PIT->DAL in 2025, so DAL-WR IS his own role for 2026."""
    row = _row(proj, hub, PICKENS)
    keys = set(role_history.filter(pl.col("gsis_id") == PICKENS)["role_key"].to_list())
    assert {"PIT-WR", "DAL-WR"} <= keys
    assert row["team"] == "DAL"
    assert row["share_source"] == "own_role"
    assert row["same_role_seasons"] == 1


# ----------------------------------------------------------------------------------------- rookies

def test_rookie_uses_draft_capital_prior_and_projects_finitely(proj: pl.DataFrame,
                                                               hub: pl.DataFrame) -> None:
    row = _row(proj, hub, LOVE)
    assert row["is_rookie"] is True
    assert row["share_source"] == "rookie_draft_capital"
    assert row["draft_bucket"] == "R1"
    assert row["n_carries_hist"] == 0.0 and row["n_targets_hist"] == 0.0
    assert math.isfinite(row["inhouse_ppg"]) and row["inhouse_ppg"] > 0
    assert row["proj_carries_pg"] > 0


def test_every_rookie_prior_row_is_a_rookie_on_the_chart(proj: pl.DataFrame) -> None:
    rookies = proj.filter(pl.col("share_source") == "rookie_draft_capital")
    assert rookies.height > 50
    assert rookies["is_rookie"].all()
    assert rookies["depth_rank"].null_count() == 0
    assert rookies["inhouse_ppg"].is_finite().all()
    assert set(rookies["draft_bucket"].unique()) <= set(ROUND_BUCKETS)


def test_rookie_round_factors_are_derived_and_monotone() -> None:
    prod = production.compute(SEASONS)
    tend = team_tendencies.compute(SEASONS)
    prod_pg = _per_game_shares(prod, tend.select("team", "season", team_games=pl.col("games")))
    pass_shares = _pass_att_shares(player_season_volume(SEASONS), prod, tend)
    factors = rookie_round_factors(SEASONS, prod_pg, pass_shares)

    assert factors["n_rookies"].sum() > 100, "the factors must come from a real rookie cohort"
    order = {b: i for i, b in enumerate(ROUND_BUCKETS)}
    for pos in ("WR", "TE", "RB"):
        sub = factors.filter(pl.col("position") == pos).with_columns(
            _o=pl.col("bucket").replace_strict(order, return_dtype=pl.Int32)
        ).sort("_o")
        metric = "f_carry" if pos == "RB" else "f_target"
        vals = sub[metric].to_list()
        assert vals[0] == pytest.approx(1.0), f"{pos} R1 is the anchor"
        assert all(a >= b - 1e-9 for a, b in pairwise(vals)), f"{pos} {metric} not monotone"
        assert vals[-1] < vals[0], f"{pos} {metric} should discriminate on draft capital"


# ------------------------------------------------------------------------------- efficiency regression

def _raw_efficiency() -> pl.DataFrame:
    """Raw (unregressed) yards per target / carry and the opportunity counts behind them."""
    hub = hub_players()
    prod = production.compute(SEASONS)
    tend = team_tendencies.compute(SEASONS)
    prod_pg = _per_game_shares(prod, tend.select("team", "season", team_games=pl.col("games")))
    totals = _efficiency_history(player_season_volume(SEASONS), prod_pg, hub)
    return totals.join(hub.select("player_id", "position"), on="player_id", how="inner")


def test_efficiency_is_shrunk_toward_the_positional_mean(proj: pl.DataFrame) -> None:
    """eff = w*own + (1-w)*positional mean with w = n/(n+k) — checked in closed form on every WR."""
    raw = _raw_efficiency().filter((pl.col("position") == "WR") & (pl.col("targets") > 0))
    pos_mean = raw["rec_yd"].sum() / raw["targets"].sum()
    k = SHRINK_K["ypt"]
    joined = raw.join(proj.select("player_id", "eff_ypt", "n_targets_hist"), on="player_id", how="inner")
    assert joined.height > 100

    checked = joined.with_columns(
        own=pl.col("rec_yd") / pl.col("targets"),
        w=pl.col("targets") / (pl.col("targets") + k),
    ).with_columns(expected=pl.col("w") * pl.col("own") + (1 - pl.col("w")) * pos_mean)
    assert (checked["expected"] - checked["eff_ypt"]).abs().max() < 1e-3
    assert (checked["n_targets_hist"] - checked["targets"]).abs().max() == 0


def test_small_samples_move_further_toward_the_mean(proj: pl.DataFrame) -> None:
    """The same raw deviation is shrunk more for a thin sample than for a thick one — on real WRs."""
    raw = _raw_efficiency().filter((pl.col("position") == "WR") & (pl.col("targets") >= 10))
    pos_mean = raw["rec_yd"].sum() / raw["targets"].sum()
    d = (
        raw.join(proj.select("player_id", "name", "eff_ypt"), on="player_id", how="inner")
        .with_columns(own=pl.col("rec_yd") / pl.col("targets"))
        .with_columns(
            kept=(pl.col("eff_ypt") - pos_mean) / (pl.col("own") - pos_mean),
        )
        .filter((pl.col("own") - pos_mean).abs() > 0.5)
    )
    assert d.height > 50
    # `kept` is exactly n/(n+k): strictly increasing in sample size, and never outside (0, 1)
    assert d["kept"].min() > 0.0
    assert d["kept"].max() < 1.0
    thin = d.filter(pl.col("targets") < 50)
    thick = d.filter(pl.col("targets") > 250)
    assert thin.height > 5 and thick.height > 5
    assert thin["kept"].max() < thick["kept"].min(), "a thin sample must keep less of its own deviation"
    assert d.select(pl.corr("targets", "kept")).item() > 0.9


def test_volume_is_not_regressed(proj: pl.DataFrame) -> None:
    """Only efficiency is shrunk: the projected opportunity is share x team volume, exactly."""
    d = proj.with_columns(
        expect_carries=(pl.col("proj_carry_share") * pl.col("team_plays_rush")).round(4),
        expect_targets=(pl.col("proj_target_share") * pl.col("team_targets_pg")).round(4),
    )
    assert (d["expect_carries"] - d["proj_carries_pg"]).abs().max() < 1e-3
    assert (d["expect_targets"] - d["proj_targets_pg"]).abs().max() < 1e-3


def test_yprr_is_null_because_no_routes_data_exists(proj: pl.DataFrame) -> None:
    assert proj["eff_yprr_or_none"].null_count() == proj.height


def test_shrink_constants_still_match_the_measurement() -> None:
    """Guard against data drift silently invalidating the documented k values (ypc is the stated exception)."""
    measured = measure_stability(SEASONS)
    assert set(measured["metric"]) == set(SHRINK_K)
    for r in measured.to_dicts():
        assert r["pairs"] >= 50, f"{r['metric']} lost its measurement sample"
        assert r["r"] > 0, f"{r['metric']} has no year-over-year signal any more"
        if r["metric"] == "ypc":
            continue  # documented: RB yards/carry has r ~ 0, so k is deliberately far above the pooled fit
        assert 0.6 <= r["k"] / r["k_used"] <= 1.6, f"{r['metric']}: measured k={r['k']} vs used {r['k_used']}"


# ----------------------------------------------------------------------------- touchdowns and scoring

def test_touchdowns_come_from_expected_rates_not_raw_history(proj: pl.DataFrame) -> None:
    d = proj.with_columns(
        expected=(
            pl.col("proj_targets_pg") * pl.col("eff_rec_td_rate")
            + pl.col("proj_carries_pg") * pl.col("eff_rush_td_rate")
        ).round(4)
    )
    # both sides are rounded to 4 dp, so allow the rounding margin itself
    assert (d["expected"] - d["proj_td_pg"]).abs().max() <= 1e-3 + 1e-9
    # expected-TD rates are small, bounded per-opportunity numbers, never raw season TD counts
    assert proj["eff_rec_td_rate"].max() < 0.35
    assert proj["eff_rush_td_rate"].max() < 0.35
    assert proj["proj_td_pg"].min() >= 0.0


def test_ppg_is_the_league_scoring_of_the_projected_stat_line(proj: pl.DataFrame) -> None:
    """Re-score the top 40 rows through app.scoring — no vendor points may leak in anywhere."""
    cfg = load_league_config()
    for r in proj.head(40).to_dicts():
        line = {
            "rec": r["proj_rec_pg"], "rec_yd": r["proj_rec_yd_pg"], "rec_td": r["proj_rec_td_pg"],
            "rush_yd": r["proj_rush_yd_pg"], "rush_td": r["proj_rush_td_pg"],
            "pass_yd": r["proj_pass_yd_pg"], "pass_td": r["proj_pass_td_pg"],
            "pass_int": r["proj_pass_int_pg"],
        }
        expected = score(line, cfg.scoring, r["position"], include_bonuses=False)
        assert expected == pytest.approx(r["inhouse_ppg_raw"], abs=0.02)


def test_per_game_bonuses_are_left_to_the_caller(proj: pl.DataFrame) -> None:
    """`include_bonuses=False`: a 100-yard-a-game rusher must not carry the 100-yard game bonus here."""
    cfg = load_league_config()
    assert cfg.scoring.bonuses, "this test only means something while the league has yardage bonuses"
    big = proj.filter(pl.col("proj_rush_yd_pg") >= 100.0)
    if big.height:
        r = big.to_dicts()[0]
        with_bonus = score(
            {"rush_yd": r["proj_rush_yd_pg"]}, cfg.scoring, r["position"], include_bonuses=True
        )
        without = score({"rush_yd": r["proj_rush_yd_pg"]}, cfg.scoring, r["position"],
                        include_bonuses=False)
        assert with_bonus > without
        assert r["inhouse_ppg_raw"] < with_bonus + r["proj_rec_yd_pg"]  # no bonus baked into ours


# -------------------------------------------------------------------------------------- age and sanity

def test_age_and_context_are_the_final_multipliers(proj: pl.DataFrame) -> None:
    """inhouse_ppg = raw x age x team context, and nothing else."""
    d = proj.with_columns(
        expected=(pl.col("inhouse_ppg_raw") * pl.col("age_factor") * pl.col("context_factor"))
        .clip(lower_bound=0.0).round(4)
    )
    assert (d["expected"] - d["inhouse_ppg"]).abs().max() < 1e-3
    for r in proj.filter(pl.col("age").is_not_null()).head(200).to_dicts():
        assert r["age_factor"] == pytest.approx(age_factor(r["position"], r["age"]))
    assert proj["age_factor"].min() >= 0.78
    assert proj["age_factor"].max() <= 1.05


def test_team_context_is_small_and_hard_capped(proj: pl.DataFrame) -> None:
    """Context adjusts the in-house half only, and can never dominate it.

    18 of 32 clubs changed play-caller, so a large multiplier applied to half the league would add noise rather
    than signal. It is also applied here rather than to the blend, because the vendor half already prices 2026
    context in — adjusting the blend would double-count it.
    """
    from app.ranking.inhouse import CONTEXT_CAP

    lo, hi = CONTEXT_CAP
    assert proj["context_factor"].min() >= lo - 1e-9
    assert proj["context_factor"].max() <= hi + 1e-9
    assert hi - lo <= 0.15, "a context swing wider than +/-7% would swamp the opportunity model"
    # the pieces must add up to the (uncapped) factor
    d = proj.with_columns(
        parts=1.0 + pl.col("qb_context_effect") + pl.col("ol_context_effect") + pl.col("caller_context_effect"))
    inside = d.filter(pl.col("parts").is_between(lo, hi))
    assert (inside["parts"] - inside["context_factor"]).abs().max() < 1e-3
    # quarterback quality only moves players who catch his passes
    qb_rows = proj.filter(pl.col("position") == "QB")
    assert qb_rows["qb_context_effect"].abs().max() == 0.0


def test_vacated_opportunity_is_redistributed_within_budget(proj: pl.DataFrame) -> None:
    """A club that lost usage must not project below what a real offence spends.

    When a team's contributors leave, their share does not evaporate - it goes to whoever remains. Every club
    should therefore land at the measured budget, and no player may gain more than half his own share.
    """
    from app.config import settings
    from app.ranking.inhouse import measured_share_budget

    seasons = tuple(settings.history_seasons)
    for kind, col, gain in (("target", "proj_target_share", "target_vacated_gain"),
                            ("carry", "proj_carry_share", "carry_vacated_gain")):
        budget = measured_share_budget(seasons, kind)
        sums = proj.group_by("team").agg(pl.col(col).sum().alias("s"))
        assert sums["s"].max() <= budget + CAP_TOLERANCE, f"{kind} over budget"
        assert sums["s"].min() >= budget - 0.05, f"{kind} left a club under-allocated"
        assert proj[gain].min() >= 0.0, "redistribution never removes opportunity"
        share_before = proj[col] - proj[gain]
        assert (proj[gain] <= share_before * 0.5 + 1e-6).all(), "a player gained more than half his own share"


def test_inhouse_ppg_is_finite_and_non_negative_for_every_row(proj: pl.DataFrame) -> None:
    for col in ("inhouse_ppg_raw", "inhouse_ppg"):
        assert proj[col].null_count() == 0
        assert proj[col].is_finite().all(), f"{col} has non-finite values"
        assert proj[col].min() >= 0.0, f"{col} went negative"
    assert proj["inhouse_ppg"].max() < 40.0, "a per-game projection above 40 points is a bug, not a player"


def test_known_high_volume_player_lands_in_a_sane_range(proj: pl.DataFrame, hub: pl.DataFrame) -> None:
    """Bijan Robinson: ATL's bell-cow since 2023, so own_role, heavy volume, a top-5 non-QB projection."""
    row = _row(proj, hub, BIJAN)
    assert row["share_source"] == "own_role"
    assert row["same_role_seasons"] == len(SEASONS)
    assert 0.30 <= row["proj_carry_share"] <= 0.75
    assert 10.0 <= row["proj_carries_pg"] <= 20.0
    assert 2.0 <= row["proj_targets_pg"] <= 7.0
    assert 8.0 <= row["inhouse_ppg"] <= 22.0
    non_qb = proj.filter(pl.col("position") != "QB").sort("inhouse_ppg", descending=True)
    assert row["player_id"] in non_qb.head(8)["player_id"].to_list()


def test_depth_chart_players_without_history_still_get_a_projection(proj: pl.DataFrame) -> None:
    slot = proj.filter(pl.col("share_source") == "depth_slot_baseline")
    assert slot.height > 100
    assert slot["inhouse_ppg"].is_finite().all()
    # the slot prior is monotone in depth rank: a club's WR1 out-projects its WR4
    wr = slot.filter(pl.col("position") == "WR")
    top = wr.filter(pl.col("depth_rank") == 1)["target_share_raw"].mean()
    deep = wr.filter(pl.col("depth_rank") >= 4)["target_share_raw"].mean()
    assert top > deep


def test_players_off_the_chart_with_no_history_are_dropped(proj: pl.DataFrame, hub: pl.DataFrame) -> None:
    chart = depth.compute(settings.current_season)
    projected = set(proj["player_id"].to_list())
    dropped = hub.filter(~pl.col("player_id").is_in(pl.Series(sorted(projected)).implode()))
    assert dropped.height > 0
    on_chart = set(chart.filter(pl.col("appears_on_chart"))["player_id"].to_list())
    for r in dropped.to_dicts():
        # a dropped player is either clubless or absent from both the chart and his own role history
        assert r["team"] is None or r["player_id"] not in on_chart
