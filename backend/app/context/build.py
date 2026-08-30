"""Load the curated 2026 team-context seeds into `team_context`, with validation and provenance.

Seeds are hand-maintained (docs/phases/05-team-context.md). This loader is strict about the things that would
silently corrupt a WHY bullet: unknown team codes, missing source URLs, wrong row counts, bad enum values.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import polars as pl
import typer
import yaml
from sqlalchemy import text

from app.config import settings
from app.db import engine, session_scope

cli = typer.Typer(no_args_is_help=True, help="Curated 2026 team context (coaching, QB rooms, offensive line)")

SEEDS = ("coaching_changes", "qb_situations", "ol_changes")
QB_STATUS = {"settled", "competition", "injury_return"}
CONFIDENCE = {"high", "medium", "low"}


def _teams() -> set[str]:
    df = pl.read_database("select distinct team from raw_nflverse_rosters where season = 2026", connection=engine)
    return set(df["team"].to_list())


def _load(name: str) -> tuple[list[dict], str]:
    p: Path = settings.seeds_dir / f"{name}.yaml"
    raw = p.read_bytes()
    doc = yaml.safe_load(raw.decode()) or {}
    return (doc.get("rows") or []), hashlib.sha256(raw).hexdigest()


def validate() -> list[str]:
    """Return a list of problems; empty means the seeds are safe to load."""
    problems: list[str] = []
    teams = _teams()
    for name in SEEDS:
        rows, _ = _load(name)
        if len(rows) != 32:
            problems.append(f"{name}: {len(rows)} rows, expected 32")
        seen = set()
        for r in rows:
            t = r.get("team")
            if t not in teams:
                problems.append(f"{name}: unknown team {t!r} (2026 roster codes only)")
            if t in seen:
                problems.append(f"{name}: duplicate team {t}")
            seen.add(t)
            if not r.get("source_url"):
                problems.append(f"{name}/{t}: missing source_url")
            if r.get("confidence") not in CONFIDENCE:
                problems.append(f"{name}/{t}: confidence {r.get('confidence')!r} not in {sorted(CONFIDENCE)}")
            if not r.get("last_checked"):
                problems.append(f"{name}/{t}: missing last_checked")
        if name == "qb_situations":
            for r in rows:
                if r.get("status") not in QB_STATUS:
                    problems.append(f"qb_situations/{r.get('team')}: status {r.get('status')!r} not in {sorted(QB_STATUS)}")
        if name == "ol_changes":
            for r in rows:
                d = r.get("delta")
                if not isinstance(d, int) or not -2 <= d <= 2:
                    problems.append(f"ol_changes/{r.get('team')}: delta {d!r} outside -2..+2")
    return problems


def _prov(seed: str, r: dict) -> dict:
    return {"source_url": r.get("source_url"), "source_url_2": r.get("source_url_2"),
            "confidence": r.get("confidence"), "last_checked": str(r.get("last_checked"))}


def build_rows() -> list[dict]:
    coach, h1 = _load("coaching_changes")
    qb, h2 = _load("qb_situations")
    ol, h3 = _load("ol_changes")
    hashes = {"coaching_changes": h1, "qb_situations": h2, "ol_changes": h3}
    by_team: dict[str, dict] = {}
    for r in coach:
        t = r["team"]
        by_team[t] = {
            "team": t, "hc": r.get("hc"), "hc_new": bool(r.get("hc_new")), "hc_since": r.get("hc_since"),
            "oc": r.get("oc"), "oc_new": bool(r.get("oc_new")), "dc": r.get("dc"), "dc_new": bool(r.get("dc_new")),
            "play_caller": r.get("play_caller"), "play_caller_role": r.get("play_caller_role"),
            "play_caller_2025": r.get("play_caller_2025"), "play_caller_new": bool(r.get("play_caller_new")),
            "sources": {"coaching_changes": _prov("coaching_changes", r)},
            "notes": {"coaching_changes": r.get("notes")}, "seed_hashes": hashes,
        }
    for r in qb:
        t = r["team"]
        row = by_team.setdefault(t, {"team": t, "sources": {}, "notes": {}, "seed_hashes": hashes})
        row.update({
            "projected_qb1": r.get("projected_qb1"), "qb1_2025": r.get("qb1_2025"),
            "qb_changed_from_2025": bool(r.get("changed_from_2025")), "qb_status": r.get("status"),
            "qb_quality_tier": r.get("qb_quality_tier"), "qb_backup": r.get("backup"),
        })
        row["sources"]["qb_situations"] = _prov("qb_situations", r)
        row["notes"]["qb_situations"] = r.get("notes")
    for r in ol:
        t = r["team"]
        row = by_team.setdefault(t, {"team": t, "sources": {}, "notes": {}, "seed_hashes": hashes})
        row.update({
            "ol_delta": r.get("delta"), "ol_rank_2026": r.get("ol_rank_2026"), "ol_adds": r.get("adds"),
            "ol_losses": r.get("losses"), "ol_injuries": r.get("injuries"), "ol_r1_pick": r.get("r1_pick"),
        })
        row["sources"]["ol_changes"] = _prov("ol_changes", r)
        row["notes"]["ol_changes"] = r.get("notes")
    today = datetime.now(UTC).date()
    for row in by_team.values():
        checked = [v.get("last_checked") for v in row["sources"].values() if v.get("last_checked")]
        oldest = min(checked) if checked else None
        row["last_checked"] = date.fromisoformat(oldest) if oldest else None
        stale = row["last_checked"] and (today - row["last_checked"]).days > 7
        low = any(v.get("confidence") == "low" for v in row["sources"].values())
        row["warning"] = "; ".join(filter(None, [
            "curated rows older than 7 days — re-check before the draft" if stale else None,
            "contains low-confidence rows" if low else None,
        ])) or None
    return list(by_team.values())


def load() -> int:
    rows = build_rows()
    cols = ["team", "hc", "hc_new", "hc_since", "oc", "oc_new", "dc", "dc_new", "play_caller", "play_caller_role",
            "play_caller_2025", "play_caller_new", "projected_qb1", "qb1_2025", "qb_changed_from_2025", "qb_status",
            "qb_quality_tier", "qb_backup", "ol_delta", "ol_rank_2026", "ol_adds", "ol_losses", "ol_injuries",
            "ol_r1_pick", "sources", "notes", "last_checked", "seed_hashes", "warning"]
    json_cols = {"ol_adds", "ol_losses", "ol_injuries", "sources", "notes", "seed_hashes"}
    import json as _json

    payload = []
    for r in rows:
        rec = {c: r.get(c) for c in cols}
        for c in json_cols:
            rec[c] = _json.dumps(rec[c]) if rec[c] is not None else None
        payload.append(rec)
    placeholders = ", ".join(f"cast(:{c} as jsonb)" if c in json_cols else f":{c}" for c in cols)
    with session_scope() as s:
        s.execute(text("delete from team_context"))
        s.execute(text(f"insert into team_context ({', '.join(cols)}) values ({placeholders})"), payload)
    return len(payload)


@cli.command("load")
def load_cmd(force: bool = typer.Option(False, help="Load even when validation reports problems")) -> None:
    """Validate the curated seeds and load them into team_context."""
    problems = validate()
    for p in problems:
        typer.secho(f"  {p}", fg=typer.colors.RED)
    if problems and not force:
        typer.secho(f"{len(problems)} problem(s) — nothing loaded (use --force to override)", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    n = load()
    with engine.connect() as c:
        flags = c.execute(text(
            "select count(*) filter (where hc_new), count(*) filter (where play_caller_new), "
            "count(*) filter (where qb_status <> 'settled'), count(*) filter (where ol_delta <> 0), "
            "count(*) filter (where warning is not null) from team_context"
        )).one()
    typer.echo({"teams": n, "new_hc": flags[0], "new_play_caller": flags[1], "qb_unsettled": flags[2],
                "ol_delta_nonzero": flags[3], "with_warning": flags[4]})


@cli.command("check")
def check() -> None:
    """Phase 5 gate: 32 teams, every row sourced, enums valid."""
    problems = validate()
    if problems:
        for p in problems:
            typer.secho(f"  {p}", fg=typer.colors.RED)
        typer.echo("GATE FAILED")
        raise typer.Exit(code=1)
    typer.echo({"seeds": list(SEEDS), "rows_each": 32, "all_sourced": True})
    typer.echo("GATE PASSED")


@cli.command("review")
def review() -> None:
    """The one-table review Derek reads before the draft (docs/phases/05-team-context.md)."""
    df = pl.read_database(
        "select team, hc, hc_new, play_caller, play_caller_new, projected_qb1, qb_status, ol_delta, ol_rank_2026, "
        "warning from team_context order by team", connection=engine)
    pl.Config.set_tbl_rows(40)
    pl.Config.set_tbl_width_chars(200)
    typer.echo(df)


if __name__ == "__main__":
    cli()
