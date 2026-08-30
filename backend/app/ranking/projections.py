"""Season projections in league points.

MVP blend (docs/spec/ranking-model.md §1) is 0.70 vendor (Sleeper/Rotowire stat line, re-scored under the league
config) + 0.30 in-house. Until the Phase 3 in-house component lands this module exposes the vendor half plus the
expected-games conversion, which is enough for value-based drafting and the keeper helper.

Never uses Sleeper's own point columns (`pts_ppr`, ...) or its `gp` field (a constant 18): points are always
recomputed from the raw stat line, and per-game means dividing by 17 minus known missed weeks.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import polars as pl
import yaml

from app.config import settings
from app.db import engine
from app.ranking.adjustments import expected_games
from app.scoring.adapters import from_sleeper_projection
from app.scoring.bonuses import season_bonus_points
from app.scoring.config import LeagueConfig, load_league_config
from app.scoring.engine import score

SEASON_GAMES = 17


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def known_missed_weeks(path: Path | None = None) -> dict[str, int]:
    """gsis_id -> announced missed REG weeks, from backend/seeds/known_missed_weeks.yaml."""
    p = path or (settings.seeds_dir / "known_missed_weeks.yaml")
    if not p.exists():
        return {}
    doc = yaml.safe_load(p.read_text()) or {}
    out: dict[str, int] = {}
    for r in doc.get("rows", []) or []:
        gsis, weeks = r.get("gsis_id"), r.get("known_missed_weeks")
        if gsis and weeks:
            out[str(gsis)] = int(weeks)
    return out


@dataclass(frozen=True)
class ProjectionRow:
    player_id: int
    position: str
    ppg: float
    e_games: float


def vendor_projections(cfg: LeagueConfig | None = None) -> pl.DataFrame:
    """One row per player with a Sleeper stat line: season points and PPG under the league's own scoring."""
    cfg = cfg or load_league_config()
    stat_cols = _q(
        "select column_name from information_schema.columns "
        "where table_name='raw_sleeper_projections' and column_name like 'stat\\_%'"
    )["column_name"].to_list()
    sel = ", ".join(f"s.{c}" for c in stat_cols)
    df = _q(
        f"select p.id as player_id, p.gsis_id, p.name, p.position, p.team, p.is_rookie, {sel} "
        f"from raw_sleeper_projections s join players p on p.sleeper_id = s.player_id where s.has_projection"
    )
    if df.is_empty():
        return df
    missed = known_missed_weeks()
    # The yardage bonuses are per game, so they cannot be read off a season total: estimate the per-game bonus
    # from the player's own weekly history instead (app/scoring/bonuses.py).
    bonus_pg = season_bonus_points(cfg, list(settings.history_seasons))
    rows = []
    for r in df.to_dicts():
        base = score(from_sleeper_projection(r, strict=False), cfg.scoring, r["position"], include_bonuses=False)
        km = missed.get(r["gsis_id"] or "", 0)
        games = max(1, SEASON_GAMES - km)
        bpg = bonus_pg.get(r["player_id"], 0.0)
        rows.append({
            "player_id": r["player_id"], "gsis_id": r["gsis_id"], "name": r["name"], "position": r["position"],
            "team": r["team"], "is_rookie": r["is_rookie"],
            "vendor_season_points": round(base + bpg * games, 2),
            "vendor_ppg": round(base / games + bpg, 3),
            "vendor_ppg_no_bonus": round(base / games, 3), "bonus_pg": round(bpg, 3),
            "known_missed_weeks": km,
        })
    return pl.DataFrame(rows)


def with_expected_games(proj: pl.DataFrame, market: pl.DataFrame, num_teams: int) -> pl.DataFrame:
    """Attach E[games] (ONE application, at the per-game -> season conversion) using the ADP band for the base rate."""
    wanted = ["player_id", "composite_rank", "composite_adp", "ecr_rank", "ecr", "ecr_sd", "ecr_best", "ecr_worst",
              "disagreement", "yahoo_adp", "ffc_adp", "sleeper_adp", "sd_adp", "sd_adp_source", "n_adp_sources"]
    m = market.select([c for c in wanted if c in market.columns])
    df = proj.join(m, on="player_id", how="left")
    out = []
    for r in df.to_dicts():
        pick = r.get("composite_rank") or r.get("ecr_rank")
        adp_round = (pick / num_teams) if pick else None
        eg, detail = expected_games(
            r["position"], adp_round=adp_round, hist_missed=None, hist_eligible=None,
            known_missed_weeks=r["known_missed_weeks"],
        )
        out.append({**r, "adp_round": None if adp_round is None else round(adp_round, 2),
                    "e_games": eg, "e_games_base_missed": detail["base_missed"]})
    return pl.DataFrame(out)


def projection_pool(cfg: LeagueConfig | None = None) -> pl.DataFrame:
    """Vendor projections + market + E[games], ready for VBD. One row per projected player."""
    from app.market.build import compute_market

    cfg = cfg or load_league_config()
    return with_expected_games(vendor_projections(cfg), compute_market(), cfg.league.num_teams)
