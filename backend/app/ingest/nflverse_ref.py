"""nflverse reference datasets (Phase 1a): players, ff_playerids, rosters, depth_charts, schedules (+team_bye),
draft_picks and ff_rankings(draft).

Flow per dataset: nflreadpy load_* with EXPLICIT seasons -> parquet snapshot registered in raw_snapshots ->
raw_nflverse_<dataset> table mirroring upstream columns verbatim (loaders.replace_partition; every row carries snapshot_id).
Datasets are isolated: a failure is recorded with record_failure and the remaining datasets still run. `all` prints a JSON
summary {dataset: {rows, snapshot_id, is_new, upstream_as_of, error, ...}} and exits 0 when at least one dataset succeeded.

Freshness (`upstream_as_of`): GitHub release-asset updated_at for nflverse-data tags (one releases call per tag, cached per
run); last commit touching the file for dynastyprocess raw files; ff_rankings uses its own max(scrape_date).

Run: `uv run python -m app.ingest.nflverse_ref all` (or one of the per-dataset commands).
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from collections.abc import Callable, Sequence
from typing import Annotated, Any

import polars as pl
import typer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.ingest.loaders import replace_partition
from app.ingest.nflverse_base import SOURCE, asset_updated_at, fetch_dataset
from app.ingest.snapshots import DEFAULT_HEADERS, http_get, record_failure

os.environ.setdefault("NFLREADPY_USER_AGENT", DEFAULT_HEADERS["User-Agent"])

cli = typer.Typer(help="Ingest nflverse reference datasets into raw_nflverse_* tables.")

TABLE_PREFIX = "raw_nflverse_"
REG_WEEKS = range(1, 19)  # 18-week regular season (17 games + 1 bye) since 2021
GSIS_RE = r"^\d{2}-\d{7}$"  # 00-0034796
ESB_RE = r"^[A-Z]{3}\d{6}$"  # BRA371156
DP_COMMITS_API = "https://api.github.com/repos/dynastyprocess/data/commits"
# FantasyPros page that carries the overall (all-position) redraft consensus; see `rankings_summary`.
OVERALL_REDRAFT_PAGE_TYPES = ("redraft-overall",)

_as_of_cache: dict[tuple[str, str], str | None] = {}


# ----------------------------------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------------------------------
def _nfl():
    import nflreadpy  # imported lazily so NFLREADPY_* env defaults above are in place

    return nflreadpy


def _table(dataset: str) -> str:
    return TABLE_PREFIX + dataset


def _pg_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def release_asset_as_of(tag: str, asset_name: str) -> str | None:
    """`asset_updated_at` cached per (tag, asset) for the life of the process (one releases call per tag)."""
    key = (tag, asset_name)
    if key not in _as_of_cache:
        _as_of_cache[key] = asset_updated_at(tag, asset_name)
    return _as_of_cache[key]


def dynastyprocess_as_of(filename: str) -> str | None:
    """Committer date of the last commit touching files/<filename> in dynastyprocess/data (advisory; None on failure)."""
    key = ("dynastyprocess", filename)
    if key in _as_of_cache:
        return _as_of_cache[key]
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    value: str | None = None
    try:
        r = http_get(DP_COMMITS_API, params={"path": f"files/{filename}", "per_page": 1}, headers=headers, timeout=30)
        commits = r.json()
        if commits:
            value = commits[0]["commit"]["committer"]["date"]
    except Exception:  # noqa: BLE001 - freshness is advisory
        value = None
    _as_of_cache[key] = value
    return value


def load_table(
    session: Session, table: str, df: pl.DataFrame, *, partition: Sequence[str], snapshot_id: uuid.UUID
) -> int:
    """replace_partition, but an EMPTY partition key means full replace: all rows are deleted first (never dropped)."""
    if not partition and session.execute(text("SELECT to_regclass(:t)"), {"t": _pg_ident(table)}).scalar():
        session.execute(text(f"DELETE FROM {_pg_ident(table)}"))
    return replace_partition(session, table, df, partition=partition, snapshot_id=snapshot_id)


def _summary(df: pl.DataFrame, snap, **extra: Any) -> dict[str, Any]:
    return {
        "rows": df.height,
        "snapshot_id": str(snap.snapshot.id),
        "is_new": snap.is_new,
        "upstream_as_of": snap.snapshot.upstream_as_of,
        "error": None,
        **extra,
    }


def _run(dataset: str, fn: Callable[[Session], dict[str, Any]], params: dict | None = None) -> dict[str, Any]:
    """Per-dataset failure isolation: run `fn` in its own transaction; on error record_failure and return an error dict."""
    try:
        with session_scope() as session:
            return fn(session)
    except Exception as e:  # noqa: BLE001 - one failing dataset must not fail the job
        err = f"{type(e).__name__}: {e}"
        try:
            with session_scope() as session:
                record_failure(session, source=SOURCE, endpoint=dataset, params=params, error=err)
        except Exception as e2:  # noqa: BLE001
            err = f"{err} (record_failure also failed: {e2})"
        return {"rows": 0, "snapshot_id": None, "is_new": False, "upstream_as_of": None, "error": err}


def _emit(result: dict[str, Any]) -> None:
    typer.echo(json.dumps(result, indent=2, default=str))


# ----------------------------------------------------------------------------------------------------------------------
# pure parsing / derivation functions (unit-tested on real fixtures)
# ----------------------------------------------------------------------------------------------------------------------
def id_columns(df: pl.DataFrame) -> list[str]:
    """Columns that carry an external identifier (`*_id`, plus nflverse's `headshot`-less id-ish names are excluded)."""
    return [c for c in df.columns if c.endswith("_id")]


def id_coverage(df: pl.DataFrame, cols: Sequence[str]) -> dict[str, int]:
    """Non-null count per id column (a blank string counts as null)."""
    out: dict[str, int] = {}
    for c in cols:
        if c not in df.columns:
            out[c] = 0
            continue
        s = df.get_column(c)
        if s.dtype == pl.Utf8:
            out[c] = int(s.filter(s.is_not_null() & (s.str.strip_chars() != "")).len())
        else:
            out[c] = int(s.drop_nulls().len())
    return out


def derive_team_bye(schedules: pl.DataFrame, season: int, weeks: range = REG_WEEKS) -> pl.DataFrame:
    """(season, team, bye_week): regular-season weeks in `weeks` in which a team has no scheduled game.

    Computed from the REG rows of `schedules` for `season`; a team appears once per bye week (normally exactly once).
    """
    reg = schedules.filter((pl.col("season") == season) & (pl.col("game_type") == "REG"))
    played = pl.concat(
        [
            reg.select(pl.col("home_team").alias("team"), pl.col("week").cast(pl.Int64)),
            reg.select(pl.col("away_team").alias("team"), pl.col("week").cast(pl.Int64)),
        ]
    )
    rows: list[dict[str, Any]] = []
    for team in sorted(played.get_column("team").unique().to_list()):
        have = set(played.filter(pl.col("team") == team).get_column("week").to_list())
        rows.extend({"season": season, "team": team, "bye_week": w} for w in weeks if w not in have)
    return pl.DataFrame(rows, schema={"season": pl.Int64, "team": pl.Utf8, "bye_week": pl.Int64})


def bye_map(team_bye: pl.DataFrame) -> dict[str, list[int]]:
    out: dict[str, list[int]] = {}
    for team, week in team_bye.select("team", "bye_week").iter_rows():
        out.setdefault(team, []).append(int(week))
    return out


def depth_chart_dt_summary(df: pl.DataFrame) -> dict[str, Any]:
    dt = df.get_column("dt")
    return {"n_dt": int(dt.n_unique()), "max_dt": str(dt.max()), "min_dt": str(dt.min()), "dt_dtype": str(dt.dtype)}


def draft_pick_id_styles(df: pl.DataFrame, season: int) -> dict[str, int]:
    """How many `gsis_id` values of the given draft class look like GSIS ids vs ESB ids."""
    ids = df.filter(pl.col("season") == season).get_column("gsis_id").cast(pl.Utf8)
    non_null = ids.drop_nulls()
    return {
        "rows": int(ids.len()),
        "gsis_id_non_null": int(non_null.len()),
        "gsis_style": int(non_null.str.contains(GSIS_RE).sum()),
        "esb_style": int(non_null.str.contains(ESB_RE).sum()),
    }


def rankings_summary(df: pl.DataFrame, top: int = 5) -> dict[str, Any]:
    """Distinct page_type/ecr_type values, the overall-redraft page row count and its top-N by ecr."""
    page_types = sorted(df.get_column("page_type").drop_nulls().unique().to_list())
    ecr_types = sorted(df.get_column("ecr_type").drop_nulls().unique().to_list())
    overall_pages = [p for p in page_types if p in OVERALL_REDRAFT_PAGE_TYPES]
    overall = df.filter(pl.col("page_type").is_in(overall_pages)).sort("ecr")
    cols = [c for c in ("page_type", "ecr_type", "player", "pos", "team", "ecr", "bye", "id") if c in overall.columns]
    return {
        "page_types": page_types,
        "ecr_types": ecr_types,
        "overall_page_types": overall_pages,
        "overall_rows": overall.height,
        "top": overall.select(cols).head(top).to_dicts(),
        "scrape_date_max": str(df.get_column("scrape_date").max()) if "scrape_date" in df.columns else None,
    }


# ----------------------------------------------------------------------------------------------------------------------
# datasets
# ----------------------------------------------------------------------------------------------------------------------
def ingest_players(session: Session) -> dict[str, Any]:
    df, snap = fetch_dataset(
        session, endpoint="players", loader=_nfl().load_players, seasons=None,
        upstream_as_of=release_asset_as_of("players", "players.parquet"),
    )
    n = load_table(session, _table("players"), df, partition=[], snapshot_id=snap.snapshot.id)
    return _summary(df, snap, loaded=n, id_columns=id_columns(df))


def ingest_ff_playerids(session: Session) -> dict[str, Any]:
    df, snap = fetch_dataset(
        session, endpoint="ff_playerids", loader=_nfl().load_ff_playerids, seasons=None,
        upstream_as_of=dynastyprocess_as_of("db_playerids.csv"),
    )
    n = load_table(session, _table("ff_playerids"), df, partition=[], snapshot_id=snap.snapshot.id)
    cov = id_coverage(df, ["yahoo_id", "stats_id", "gsis_id", "sleeper_id", "espn_id", "fantasypros_id"])
    return _summary(df, snap, loaded=n, id_columns=id_columns(df), id_coverage=cov)


def ingest_rosters(session: Session, season: int) -> dict[str, Any]:
    df, snap = fetch_dataset(
        session, endpoint="rosters", loader=_nfl().load_rosters, seasons=[season],
        upstream_as_of=release_asset_as_of("rosters", f"roster_{season}.parquet"),
    )
    n = load_table(session, _table("rosters"), df, partition=["season"], snapshot_id=snap.snapshot.id)
    status = df.group_by("status").len().sort("len", descending=True).to_dicts() if "status" in df.columns else None
    return _summary(df, snap, loaded=n, season=season, status_counts=status)


def ingest_depth_charts(session: Session, season: int) -> dict[str, Any]:
    df, snap = fetch_dataset(
        session, endpoint="depth_charts", loader=_nfl().load_depth_charts, seasons=[season],
        upstream_as_of=release_asset_as_of("depth_charts", f"depth_charts_{season}.parquet"),
    )
    # The 2026+ file is `dt`-timestamped and carries no `season` column; add the explicitly requested season so the
    # table can be partitioned by it (snapshot on disk stays verbatim; no upstream column is renamed or dropped).
    added_season = "season" not in df.columns
    if added_season:
        df = df.with_columns(pl.lit(season).cast(pl.Int64).alias("season"))
    n = load_table(session, _table("depth_charts"), df, partition=["season"], snapshot_id=snap.snapshot.id)
    return _summary(df, snap, loaded=n, season=season, season_column_added=added_season, **depth_chart_dt_summary(df))


def ingest_schedules(session: Session, seasons: list[int], bye_season: int) -> dict[str, Any]:
    df, snap = fetch_dataset(
        session, endpoint="schedules", loader=_nfl().load_schedules, seasons=seasons,
        upstream_as_of=release_asset_as_of("schedules", "games.parquet"),
    )
    n = load_table(session, _table("schedules"), df, partition=["season"], snapshot_id=snap.snapshot.id)
    byes = derive_team_bye(df, bye_season)
    nb = load_table(session, _table("team_bye"), byes, partition=["season"], snapshot_id=snap.snapshot.id)
    per_season = df.group_by("season", "game_type").len().sort("season", "game_type").to_dicts()
    return _summary(
        df, snap, loaded=n, seasons=seasons, rows_by_season_type=per_season,
        team_bye={"season": bye_season, "rows": nb, "byes": bye_map(byes)},
    )


def ingest_draft_picks(session: Session) -> dict[str, Any]:
    # seasons=True is nflreadpy's explicit "whole file" switch (the table is one release asset, filtered client-side).
    df, snap = fetch_dataset(
        session, endpoint="draft_picks", loader=_nfl().load_draft_picks, seasons=True,
        upstream_as_of=release_asset_as_of("draft_picks", "draft_picks.parquet"),
    )
    n = load_table(session, _table("draft_picks"), df, partition=[], snapshot_id=snap.snapshot.id)
    return _summary(
        df, snap, loaded=n, season_max=int(df.get_column("season").max()),
        current_draft_ids=draft_pick_id_styles(df, settings.current_season),
    )


def ingest_ff_rankings_draft(session: Session) -> dict[str, Any]:
    nfl = _nfl()
    df = nfl.load_ff_rankings(type="draft")
    if not isinstance(df, pl.DataFrame):
        df = pl.DataFrame(df)
    summary = rankings_summary(df)
    from app.ingest.nflverse_base import snapshot_frame

    snap = snapshot_frame(
        session, endpoint="ff_rankings_draft", df=df, params={"type": "draft"},
        upstream_as_of=summary["scrape_date_max"],
    )
    n = load_table(session, _table("ff_rankings_draft"), df, partition=[], snapshot_id=snap.snapshot.id)
    return _summary(df, snap, loaded=n, **summary)


# ----------------------------------------------------------------------------------------------------------------------
# CLI
# ----------------------------------------------------------------------------------------------------------------------
Season = Annotated[int, typer.Option(help="Season (explicit; never nflreadpy's default).")]
Seasons = Annotated[list[int] | None, typer.Option("--season", help="Repeatable; default history + current.")]


@cli.command()
def players() -> None:
    """nflverse players -> raw_nflverse_players (full replace)."""
    _emit(_run("players", ingest_players))


@cli.command()
def ff_playerids() -> None:
    """DynastyProcess db_playerids -> raw_nflverse_ff_playerids (full replace)."""
    _emit(_run("ff_playerids", ingest_ff_playerids))


@cli.command()
def rosters(season: Season = settings.current_season) -> None:
    """rosters/roster_{season} -> raw_nflverse_rosters (partition season)."""
    _emit(_run("rosters", lambda s: ingest_rosters(s, season), {"seasons": [season]}))


@cli.command()
def depth_charts(season: Season = settings.current_season) -> None:
    """depth_charts/depth_charts_{season} (ALL dt snapshots) -> raw_nflverse_depth_charts (partition season)."""
    _emit(_run("depth_charts", lambda s: ingest_depth_charts(s, season), {"seasons": [season]}))


@cli.command()
def schedules(seasons: Seasons = None, bye_season: Season = settings.current_season) -> None:
    """schedules/games -> raw_nflverse_schedules (partition season) + derived raw_nflverse_team_bye for --bye-season."""
    seasons = seasons or [*settings.history_seasons, settings.current_season]
    _emit(_run("schedules", lambda s: ingest_schedules(s, seasons, bye_season), {"seasons": seasons}))


@cli.command()
def draft_picks() -> None:
    """draft_picks/draft_picks (all seasons) -> raw_nflverse_draft_picks (full replace)."""
    _emit(_run("draft_picks", ingest_draft_picks, {"seasons": True}))


@cli.command()
def ff_rankings() -> None:
    """DynastyProcess db_fpecr_latest (FantasyPros ECR, draft) -> raw_nflverse_ff_rankings_draft (full replace)."""
    _emit(_run("ff_rankings_draft", ingest_ff_rankings_draft, {"type": "draft"}))


@cli.command("all")
def run_all() -> None:
    """Run every dataset with failure isolation; exit 0 if at least one succeeded."""
    cur = settings.current_season
    seasons = [*settings.history_seasons, cur]
    results: dict[str, dict[str, Any]] = {
        "players": _run("players", ingest_players),
        "ff_playerids": _run("ff_playerids", ingest_ff_playerids),
        "rosters": _run("rosters", lambda s: ingest_rosters(s, cur), {"seasons": [cur]}),
        "depth_charts": _run("depth_charts", lambda s: ingest_depth_charts(s, cur), {"seasons": [cur]}),
        "schedules": _run("schedules", lambda s: ingest_schedules(s, seasons, cur), {"seasons": seasons}),
        "draft_picks": _run("draft_picks", ingest_draft_picks, {"seasons": True}),
        "ff_rankings_draft": _run("ff_rankings_draft", ingest_ff_rankings_draft, {"type": "draft"}),
    }
    _emit(results)
    ok = sum(1 for r in results.values() if r.get("error") is None)
    if ok == 0:
        typer.echo("all nflverse_ref datasets failed", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
