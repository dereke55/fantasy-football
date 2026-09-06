"""Draft-board API: the pinned run, the board rows, draft state, availability, keepers and CSV export.

Everything the board shows comes from one pinned `ranking_runs` row, so the numbers on screen are reproducible
and never recomputed in the browser. Manual pick entry is first-class: every mutation works the same whether the
draft is being synced from Yahoo or driven by hand.
"""
from __future__ import annotations

import io
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.db import engine, session_scope
from app.ranking.pick_schedule import KeeperSpec, build_pick_schedule, next_live_pick, on_the_clock
from app.scoring.config import league_config_sha256, load_league_config

router = APIRouter(prefix="/api", tags=["board"])


def _q(sql: str, **p: Any) -> list[dict]:
    with engine.connect() as c:
        return [dict(r) for r in c.execute(text(sql), p).mappings()]


def _one(sql: str, **p: Any) -> dict | None:
    rows = _q(sql, **p)
    return rows[0] if rows else None


def current_run() -> dict:
    """The frozen run if there is one, else the most recent successful run."""
    run = _one("select * from ranking_runs where is_frozen and status='ok' order by started_at desc limit 1") \
        or _one("select * from ranking_runs where status='ok' order by started_at desc limit 1")
    if not run:
        raise HTTPException(status_code=503, detail="no ranking run yet — run `uv run ff rank run`")
    return run


def _league_row() -> dict | None:
    return _one("select * from leagues order by id limit 1")


def _keeper_specs() -> list[KeeperSpec]:
    return [KeeperSpec(r["team_slot"], r["cost_round"], r["player_id"])
            for r in _q("select team_slot, cost_round, player_id from keepers order by team_slot, cost_round")]


# --------------------------------------------------------------------------- run / rankings

@router.get("/run")
def get_run() -> dict:
    run = current_run()
    cfg = load_league_config()
    live_hash = league_config_sha256()
    return {
        "run_id": str(run["run_id"]),
        "generated_at": run["started_at"].isoformat() if run["started_at"] else None,
        "is_frozen": run["is_frozen"],
        "model_version": run["model_version"],
        "spearman_top150": run["spearman_top150"],
        "n_players_ranked": run["n_players_ranked"],
        "league_config_sha256": run["league_config_sha256"],
        "config_hash_matches": run["league_config_sha256"] == live_hash,
        "scoring_source": cfg.source,
        "weights": run["weights"],
        "managers": (_league_row() or {}).get("draft_order") or {},
        "league": {"teams": cfg.league.num_teams, "rounds": cfg.roster.rounds,
                   "my_slot": cfg.league.my_draft_slot, "draft_time": cfg.league.draft_datetime,
                   "slots": cfg.roster.slots, "flex_eligible": cfg.roster.flex_eligible,
                   "bench": cfg.roster.bench, "max_keepers": cfg.league.keepers.max_per_team,
                   "keeper_deadline": cfg.league.keepers.deadline},
        "attribution": ["Data from nflverse (CC-BY-4.0)", "ADP data from fantasyfootballcalculator.com",
                        "Fantasy data provided by Yahoo Fantasy", "FantasyPros consensus — personal use only"],
    }


@router.get("/rankings")
def get_rankings(limit: int = Query(600, le=1000)) -> dict:
    """The whole board in one payload; the client filters and sorts without a round trip."""
    run = current_run()
    rows = _q(
        """
        select k.player_id, p.name, p.yahoo_id, k.position as pos, k.team,
               k.overall_rank as rank, k.pos_rank, k.tier, k.value_tier,
               k.ppg_blend as proj_ppg, k.season_value as proj_season, k.e_games,
               k.vorp as value, k.vols, k.ecr, k.ecr_sd, k.yahoo_adp as adp_yahoo_site,
               k.ffc_adp, k.sleeper_adp, k.composite_adp, k.room_adp, k.sd_adp, k.gap, k.gap_z,
               k.p_avail_next as p_avail, k.vona, k.flags, k.signals, k.is_kdst, k.is_keeper,
               b.bye_week as bye,
               f.depth_rank, f.injury_prone, f.structural_injury_return, f.current_injury_status,
               f.td_diff_2025, f.ppg_2025, f.age_2026, f.years_exp, f.is_rookie,
               d.team_slot as drafted_by, d.id as pick_id,
               ke.team_slot as kept_by, ke.cost_round as keeper_cost_round
        from rankings k
        join players p on p.id = k.player_id
        left join raw_nflverse_team_bye b on b.team = k.team and b.season = 2026
        left join player_features f on f.player_id = k.player_id
        left join draft_picks d on d.player_id = k.player_id and d.undone_at is null
        left join keepers ke on ke.player_id = k.player_id
        where k.run_id = :run
        order by k.overall_rank
        limit :limit
        """, run=run["run_id"], limit=limit)
    cfg = load_league_config()
    my_slot = cfg.league.my_draft_slot
    # P(avail) is the one board column that goes stale the moment the draft starts. The stored `p_avail_next`
    # was computed once, for my FIRST pick, against a pre-draft room ADP; by round 5 it was reporting 100% for
    # players with a 4% chance and it is a sortable column. Recompute it against where the draft actually is.
    st = _state()
    before_pick, horizon = _decision_horizon(st)
    live_room = _live_room_adp(run["run_id"], st["picks_made"]) if before_pick is not None else {}
    for r in rows:
        # A kept player is off the board exactly like a drafted one — that is what "kept" means. Reporting it
        # here rather than making every client join /api/keepers keeps one definition of "available".
        r["drafted"] = r["drafted_by"] is not None or r["kept_by"] is not None
        owner = r["drafted_by"] if r["drafted_by"] is not None else r["kept_by"]
        r["drafted_by"] = owner
        r["is_mine"] = owner == my_slot if owner is not None else False
        r["live_room_adp"] = live_room.get(r["player_id"])
        r["p_avail"] = (None if r["drafted"] or before_pick is None
                        else _p_avail_at(r["live_room_adp"], r["sd_adp"], before_pick, st["picks_made"]))
        r["tags"] = [t for t in (
            "injury_prone" if r.pop("injury_prone", None) else None,
            "structural_injury_return" if r.pop("structural_injury_return", None) else None,
        ) if t]
    _apply_live_vona(rows, st, cfg, before_pick, live_room)
    return {"run_id": str(run["run_id"]), "count": len(rows), "players": rows,
            "p_avail_horizon": horizon}


def _apply_live_vona(rows: list[dict], st: dict, cfg, before_pick: int | None,
                     live_room: dict[int, float]) -> None:
    """Overwrite the stored VONA with one computed for where the draft is and what my roster already holds.

    The stored column is frozen at "my first pick, empty roster", which by round 5 had the best available running
    back at -45.0 while he was in fact the most valuable pick on the board. DraftPanel renders this for the
    selected player and for best-available, so it has to track the live state.
    """
    from app.ranking.availability import Candidate, expected_best_excluding

    if before_pick is None:
        for r in rows:
            r["vona"] = None
        return
    made = st["picks_made"]
    by_pos: dict[str, list[Candidate]] = {}
    for r in rows:
        if r["drafted"] or r["value"] is None or r["is_kdst"]:
            continue
        by_pos.setdefault(r["pos"], []).append(
            Candidate(r["player_id"], r["pos"], max(0.0, r["value"]),
                      live_room.get(r["player_id"]), r["sd_adp"] or 10.0))
    exp = {pos: (expected_best_excluding(cs, before_pick) if before_pick > made else {})
           for pos, cs in by_pos.items()}
    weights = {pos: _slot_weight(pos, st, cfg)[0] for pos in by_pos}
    for r in rows:
        e = exp.get(r["pos"], {}).get(r["player_id"])
        if r["drafted"] or r["value"] is None or r["is_kdst"] or r["pos"] not in weights:
            r["vona"] = None
        else:
            r["vona"] = round(weights[r["pos"]] * (max(0.0, r["value"]) - (e or 0.0)), 2)


# --------------------------------------------------------------------------- draft state

def _picks() -> list[dict]:
    return _q("select d.*, p.name, p.position, p.team from draft_picks d left join players p on p.id = d.player_id "
              "where d.undone_at is null order by d.overall_pick")


def _state() -> dict:
    cfg = load_league_config()
    specs = _keeper_specs()
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds, specs)
    picks = [p for p in _picks() if not p["is_keeper"]]
    made = len(picks)
    otc = on_the_clock(sched, made)
    my_slot = cfg.league.my_draft_slot
    nxt, until = next_live_pick(sched, my_slot, made) if my_slot else (None, None)

    # A keeper already occupies a roster slot before the draft starts, so it must count toward my roster and
    # against my open slots — otherwise the board would keep recommending the position I have already filled.
    my_players = []
    if my_slot:
        my_players = _q(
            "select p.id, p.name, p.position, p.team, b.bye_week as bye, true as is_keeper, k.cost_round "
            "from keepers k join players p on p.id = k.player_id "
            "left join raw_nflverse_team_bye b on b.team = p.team and b.season = 2026 "
            "where k.team_slot = :s order by k.cost_round", s=my_slot)
        my_players += _q(
            "select p.id, p.name, p.position, p.team, b.bye_week as bye, false as is_keeper, "
            "d.round as cost_round from draft_picks d join players p on p.id = d.player_id "
            "left join raw_nflverse_team_bye b on b.team = p.team and b.season = 2026 "
            "where d.undone_at is null and d.team_slot = :s order by d.overall_pick", s=my_slot)
    byes: dict[int, list[str]] = {}
    for pl in my_players:
        if pl["bye"]:
            byes.setdefault(pl["bye"], []).append(pl["name"])
    warnings = [{"bye_week": w, "players": names} for w, names in sorted(byes.items()) if len(names) >= 3]

    filled: dict[str, int] = {}
    for pl in my_players:
        filled[pl["position"]] = filled.get(pl["position"], 0) + 1
    open_slots = {}
    for pos, n in cfg.roster.slots.items():
        if pos == "FLEX":
            continue
        open_slots[pos] = max(0, n - filled.get(pos, 0))
    # FLEX was previously skipped, which quietly told the model a third running back was a bench body when he can
    # actually start. Surplus at any flex-eligible position competes for the FLEX slots.
    flex_total = cfg.roster.slots.get("FLEX", 0) * 1
    surplus = sum(max(0, filled.get(p, 0) - cfg.roster.slots.get(p, 0)) for p in cfg.roster.flex_eligible)
    flex_open = max(0, flex_total - surplus)
    return {
        "mode": "manual",
        "picks_made": made,
        "total_picks": sum(1 for s in sched if s.live_pick_no is not None),
        "on_the_clock": None if not otc else {"round": otc.round, "overall_pick": otc.overall_pick,
                                              "live_pick": otc.live_pick_no, "team_slot": otc.team_slot,
                                              "is_mine": otc.team_slot == my_slot},
        "my_slot": my_slot,
        "my_next_pick": None if not nxt else {"round": nxt.round, "live_pick": nxt.live_pick_no,
                                              "overall_pick": nxt.overall_pick},
        "picks_until_mine": until,
        "my_roster": my_players,
        "open_slots": open_slots,
        "flex_open": flex_open,
        "flex_eligible": cfg.roster.flex_eligible,
        "bench_by_pos": {p: max(0, filled.get(p, 0) - cfg.roster.slots.get(p, 0)) for p in filled},
        "bye_stack_warnings": warnings,
        "recent_picks": picks[-8:],
    }


@router.get("/state")
def get_state() -> dict:
    return _state()


@router.get("/schedule")
def get_schedule() -> dict:
    cfg = load_league_config()
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds, _keeper_specs())
    return {"picks": [{"overall_pick": s.overall_pick, "round": s.round, "team_slot": s.team_slot,
                       "is_keeper_slot": s.is_keeper_slot, "live_pick_no": s.live_pick_no} for s in sched],
            "my_slot": cfg.league.my_draft_slot}


class PickIn(BaseModel):
    player_id: int
    my_pick: bool = False
    team_slot: int | None = None


@router.post("/draft/picks")
def make_pick(body: PickIn) -> dict:
    cfg = load_league_config()
    league = _league_row()
    if not league:
        raise HTTPException(status_code=503, detail="no league row — run `uv run ff league init`")
    if _one("select id from draft_picks where player_id = :p and undone_at is null", p=body.player_id):
        raise HTTPException(status_code=409, detail="player already drafted")
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds, _keeper_specs())
    made = len([p for p in _picks() if not p["is_keeper"]])
    slot_row = on_the_clock(sched, made)
    if slot_row is None:
        raise HTTPException(status_code=409, detail="draft is complete")
    team_slot = body.team_slot or (cfg.league.my_draft_slot if body.my_pick else slot_row.team_slot)
    with session_scope() as s:
        s.execute(text(
            "insert into draft_picks (league_id, overall_pick, round, team_slot, player_id, is_keeper, source) "
            "values (:l, :o, :r, :t, :p, false, 'manual')"),
            {"l": league["id"], "o": slot_row.overall_pick, "r": slot_row.round, "t": team_slot,
             "p": body.player_id})
    return {"ok": True, "state": _state()}


@router.post("/draft/undo")
def undo_pick() -> dict:
    last = _one("select id, source from draft_picks where undone_at is null order by overall_pick desc limit 1")
    if not last:
        raise HTTPException(status_code=409, detail="nothing to undo")
    if last["source"] != "manual":
        raise HTTPException(status_code=409, detail="last pick came from Yahoo; it will be re-synced")
    with session_scope() as s:
        s.execute(text("update draft_picks set undone_at = now() where id = :i"), {"i": last["id"]})
    return {"ok": True, "state": _state()}


# --------------------------------------------------------------------------- live availability inputs

def _live_room_adp(run_id, made: int) -> dict[int, float]:
    """Expected live pick number for each still-available player, counted from where the draft actually is.

    The stored `room_adp` is a PRE-DRAFT quantity: it re-ranks the pool with keepers removed and knows nothing
    about who has since come off the board. Comparing it against an advancing pick number is what made the board
    report P(avail) = 100% for a player whose real chance of surviving was 4%. Re-ranking what is left and
    offsetting by the picks already made says the room keeps taking the best available in ADP order from here.
    """
    rows = _q("""select k.player_id, k.composite_adp from rankings k
                 left join draft_picks d on d.player_id = k.player_id and d.undone_at is null
                 left join keepers ke on ke.player_id = k.player_id
                 where k.run_id = :run and d.id is null and ke.id is null and k.composite_adp is not null""",
              run=run_id)
    rows.sort(key=lambda r: r["composite_adp"])
    return {r["player_id"]: float(made + i) for i, r in enumerate(rows, start=1)}


def _decision_horizon(st: dict) -> tuple[int | None, dict | None]:
    """The pick the board should reason about, and the last pick that happens before it.

    "Will he be there at my next pick?" is only a useful question while that pick is still ahead of me. On the
    clock my next pick is this one, every available player survives to it trivially, and the decision I am
    actually making is what I can still get at the pick AFTER this one -- so the horizon steps forward when
    picks_until_mine is 0.
    """
    cfg = load_league_config()
    my_slot = cfg.league.my_draft_slot
    if not my_slot:
        return None, None
    sched = build_pick_schedule(cfg.league.num_teams, cfg.roster.rounds, _keeper_specs())
    made = st["picks_made"]
    mine = [s for s in sched
            if s.team_slot == my_slot and s.live_pick_no is not None and s.live_pick_no > made]
    if not mine:
        return None, None
    target = mine[1] if st.get("picks_until_mine") == 0 and len(mine) > 1 else mine[0]
    return target.live_pick_no - 1, {"round": target.round, "live_pick": target.live_pick_no,
                                     "overall_pick": target.overall_pick}


def _p_avail_at(room: float | None, sd: float | None, before_pick: int, made: int) -> float | None:
    """P(a player survives every pick between now and my horizon pick). No intervening picks -> certainty."""
    from app.ranking.availability import p_available

    if room is None:
        return None
    if before_pick <= made:
        return 1.0
    return round(p_available(room, sd or 10.0, before_pick), 3)


# --------------------------------------------------------------------------- availability / VONA

# What the NEXT player at a position is actually worth to the roster. A binary "open slot or half" was too crude
# in both directions: it treated a third running back (who can start at FLEX) the same as a backup quarterback
# (who in a 1-QB league can never start), and it ignored the FLEX slot entirely.
BENCH_FIRST = 0.35        # first bench body at a flex-eligible position: injury and bye cover that can start
BENCH_DECAY = 0.55        # each additional one is worth less than the last
BENCH_FLOOR = 0.10
QB_BACKUP = 0.15          # a second QB can only ever cover a bye or an injury at one slot
KDST_BACKUP = 0.03        # kickers and defences are streamed, never stockpiled
KDST_FROM_ROUND = 12      # docs/spec/ranking-model.md §12: a kicker before this is a wasted pick


def _slot_weight(pos: str, st: dict, cfg) -> tuple[float, str]:
    if st["open_slots"].get(pos, 0) > 0:
        return 1.0, "fills a starting slot"
    if pos in cfg.roster.flex_eligible and st.get("flex_open", 0) > 0:
        return 1.0, "fills the FLEX"
    if pos in ("K", "DEF", "DST"):
        return KDST_BACKUP, "already rostered — streamed weekly"
    if pos == "QB":
        return QB_BACKUP, "backup QB — cannot start in a 1-QB lineup"
    depth = st.get("bench_by_pos", {}).get(pos, 0)
    w = max(BENCH_FLOOR, BENCH_FIRST * (BENCH_DECAY ** max(0, depth - 1)))
    return round(w, 3), f"bench depth {depth} — can cover injuries and byes"


@router.get("/availability")
def get_availability(top: int = 3) -> dict:
    """VONA top-N per position at my next pick, weighted by which of my slots are still open."""
    from app.ranking.availability import Candidate, expected_best_value

    run = current_run()
    cfg = load_league_config()
    st = _state()
    before_pick, horizon = _decision_horizon(st)
    if not horizon or before_pick is None:
        return {"my_next_pick": None, "positions": {}}
    made = st["picks_made"]
    live_room = _live_room_adp(run["run_id"], made)
    rows = _q("""select k.player_id, p.name, k.position, k.team, k.vorp, k.composite_adp, k.sd_adp, k.is_kdst
                 from rankings k join players p on p.id = k.player_id
                 left join draft_picks d on d.player_id = k.player_id and d.undone_at is null
                 left join keepers ke on ke.player_id = k.player_id
                 -- a kept player cannot be drafted, so he is not a candidate (same rule as /api/rankings)
                 where k.run_id = :run and d.id is null and ke.id is null
                   and (k.vorp is not null or k.is_kdst)
                   and (not k.is_kdst or :kdst)""",
              run=run["run_id"], kdst=horizon["round"] >= KDST_FROM_ROUND)
    by_pos: dict[str, list] = {}
    for r in rows:
        by_pos.setdefault(r["position"], []).append(r)
    out: dict[str, Any] = {}
    for pos, rs in by_pos.items():
        cands = [Candidate(r["player_id"], pos, max(0.0, r["vorp"] or 0.0),
                           live_room.get(r["player_id"]), r["sd_adp"] or 10.0)
                 for r in rs]
        weight, reason = _slot_weight(pos, st, cfg)
        # K and DST are deliberately given no VBD, so sorting them by it would return an arbitrary three.
        # Consensus ADP is the only ordering that means anything for them (spec §12).
        kdst = rs[0]["is_kdst"]
        ranked = (sorted(rs, key=lambda r: (r["composite_adp"] is None, r["composite_adp"]))[:top] if kdst
                  else sorted(rs, key=lambda r: -(r["vorp"] or 0))[:top])
        items = []
        for r in ranked:
            others = [c for c in cands if c.player_id != r["player_id"]]
            exp = 0.0 if kdst or before_pick <= made else expected_best_value(others, before_pick)
            # Clamp at replacement, exactly as the candidate pool does. A negative VORP means "worse than a
            # freely available replacement", and the gain from drafting him is 0, not negative -- leaving it
            # signed here subtracted a clamped expectation from an unclamped value and disagreed with the board.
            value_now = round(max(0.0, r["vorp"] or 0.0), 1)
            items.append({
                "player_id": r["player_id"], "name": r["name"], "team": r["team"],
                "value_now": value_now,
                "expected_value_at_next": round(exp, 1),
                "vona": round(weight * (value_now - exp), 1),
                "p_avail": _p_avail_at(live_room.get(r["player_id"]), r["sd_adp"], before_pick, made),
            })
        out[pos] = {"slot_weight": weight, "slot_reason": reason,
                    "open_slots": st["open_slots"].get(pos, 0), "candidates": items}
    return {"my_next_pick": horizon, "positions": out}


def _recompute(reason: str) -> str | None:
    """Rebuild the board after a keeper change.

    Keepers move the VBD baselines, the pick schedule and room ADP, so without this every availability number on
    screen silently describes the previous keeper set. It reads only stored data (no network) and takes ~2 s.
    """
    import time

    from app.ranking.pipeline import build_board, save, spearman_vs_market

    cfg = load_league_config()
    t0 = time.time()
    board, meta = build_board(cfg)
    run_id = save(board, meta, cfg, duration=round(time.time() - t0, 2),
                  spearman=spearman_vs_market(board))
    # The freeze pins the INPUTS (snapshots + config hash) so the board is reproducible; it must not swallow a
    # keeper correction. current_run() prefers the frozen run, so a recompute that left the freeze behind would
    # build a new run nobody ever saw. This reads only stored data, so the inputs are identical to the frozen
    # run's -- only keeper state moved -- and the freeze moves with it. Exactly one run stays frozen.
    prev = _one("select run_id from ranking_runs where is_frozen and status='ok' order by started_at desc limit 1")
    with session_scope() as s:
        s.execute(text("update ranking_runs set note = :n where run_id = :r"),
                  {"n": f"auto-recompute: {reason}", "r": str(run_id)})
        if prev:
            s.execute(text("update ranking_runs set is_frozen = false where run_id = :p"),
                      {"p": str(prev["run_id"])})
            s.execute(text("update ranking_runs set is_frozen = true, note = coalesce(note,'') || :n "
                           "where run_id = :r"),
                      {"n": f" (carried the freeze forward from {str(prev['run_id'])[:8]})", "r": str(run_id)})
    return str(run_id)


# --------------------------------------------------------------------------- keepers

class KeeperIn(BaseModel):
    player_id: int
    team_slot: int
    cost_round: int
    status: str = "declared"


@router.get("/keepers")
def list_keepers() -> dict:
    return {"keepers": _q(
        "select k.id, k.team_slot, k.cost_round, k.status, k.source, p.id as player_id, p.name, p.position, p.team "
        "from keepers k join players p on p.id = k.player_id order by k.team_slot, k.cost_round")}


@router.post("/keepers")
def add_keeper(body: KeeperIn) -> dict:
    cfg = load_league_config()
    league = _league_row()
    if not league:
        raise HTTPException(status_code=503, detail="no league row — run `uv run ff league init`")
    if not 1 <= body.team_slot <= cfg.league.num_teams:
        raise HTTPException(status_code=422, detail=f"team_slot must be 1..{cfg.league.num_teams}")
    if not 1 <= body.cost_round <= cfg.roster.rounds:
        raise HTTPException(status_code=422, detail=f"cost_round must be 1..{cfg.roster.rounds}")
    if _one("select id from keepers where team_slot=:t and cost_round=:r", t=body.team_slot, r=body.cost_round):
        raise HTTPException(status_code=409, detail=f"team {body.team_slot} already has a keeper in round {body.cost_round}")
    if _one("select id from keepers where player_id = :p", p=body.player_id):
        raise HTTPException(status_code=409, detail="player is already kept")
    mx = cfg.league.keepers.max_per_team
    if mx is not None:
        n = len(_q("select id from keepers where team_slot = :t", t=body.team_slot))
        if n >= mx:
            raise HTTPException(status_code=409, detail=f"team {body.team_slot} already has {n} keeper(s); max is {mx}")
    with session_scope() as s:
        s.execute(text("insert into keepers (league_id, team_slot, player_id, cost_round, status, source) "
                       "values (:l, :t, :p, :r, :st, 'manual')"),
                  {"l": league["id"], "t": body.team_slot, "p": body.player_id, "r": body.cost_round,
                   "st": body.status})
    run_id = _recompute("keeper added")
    return {"ok": True, "keepers": list_keepers()["keepers"], "state": _state(), "run_id": run_id}


@router.delete("/keepers/{keeper_id}")
def delete_keeper(keeper_id: int) -> dict:
    with session_scope() as s:
        n = s.execute(text("delete from keepers where id = :i"), {"i": keeper_id}).rowcount
    if not n:
        raise HTTPException(status_code=404, detail="keeper not found")
    run_id = _recompute("keeper removed")
    return {"ok": True, "keepers": list_keepers()["keepers"], "state": _state(), "run_id": run_id}


# --------------------------------------------------------------------------- CSV

@router.get("/export/board.csv")
def export_csv(limit: int = Query(300, le=1000), position: str | None = None) -> StreamingResponse:
    import csv

    data = get_rankings(limit=1000)
    rows = data["players"]
    if position:
        rows = [r for r in rows if r["pos"] == position.upper()]
    rows = rows[:limit]
    cols = ["rank", "pos_rank", "name", "pos", "team", "bye", "tier", "value_tier", "proj_ppg", "proj_season",
            "value", "ecr", "adp_yahoo_site", "room_adp", "gap", "p_avail", "flags", "player_id", "yahoo_id"]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([*cols, "run_id"])
    for r in rows:
        w.writerow([("|".join(r[c]) if c == "flags" and r.get(c) else r.get(c)) for c in cols] + [data["run_id"]])
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv",
                             headers={"Content-Disposition": 'attachment; filename="draft_board.csv"'})
