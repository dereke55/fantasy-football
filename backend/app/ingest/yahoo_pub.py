"""Yahoo Fantasy public read-only API ("pub-api-ro") -> raw_yahoo_players.

Unofficial, unauthenticated mirror of the Fantasy Sports API (verified 2026-08-29, game_key 470 = NFL 2026):

    GET https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players
        ;sort=AR;start={start};count=100;out=draft_analysis?format=json

Passes (each paged start=0,100,... with count=100, stopping early when a page returns < 100 players):
  1. `sort=DA_AP` (draft-analysis average pick, nulls trail) up to start=500 -> every player Yahoo has an ADP for;
     stops as soon as a page's last row has no average_pick. Verified 2026-08-29: `sort=AR` (actual rank = last
     season's points, all positions incl. IDP) gives only ~227 ADP rows in its top 600, so this pass is what fills the
     "top-400 Yahoo pool" gate in docs/PLAN.md.
  2. `sort=AR` up to start=500 (top-600 by actual rank; includes IDP / team OFF rows without draft analysis).
  3. `sort=AR;position=K` and `sort=AR;position=DEF` (up to start=100) so kickers / team defenses are always present.
Every page's raw JSON is snapshotted (endpoint `players_DA_AP_p{start}`, `players_AR_p{start}`, `players_AR_K_p{start}`,
`players_AR_DEF_p{start}`) before parsing; the parsed union (deduped on player_key, first occurrence wins, in pass
order) is loaded with a full replace into `raw_yahoo_players`. Each row's `snapshot_id` points at the page it came from.

Yahoo's JSON is deeply nested with numeric-string keys:
    fantasy_content.game[1].players["0"].player[0]  -> list of single-key dicts (plus stray empty lists)
    fantasy_content.game[1].players["0"].player[1]  -> {"draft_analysis": [single-key dicts]}
`parse_players_page` flattens that into one dict per player. Nested upstream fields keep their upstream names joined
with "_" (name.full -> name_full, bye_weeks.week -> bye_weeks_week, draft_analysis.* -> unprefixed as upstream names them).
Draft-analysis values are strings ("1.4", "-") and are cast to float with "-" -> null.

Be polite: >= 2 s between page calls, default User-Agent from snapshots.py; run once/day, never during the draft.
Usage: `uv run python -m app.ingest.yahoo_pub all` (or `players`).
"""
from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from typing import Any

import polars as pl
import typer
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.loaders import replace_partition
from app.ingest.snapshots import SnapshotResult, http_get, record_failure, write_snapshot

SOURCE = "yahoo_pub"
TABLE = "raw_yahoo_players"
BASE_URL = "https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players"
PAGE_SIZE = 100
MAIN_MAX_START = 500  # 6 pages of 100 (top-600 by AR); "top-400 Yahoo pool" gate in docs/PLAN.md
POSITION_MAX_START = 100  # K / DEF passes: 2 pages max (there are ~35 K and 32 DEF)
POLITE_DELAY_S = 2.0

# Yahoo `editorial_team_abbr` (title-case) -> nflverse `team_abbr` (raw_nflverse_teams). nflverse uses "LA" for the
# Rams (LAR also exists in raw_nflverse_teams as a legacy alias, same team_id 2510) and "LV" for the Raiders.
YAHOO_TEAM_TO_NFLVERSE: dict[str, str] = {
    "Ari": "ARI", "Atl": "ATL", "Bal": "BAL", "Buf": "BUF", "Car": "CAR", "Chi": "CHI", "Cin": "CIN", "Cle": "CLE",
    "Dal": "DAL", "Den": "DEN", "Det": "DET", "GB": "GB", "Hou": "HOU", "Ind": "IND", "Jax": "JAX", "KC": "KC",
    "LAC": "LAC", "LAR": "LA", "LV": "LV", "Mia": "MIA", "Min": "MIN", "NE": "NE", "NO": "NO", "NYG": "NYG",
    "NYJ": "NYJ", "Phi": "PHI", "Pit": "PIT", "SF": "SF", "Sea": "SEA", "TB": "TB", "Ten": "TEN", "Was": "WAS",
}

DRAFT_ANALYSIS_FIELDS = (
    "average_pick", "average_round", "average_cost", "percent_drafted",
    "preseason_average_pick", "preseason_average_round", "preseason_average_cost", "preseason_percent_drafted",
)

# Column order / dtypes for raw_yahoo_players (upstream names kept; nested keys joined with "_").
COLUMNS: dict[str, Any] = {
    "player_key": pl.Utf8, "player_id": pl.Utf8,
    "name_full": pl.Utf8, "name_first": pl.Utf8, "name_last": pl.Utf8,
    "name_ascii_first": pl.Utf8, "name_ascii_last": pl.Utf8,
    "url": pl.Utf8, "editorial_player_key": pl.Utf8, "editorial_team_key": pl.Utf8,
    "editorial_team_full_name": pl.Utf8, "editorial_team_abbr": pl.Utf8, "team_abbr_nflverse": pl.Utf8,
    "editorial_team_url": pl.Utf8,
    "bye_weeks_week": pl.Int64, "uniform_number": pl.Utf8,
    "display_position": pl.Utf8, "position_type": pl.Utf8, "primary_position": pl.Utf8,
    "eligible_positions": pl.List(pl.Utf8),
    "status": pl.Utf8, "status_full": pl.Utf8, "injury_note": pl.Utf8,
    "is_undroppable": pl.Utf8, "has_player_notes": pl.Int64, "player_notes_last_timestamp": pl.Int64,
    "headshot_url": pl.Utf8, "image_url": pl.Utf8,
    **{f: pl.Float64 for f in DRAFT_ANALYSIS_FIELDS},
    "query_sort": pl.Utf8, "query_position": pl.Utf8, "page_start": pl.Int64, "page_index": pl.Int64,
}


def page_url(start: int, position: str | None = None, sort: str = "AR") -> str:
    pos = f";position={position}" if position else ""
    return f"{BASE_URL};sort={sort}{pos};start={start};count={PAGE_SIZE};out=draft_analysis?format=json"


def endpoint_name(start: int, position: str | None = None, sort: str = "AR") -> str:
    return f"players_{sort}_{position}_p{start}" if position else f"players_{sort}_p{start}"


# ----------------------------------------------------------------------------------------------- parsing
def _merge_single_key_dicts(items: Any) -> dict[str, Any]:
    """Yahoo encodes objects as a list of single-key dicts interleaved with empty lists; collapse to one dict."""
    out: dict[str, Any] = {}
    if isinstance(items, dict):
        return dict(items)
    if isinstance(items, list):
        for it in items:
            if isinstance(it, dict):
                out.update(it)
    return out


def to_float(v: Any) -> float | None:
    """Yahoo numeric strings -> float; '-' / '' / None -> None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _to_int(v: Any) -> int | None:
    f = to_float(v)
    return int(f) if f is not None else None


def normalize_team_abbr(yahoo_abbr: str | None) -> str | None:
    if not yahoo_abbr:
        return None
    return YAHOO_TEAM_TO_NFLVERSE.get(yahoo_abbr, yahoo_abbr.upper())


def flatten_player(parts: list[Any]) -> dict[str, Any]:
    """`players["N"].player` (a list: [base-attrs list, {"draft_analysis": [...]}, ...]) -> flat dict."""
    base = _merge_single_key_dicts(parts[0] if parts else [])
    extras: dict[str, Any] = {}
    for p in parts[1:]:
        if isinstance(p, dict):
            for k, v in p.items():
                extras[k] = _merge_single_key_dicts(v) if isinstance(v, list) else v
    da = extras.get("draft_analysis") or {}
    name = base.get("name") or {}
    bye = base.get("bye_weeks") or {}
    headshot = base.get("headshot") or {}
    elig = [e.get("position") for e in (base.get("eligible_positions") or []) if isinstance(e, dict)]
    row: dict[str, Any] = {
        "player_key": base.get("player_key"),
        "player_id": base.get("player_id"),
        "name_full": name.get("full"), "name_first": name.get("first"), "name_last": name.get("last"),
        "name_ascii_first": name.get("ascii_first"), "name_ascii_last": name.get("ascii_last"),
        "url": base.get("url"),
        "editorial_player_key": base.get("editorial_player_key"),
        "editorial_team_key": base.get("editorial_team_key"),
        "editorial_team_full_name": base.get("editorial_team_full_name"),
        "editorial_team_abbr": base.get("editorial_team_abbr"),
        "team_abbr_nflverse": normalize_team_abbr(base.get("editorial_team_abbr")),
        "editorial_team_url": base.get("editorial_team_url"),
        "bye_weeks_week": _to_int(bye.get("week")),
        "uniform_number": base.get("uniform_number"),
        "display_position": base.get("display_position"),
        "position_type": base.get("position_type"),
        "primary_position": base.get("primary_position"),
        "eligible_positions": elig,
        "status": base.get("status"),
        "status_full": base.get("status_full"),
        "injury_note": base.get("injury_note"),
        "is_undroppable": base.get("is_undroppable"),
        "has_player_notes": _to_int(base.get("has_player_notes")),
        "player_notes_last_timestamp": _to_int(base.get("player_notes_last_timestamp")),
        "headshot_url": headshot.get("url"),
        "image_url": base.get("image_url"),
    }
    for f in DRAFT_ANALYSIS_FIELDS:
        row[f] = to_float(da.get(f))
    # Yahoo emits JSON `false` for absent scalars (e.g. uniform_number on DEF rows): treat as null.
    return {k: (None if v is False else v) for k, v in row.items()}


def parse_players_page(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten one page of `game/nfl/players;...;out=draft_analysis?format=json` into player dicts (page order)."""
    game = payload["fantasy_content"]["game"]
    players_blob: dict[str, Any] | None = None
    for g in game if isinstance(game, list) else [game]:
        if isinstance(g, dict) and "players" in g:
            players_blob = g["players"]
            break
    if not players_blob:
        return []
    rows = []
    for key in sorted((k for k in players_blob if k.isdigit()), key=int):
        entry = players_blob[key]
        if not isinstance(entry, dict) or "player" not in entry:
            continue
        row = flatten_player(entry["player"])
        row["page_index"] = int(key)
        rows.append(row)
    return rows


def _coerce(v: Any, dtype: Any) -> Any:
    """Yahoo uses JSON `false` for absent scalars (e.g. uniform_number); map that to null and cast per column dtype."""
    if v is None or v is False:
        return None
    if dtype == pl.Utf8:
        return str(v)
    if dtype == pl.Int64:
        return _to_int(v)
    if dtype == pl.Float64:
        return to_float(v)
    return v


def rows_to_frame(rows: list[dict[str, Any]]) -> pl.DataFrame:
    if not rows:
        return pl.DataFrame(schema=COLUMNS)
    data = {c: [_coerce(r.get(c), t) for r in rows] for c, t in COLUMNS.items()}
    return pl.DataFrame(data, schema=COLUMNS)


# ----------------------------------------------------------------------------------------------- fetching
def _fetch_page(session: Session, *, start: int, position: str | None, sort: str,
                fetched_at: datetime) -> tuple[SnapshotResult, list[dict]]:
    url = page_url(start, position, sort)
    r = http_get(url)
    payload = r.json()
    rows = parse_players_page(payload)
    snap = write_snapshot(
        session, source=SOURCE, endpoint=endpoint_name(start, position, sort), content=r.content, ext="json",
        params={"url": url, "sort": sort, "start": start, "count": PAGE_SIZE, "position": position,
                "out": "draft_analysis"},
        upstream_as_of=fetched_at.date().isoformat(), row_count=len(rows), fetched_at=fetched_at,
    )
    for row in rows:
        row["query_sort"] = sort
        row["query_position"] = position
        row["page_start"] = start
    return snap, rows


def fetch_players(session: Session, *, main_max_start: int = MAIN_MAX_START,
                  position_max_start: int = POSITION_MAX_START, delay_s: float = POLITE_DELAY_S) -> dict[str, Any]:
    """Page the AR-sorted pool (+ K and DEF passes), snapshot every page, load the deduped union. Returns a summary."""
    fetched_at = datetime.now(UTC)
    # (sort, position filter, max start). DA_AP first so the ADP pool owns the first-occurrence rows.
    passes: list[tuple[str, str | None, int]] = [
        ("DA_AP", None, main_max_start), ("AR", None, main_max_start),
        ("AR", "K", position_max_start), ("AR", "DEF", position_max_start),
    ]

    pages: list[tuple[SnapshotResult, list[dict]]] = []
    calls = 0
    for sort, position, max_start in passes:
        for start in range(0, max_start + 1, PAGE_SIZE):
            if calls:
                time.sleep(delay_s)
            calls += 1
            snap, rows = _fetch_page(session, start=start, position=position, sort=sort, fetched_at=fetched_at)
            pages.append((snap, rows))
            n_adp = sum(r["average_pick"] is not None for r in rows)
            typer.echo(f"  {endpoint_name(start, position, sort)}: {len(rows)} players, {n_adp} with ADP "
                       f"(snapshot {snap.snapshot.id}, new={snap.is_new})")
            if len(rows) < PAGE_SIZE:
                break  # short page = end of this pass
            if sort == "DA_AP" and rows[-1]["average_pick"] is None:
                break  # sorted by ADP with nulls trailing: nothing with an ADP remains

    # Union, dedupe on player_key (first occurrence wins: main AR pass before K / DEF passes).
    seen: set[str] = set()
    per_page: list[tuple[SnapshotResult, list[dict]]] = []
    for snap, rows in pages:
        kept = []
        for row in rows:
            k = row.get("player_key")
            if not k or k in seen:
                continue
            seen.add(k)
            kept.append(row)
        per_page.append((snap, kept))

    # Full replace: delete everything, insert the union in ONE replace_partition call (ensure_table inspects via a
    # separate pooled connection, so a table created earlier in this transaction is invisible to a second call),
    # then point each row's snapshot_id at the page it was parsed from.
    if inspect(session.get_bind()).has_table(TABLE):
        session.execute(text(f'DELETE FROM "{TABLE}"'))
    union = [row for _, rows in per_page for row in rows]
    total = 0
    if union:
        total = replace_partition(session, TABLE, rows_to_frame(union), partition=[], snapshot_id=pages[0][0].snapshot.id)
        for snap, rows in per_page[1:]:
            if rows:
                session.execute(
                    text(f'UPDATE "{TABLE}" SET snapshot_id = :sid WHERE page_start = :start '
                         "AND query_sort = :sort AND query_position IS NOT DISTINCT FROM :pos"),
                    {"sid": str(snap.snapshot.id), "start": rows[0]["page_start"], "sort": rows[0]["query_sort"],
                     "pos": rows[0]["query_position"]},
                )

    unmapped = sorted({r["editorial_team_abbr"] for _, rows in per_page for r in rows
                       if r.get("editorial_team_abbr") and r["editorial_team_abbr"] not in YAHOO_TEAM_TO_NFLVERSE})
    return {
        "rows": total,
        "rows_with_adp": sum(r["average_pick"] is not None for r in union),
        "snapshot_id": str(pages[0][0].snapshot.id) if pages else None,
        "snapshot_ids": [str(s.snapshot.id) for s, _ in pages],
        "is_new": any(s.is_new for s, _ in pages),
        "upstream_as_of": fetched_at.date().isoformat(),
        "pages": calls,
        "unmapped_team_abbrs": unmapped,
        "error": None,
    }


# ----------------------------------------------------------------------------------------------- CLI
cli = typer.Typer(no_args_is_help=True, help="Yahoo public (no-auth) player pool + draft_analysis ADP -> raw_yahoo_players")


def _kickoff_guard(post_kickoff: bool) -> None:
    if datetime.now(UTC).date() >= date.fromisoformat(settings.kickoff_date) and not post_kickoff:
        typer.echo(f"Refusing to ingest on/after kickoff {settings.kickoff_date} without --post-kickoff (ROS semantics).")
        raise typer.Exit(code=2)


def _run(name: str, fn, summary: dict[str, Any]) -> bool:
    from app.db import session_scope

    try:
        with session_scope() as session:
            summary[name] = fn(session)
        return True
    except Exception as e:  # noqa: BLE001 - per-dataset isolation
        with session_scope() as session:
            record_failure(session, source=SOURCE, endpoint=name, params=None, error=f"{type(e).__name__}: {e}")
        summary[name] = {"rows": 0, "snapshot_id": None, "is_new": False, "upstream_as_of": None,
                         "error": f"{type(e).__name__}: {e}"}
        return False


@cli.command("players")
def players_cmd(post_kickoff: bool = typer.Option(False, "--post-kickoff", help="Allow ingest on/after kickoff day.")) -> None:
    """Fetch the DA_AP (ADP-sorted) pool, the AR top-600, and K + DEF passes -> raw_yahoo_players."""
    _kickoff_guard(post_kickoff)
    summary: dict[str, Any] = {}
    ok = _run("players", fetch_players, summary)
    typer.echo(json.dumps(summary, indent=2, default=str))
    raise typer.Exit(code=0 if ok else 1)


@cli.command("all")
def all_cmd(post_kickoff: bool = typer.Option(False, "--post-kickoff", help="Allow ingest on/after kickoff day.")) -> None:
    """Run every yahoo_pub dataset with per-dataset failure isolation; exit 0 if at least one succeeded."""
    _kickoff_guard(post_kickoff)
    summary: dict[str, Any] = {}
    results = [_run("players", fetch_players, summary)]
    typer.echo(json.dumps(summary, indent=2, default=str))
    raise typer.Exit(code=0 if any(results) else 1)


if __name__ == "__main__":
    cli()
