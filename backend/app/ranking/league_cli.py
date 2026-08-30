"""`ff league …` — the league row, keepers and the pick schedule that draft day runs on."""
from __future__ import annotations

import polars as pl
import typer
from sqlalchemy import text

from app.db import engine, session_scope
from app.ingest.players_hub import norm_name
from app.ranking.pick_schedule import KeeperSpec, build_pick_schedule, my_picks, next_live_pick
from app.scoring.config import load_league_config

cli = typer.Typer(no_args_is_help=True, help="League, keepers and the pick schedule")


def _league_id(create: bool = True) -> int | None:
    cfg = load_league_config()
    with session_scope() as s:
        row = s.execute(text("select id from leagues where league_key = :k or (:k is null and league_key is null) "
                             "order by id limit 1"), {"k": cfg.league.league_key}).first()
        if row:
            return row[0]
        if not create:
            return None
        r = s.execute(text(
            "insert into leagues (platform, league_key, name, num_teams, rounds, draft_type, draft_time, "
            "draft_status, draft_order, my_team_slot) values (:p, :k, :n, :t, :r, :dt, :time, 'predraft', "
            "cast('{}' as jsonb), :slot) returning id"),
            {"p": cfg.league.platform, "k": cfg.league.league_key, "n": "shirtlesschugsonly",
             "t": cfg.league.num_teams, "r": cfg.roster.rounds, "dt": cfg.league.draft_type,
             "time": cfg.league.draft_datetime, "slot": cfg.league.my_draft_slot}).first()
        return r[0]


@cli.command("init")
def init() -> None:
    """Create or refresh the league row from config/league.yaml."""
    cfg = load_league_config()
    lid = _league_id()
    with session_scope() as s:
        s.execute(text("update leagues set num_teams=:t, rounds=:r, draft_time=:time, my_team_slot=:slot, "
                       "draft_type=:dt where id=:id"),
                  {"t": cfg.league.num_teams, "r": cfg.roster.rounds, "time": cfg.league.draft_datetime,
                   "slot": cfg.league.my_draft_slot, "dt": cfg.league.draft_type, "id": lid})
    typer.echo({"league_id": lid, "league_key": cfg.league.league_key, "teams": cfg.league.num_teams,
                "rounds": cfg.roster.rounds, "my_slot": cfg.league.my_draft_slot,
                "draft_time": cfg.league.draft_datetime})


@cli.command("keeper-set")
def keeper_set(name: str, cost_round: int, team_slot: int = typer.Option(None, help="defaults to your slot")) -> None:
    """Record a keeper: `ff league keeper-set 'Colston Loveland' 13`."""
    cfg = load_league_config()
    slot = team_slot or cfg.league.my_draft_slot
    if slot is None:
        typer.secho("no team slot: pass --team-slot or set league.my_draft_slot", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    hub = pl.read_database("select id, name, position, team from players", connection=engine)
    hit = hub.filter(pl.col("name").map_elements(norm_name, return_dtype=pl.Utf8) == norm_name(name))
    if hit.is_empty():
        typer.secho(f"no player matching {name!r}", fg=typer.colors.RED)
        raise typer.Exit(code=1)
    p = hit.to_dicts()[0]
    lid = _league_id()
    with session_scope() as s:
        s.execute(text("delete from keepers where league_id=:l and team_slot=:s and cost_round=:r"),
                  {"l": lid, "s": slot, "r": cost_round})
        s.execute(text("insert into keepers (league_id, team_slot, player_id, cost_round, status, source) "
                       "values (:l, :s, :p, :r, 'declared', 'manual')"),
                  {"l": lid, "s": slot, "p": p["id"], "r": cost_round})
    typer.echo({"kept": p["name"], "position": p["position"], "team": p["team"],
                "team_slot": slot, "cost_round": cost_round})


@cli.command("keepers")
def keepers() -> None:
    """List recorded keepers."""
    df = pl.read_database(
        "select k.team_slot, k.cost_round, p.name, p.position, p.team, k.status, k.source "
        "from keepers k join players p on p.id = k.player_id order by k.team_slot, k.cost_round",
        connection=engine)
    typer.echo(df if df.height else "no keepers recorded yet")


@cli.command("keeper-clear")
def keeper_clear(team_slot: int = typer.Option(None)) -> None:
    """Remove keepers (all, or just one team's)."""
    with session_scope() as s:
        if team_slot:
            n = s.execute(text("delete from keepers where team_slot=:s"), {"s": team_slot}).rowcount
        else:
            n = s.execute(text("delete from keepers")).rowcount
    typer.echo({"removed": n})


@cli.command("picks")
def picks() -> None:
    """Your actual picks, accounting for keeper holes."""
    cfg = load_league_config()
    slot = cfg.league.my_draft_slot
    if slot is None:
        typer.secho("set league.my_draft_slot in config/league.yaml first", fg=typer.colors.RED)
        raise typer.Exit(code=2)
    ks = pl.read_database(
        "select k.team_slot, k.cost_round, k.player_id, p.name from keepers k join players p on p.id=k.player_id",
        connection=engine)
    specs = [KeeperSpec(r["team_slot"], r["cost_round"], r["player_id"]) for r in ks.to_dicts()]
    kept_names = {(r["team_slot"], r["cost_round"]): r["name"] for r in ks.to_dicts()}
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds, specs)
    mine = [s for s in sched if s.team_slot == slot]
    rows = []
    for s_ in mine:
        gap = None
        if s_.live_pick_no is not None:
            _nxt, before = next_live_pick(sched, slot, s_.live_pick_no)
            gap = before
        rows.append({"round": s_.round, "overall": s_.overall_pick,
                     "live_pick": s_.live_pick_no if s_.live_pick_no else "— KEEPER —",
                     "keeper": kept_names.get((slot, s_.round), ""),
                     "picks_until_my_next": gap})
    typer.echo(pl.DataFrame(rows))
    typer.echo(f"\n{len(my_picks(sched, slot))} live picks from slot {slot} of {cfg.league.num_teams}; "
               f"{len(specs)} keeper(s) recorded across the league.")


if __name__ == "__main__":
    cli()
