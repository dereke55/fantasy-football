"""Assemble the Phase 3 feature layer into `player_features` and `player_season_features`.

These two tables are *derived*: they are dropped and rebuilt wholesale from the raw tables on every run, so their
schema follows the feature modules rather than a hand-maintained model (Alembic excludes them — see alembic/env.py
DERIVED_TABLES). Everything they contain is recomputed under `config/league.yaml`; no vendor points are stored.
"""
from __future__ import annotations

from datetime import UTC, datetime

import polars as pl
import typer
from sqlalchemy import text

from app.config import settings
from app.db import engine, session_scope
from app.features import consistency, depth, durability, luck, production
from app.ingest.loaders import replace_partition
from app.scoring.config import league_config_sha256, load_league_config

cli = typer.Typer(no_args_is_help=True, help="Historical feature layer (Phase 3)")

SEASON_TABLE = "player_season_features"
SUMMARY_TABLE = "player_features"


def build_season_frame(seasons: list[int]) -> pl.DataFrame:
    """Per (player, season): production joined to luck and consistency."""
    prod = production.compute(seasons)
    lk = luck.compute(seasons).drop("gsis_id", "position", strict=False)
    cons = consistency.compute(seasons).drop("gsis_id", "position", strict=False)
    return prod.join(lk, on=["player_id", "season"], how="left").join(cons, on=["player_id", "season"], how="left")


def build_summary_frame(seasons: list[int]) -> pl.DataFrame:
    """Per player: every module's summary, one row for every QB/RB/WR/TE in the hub (no-history players get nulls)."""
    prod = production.compute_summary(seasons)
    dur = durability.compute_summary(seasons).drop("gsis_id", "position", "team", strict=False)
    dep = depth.compute().drop("gsis_id", "name", "position", "team", strict=False)
    lk = luck.compute_summary(seasons)
    cons = consistency.compute_summary(seasons)
    out = prod
    for frame in (dur, dep, lk, cons):
        out = out.join(frame, on="player_id", how="left")
    out = _final_expected_games(out)
    # nested columns become readable text so the derived table stays queryable from SQL
    for col, dtype in out.schema.items():
        if isinstance(dtype, pl.Struct):
            out = out.with_columns(pl.col(col).struct.json_encode().alias(col))
        elif isinstance(dtype, (pl.List, pl.Array)):
            out = out.with_columns(
                pl.col(col).cast(pl.List(pl.Utf8), strict=False).list.join("; ").alias(col)
            )
    return out.with_columns(computed_at=pl.lit(datetime.now(UTC)))


def _final_expected_games(df: pl.DataFrame) -> pl.DataFrame:
    """Recompute E[games] once, using BOTH inputs.

    `durability.compute_summary` runs before the market exists, so it passes `adp_round=None` (everyone lands in the
    middle base band); `projections.with_expected_games` has the ADP band but no injury history. Neither is complete,
    so the authoritative value is computed here from the ADP band + the player's own miss rate + announced absences.

    Durability caveat (durability.py, quirk 1): `games_played` requires an actual opportunity, so a healthy backup
    with no touches reads as "missed" every week. History is therefore only applied when the player has real usage
    (>= 8 games played across 2023-25); otherwise the positional base rate stands on its own.
    """
    from app.market.build import compute_market
    from app.ranking.adjustments import expected_games

    cfg = load_league_config()
    market = compute_market()
    adp = {}
    if not market.is_empty():
        adp = {r["player_id"]: (r.get("composite_rank") or r.get("ecr_rank")) for r in market.to_dicts()}

    rows = []
    for r in df.to_dicts():
        pick = adp.get(r["player_id"])
        adp_round = (pick / cfg.league.num_teams) if pick else None
        eligible = r.get("games_eligible_3yr")
        missed = r.get("games_missed_3yr")
        played = (eligible - missed) if (eligible is not None and missed is not None) else None
        use_history = played is not None and played >= 8
        eg, detail = expected_games(
            r["position"], adp_round=adp_round,
            hist_missed=missed if use_history else None,
            hist_eligible=eligible if use_history else None,
            known_missed_weeks=int(r.get("known_missed_weeks") or 0),
        )
        rows.append({**r, "e_games": eg, "e_games_detail": str({**detail, "adp_round": adp_round,
                                                               "history_applied": use_history})})
    return pl.DataFrame(rows)


@cli.command("build")
def build(seasons: str = typer.Option(None, help="Comma-separated; defaults to settings.history_seasons")) -> None:
    """Rebuild both feature tables from the raw tables (idempotent full replace)."""
    seasons_l = [int(s) for s in seasons.split(",")] if seasons else list(settings.history_seasons)
    cfg = load_league_config()
    season_df = build_season_frame(seasons_l)
    summary_df = build_summary_frame(seasons_l)
    with session_scope() as s:
        for table in (SEASON_TABLE, SUMMARY_TABLE):
            s.execute(text(f"drop table if exists {table}"))
        s.flush()
        n1 = replace_partition(s, SEASON_TABLE, season_df, partition=[], snapshot_id=None)
        n2 = replace_partition(s, SUMMARY_TABLE, summary_df, partition=[], snapshot_id=None)
    typer.echo({
        "seasons": seasons_l, SEASON_TABLE: n1, SUMMARY_TABLE: n2,
        "league_config": cfg.source, "league_config_sha256": league_config_sha256()[:12],
        "no_history_players": int(summary_df.filter(pl.col("ppg_2025").is_null()).height),
    })


@cli.command("check")
def check() -> None:
    """Phase 3 gate: named 2025 totals reconcile with nflverse, and rookies come back as nulls (not errors)."""
    import polars as pl_

    q = lambda sql: pl_.read_database(sql, connection=engine, infer_schema_length=None)
    checks: list[tuple[str, bool, str]] = []
    names = ["Bijan Robinson", "Ja'Marr Chase", "Puka Nacua", "Josh Allen", "Jahmyr Gibbs"]
    for name in names:
        row = q(
            "select f.games, f.receiving_yards, f.rushing_yards, f.targets, f.carries from player_season_features f "
            f"join players p on p.id = f.player_id where p.name = '{name.replace(chr(39), chr(39) * 2)}' and f.season = 2025"
        )
        ref = q(
            "select r.games, r.receiving_yards, r.rushing_yards, r.targets, r.carries "
            "from raw_nflverse_stats_player_reg r join players p on p.gsis_id = r.player_id "
            f"where p.name = '{name.replace(chr(39), chr(39) * 2)}' and r.season = 2025"
        )
        ok = (not row.is_empty() and not ref.is_empty()
              and row.to_dicts()[0] == {k: v for k, v in ref.to_dicts()[0].items()})
        checks.append((f"{name} 2025 totals reconcile with nflverse REG", ok,
                       f"{row.to_dicts()[0] if not row.is_empty() else None} vs {ref.to_dicts()[0] if not ref.is_empty() else None}"))
    cov = q("select count(*) n, count(*) filter (where ppg_2025 is null) nulls from player_features").to_dicts()[0]
    checks.append(("player_features covers the whole QB/RB/WR/TE hub", cov["n"] >= 900, str(cov)))
    rook = q(
        "select f.ppg_2025, f.games_2025, f.depth_rank, f.age_2026, f.is_rookie from player_features f "
        "join players p on p.id = f.player_id where p.is_rookie and p.position in ('RB','WR') "
        "and f.depth_rank is not null limit 5"
    )
    ok = (not rook.is_empty() and rook["ppg_2025"].null_count() == rook.height
          and rook["depth_rank"].null_count() == 0)
    checks.append(("rookies return null history with populated depth/bio", ok, str(rook.to_dicts()[:2])))
    for label, ok, ev in checks:
        typer.secho(f"[{'PASS' if ok else 'FAIL'}] {label}: {ev}", fg=typer.colors.GREEN if ok else typer.colors.RED)
    if not all(ok for _, ok, _ in checks):
        typer.echo("GATE FAILED")
        raise typer.Exit(code=1)
    typer.echo("GATE PASSED")


if __name__ == "__main__":
    cli()
