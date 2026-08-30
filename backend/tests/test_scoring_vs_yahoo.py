"""Phase 2 gate: our scoring engine must reproduce Yahoo's own 2025 point totals for this league.

Ground truth is Derek's Yahoo league page (tests/fixtures/yahoo_league/derek_2025_fan_points.yaml), scored by
Yahoo under the exact settings transcribed into config/league.yaml. Recomputing them from nflverse weekly stat
lines is the strongest available check that the scoring config and the engine are both right.
"""
from pathlib import Path

import polars as pl
import pytest
import yaml

from app.db import engine
from app.scoring.adapters import from_nflverse_week
from app.scoring.config import load_league_config
from app.scoring.engine import score

FIXTURE = Path(__file__).parent / "fixtures" / "yahoo_league" / "derek_2025_fan_points.yaml"


@pytest.fixture(scope="module")
def truth() -> dict[str, float]:
    return yaml.safe_load(FIXTURE.read_text())["players"]


@pytest.fixture(scope="module")
def weeks(truth) -> pl.DataFrame:
    names = "', '".join(n.replace("'", "''") for n in truth)
    return pl.read_database(
        f"select p.name, w.* from raw_nflverse_stats_player_week w join players p on p.gsis_id = w.player_id "
        f"where w.season = 2025 and w.season_type = 'REG' and p.name in ('{names}')",
        connection=engine, infer_schema_length=None)


def _total(rows: list[dict], scoring, **kw) -> float:
    return round(sum(score(from_nflverse_week(r, strict=False), scoring, r["position"], **kw) for r in rows), 2)


def test_every_player_matches_yahoo_exactly(truth, weeks):
    cfg = load_league_config()
    assert cfg.source == "yahoo_settings_page", "the real league settings must be loaded, not the placeholder"
    errors = {}
    for name, expected in truth.items():
        rows = weeks.filter(pl.col("name") == name).to_dicts()
        assert rows, f"no 2025 REG weeks found for {name}"
        got = _total(rows, cfg.scoring)
        if abs(got - expected) > 0.005:
            errors[name] = (expected, got)
    assert not errors, f"scoring mismatch vs Yahoo: {errors}"


def test_bonus_mode_cumulative_is_what_yahoo_does(truth, weeks):
    """Pickens and Wan'Dale Robinson each cleared two receiving-yard tiers in a game, so they discriminate
    between awarding every tier crossed (cumulative) and only the top one (highest)."""
    cfg = load_league_config()
    highest = cfg.scoring.model_copy(update={"bonus_mode": "highest"})
    for name in ("George Pickens", "Wan'Dale Robinson"):
        rows = weeks.filter(pl.col("name") == name).to_dicts()
        assert _total(rows, cfg.scoring) == pytest.approx(truth[name], abs=0.005)
        assert _total(rows, highest) != pytest.approx(truth[name], abs=0.005)


def test_bonuses_are_per_game_not_per_season(truth, weeks):
    """Scoring a season total with per-game bonuses would silently inflate every skill player."""
    cfg = load_league_config()
    rows = weeks.filter(pl.col("name") == "Christian McCaffrey").to_dicts()
    per_game = _total(rows, cfg.scoring)
    no_bonus = _total(rows, cfg.scoring, include_bonuses=False)
    assert per_game > no_bonus, "McCaffrey cleared 100-yard games in 2025"
    assert per_game == pytest.approx(truth["Christian McCaffrey"], abs=0.005)
    # A season-total line would silently collect every tier once: McCaffrey's 2025 totals clear all three
    # rushing tiers (1+2+3) and all three receiving tiers (1+2+3) = 12 phantom points.
    season = {"rush_yd": 1202, "rec_yd": 924, "rec": 102, "rush_td": 10, "rec_td": 7}
    assert score(season, cfg.scoring) - score(season, cfg.scoring, include_bonuses=False) == pytest.approx(12.0)


def test_league_overrides_are_loaded():
    s = load_league_config().scoring
    assert s.pass_td == 6 and s.pass_int == -2, "this league overrides Yahoo's 4 / -1 defaults"
    assert s.rec == 0.5 and s.uses_fractional_points and s.uses_negative_points
    assert len(s.bonuses) == 9 and s.bonus_mode == "cumulative"
