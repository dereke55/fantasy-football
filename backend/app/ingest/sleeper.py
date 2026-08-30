"""Sleeper ingestion: season projections (+ multi-format ADP) and the players master.

Datasets (both unofficial-but-public, no key; verified 2026-08-29):
  projections  GET https://api.sleeper.com/projections/nfl/{season}?season_type=regular
               -> snapshot data/raw/sleeper/projections_{season}_regular/*.json
               -> raw_sleeper_projections  (partition: season)
  players      GET https://api.sleeper.app/v1/players/nfl   (~14.6 MB dict keyed by player_id)
               -> snapshot data/raw/sleeper/players_nfl/*.json
               -> raw_sleeper_players      (full replace)

Rules honoured here (see CLAUDE.md / docs/PLAN.md Phase 1a):
  * Snapshot first, content-hash dedupe, one failing dataset never fails the other (`all`).
  * Projections are filtered to QB/RB/WR/TE/K/DEF rows that carry >= 1 counting stat (`has_projection`);
    ADP-only rows (1,700+ practice-squad / FA names with ADP >= 200) are dropped. Every stats key is flattened
    (`stat_<key>` for counting stats, `adp_*` kept as-is) and the untouched dict is kept in `stats_json` (jsonb).
    ADP values >= 999 (Sleeper's "undrafted" sentinel) are nulled in the flattened columns only.
  * `stat_gp` / `stat_pts_*` are mirrored for completeness but MUST NOT be used downstream: points come from
    app/scoring, games-played from app/features (E[games]).
  * Players master is fetched at most once per ~20 h (docs.sleeper.com asks for <= 1/day). A fresh snapshot is
    reused for the load; an ETag from the previous pull is sent as If-None-Match.
  * Parsers assert the pre-kickoff shape (projection `week` is null for every record); after settings.kickoff_date
    the commands refuse to run without --post-kickoff.

Run:  cd backend && uv run python -m app.ingest.sleeper all
"""
from __future__ import annotations

import json
import time
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl
import typer
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.ingest.loaders import _pg_ident, replace_partition
from app.ingest.snapshots import SnapshotResult, http_get, latest_snapshot, record_failure, write_snapshot

SOURCE = "sleeper"
PROJECTIONS_URL = "https://api.sleeper.com/projections/nfl/{season}"
PLAYERS_URL = "https://api.sleeper.app/v1/players/nfl"
PLAYERS_ENDPOINT = "players_nfl"
PLAYERS_TABLE = "raw_sleeper_players"
PROJECTIONS_TABLE = "raw_sleeper_projections"
PLAYERS_MAX_AGE = timedelta(hours=20)
POLITE_PAUSE_S = 2.0

FANTASY_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")
ADP_SENTINEL = 999.0
# stats keys that are NOT counting stats: market data, vendor points, games played.
_NON_COUNTING_PREFIXES = ("adp_", "pts_")
_NON_COUNTING_KEYS = frozenset({"gp"})

# Sleeper `status` values that keep a team-less player in raw_sleeper_players (injured lists + active).
PLAYER_KEEP_STATUSES = frozenset(
    {
        "Active",
        "Injured Reserve",
        "Physically Unable to Perform",
        "Non Football Injury",
        "Non Football Illness",
        "Reserve/Injured",
        "Reserve/PUP",
        "Reserve/NFI",
        "Practice Squad",
        "Practice Squad; Injured",
    }
)


# --------------------------------------------------------------------------------------------- helpers
def _is_counting_stat(key: str) -> bool:
    return not key.startswith(_NON_COUNTING_PREFIXES) and key not in _NON_COUNTING_KEYS


def _ms_to_iso(ms: float | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat(timespec="seconds")


def _to_int(v: Any) -> int | None:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None


def _to_text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _json_text(v: Any) -> str | None:
    return None if v is None else json.dumps(v, sort_keys=True, separators=(",", ":"))


def _promote_jsonb(session: Session, table: str, columns: Iterable[str]) -> None:
    """Promote JSON-string columns of a freshly created raw table to jsonb (one-time; no-op once jsonb).

    loaders.ensure_table maps Utf8 -> text, so the first load lands JSON text; this ALTER (same transaction,
    inspected through the session connection) converts it. On later loads psycopg casts str params to the
    existing jsonb column implicitly.
    """
    types = {c["name"]: str(c["type"]).lower() for c in inspect(session.connection()).get_columns(table)}
    for col in columns:
        if col in types and types[col] != "jsonb":
            session.execute(
                text(
                    f"ALTER TABLE {_pg_ident(table)} ALTER COLUMN {_pg_ident(col)} TYPE jsonb "
                    f"USING {_pg_ident(col)}::jsonb"
                )
            )


def _guard_kickoff(post_kickoff: bool) -> None:
    if not post_kickoff and datetime.now(tz=UTC).date().isoformat() >= settings.kickoff_date:
        raise typer.BadParameter(
            f"today >= kickoff ({settings.kickoff_date}); Sleeper projections switch to rest-of-season semantics. "
            "Re-run with --post-kickoff to acknowledge."
        )


# --------------------------------------------------------------------------------------------- projections
def assert_projection_shape(records: list[dict]) -> None:
    """Pre-kickoff invariant: every record is a season-total (`week` null) projection."""
    bad = [r.get("player_id") for r in records if r.get("week") is not None]
    if bad:
        raise ValueError(f"{len(bad)} projection records have week != null (e.g. {bad[:5]}); refusing to load")


def parse_projections(records: list[dict], season: int | None = None) -> pl.DataFrame:
    """Flatten Sleeper projection records to one row per fantasy-relevant player.

    Keeps rows whose player.position is in QB/RB/WR/TE/K/DEF. `has_projection` is True when the stats dict holds at
    least one counting stat (anything other than adp_*, pts_*, gp). ADP values >= 999 are nulled in the flattened
    adp_* columns; `stats_json` keeps the upstream dict verbatim.
    """
    rows: list[dict[str, Any]] = []
    stat_keys: set[str] = set()
    for rec in records:
        player = rec.get("player") or {}
        position = player.get("position")
        if position not in FANTASY_POSITIONS:
            continue
        stats: dict[str, Any] = rec.get("stats") or {}
        stat_keys.update(stats)
        row: dict[str, Any] = {
            "player_id": _to_text(rec.get("player_id")),
            "first_name": player.get("first_name"),
            "last_name": player.get("last_name"),
            "position": position,
            "team": rec.get("team"),
            "company": rec.get("company"),
            "last_modified": _to_int(rec.get("last_modified")),
            "updated_at": _to_int(rec.get("updated_at")),
            "week": _to_int(rec.get("week")),
            "season": _to_int(rec.get("season")) if season is None else season,
            "season_type": rec.get("season_type"),
            "category": rec.get("category"),
            "game_id": _to_text(rec.get("game_id")),
            "player_team": player.get("team"),
            "player_team_abbr": player.get("team_abbr"),
            "player_fantasy_positions": player.get("fantasy_positions"),
            "player_injury_status": player.get("injury_status"),
            "player_years_exp": _to_int(player.get("years_exp")),
            "player_news_updated": _to_int(player.get("news_updated")),
            "has_projection": any(_is_counting_stat(k) for k in stats),
            "stats_json": _json_text(stats),
        }
        for key, value in stats.items():
            if key.startswith("adp_"):
                row[key] = None if value is None or float(value) >= ADP_SENTINEL else float(value)
            else:
                row[f"stat_{key}"] = None if value is None else float(value)
        rows.append(row)

    schema: dict[str, pl.DataType] = {
        "player_id": pl.Utf8,
        "first_name": pl.Utf8,
        "last_name": pl.Utf8,
        "position": pl.Utf8,
        "team": pl.Utf8,
        "company": pl.Utf8,
        "last_modified": pl.Int64,
        "updated_at": pl.Int64,
        "week": pl.Int64,
        "season": pl.Int64,
        "season_type": pl.Utf8,
        "category": pl.Utf8,
        "game_id": pl.Utf8,
        "player_team": pl.Utf8,
        "player_team_abbr": pl.Utf8,
        "player_fantasy_positions": pl.List(pl.Utf8),
        "player_injury_status": pl.Utf8,
        "player_years_exp": pl.Int64,
        "player_news_updated": pl.Int64,
        "has_projection": pl.Boolean,
        "stats_json": pl.Utf8,
    }
    for key in sorted(stat_keys):
        schema[key if key.startswith("adp_") else f"stat_{key}"] = pl.Float64
    return pl.from_dicts(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def fetch_projections(session: Session, season: int) -> tuple[list[dict], SnapshotResult]:
    url = PROJECTIONS_URL.format(season=season)
    params = {"season_type": "regular"}
    resp = http_get(url, params=params)
    records = resp.json()
    if not isinstance(records, list):
        raise TypeError(f"unexpected payload type {type(records).__name__} from {url}")
    assert_projection_shape(records)
    last_modified = max((r.get("last_modified") or 0) for r in records) if records else None
    snap = write_snapshot(
        session,
        source=SOURCE,
        endpoint=f"projections_{season}_regular",
        content=resp.content,
        ext="json",
        params={"url": url, **params, "etag": resp.headers.get("etag")},
        upstream_as_of=_ms_to_iso(last_modified) if last_modified else None,
        row_count=len(records),
    )
    return records, snap


def load_projections(session: Session, records: list[dict], snapshot_id, season: int) -> int:
    df = parse_projections(records, season=season).filter(pl.col("has_projection"))
    n = replace_partition(session, PROJECTIONS_TABLE, df, partition=["season"], snapshot_id=snapshot_id)
    _promote_jsonb(session, PROJECTIONS_TABLE, ["stats_json"])
    return n


def ingest_projections(session: Session, season: int) -> dict[str, Any]:
    records, snap = fetch_projections(session, season)
    n = load_projections(session, records, snap.snapshot.id, season)
    return {
        "rows": n,
        "snapshot_id": str(snap.snapshot.id),
        "is_new": snap.is_new,
        "upstream_as_of": snap.snapshot.upstream_as_of,
        "error": None,
    }


# --------------------------------------------------------------------------------------------- players
_PLAYER_INT_COLS = (
    "depth_chart_order", "age", "years_exp", "number", "search_rank", "news_updated", "team_changed_at",
)
_PLAYER_BOOL_COLS = ("active",)
_PLAYER_LIST_COLS = ("fantasy_positions",)
_PLAYER_JSON_COLS = ("metadata", "competitions")
_PLAYER_TEXT_COLS = (
    "first_name", "last_name", "full_name", "position", "team", "team_abbr", "status", "injury_status",
    "injury_body_part", "injury_start_date", "injury_notes", "practice_participation", "practice_description",
    "depth_chart_position", "birth_date", "college", "height", "weight", "hashtag", "sport", "player_shard",
)
_ID_SUFFIX = "_id"


def parse_players(players: dict[str, dict], *, keep_statuses: frozenset[str] = PLAYER_KEEP_STATUSES) -> pl.DataFrame:
    """Players master dict -> one row per fantasy-relevant player.

    Keeps position in QB/RB/WR/TE/K/DEF and (team not null OR status in `keep_statuses`). Every `*_id` key present
    upstream becomes a text column (ids are mixed int/str upstream); nested `metadata` / `competitions` are JSON
    strings promoted to jsonb on load.
    """
    id_cols: set[str] = set()
    kept: list[dict] = []
    for pid, p in players.items():
        if not isinstance(p, dict) or p.get("position") not in FANTASY_POSITIONS:
            continue
        if p.get("team") is None and p.get("status") not in keep_statuses:
            continue
        id_cols.update(k for k in p if k.endswith(_ID_SUFFIX))
        kept.append({"player_id": _to_text(p.get("player_id") or pid), **p})
    id_cols.discard("player_id")
    id_order = sorted(id_cols)

    schema: dict[str, pl.DataType] = {"player_id": pl.Utf8}
    for c in _PLAYER_TEXT_COLS:
        schema[c] = pl.Utf8
    for c in _PLAYER_LIST_COLS:
        schema[c] = pl.List(pl.Utf8)
    for c in _PLAYER_INT_COLS:
        schema[c] = pl.Int64
    for c in _PLAYER_BOOL_COLS:
        schema[c] = pl.Boolean
    for c in id_order:
        schema[c] = pl.Utf8
    for c in _PLAYER_JSON_COLS:
        schema[c] = pl.Utf8

    rows: list[dict[str, Any]] = []
    for p in kept:
        row: dict[str, Any] = {"player_id": p["player_id"]}
        for c in _PLAYER_TEXT_COLS:
            row[c] = _to_text(p.get(c))
        for c in _PLAYER_LIST_COLS:
            v = p.get(c)
            row[c] = [str(x) for x in v] if isinstance(v, list) else None
        for c in _PLAYER_INT_COLS:
            row[c] = _to_int(p.get(c))
        for c in _PLAYER_BOOL_COLS:
            v = p.get(c)
            row[c] = None if v is None else bool(v)
        for c in id_order:
            row[c] = _to_text(p.get(c))
        for c in _PLAYER_JSON_COLS:
            row[c] = _json_text(p.get(c))
        rows.append(row)
    return pl.from_dicts(rows, schema=schema) if rows else pl.DataFrame(schema=schema)


def fetch_players(session: Session, *, force: bool = False) -> tuple[dict[str, dict], SnapshotResult, bool]:
    """Return (payload, snapshot, reused). Reuses a snapshot < PLAYERS_MAX_AGE old unless `force`."""
    latest = latest_snapshot(session, SOURCE, PLAYERS_ENDPOINT)
    now = datetime.now(UTC)
    if latest is not None and not force:
        fetched_at = latest.fetched_at if latest.fetched_at.tzinfo else latest.fetched_at.replace(tzinfo=UTC)
        age = now - fetched_at
        if age < PLAYERS_MAX_AGE and Path(latest.path).exists():
            typer.echo(f"[sleeper] players_nfl snapshot {latest.id} is {age} old (< {PLAYERS_MAX_AGE}); reusing", err=True)
            return json.loads(Path(latest.path).read_bytes()), SnapshotResult(latest, Path(latest.path), False), True

    headers: dict[str, str] = {}
    prev_etag = (latest.params or {}).get("etag") if latest is not None else None
    if prev_etag and latest is not None and Path(latest.path).exists():
        headers["If-None-Match"] = prev_etag
    resp = http_get(PLAYERS_URL, headers=headers, timeout=180)
    if resp.status_code == 304 and latest is not None:
        typer.echo(f"[sleeper] players_nfl unchanged upstream (ETag {prev_etag}); reusing {latest.id}", err=True)
        return json.loads(Path(latest.path).read_bytes()), SnapshotResult(latest, Path(latest.path), False), True

    payload = resp.json()
    if not isinstance(payload, dict) or len(payload) < 1000:
        raise ValueError(f"unexpected players payload ({type(payload).__name__}, {len(payload)} entries)")
    news = [_to_int(p.get("news_updated")) for p in payload.values() if isinstance(p, dict)]
    news_max = max((n for n in news if n), default=None)
    snap = write_snapshot(
        session,
        source=SOURCE,
        endpoint=PLAYERS_ENDPOINT,
        content=resp.content,
        ext="json",
        params={"url": PLAYERS_URL, "etag": resp.headers.get("etag")},
        upstream_as_of=_ms_to_iso(news_max),
        row_count=len(payload),
        fetched_at=now,
    )
    return payload, snap, False


def load_players(session: Session, payload: dict[str, dict], snapshot_id) -> int:
    df = parse_players(payload)
    if inspect(session.connection()).has_table(PLAYERS_TABLE):
        session.execute(text(f"DELETE FROM {_pg_ident(PLAYERS_TABLE)}"))  # partition [] = full replace
    n = replace_partition(session, PLAYERS_TABLE, df, partition=[], snapshot_id=snapshot_id)
    _promote_jsonb(session, PLAYERS_TABLE, _PLAYER_JSON_COLS)
    return n


def ingest_players(session: Session, *, force: bool = False) -> dict[str, Any]:
    payload, snap, reused = fetch_players(session, force=force)
    n = load_players(session, payload, snap.snapshot.id)
    return {
        "rows": n,
        "snapshot_id": str(snap.snapshot.id),
        "is_new": snap.is_new,
        "reused_snapshot": reused,
        "upstream_as_of": snap.snapshot.upstream_as_of,
        "error": None,
    }


# --------------------------------------------------------------------------------------------- CLI
cli = typer.Typer(no_args_is_help=True, help="Sleeper: projections (+ADP) and players master")


def _run(name: str, endpoint: str, params: dict, fn) -> dict[str, Any]:
    """Run one dataset in its own transaction; on failure record it and return an error summary."""
    try:
        with session_scope() as session:
            return fn(session)
    except Exception as e:  # noqa: BLE001 - per-dataset isolation by design
        err = f"{type(e).__name__}: {e}"
        typer.echo(f"[sleeper] {name} FAILED: {err}", err=True)
        try:
            with session_scope() as session:
                record_failure(session, source=SOURCE, endpoint=endpoint, params=params, error=err)
        except Exception as e2:  # noqa: BLE001
            typer.echo(f"[sleeper] could not record failure: {e2}", err=True)
        return {"rows": 0, "snapshot_id": None, "is_new": False, "upstream_as_of": None, "error": err}


@cli.command()
def projections(
    season: int = typer.Option(settings.current_season, help="Projection season (explicit; never inferred)."),
    post_kickoff: bool = typer.Option(False, "--post-kickoff", help="Acknowledge post-kickoff ROS semantics."),
) -> None:
    """Season projections + Sleeper ADP -> raw_sleeper_projections."""
    _guard_kickoff(post_kickoff)
    out = _run(
        "projections", f"projections_{season}_regular", {"season_type": "regular"},
        lambda s: ingest_projections(s, season),
    )
    typer.echo(json.dumps({"projections": out}, indent=2))
    raise typer.Exit(code=0 if out["error"] is None else 1)


@cli.command()
def players(
    force: bool = typer.Option(False, "--force", help="Re-download even if a snapshot < 20 h old exists."),
) -> None:
    """Players master (ids, injury status, depth chart) -> raw_sleeper_players. Once per day by default."""
    out = _run("players", PLAYERS_ENDPOINT, {"url": PLAYERS_URL}, lambda s: ingest_players(s, force=force))
    typer.echo(json.dumps({"players": out}, indent=2))
    raise typer.Exit(code=0 if out["error"] is None else 1)


@cli.command("all")
def all_datasets(
    season: int = typer.Option(settings.current_season, help="Projection season (explicit; never inferred)."),
    force_players: bool = typer.Option(False, "--force-players", help="Ignore the once/day players cache."),
    post_kickoff: bool = typer.Option(False, "--post-kickoff", help="Acknowledge post-kickoff ROS semantics."),
) -> None:
    """Run every Sleeper dataset; exit 0 if at least one succeeded. Prints a JSON summary."""
    _guard_kickoff(post_kickoff)
    summary: dict[str, dict[str, Any]] = {}
    summary["projections"] = _run(
        "projections", f"projections_{season}_regular", {"season_type": "regular"},
        lambda s: ingest_projections(s, season),
    )
    time.sleep(POLITE_PAUSE_S)
    summary["players"] = _run(
        "players", PLAYERS_ENDPOINT, {"url": PLAYERS_URL}, lambda s: ingest_players(s, force=force_players)
    )
    typer.echo(json.dumps(summary, indent=2))
    raise typer.Exit(code=0 if any(v["error"] is None for v in summary.values()) else 1)


if __name__ == "__main__":
    cli()
