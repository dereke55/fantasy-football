"""Players hub builder: one row per fantasy-relevant player with every external id we can resolve.

Universe: 2026 nflverse roster (QB/RB/WR/TE/K) ∪ FantasyPros ECR top-400 ∪ Yahoo public pool ∪ Sleeper projections,
plus 32 team defenses (DEF). Resolution order for each external source: direct id -> normalized name+team+position
-> normalized name+position (if unique) -> seeds/id_overrides.yaml. Never deletes rows (draft tables reference players.id).
"""
from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

import polars as pl
import typer
import yaml
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db import engine, session_scope
from app.models.players import Player

cli = typer.Typer(no_args_is_help=True, help="Players hub (identity crosswalk)")

FANTASY_POS = {"QB", "RB", "WR", "TE", "K"}
POS_MAP = {"FB": "RB", "HB": "RB", "PK": "K", "DST": "DEF", "D/ST": "DEF"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv", "v"}

YAHOO_TEAM_MAP = {  # Yahoo editorial_team_abbr -> nflverse
    "Ari": "ARI", "Atl": "ATL", "Bal": "BAL", "Buf": "BUF", "Car": "CAR", "Chi": "CHI", "Cin": "CIN", "Cle": "CLE",
    "Dal": "DAL", "Den": "DEN", "Det": "DET", "GB": "GB", "Hou": "HOU", "Ind": "IND", "Jax": "JAX", "KC": "KC",
    "LAR": "LA", "LAC": "LAC", "LV": "LV", "Mia": "MIA", "Min": "MIN", "NE": "NE", "NO": "NO", "NYG": "NYG",
    "NYJ": "NYJ", "Phi": "PHI", "Pit": "PIT", "Sea": "SEA", "SF": "SF", "TB": "TB", "Ten": "TEN", "Was": "WAS",
}
TEAM_FIX = {"LAR": "LA", "JAC": "JAX", "WSH": "WAS", "OAK": "LV", "SD": "LAC", "STL": "LA"}


def norm_name(name: str | None) -> str:
    """Lowercase, strip accents/punctuation/suffixes: "Eddy Piñeiro" -> "eddy pineiro"."""
    if not name:
        return ""
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower().replace(".", "").replace("'", "").replace("’", "")
    s = re.sub(r"[-_/]", " ", s)
    s = re.sub(r"[^a-z0-9 ]", "", s)
    parts = [p for p in s.split() if p not in SUFFIXES]
    return " ".join(parts)


def norm_team(t: str | None) -> str | None:
    if not t:
        return None
    t = t.strip()
    return YAHOO_TEAM_MAP.get(t) or TEAM_FIX.get(t.upper()) or t.upper()


def norm_pos(p: str | None) -> str | None:
    if not p:
        return None
    p = p.upper().split(",")[0].strip()
    return POS_MAP.get(p, p)


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


class Hub:
    """In-memory hub keyed by a stable `key` (gsis_id, or 'DEF:<team>', or 'name:<norm>|<pos>' for id-less players)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}
        self.by_name_pos: dict[tuple[str, str], list[str]] = defaultdict(list)
        self.by_name_team_pos: dict[tuple[str, str, str], str] = {}
        self.by_id: dict[tuple[str, str], str] = {}   # (field, value) -> key

    def add(self, key: str, **fields) -> dict:
        row = self.rows.get(key)
        if row is None:
            row = {"key": key, "match_sources": {}}
            self.rows[key] = row
        for k, v in fields.items():
            if v is not None and v != "" and (row.get(k) is None or row.get(k) == ""):
                row[k] = v
        self._index(key, row)
        return row

    def _index(self, key: str, row: dict) -> None:
        nn, pos, team = row.get("name_norm"), row.get("position"), row.get("team")
        if nn and pos:
            if key not in self.by_name_pos[(nn, pos)]:
                self.by_name_pos[(nn, pos)].append(key)
            if team:
                self.by_name_team_pos.setdefault((nn, team, pos), key)
        for f in ("gsis_id", "esb_id", "sleeper_id", "espn_id", "yahoo_id", "fantasypros_id", "pfr_id", "stats_id", "yahoo_player_key"):
            v = row.get(f)
            if v:
                self.by_id.setdefault((f, str(v)), key)

    def find(self, *, ids: dict[str, str | None], name: str | None, team: str | None, pos: str | None) -> tuple[str | None, str]:
        for f, v in ids.items():
            if v and (f, str(v)) in self.by_id:
                return self.by_id[(f, str(v))], f"id:{f}"
        nn = norm_name(name)
        if nn and pos:
            k = self.by_name_team_pos.get((nn, team or "", pos))
            if k:
                return k, "name+team+pos"
            cands = self.by_name_pos.get((nn, pos), [])
            if len(cands) == 1:
                return cands[0], "name+pos"
            if len(cands) > 1 and team:
                for c in cands:
                    if self.rows[c].get("team") == team:
                        return c, "name+pos(team)"
        return None, "unmatched"


def _s(v) -> str | None:
    if v is None:
        return None
    if isinstance(v, float):
        if math.isnan(v):
            return None
        v = int(v)
    s = str(v).strip()
    return s or None


def build_hub(report_dir: Path) -> dict:
    hub = Hub()
    # 1. 2026 roster (canonical team-of-record)
    ros = _q(
        "select gsis_id, esb_id, espn_id, yahoo_id, sleeper_id, pfr_id, full_name, first_name, last_name, position, team, status, "
        "birth_date, years_exp, entry_year, rookie_year, draft_club, draft_number, college from raw_nflverse_rosters where season=2026"
    )
    for r in ros.iter_rows(named=True):
        pos = norm_pos(r["position"])
        if pos not in FANTASY_POS or not r["gsis_id"]:
            continue
        row = hub.add(
            r["gsis_id"], gsis_id=r["gsis_id"], esb_id=_s(r["esb_id"]), espn_id=_s(r["espn_id"]), yahoo_id=_s(r["yahoo_id"]),
            sleeper_id=_s(r["sleeper_id"]), pfr_id=_s(r["pfr_id"]), name=r["full_name"], name_norm=norm_name(r["full_name"]),
            first_name=r["first_name"], last_name=r["last_name"], position=pos, team=norm_team(r["team"]), status=r["status"],
            birth_date=r["birth_date"], years_exp=r["years_exp"], draft_pick=r["draft_number"], draft_team=norm_team(r["draft_club"]),
            college=r["college"], is_rookie=(r["entry_year"] == 2026),
        )
        row["match_sources"]["nflverse_roster_2026"] = "gsis_id"

    # 2. nflverse players master (draft capital, otc_id) for hub rows
    pm = _q("select gsis_id, otc_id, draft_year, draft_round, draft_pick, draft_team, rookie_season from raw_nflverse_players where gsis_id is not null")
    pm_by = {r["gsis_id"]: r for r in pm.iter_rows(named=True)}

    # 3. ff_playerids crosswalk (also brings in players not on a 2026 roster, e.g. unsigned veterans)
    ff = _q(
        "select gsis_id, fantasypros_id, sleeper_id, espn_id, yahoo_id, stats_id, pfr_id, name, position, team, birthdate, "
        "draft_year, draft_round, draft_ovr from raw_nflverse_ff_playerids"
    )
    ff_by_gsis = {r["gsis_id"]: r for r in ff.iter_rows(named=True) if r["gsis_id"]}
    ff_by_fp = {_s(r["fantasypros_id"]): r for r in ff.iter_rows(named=True) if _s(r["fantasypros_id"])}
    ff_by_yahoo: dict[str, dict] = {}
    ff_by_sleeper: dict[str, dict] = {}
    for r in ff.iter_rows(named=True):
        for v in (_s(r["yahoo_id"]), _s(r["stats_id"])):
            if v:
                ff_by_yahoo.setdefault(v, r)
        if _s(r["sleeper_id"]):
            ff_by_sleeper.setdefault(_s(r["sleeper_id"]), r)

    def add_from_ff(f: dict, *, name: str, pos: str, team: str | None) -> str:
        """Add a player known to ff_playerids but absent from the hub (e.g. unsigned/just-signed veteran)."""
        key = f["gsis_id"] or f"name:{norm_name(f['name'] or name)}|{pos}"
        hub.add(key, gsis_id=f["gsis_id"], name=f["name"] or name, name_norm=norm_name(f["name"] or name), position=pos,
                team=team or norm_team(f["team"]), draft_year=f["draft_year"], draft_round=f["draft_round"], draft_pick=f["draft_ovr"])
        enrich(key, f)
        return key

    def enrich(key: str, r: dict) -> None:
        row = hub.rows[key]
        hub.add(
            key, fantasypros_id=_s(r.get("fantasypros_id")), sleeper_id=_s(r.get("sleeper_id")), espn_id=_s(r.get("espn_id")),
            yahoo_id=_s(r.get("yahoo_id")) or _s(r.get("stats_id")), stats_id=_s(r.get("stats_id")), pfr_id=_s(r.get("pfr_id")),
        )
        row["match_sources"]["ff_playerids"] = "gsis_id"

    for key in list(hub.rows):
        if key in ff_by_gsis:
            enrich(key, ff_by_gsis[key])
        if key in pm_by:
            p = pm_by[key]
            hub.add(key, otc_id=_s(p["otc_id"]), draft_year=p["draft_year"], draft_round=p["draft_round"],
                    draft_pick=p["draft_pick"], draft_team=norm_team(p["draft_team"]))

    # 4. FantasyPros ECR top-400 (redraft overall): add any missing player via ff_playerids
    ecr = _q(
        "select id, player, pos, team, ecr, yahoo_id from raw_nflverse_ff_rankings_draft "
        "where page_type='redraft-overall' and ecr_type='ro' order by ecr limit 400"
    )
    for r in ecr.iter_rows(named=True):
        pos = norm_pos(r["pos"])
        fpid = _s(r["id"])
        key, how = hub.find(ids={"fantasypros_id": fpid}, name=r["player"], team=norm_team(r["team"]), pos=pos)
        if key is None and pos == "DEF":
            key = f"DEF:{norm_team(r['team'])}"
            hub.add(key, name=r["player"], name_norm=norm_name(r["player"]), position="DEF", team=norm_team(r["team"]))
            how = "def:team"
        if key is None and fpid in ff_by_fp:
            f = ff_by_fp[fpid]
            key = f["gsis_id"] or f"name:{norm_name(f['name'])}|{pos}"
            hub.add(key, gsis_id=f["gsis_id"], name=f["name"], name_norm=norm_name(f["name"]), position=pos, team=norm_team(f["team"]),
                    draft_year=f["draft_year"], draft_round=f["draft_round"], draft_pick=f["draft_ovr"])
            enrich(key, f)
            how = "ff_playerids:new"
        if key is None:
            key = f"name:{norm_name(r['player'])}|{pos}"
            hub.add(key, name=r["player"], name_norm=norm_name(r["player"]), position=pos, team=norm_team(r["team"]))
            how = "ecr:new-unlinked"
        hub.add(key, fantasypros_id=fpid, yahoo_id=_s(r["yahoo_id"]))
        hub.rows[key]["match_sources"]["fantasypros_ecr"] = how

    # 5. Yahoo public pool
    yh = _q(
        "select player_key, player_id, name_full, editorial_team_abbr, team_abbr_nflverse, display_position, primary_position, "
        "average_pick from raw_yahoo_players"
    )
    y_unmatched = []
    for r in yh.iter_rows(named=True):
        pos = norm_pos(r["primary_position"] or r["display_position"])
        team = norm_team(r["team_abbr_nflverse"] or r["editorial_team_abbr"])
        pid = _s(r["player_id"])
        if pos == "DEF":
            key = f"DEF:{team}"
            hub.add(key, name=r["name_full"], name_norm=norm_name(r["name_full"]), position="DEF", team=team)
            how = "def:team"
        elif pos not in FANTASY_POS:
            continue  # IDP etc. — not draftable in this league
        else:
            key, how = hub.find(ids={"yahoo_id": pid}, name=r["name_full"], team=team, pos=pos)
        if key is None and pid in ff_by_yahoo:
            key, how = add_from_ff(ff_by_yahoo[pid], name=r["name_full"], pos=pos, team=team), "ff_playerids:yahoo_id"
        if key is None:
            # real player in the Yahoo pool with no nflverse identity yet (typically a fringe/rookie K or just-signed vet)
            key = f"name:{norm_name(r['name_full'])}|{pos}"
            hub.add(key, name=r["name_full"], name_norm=norm_name(r["name_full"]), position=pos, team=team)
            how = "yahoo:new-unlinked"
            y_unmatched.append({"source": "yahoo", "name": r["name_full"], "team": team, "pos": pos, "ext_id": pid, "adp": r["average_pick"]})
        hub.add(key, yahoo_id=pid, yahoo_player_key=r["player_key"])
        hub.rows[key]["match_sources"]["yahoo_pub"] = how

    # 6. Sleeper projections (+ players master for injury ids)
    sl = _q(
        "select p.player_id, p.first_name, p.last_name, p.position, coalesce(p.player_team_abbr, p.team) as team, p.adp_half_ppr, "
        "m.gsis_id, m.yahoo_id, m.espn_id, m.stats_id from raw_sleeper_projections p left join raw_sleeper_players m using (player_id) "
        "where p.has_projection"
    )
    s_unmatched = []
    for r in sl.iter_rows(named=True):
        pos = norm_pos(r["position"])
        team = norm_team(r["team"])
        name = f"{r['first_name'] or ''} {r['last_name'] or ''}".strip()
        if pos == "DEF":
            key = f"DEF:{norm_team(r['player_id'])}"
            hub.add(key, name=name or r["player_id"], name_norm=norm_name(name or r["player_id"]), position="DEF", team=norm_team(r["player_id"]))
            how = "def:team"
        elif pos not in FANTASY_POS:
            continue
        else:
            key, how = hub.find(ids={"sleeper_id": r["player_id"], "gsis_id": _s(r["gsis_id"]), "yahoo_id": _s(r["yahoo_id"])},
                                name=name, team=team, pos=pos)
        if key is None and _s(r["player_id"]) in ff_by_sleeper:
            key, how = add_from_ff(ff_by_sleeper[_s(r["player_id"])], name=name, pos=pos, team=team), "ff_playerids:sleeper_id"
        if key is None:
            key = f"name:{norm_name(name)}|{pos}"
            hub.add(key, name=name, name_norm=norm_name(name), position=pos, team=team)
            how = "sleeper:new-unlinked"
            s_unmatched.append({"source": "sleeper", "name": name, "team": team, "pos": pos, "ext_id": r["player_id"], "adp": r["adp_half_ppr"]})
        hub.add(key, sleeper_id=_s(r["player_id"]), gsis_id=_s(r["gsis_id"]) if key.startswith("name:") else None,
                yahoo_id=_s(r["yahoo_id"]) or _s(r["stats_id"]), espn_id=_s(r["espn_id"]), stats_id=_s(r["stats_id"]))
        hub.rows[key]["match_sources"]["sleeper"] = how

    # 7. DEF names for any DEF rows lacking one
    try:
        teams = _q("select team_abbr, team_name from raw_nflverse_teams")
        tn = {r["team_abbr"]: r["team_name"] for r in teams.iter_rows(named=True)}
    except Exception:  # noqa: BLE001 - optional reference table
        tn = {}
    for key, row in hub.rows.items():
        if key.startswith("DEF:") and not row.get("name"):
            t = key[4:]
            row["name"] = tn.get(t, t)
            row["name_norm"] = norm_name(row["name"])

    # 8. manual overrides
    ov_path = settings.seeds_dir / "id_overrides.yaml"
    if ov_path.exists():
        for o in (yaml.safe_load(ov_path.read_text()) or {}).get("rows", []) or []:
            m = o.get("match", {})
            key, how = hub.find(ids={}, name=m.get("name"), team=norm_team(m.get("team")), pos=norm_pos(m.get("position")))
            if key:
                for k, v in (o.get("set") or {}).items():
                    hub.rows[key][k] = str(v)
                hub.rows[key]["match_sources"]["override"] = o.get("note", "manual")

    # report unmatched (top-N per source) for check-ids
    report_dir.mkdir(parents=True, exist_ok=True)
    unmatched = sorted(y_unmatched + s_unmatched, key=lambda r: (r["source"], r["adp"] if r["adp"] is not None else 9999))
    with open(report_dir / "unmatched.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["source", "name", "team", "pos", "ext_id", "adp"])
        w.writeheader()
        w.writerows(unmatched)
    return {"hub_rows": len(hub.rows), "yahoo_unmatched": len(y_unmatched), "sleeper_unmatched": len(s_unmatched), "rows": hub.rows}


def upsert_players(session: Session, rows: dict[str, dict]) -> dict:
    existing = {p.gsis_id: p for p in session.execute(select(Player).where(Player.gsis_id.is_not(None))).scalars()}
    existing_def = {(p.position, p.team): p for p in session.execute(select(Player).where(Player.position == "DEF")).scalars()}
    existing_name = {(p.name_norm, p.position): p for p in session.execute(select(Player).where(Player.gsis_id.is_(None), Player.position != "DEF")).scalars()}
    fields = ("gsis_id", "esb_id", "sleeper_id", "espn_id", "yahoo_id", "fantasypros_id", "pfr_id", "otc_id", "stats_id", "yahoo_player_key",
              "name", "name_norm", "first_name", "last_name", "position", "team", "status", "birth_date", "years_exp", "draft_year",
              "draft_round", "draft_pick", "draft_team", "is_rookie", "college", "match_sources")
    inserted = updated = 0
    for r in rows.values():
        if not r.get("name") or not r.get("position"):
            continue
        p = None
        if r.get("gsis_id"):
            p = existing.get(r["gsis_id"])
        elif r["position"] == "DEF":
            p = existing_def.get(("DEF", r.get("team")))
        else:
            p = existing_name.get((r["name_norm"], r["position"]))
        vals = {f: r.get(f) for f in fields}
        vals["is_rookie"] = bool(vals.get("is_rookie"))
        vals["match_sources"] = vals.get("match_sources") or {}
        for f in ("years_exp", "draft_year", "draft_round", "draft_pick"):
            if vals.get(f) is not None:
                try:
                    vals[f] = int(vals[f])
                except (TypeError, ValueError):
                    vals[f] = None
        if p is None:
            session.add(Player(**vals))
            inserted += 1
        else:
            for f, v in vals.items():
                if v is not None and v != "" and v != {}:
                    setattr(p, f, v)
            updated += 1
    session.flush()
    return {"inserted": inserted, "updated": updated}


@cli.command("build")
def build() -> None:
    """Build/refresh the players hub from raw_* tables (idempotent upsert; never deletes)."""
    report_dir = settings.data_dir / "reports"
    res = build_hub(report_dir)
    with session_scope() as s:
        up = upsert_players(s, res["rows"])
    typer.echo({"hub_rows": res["hub_rows"], **up, "yahoo_unmatched": res["yahoo_unmatched"], "sleeper_unmatched": res["sleeper_unmatched"],
                "unmatched_csv": str(report_dir / "unmatched.csv"), "built_at": datetime.now(UTC).isoformat()})


@cli.command("check-ids")
def check_ids(max_unmatched_pct: float = 3.0) -> None:
    """Phase 1a gate: top-300 ECR, top-300 Sleeper, top-400 Yahoo and 2026 R1-R4 skill picks resolve to players; unmatched < 3%."""
    checks = {
        "ecr_top300": (
            "select count(*) as n, count(p.id) as ok from (select id from raw_nflverse_ff_rankings_draft where page_type='redraft-overall' "
            "and ecr_type='ro' and pos<>'DST' order by ecr limit 300) e left join players p on p.fantasypros_id = e.id::text"
        ),
        "yahoo_top400": (
            "select count(*) as n, count(p.id) as ok from (select player_key from raw_yahoo_players where display_position in ('QB','RB','WR','TE','K') "
            "order by average_pick nulls last, page_start, page_index limit 400) y left join players p on p.yahoo_player_key = y.player_key"
        ),
        "sleeper_top300": (
            "select count(*) as n, count(p.id) as ok from (select player_id from raw_sleeper_projections where has_projection and position<>'DEF' "
            "and adp_half_ppr is not null order by adp_half_ppr limit 300) s left join players p on p.sleeper_id = s.player_id"
        ),
    }
    out, worst = {}, 0.0
    with engine.connect() as c:
        for name, sql in checks.items():
            n, ok = c.execute(text(sql)).one()
            pct = 100.0 * (n - ok) / n if n else 0.0
            worst = max(worst, pct)
            out[name] = {"n": n, "resolved": ok, "unmatched_pct": round(pct, 2)}
        picks = c.execute(text(
            "select gsis_id as esb, pfr_player_name, position from raw_nflverse_draft_picks where season=2026 and round<=4 "
            "and position in ('QB','RB','WR','TE')"
        )).all()
        by_esb = {e for (e,) in c.execute(text("select esb_id from players where esb_id is not null"))}
        by_name = {(nn, pos) for nn, pos in c.execute(text("select name_norm, position from players"))}
        ok = sum(1 for esb, nm, pos in picks if (esb and esb in by_esb) or (norm_name(nm), norm_pos(pos)) in by_name)
        pct = 100.0 * (len(picks) - ok) / len(picks) if picks else 0.0
        worst = max(worst, pct)
        out["draft2026_r1_r4_skill"] = {"n": len(picks), "resolved": ok, "unmatched_pct": round(pct, 2)}
        out["players_total"] = c.execute(text("select count(*) from players")).scalar_one()
    typer.echo(out)
    if worst > max_unmatched_pct:
        typer.echo(f"GATE FAILED: worst unmatched {worst:.2f}% > {max_unmatched_pct}% — see data/reports/unmatched.csv")
        raise typer.Exit(code=1)
    typer.echo("GATE PASSED")


if __name__ == "__main__":
    cli()
