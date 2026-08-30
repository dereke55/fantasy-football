"""Player endpoints: the board list and the per-player profile the WHY drawer reads."""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text

from app.db import engine

router = APIRouter(prefix="/api", tags=["players"])

def _q(sql: str, **params: Any) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), params).mappings()]


def _table_exists(name: str) -> bool:
    with engine.connect() as c:
        return bool(c.execute(text("select to_regclass(:n) is not null"), {"n": name}).scalar())


@router.get("/players")
def list_players(
    position: str | None = None,
    team: str | None = None,
    q: str | None = Query(None, description="name substring"),
    limit: int = Query(200, le=1000),
) -> dict:
    """Hub players with their headline features, ordered by market consensus."""
    where, params = ["p.position in ('QB','RB','WR','TE','K','DEF')"], {"limit": limit}
    if position:
        where.append("p.position = :position")
        params["position"] = position.upper()
    if team:
        where.append("p.team = :team")
        params["team"] = team.upper()
    if q:
        where.append("p.name_norm like :q")
        params["q"] = f"%{q.lower()}%"
    feat = ", f.ppg_2025, f.e_games, f.injury_prone, f.depth_rank, f.td_diff_2025" if _table_exists("player_features") else ""
    join = " left join player_features f on f.player_id = p.id" if feat else ""
    rows = _q(
        f"select p.id, p.name, p.position, p.team, p.is_rookie{feat}, "
        "r.rank as ecr_rank from players p"
        f"{join} left join rank_snapshots r on r.player_id = p.id and r.source = 'fantasypros_mirror' "
        f"where {' and '.join(where)} order by r.rank nulls last, p.name limit :limit",
        **params,
    )
    return {"count": len(rows), "players": rows}


@router.get("/players/{player_id}/profile")
def player_profile(player_id: int) -> dict:
    """Everything the WHY drawer shows: identity, per-season history, summary features and team context."""
    player = _q("select * from players where id = :id", id=player_id)
    if not player:
        raise HTTPException(status_code=404, detail=f"player {player_id} not found")
    player = player[0]

    seasons: list[dict] = []
    summary: dict = {}
    if _table_exists("player_season_features"):
        seasons = _q(
            "select * from player_season_features where player_id = :id order by season", id=player_id)
    if _table_exists("player_features"):
        got = _q("select * from player_features where player_id = :id", id=player_id)
        summary = got[0] if got else {}

    market = _q(
        "select source, format, kind, rank, adp, std, min_pick, max_pick, as_of "
        "from rank_snapshots where player_id = :id order by source", id=player_id)

    why = _q(
        "select rule_id, text, kind, polarity, priority, inputs, seasons, source_url, template_version "
        "from why_bullets where player_id = :id and run_id = "
        "(select run_id from ranking_runs where status='ok' order by is_frozen desc, started_at desc limit 1) "
        "order by priority", id=player_id)
    ranking = _q(
        "select * from rankings where player_id = :id and run_id = "
        "(select run_id from ranking_runs where status='ok' order by is_frozen desc, started_at desc limit 1)",
        id=player_id)

    context: dict = {}
    if player.get("team") and _table_exists("team_context"):
        got = _q("select * from team_context where team = :t", t=player["team"])
        context = got[0] if got else {}

    return {
        "player": player,
        "seasons": seasons,
        "summary": summary,
        "why": why,
        "ranking": ranking[0] if ranking else {},
        "market": market,
        "team_context": context,
        "provenance": {
            "scoring": "all points recomputed from raw stat lines under config/league.yaml",
            "team_context_sources": context.get("sources"),
            "team_context_warning": context.get("warning"),
        },
    }


@router.get("/teams/{team}/context")
def team_context(team: str) -> dict:
    if not _table_exists("team_context"):
        raise HTTPException(status_code=503, detail="team_context not loaded — run `ff context load`")
    rows = _q("select * from team_context where team = :t", t=team.upper())
    if not rows:
        raise HTTPException(status_code=404, detail=f"team {team} not found")
    return rows[0]


@router.get("/teams/context")
def all_team_context() -> dict:
    if not _table_exists("team_context"):
        raise HTTPException(status_code=503, detail="team_context not loaded — run `ff context load`")
    return {"teams": _q("select * from team_context order by team")}
