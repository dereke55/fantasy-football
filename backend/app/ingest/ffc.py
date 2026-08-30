"""Fantasy Football Calculator (FFC) ADP via the official free REST API, snapshot-first.

GET https://fantasyfootballcalculator.com/api/v1/adp/{format}?teams=10&year=2026  (format: half-ppr | ppr | standard)
-> {status, meta{type, teams, rounds, total_drafts, start_date, end_date},
    players[{player_id, name, position, team, adp, adp_formatted, times_drafted, high, low, stdev, bye}]}
The data is a rolling window of FFC mock drafts, refreshed about once per day; FFC asks for attribution and
infrequent calls (help article 42, "ADP REST API"). No auth.

Each pull is written verbatim to data/raw/ffc/adp_{format}_{teams}/ and registered in raw_snapshots, then loaded into
`raw_ffc_adp`: every player field as-is plus the meta fields (type, teams, rounds, total_drafts, start_date, end_date)
and the request `format` / `year`. Partition = (format, teams, year). upstream_as_of = meta.end_date.

Smoke: `uv run python -m app.ingest.ffc all` -> JSON {dataset: {rows, snapshot_id, is_new, upstream_as_of, error}}.
`compare-teams` pulls half-ppr with teams=12 once and reports whether it differs from the teams=10 snapshot
(the plan wants to know whether `teams` filters drafts or only re-formats adp_formatted).
"""
from __future__ import annotations

import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import polars as pl
import typer
from sqlalchemy.orm import Session

from app.config import settings
from app.db import session_scope
from app.ingest.loaders import replace_partition
from app.ingest.snapshots import http_get, latest_snapshot, record_failure, write_snapshot

SOURCE = "ffc"
TABLE = "raw_ffc_adp"
BASE_URL = "https://fantasyfootballcalculator.com/api/v1/adp/{fmt}"
FORMATS: tuple[str, ...] = ("half-ppr", "ppr", "standard")
PARTITION = ["format", "teams", "year"]
META_FIELDS = ("type", "teams", "rounds", "total_drafts", "start_date", "end_date")
PLAYER_SCHEMA: dict[str, type[pl.DataType]] = {
    "player_id": pl.Int64,
    "name": pl.Utf8,
    "position": pl.Utf8,
    "team": pl.Utf8,
    "adp": pl.Float64,
    "adp_formatted": pl.Utf8,
    "times_drafted": pl.Int64,
    "high": pl.Int64,
    "low": pl.Int64,
    "stdev": pl.Float64,
    "bye": pl.Int64,
}
POLITE_DELAY_S = 2.0

_last_call_monotonic = 0.0


def endpoint_name(fmt: str, teams: int) -> str:
    return f"adp_{fmt}_{teams}"


def _polite_get(url: str, params: dict[str, Any]):
    """>= POLITE_DELAY_S between FFC calls within one process."""
    global _last_call_monotonic
    wait = POLITE_DELAY_S - (time.monotonic() - _last_call_monotonic)
    if wait > 0:
        time.sleep(wait)
    try:
        return http_get(url, params=params)
    finally:
        _last_call_monotonic = time.monotonic()


def fetch_adp(fmt: str, *, teams: int, year: int) -> tuple[bytes, dict[str, Any]]:
    """Raw response bytes (what gets snapshotted) + parsed JSON. Raises on non-Success status."""
    if fmt not in FORMATS:
        raise ValueError(f"unknown FFC format {fmt!r}; expected one of {FORMATS}")
    r = _polite_get(BASE_URL.format(fmt=fmt), {"teams": teams, "year": year})
    payload = r.json()
    if payload.get("status") != "Success":
        raise RuntimeError(f"FFC status={payload.get('status')!r} for {fmt} teams={teams} year={year}")
    return r.content, payload


def parse_adp(payload: dict[str, Any], *, fmt: str, teams: int, year: int) -> pl.DataFrame:
    """players[] -> one row each with all upstream fields verbatim, plus meta fields and request format/year."""
    meta = payload.get("meta") or {}
    players = payload.get("players") or []
    if not players:
        raise ValueError(f"FFC {fmt} teams={teams} year={year}: empty players list")
    if meta.get("teams") is not None and int(meta["teams"]) != teams:
        raise ValueError(f"FFC meta.teams={meta['teams']} != requested teams={teams}")
    df = pl.DataFrame(players, schema_overrides=PLAYER_SCHEMA, infer_schema_length=None)
    missing = [c for c in PLAYER_SCHEMA if c not in df.columns]
    if missing:
        raise ValueError(f"FFC payload missing expected player fields {missing}")
    return df.with_columns(
        pl.lit(fmt).alias("format"),
        pl.lit(meta.get("type"), dtype=pl.Utf8).alias("type"),
        pl.lit(teams, dtype=pl.Int64).alias("teams"),
        pl.lit(meta.get("rounds"), dtype=pl.Int64).alias("rounds"),
        pl.lit(meta.get("total_drafts"), dtype=pl.Int64).alias("total_drafts"),
        pl.lit(meta.get("start_date"), dtype=pl.Utf8).alias("start_date"),
        pl.lit(meta.get("end_date"), dtype=pl.Utf8).alias("end_date"),
        pl.lit(year, dtype=pl.Int64).alias("year"),
    )


def ingest_format(session: Session, fmt: str, *, teams: int, year: int) -> dict[str, Any]:
    """Fetch -> snapshot -> load one (format, teams, year) partition. Returns the summary dict for this dataset."""
    content, payload = fetch_adp(fmt, teams=teams, year=year)
    df = parse_adp(payload, fmt=fmt, teams=teams, year=year)
    meta = payload.get("meta") or {}
    snap = write_snapshot(
        session, source=SOURCE, endpoint=endpoint_name(fmt, teams), content=content, ext="json",
        params={"format": fmt, "teams": teams, "year": year}, upstream_as_of=meta.get("end_date"), row_count=df.height,
    )
    rows = replace_partition(session, TABLE, df, partition=PARTITION, snapshot_id=snap.snapshot.id)
    return {
        "rows": rows,
        "snapshot_id": str(snap.snapshot.id),
        "is_new": snap.is_new,
        "upstream_as_of": meta.get("end_date"),
        "total_drafts": meta.get("total_drafts"),
        "error": None,
    }


def run(formats: list[str], *, teams: int, year: int) -> dict[str, dict[str, Any]]:
    """Per-dataset failure isolation: each format in its own transaction; failures recorded, never raised."""
    summary: dict[str, dict[str, Any]] = {}
    for fmt in formats:
        name = endpoint_name(fmt, teams)
        try:
            with session_scope() as s:
                summary[name] = ingest_format(s, fmt, teams=teams, year=year)
        except Exception as e:  # noqa: BLE001 - one failing dataset must not fail the job
            err = f"{type(e).__name__}: {e}"
            with session_scope() as s:
                record_failure(s, source=SOURCE, endpoint=name, params={"format": fmt, "teams": teams, "year": year}, error=err)
            summary[name] = {"rows": 0, "snapshot_id": None, "is_new": False, "upstream_as_of": None, "error": err}
    return summary


def compare_payloads(base: dict[str, Any], other: dict[str, Any]) -> dict[str, Any]:
    """Does `other` (e.g. teams=12) carry different drafts than `base` (teams=10)? Compare meta + per-player adp."""
    b = {p["player_id"]: p for p in base.get("players", [])}
    o = {p["player_id"]: p for p in other.get("players", [])}
    common = sorted(set(b) & set(o))
    adp_diffs = [abs(float(b[i]["adp"]) - float(o[i]["adp"])) for i in common]
    fields_differ = {
        f: [b[i][f] for i in common] != [o[i][f] for i in common]
        for f in ("adp", "adp_formatted", "times_drafted", "high", "low", "stdev")
    }
    bm, om = base.get("meta", {}), other.get("meta", {})
    return {
        "base_meta": bm,
        "other_meta": om,
        "total_drafts_differs": bm.get("total_drafts") != om.get("total_drafts"),
        "window_differs": (bm.get("start_date"), bm.get("end_date")) != (om.get("start_date"), om.get("end_date")),
        "players_base": len(b),
        "players_other": len(o),
        "players_common": len(common),
        "players_with_adp_diff": sum(1 for d in adp_diffs if d > 1e-9),
        "max_abs_adp_diff": max(adp_diffs) if adp_diffs else None,
        "fields_differ": fields_differ,
        # Only adp_formatted is expected to change if `teams` merely re-formats round.pick.
        "differs": any(v for f, v in fields_differ.items() if f != "adp_formatted")
        or bm.get("total_drafts") != om.get("total_drafts")
        or set(b) != set(o),
    }


def _guard_post_kickoff(post_kickoff: bool) -> None:
    today = datetime.now(UTC).date().isoformat()
    if today >= settings.kickoff_date and not post_kickoff:
        raise typer.BadParameter(
            f"today {today} >= kickoff {settings.kickoff_date}: FFC ADP semantics change after kickoff; pass --post-kickoff"
        )


def _echo(obj: Any) -> None:
    typer.echo(json.dumps(obj, indent=2, default=str))


cli = typer.Typer(no_args_is_help=True, help="FFC ADP ingestion (half-ppr / ppr / standard) -> raw_ffc_adp")

TEAMS_OPT = typer.Option(10, help="League size sent to FFC (partition key).")
YEAR_OPT = typer.Option(settings.current_season, help="Draft year (explicit; partition key).")
KICKOFF_OPT = typer.Option(False, "--post-kickoff", help="Required after kickoff (settings.kickoff_date).")


def _one(fmt: str, teams: int, year: int, post_kickoff: bool) -> None:
    _guard_post_kickoff(post_kickoff)
    summary = run([fmt], teams=teams, year=year)
    _echo(summary)
    if summary[endpoint_name(fmt, teams)]["error"]:
        raise typer.Exit(code=1)


@cli.command("half-ppr")
def half_ppr(teams: int = TEAMS_OPT, year: int = YEAR_OPT, post_kickoff: bool = KICKOFF_OPT) -> None:
    """FFC half-PPR ADP -> raw_ffc_adp (format='half-ppr')."""
    _one("half-ppr", teams, year, post_kickoff)


@cli.command("ppr")
def ppr(teams: int = TEAMS_OPT, year: int = YEAR_OPT, post_kickoff: bool = KICKOFF_OPT) -> None:
    """FFC PPR ADP -> raw_ffc_adp (format='ppr')."""
    _one("ppr", teams, year, post_kickoff)


@cli.command("standard")
def standard(teams: int = TEAMS_OPT, year: int = YEAR_OPT, post_kickoff: bool = KICKOFF_OPT) -> None:
    """FFC standard (non-PPR) ADP -> raw_ffc_adp (format='standard')."""
    _one("standard", teams, year, post_kickoff)


@cli.command("all")
def all_formats(teams: int = TEAMS_OPT, year: int = YEAR_OPT, post_kickoff: bool = KICKOFF_OPT) -> None:
    """All three formats; exit 0 if at least one succeeded. Prints a JSON summary."""
    _guard_post_kickoff(post_kickoff)
    summary = run(list(FORMATS), teams=teams, year=year)
    _echo(summary)
    if not any(v["error"] is None for v in summary.values()):
        raise typer.Exit(code=1)


@cli.command("compare-teams")
def compare_teams(
    fmt: str = typer.Option("half-ppr", "--format"),
    teams: int = typer.Option(12, help="Alternate league size to probe."),
    baseline_teams: int = typer.Option(10, help="League size already loaded (latest ok snapshot is the baseline)."),
    year: int = YEAR_OPT,
    post_kickoff: bool = KICKOFF_OPT,
) -> None:
    """Pull `fmt` with an alternate `teams`, snapshot it, and load it ONLY if the drafts differ from the baseline."""
    _guard_post_kickoff(post_kickoff)
    with session_scope() as s:
        base = latest_snapshot(s, SOURCE, endpoint_name(fmt, baseline_teams))
        if base is None:
            raise typer.BadParameter(f"no ok snapshot for {endpoint_name(fmt, baseline_teams)}; run `{fmt}` first")
        base_payload = json.loads(Path(base.path).read_bytes())
        content, payload = fetch_adp(fmt, teams=teams, year=year)
        meta = payload.get("meta") or {}
        snap = write_snapshot(
            s, source=SOURCE, endpoint=endpoint_name(fmt, teams), content=content, ext="json",
            params={"format": fmt, "teams": teams, "year": year}, upstream_as_of=meta.get("end_date"),
            row_count=len(payload.get("players") or []), note=f"teams-parameter probe vs {base.id}",
        )
        result = compare_payloads(base_payload, payload)
        result.update({"baseline_snapshot_id": str(base.id), "snapshot_id": str(snap.snapshot.id), "loaded_rows": 0})
        if result["differs"]:
            df = parse_adp(payload, fmt=fmt, teams=teams, year=year)
            result["loaded_rows"] = replace_partition(s, TABLE, df, partition=PARTITION, snapshot_id=snap.snapshot.id)
    _echo(result)


if __name__ == "__main__":
    cli()
