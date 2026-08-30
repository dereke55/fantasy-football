"""nflverse historical stats ingestion (Phase 1a): player stats, ff_opportunity, weekly rosters, injuries.

Every dataset is pulled ONE SEASON AT A TIME with an explicit `seasons=[season]` (CLAUDE.md rule), snapshotted as parquet
(`raw_snapshots` endpoint `<dataset>_<season>` mirrors the upstream asset name) and loaded into `raw_nflverse_<dataset>`
with `replace_partition(partition=["season"])`, so a re-run replaces exactly one season and every row carries `snapshot_id`.

Freshness: the GitHub release asset `updated_at` is stored as `upstream_as_of` (one releases API call per tag per run).
ff_opportunity lives in a different repo (ffverse/ffopportunity, tag `latest-data`), so the lookup is repo-aware here.

Run:  cd backend && uv run python -m app.ingest.nflverse_stats all
      uv run python -m app.ingest.nflverse_stats stats-player-week --season 2025
      uv run python -m app.ingest.nflverse_stats check
"""
from __future__ import annotations

import json
import sys
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import nflreadpy
import polars as pl
import typer
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.ingest.loaders import replace_partition
from app.ingest.nflverse_base import SOURCE, fetch_dataset
from app.ingest.snapshots import http_get, record_failure

NFLVERSE_REPO = "nflverse/nflverse-data"
FFOPPORTUNITY_REPO = "ffverse/ffopportunity"
RELEASES_API = "https://api.github.com/repos/{repo}/releases/tags/{tag}"


@dataclass(frozen=True)
class DatasetSpec:
    """One upstream dataset: how to load it, where it lands, and which release asset dates it."""

    name: str  # snapshot endpoint prefix, CLI command and table suffix
    loader: Callable[..., pl.DataFrame]
    tag: str
    asset: str  # format string with {season}
    kwargs: dict[str, Any] = field(default_factory=dict)
    repo: str = NFLVERSE_REPO

    @property
    def table(self) -> str:
        return f"raw_{SOURCE}_{self.name}"

    def endpoint(self, season: int) -> str:
        return f"{self.name}_{season}"


DATASETS: dict[str, DatasetSpec] = {
    "stats_player_week": DatasetSpec(
        "stats_player_week", nflreadpy.load_player_stats, "stats_player",
        "stats_player_week_{season}.parquet", {"summary_level": "week"},
    ),
    "stats_player_reg": DatasetSpec(
        "stats_player_reg", nflreadpy.load_player_stats, "stats_player",
        "stats_player_reg_{season}.parquet", {"summary_level": "reg"},
    ),
    "ff_opportunity_weekly": DatasetSpec(
        "ff_opportunity_weekly", nflreadpy.load_ff_opportunity, "latest-data",
        "ep_weekly_{season}.parquet", {"stat_type": "weekly"}, repo=FFOPPORTUNITY_REPO,
    ),
    "roster_weekly": DatasetSpec(
        "roster_weekly", nflreadpy.load_rosters_weekly, "weekly_rosters", "roster_weekly_{season}.parquet",
    ),
    "injuries": DatasetSpec("injuries", nflreadpy.load_injuries, "injuries", "injuries_{season}.parquet"),
}
PARTITION = ["season"]


# --------------------------------------------------------------------------- freshness (release asset timestamps)
class AssetClock:
    """Per-run cache: one GitHub releases call per (repo, tag); returns asset `updated_at` or None (advisory only)."""

    def __init__(self) -> None:
        self._cache: dict[tuple[str, str], dict[str, str]] = {}

    def updated_at(self, repo: str, tag: str, asset: str) -> str | None:
        key = (repo, tag)
        if key not in self._cache:
            self._cache[key] = self._fetch(repo, tag)
        return self._cache[key].get(asset)

    @staticmethod
    def _fetch(repo: str, tag: str) -> dict[str, str]:
        headers = {"Accept": "application/vnd.github+json"}
        if settings.github_token:
            headers["Authorization"] = f"Bearer {settings.github_token}"
        try:
            r = http_get(RELEASES_API.format(repo=repo, tag=tag), headers=headers, timeout=30)
        except Exception:  # noqa: BLE001 - freshness is advisory, never fails ingest
            return {}
        return {a["name"]: a.get("updated_at") for a in r.json().get("assets", []) if a.get("name")}


# --------------------------------------------------------------------------- pure helpers (also used by tests)
def read_snapshot(path: str) -> pl.DataFrame:
    """Parse one snapshot / fixture parquet exactly as it was stored (upstream columns verbatim)."""
    return pl.read_parquet(path)


def reg_weeks_by_season(df: pl.DataFrame) -> dict[int, list[int]]:
    """{season: sorted distinct REG weeks} from a stats_player_week-shaped frame."""
    out = (
        df.filter(pl.col("season_type") == "REG")
        .group_by("season")
        .agg(pl.col("week").unique().sort())
        .sort("season")
    )
    return {int(s): [int(w) for w in ws] for s, ws in out.iter_rows()}


def player_week_line(df: pl.DataFrame, player_id: str, season: int, week: int) -> dict[str, Any]:
    """The single stat line for one player-week (raises if not exactly one row)."""
    rows = df.filter(
        (pl.col("player_id") == player_id) & (pl.col("season") == season) & (pl.col("week") == week)
    ).to_dicts()
    if len(rows) != 1:
        raise ValueError(f"expected 1 row for {player_id} {season} wk{week}, got {len(rows)}")
    return rows[0]


# --------------------------------------------------------------------------- ingest
def _already_loaded(session: Session, table: str, season: int, snapshot_id: uuid.UUID) -> int | None:
    """Row count if `table` already holds this season from this exact snapshot, else None."""
    if not inspect(session.get_bind()).has_table(table):
        return None
    n = session.execute(
        text(f'SELECT count(*) FROM "{table}" WHERE CAST(season AS text) = :season AND snapshot_id = :sid'),
        {"season": str(season), "sid": str(snapshot_id)},
    ).scalar_one()
    return int(n) if n else None


def ingest_season(spec: DatasetSpec, season: int, clock: AssetClock, *, force: bool = False) -> dict[str, Any]:
    """Fetch + snapshot + load one season of one dataset in its own transaction. Returns a summary dict."""
    upstream_as_of = clock.updated_at(spec.repo, spec.tag, spec.asset.format(season=season))
    with session_scope() as session:
        df, snap = fetch_dataset(
            session, endpoint=spec.endpoint(season), loader=spec.loader, seasons=[season],
            upstream_as_of=upstream_as_of, **spec.kwargs,
        )
        if "season" not in df.columns:
            raise ValueError(f"{spec.name} {season}: upstream frame has no `season` column: {df.columns[:10]}")
        # ff_opportunity ships `season` as a string ('2023'); keep upstream dtypes verbatim, compare loosely.
        seasons_seen = {str(s) for s in df.get_column("season").unique().to_list()}
        if seasons_seen != {str(season)}:
            raise ValueError(f"{spec.name}: asked for {season}, upstream returned seasons {sorted(seasons_seen)}")
        loaded = None if force else _already_loaded(session, spec.table, season, snap.snapshot.id)
        rows = loaded if loaded is not None else replace_partition(
            session, spec.table, df, partition=PARTITION, snapshot_id=snap.snapshot.id
        )
        return {
            "rows": rows, "snapshot_id": str(snap.snapshot.id), "is_new": snap.is_new,
            "upstream_as_of": upstream_as_of, "skipped_reload": loaded is not None, "columns": df.width,
        }


def ingest_dataset(
    spec: DatasetSpec, seasons: list[int], clock: AssetClock | None = None, *, force: bool = False
) -> dict[str, Any]:
    """Load every season; on the first failure record it in raw_snapshots and stop this dataset (others continue)."""
    clock = clock or AssetClock()
    summary: dict[str, Any] = {
        "rows": 0, "snapshot_id": None, "is_new": False, "upstream_as_of": None, "error": None, "seasons": {},
    }
    for season in seasons:
        try:
            s = ingest_season(spec, season, clock, force=force)
        except Exception as e:  # noqa: BLE001 - per-dataset isolation is the contract
            err = f"{type(e).__name__}: {e}"
            with session_scope() as session:
                record_failure(
                    session, source=SOURCE, endpoint=spec.endpoint(season),
                    params={"seasons": [season], **spec.kwargs}, error=err,
                )
            summary["error"] = f"season {season}: {err}"
            typer.echo(f"[{spec.name}] {season} FAILED: {err}", err=True)
            break
        summary["seasons"][str(season)] = s
        summary["rows"] += s["rows"]
        summary["snapshot_id"] = s["snapshot_id"]
        summary["is_new"] = summary["is_new"] or s["is_new"]
        summary["upstream_as_of"] = max(filter(None, [summary["upstream_as_of"], s["upstream_as_of"]]), default=None)
        typer.echo(f"[{spec.name}] {season}: {s['rows']} rows, snapshot {s['snapshot_id'][:8]}"
                   f"{' (unchanged, load skipped)' if s['skipped_reload'] else ''}", err=True)
    return summary


def _seasons(season: int | None) -> list[int]:
    return [season] if season is not None else list(settings.history_seasons)


# --------------------------------------------------------------------------- CLI
cli = typer.Typer(help="Ingest nflverse historical stats into raw_nflverse_* tables (explicit seasons only).")

_SEASON_OPT = typer.Option(None, help="One season; default settings.history_seasons")
_FORCE_OPT = typer.Option(False, help="Reload even if this exact snapshot is already in the table")


def _run_one(name: str, season: int | None, force: bool) -> None:
    summary = ingest_dataset(DATASETS[name], _seasons(season), force=force)
    typer.echo(json.dumps({name: summary}, indent=2, default=str))
    if summary["error"]:
        raise typer.Exit(code=1)


@cli.command("stats-player-week")
def stats_player_week(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """load_player_stats(summary_level='week') -> raw_nflverse_stats_player_week."""
    _run_one("stats_player_week", season, force)


@cli.command("stats-player-reg")
def stats_player_reg(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """load_player_stats(summary_level='reg') -> raw_nflverse_stats_player_reg."""
    _run_one("stats_player_reg", season, force)


@cli.command("ff-opportunity-weekly")
def ff_opportunity_weekly(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """load_ff_opportunity(stat_type='weekly') -> raw_nflverse_ff_opportunity_weekly."""
    _run_one("ff_opportunity_weekly", season, force)


@cli.command("roster-weekly")
def roster_weekly(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """load_rosters_weekly -> raw_nflverse_roster_weekly."""
    _run_one("roster_weekly", season, force)


@cli.command("injuries")
def injuries(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """load_injuries -> raw_nflverse_injuries."""
    _run_one("injuries", season, force)


@cli.command("all")
def ingest_all(season: int | None = _SEASON_OPT, force: bool = _FORCE_OPT) -> None:
    """Every dataset for settings.history_seasons; exit 0 if at least one dataset succeeded."""
    clock = AssetClock()
    results = {name: ingest_dataset(spec, _seasons(season), clock, force=force) for name, spec in DATASETS.items()}
    typer.echo(json.dumps(results, indent=2, default=str))
    if not any(r["error"] is None for r in results.values()):
        raise typer.Exit(code=1)


@cli.command("check")
def check() -> None:
    """Phase 1a gate checks (SQL): REG weeks 1-18 x 32 teams per season, POST presence, roster status codes."""
    out: dict[str, Any] = {}
    with session_scope() as session:
        out["stats_player_week"] = [
            dict(r) for r in session.execute(text("""
                SELECT season,
                       array_agg(DISTINCT week ORDER BY week) FILTER (WHERE season_type = 'REG') AS reg_weeks,
                       count(DISTINCT team) FILTER (WHERE season_type = 'REG') AS reg_teams,
                       count(*) FILTER (WHERE season_type = 'POST') AS post_rows,
                       array_agg(DISTINCT week ORDER BY week) FILTER (WHERE season_type = 'POST') AS post_weeks,
                       count(*) AS rows
                FROM raw_nflverse_stats_player_week GROUP BY season ORDER BY season
            """)).mappings()
        ]
        out["roster_weekly_status"] = [
            dict(r) for r in session.execute(text("""
                SELECT status, status_description_abbr, count(*) AS n
                FROM raw_nflverse_roster_weekly GROUP BY 1, 2 ORDER BY n DESC
            """)).mappings()
        ]
        out["row_counts"] = {
            spec.table: [dict(r) for r in session.execute(
                text(f'SELECT season, count(*) AS rows FROM "{spec.table}" GROUP BY season ORDER BY season')
            ).mappings()]
            for spec in DATASETS.values()
            if inspect(session.get_bind()).has_table(spec.table)
        }
    typer.echo(json.dumps(out, indent=2, default=str))
    ok = all(r["reg_weeks"] == list(range(1, 19)) and r["reg_teams"] == 32 for r in out["stats_player_week"])
    typer.echo(f"GATE {'PASS' if ok else 'FAIL'}: REG weeks 1-18 for 32 teams in every season", err=True)
    if not ok:
        raise typer.Exit(code=1)


if __name__ == "__main__":
    cli()
    sys.exit(0)
