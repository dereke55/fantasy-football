"""Board API tests against the real database and the live ranking run (read-only except the pick round-trip)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.scoring.config import load_league_config

client = TestClient(app)


@pytest.fixture(scope="module")
def cfg():
    return load_league_config()


@pytest.fixture(scope="module")
def board() -> dict:
    r = client.get("/api/rankings", params={"limit": 600})
    assert r.status_code == 200
    return r.json()


def test_run_exposes_provenance_and_league_shape(cfg):
    r = client.get("/api/run").json()
    assert r["run_id"] and r["model_version"]
    assert r["config_hash_matches"] is True, "the pinned run was built from a different league.yaml"
    assert r["scoring_source"] == "yahoo_settings_page"
    assert r["league"]["teams"] == cfg.league.num_teams and r["league"]["rounds"] == cfg.roster.rounds
    assert r["attribution"], "licensing attribution is required by the README sources table"


def test_board_has_every_spec_column(board):
    p = board["players"][0]
    for col in ("rank", "pos_rank", "tier", "value_tier", "pos", "team", "bye", "proj_ppg", "proj_season",
                "value", "ecr", "adp_yahoo_site", "room_adp", "gap", "p_avail", "flags", "drafted", "name"):
        assert col in p, f"missing board column {col}"
    assert board["count"] >= 400, "the Phase 7 gate renders 400 rows from one payload"
    assert p["rank"] == 1


def test_no_vendor_points_are_exposed(board):
    forbidden = {"pts_ppr", "pts_half_ppr", "fantasy_points", "fantasy_points_ppr", "appliedTotal"}
    assert not forbidden & set(board["players"][0])


def test_keeper_counts_against_my_roster_and_open_slots(cfg):
    st = client.get("/api/state").json()
    keepers = client.get("/api/keepers").json()["keepers"]
    mine = [k for k in keepers if k["team_slot"] == cfg.league.my_draft_slot]
    if not mine:
        pytest.skip("no keeper recorded for my slot")
    kept_pos = mine[0]["position"]
    assert any(p["is_keeper"] for p in st["my_roster"]), "keepers must pre-populate my roster"
    assert st["open_slots"].get(kept_pos, 0) == max(0, cfg.roster.slots.get(kept_pos, 0) - 1)
    # the keeper consumes a pick, so the live draft is one pick shorter
    assert st["total_picks"] == cfg.league.num_teams * cfg.roster.rounds - len(keepers)


def test_my_next_pick_matches_the_snake_for_my_slot(cfg):
    st = client.get("/api/state").json()
    if cfg.league.my_draft_slot is None:
        pytest.skip("no draft slot set")
    # Derive from where the draft actually is rather than assuming an untouched board: asserting live_pick == 10
    # made this test a tripwire for any earlier test that left a pick behind, which is not what it is checking.
    made = st["picks_made"]
    assert st["my_next_pick"]["live_pick"] > made
    assert st["picks_until_mine"] == st["my_next_pick"]["live_pick"] - made - 1
    if made == 0:
        assert st["my_next_pick"]["live_pick"] == cfg.league.my_draft_slot


def test_availability_weights_by_open_slots():
    a = client.get("/api/availability").json()
    assert a["my_next_pick"]
    st = client.get("/api/state").json()
    for pos, blk in a["positions"].items():
        assert 0.0 < blk["slot_weight"] <= 1.0
        starts = blk["open_slots"] > 0 or (pos in st["flex_eligible"] and st["flex_open"] > 0)
        assert (blk["slot_weight"] == 1.0) == starts, pos
        for c in blk["candidates"]:
            assert 0.0 <= c["p_avail"] <= 1.0
            assert c["vona"] == pytest.approx(
                blk["slot_weight"] * (c["value_now"] - c["expected_value_at_next"]), abs=0.15)


def test_pick_undo_round_trip(board):
    """A manual pick marks the player drafted and undo restores the board exactly."""
    target = next(p for p in board["players"] if not p["drafted"] and p["pos"] == "WR")
    before = client.get("/api/state").json()["picks_made"]
    r = client.post("/api/draft/picks", json={"player_id": target["player_id"]})
    assert r.status_code == 200
    assert r.json()["state"]["picks_made"] == before + 1
    dup = client.post("/api/draft/picks", json={"player_id": target["player_id"]})
    assert dup.status_code == 409, "a drafted player cannot be drafted twice"
    rows = client.get("/api/rankings", params={"limit": 600}).json()["players"]
    assert next(p for p in rows if p["player_id"] == target["player_id"])["drafted"] is True
    u = client.post("/api/draft/undo")
    assert u.status_code == 200 and u.json()["state"]["picks_made"] == before
    rows = client.get("/api/rankings", params={"limit": 600}).json()["players"]
    assert next(p for p in rows if p["player_id"] == target["player_id"])["drafted"] is False


def test_keeper_validation_rejects_duplicates(cfg):
    keepers = client.get("/api/keepers").json()["keepers"]
    if not keepers:
        pytest.skip("no keeper recorded")
    k = keepers[0]
    dup = client.post("/api/keepers", json={"player_id": k["player_id"], "team_slot": k["team_slot"],
                                            "cost_round": k["cost_round"]})
    assert dup.status_code == 409
    bad = client.post("/api/keepers", json={"player_id": k["player_id"], "team_slot": 99, "cost_round": 1})
    assert bad.status_code == 422


def test_profile_carries_why_bullets_and_ranking(board):
    top = board["players"][0]
    p = client.get(f"/api/players/{top['player_id']}/profile").json()
    assert len(p["why"]) >= 3
    assert p["ranking"]["overall_rank"] == 1
    assert all(b["rule_id"] and b["text"] for b in p["why"])


def test_csv_export_header_matches_the_spec():
    r = client.get("/api/export/board.csv", params={"limit": 5})
    assert r.status_code == 200 and "text/csv" in r.headers["content-type"]
    header = r.text.splitlines()[0].split(",")
    for col in ("rank", "name", "pos", "team", "bye", "value", "ecr", "room_adp", "gap", "p_avail", "flags",
                "player_id", "yahoo_id", "run_id"):
        assert col in header


def test_kept_players_are_valued_not_buried(board, cfg):
    """A keeper is excluded from the draftable POOL but must still be VALUED against the same baselines.

    Regression: kept players got a null VORP and sorted last, which put Derek's own keeper at rank 631 of 631
    despite a healthy projection.
    """
    keepers = client.get("/api/keepers").json()["keepers"]
    if not keepers:
        pytest.skip("no keeper recorded")
    kept_ids = {k["player_id"] for k in keepers}
    rows = {p["player_id"]: p for p in board["players"]}
    for pid in kept_ids:
        assert pid in rows, "a kept player must still appear on the board"
        r = rows[pid]
        assert r["value"] is not None and r["value"] > 0, f"{r['name']} has no value"
        assert r["rank"] < len(board["players"]) // 2, f"{r['name']} is buried at rank {r['rank']}"
    assert not [p for p in board["players"] if p["value"] is None and not p["is_kdst"]]


def test_kept_players_are_off_the_board_server_side(board):
    """"Available" has one definition, on the server — a client should not have to join /api/keepers."""
    keepers = client.get("/api/keepers").json()["keepers"]
    if not keepers:
        pytest.skip("no keeper recorded")
    rows = {p["player_id"]: p for p in board["players"]}
    for k in keepers:
        r = rows[k["player_id"]]
        assert r["drafted"] is True and r["is_keeper"] is True
        assert r["drafted_by"] == k["team_slot"] and r["keeper_cost_round"] == k["cost_round"]


def test_keeper_edit_recomputes_room_adp_and_availability(board):
    """Phase 7 gate: keeper edits recompute best-available and P(avail) without a reload.

    Keepers move the VBD baselines, the pick schedule and room ADP, so a stale board would quietly describe the
    previous keeper set.
    """
    # Room ADP is a re-rank of the remaining pool, so removing a player only shifts those BEHIND him in ADP
    # order. Probe someone with a worse ADP than the player being kept.
    avail = [p for p in board["players"] if not p["drafted"] and p["composite_adp"]]
    target = next(p for p in avail if p["pos"] == "RB" and 40 < p["composite_adp"] < 80)
    probe = next(p for p in avail if p["composite_adp"] > target["composite_adp"] + 20)
    probe_name = probe["name"]
    before = probe
    # the league caps keepers per team, and most teams already have one — find a team that is free
    cfg = load_league_config()
    taken = {k["team_slot"] for k in client.get("/api/keepers").json()["keepers"]}
    free_slot = next((s for s in range(1, cfg.league.num_teams + 1) if s not in taken), None)
    if free_slot is None:
        pytest.skip("every team already has its maximum keepers")
    add = client.post("/api/keepers",
                      json={"player_id": target["player_id"], "team_slot": free_slot, "cost_round": 7})
    assert add.status_code == 200 and add.json()["run_id"], "a keeper edit must produce a new ranking run"
    try:
        after_rows = client.get("/api/rankings", params={"limit": 700}).json()["players"]
        after = next(p for p in after_rows if p["name"] == probe_name)
        assert after["room_adp"] != before["room_adp"], "room ADP must re-rank around the removed player"
        assert next(p for p in after_rows if p["player_id"] == target["player_id"])["drafted"] is True
    finally:
        kid = next(k["id"] for k in client.get("/api/keepers").json()["keepers"]
                   if k["team_slot"] == free_slot and k["player_id"] == target["player_id"])
        rm = client.delete(f"/api/keepers/{kid}")
        assert rm.status_code == 200
    restored = next(p for p in client.get("/api/rankings", params={"limit": 700}).json()["players"]
                    if p["name"] == probe_name)
    assert restored["room_adp"] == before["room_adp"], "removing the keeper must restore the board exactly"


def test_why_bullets_never_render_python_none():
    """A rookie with no draft team rendered "pick #3 overall (None)"."""
    bullets = client.get("/api/players/1/profile")
    rows = client.get("/api/rankings", params={"limit": 200}).json()["players"]
    seen = 0
    for p in rows[:80]:
        prof = client.get(f"/api/players/{p['player_id']}/profile").json()
        for b in prof["why"]:
            assert "None" not in b["text"], f"{p['name']}: {b['text']}"
            seen += 1
    assert seen > 100 and bullets.status_code in (200, 404)


def test_availability_never_offers_a_kept_or_drafted_player():
    """You cannot draft someone who is already off the board — the VONA panel listed a keeper as a candidate."""
    keepers = client.get("/api/keepers").json()["keepers"]
    kept = {k["player_id"] for k in keepers}
    drafted = {p["player_id"] for p in client.get("/api/rankings", params={"limit": 700}).json()["players"]
               if p["drafted"]}
    a = client.get("/api/availability").json()
    offered = {c["player_id"] for blk in a["positions"].values() for c in blk["candidates"]}
    assert not offered & kept, "a kept player was offered as a draft candidate"
    assert not offered & drafted


def _fill_board(client_, n: int, mine: set[str]) -> int:
    board = client_.get("/api/rankings", params={"limit": 700}).json()["players"]
    pool = sorted([p for p in board if not p["drafted"] and p["composite_adp"]], key=lambda p: p["composite_adp"])
    taken = 0
    for p in pool:
        if taken >= n:
            break
        body = {"player_id": p["player_id"]}
        if p["name"] in mine:
            body.update({"my_pick": True, "team_slot": 10})
        if client_.post("/api/draft/picks", json=body).status_code == 200:
            taken += 1
    return taken


def _undo_all(client_) -> None:
    while client_.post("/api/draft/undo").status_code == 200:
        pass


def test_roster_need_outranks_raw_value(cfg):
    """The board must not recommend a player it cannot start.

    In a 1-QB league the highest-scoring player left is often a quarterback, and a fourth running back often has
    more raw value than a second startable receiver. VONA weights each position by what the NEXT player there is
    actually worth to the roster, so neither wins once the slot is filled.
    """
    try:
        _fill_board(client, 95, {"Josh Allen", "CeeDee Lamb", "Saquon Barkley", "Breece Hall", "Nico Collins"})
        st = client.get("/api/state").json()
        assert any(p["position"] == "QB" for p in st["my_roster"]), "setup: a QB should be rostered"
        assert st["open_slots"]["QB"] == 0

        av = client.get("/api/availability").json()["positions"]
        qb = av["QB"]
        assert qb["slot_weight"] <= 0.2, "a backup QB cannot start in a 1-QB lineup"
        assert "cannot start" in qb["slot_reason"]

        best = {pos: b["candidates"][0] for pos, b in av.items() if b["candidates"]}
        # the QB is still the loudest raw number for his position, but must not be the top recommendation
        top_by_vona = max(best.items(), key=lambda kv: kv[1]["vona"])[0]
        assert top_by_vona != "QB", f"recommended a backup QB ({best['QB']['name']})"
        # and a deeper-bench position must not beat a shallower one on raw value alone
        deeper_rb = ("RB" in best and "WR" in best
                     and av["RB"]["slot_weight"] < av["WR"]["slot_weight"]
                     and best["RB"]["value_now"] > best["WR"]["value_now"])
        if deeper_rb:
            assert best["RB"]["vona"] < best["WR"]["vona"], (
                "a deep-bench RB with higher raw value should still rank below a startable WR")
    finally:
        _undo_all(client)


def test_flex_counts_as_a_starting_slot():
    """FLEX was skipped entirely, so a third RB looked like a bench body when he can actually start."""
    try:
        _fill_board(client, 30, {"Saquon Barkley", "Breece Hall"})
        st = client.get("/api/state").json()
        assert "flex_open" in st and "bench_by_pos" in st
        av = client.get("/api/availability").json()["positions"]
        if st["flex_open"] > 0:
            for pos in st["flex_eligible"]:
                if pos in av and st["open_slots"].get(pos, 0) == 0:
                    assert av[pos]["slot_weight"] == 1.0, f"{pos} can fill the open FLEX"
                    assert "FLEX" in av[pos]["slot_reason"]
    finally:
        _undo_all(client)


def test_slot_weights_are_ordered_and_explainable():
    av = client.get("/api/availability").json()["positions"]
    for pos, b in av.items():
        assert 0.0 < b["slot_weight"] <= 1.0
        assert b["slot_reason"], f"{pos} weight must be explainable on screen"


def test_p_avail_and_vona_track_the_live_draft():
    """The two decision columns must describe where the draft IS, not where it started.

    Both were computed once, at freeze time, for my first pick against a pre-draft room ADP. By round 5 the
    board reported P(avail) = 100% for a running back whose real chance of surviving was 4%, and VONA -45.0 for
    the most valuable pick on the board -- on a sortable column, and in the panel used on every pick.
    """
    try:
        board = client.get("/api/rankings", params={"limit": 700}).json()
        before = {p["player_id"]: p for p in board["players"]}
        start_horizon = board["p_avail_horizon"]
        _fill_board(client, 40, set())
        after = client.get("/api/rankings", params={"limit": 700}).json()
        assert after["p_avail_horizon"]["live_pick"] > start_horizon["live_pick"], "the horizon must advance"

        rows = {p["player_id"]: p for p in after["players"]}
        avail = [p for p in after["players"] if not p["drafted"] and p["value"] is not None]
        assert avail, "setup: players should remain"
        moved = [p for p in avail if p["p_avail"] != before[p["player_id"]]["p_avail"]]
        assert moved, "P(avail) did not respond to 40 picks coming off the board"

        for p in after["players"]:
            if p["drafted"]:
                assert p["p_avail"] is None and p["vona"] is None, "a drafted player has nothing to wait for"
            elif p["p_avail"] is not None:
                assert 0.0 <= p["p_avail"] <= 1.0

        # the board and the VONA panel must not disagree about the same player
        panel = client.get("/api/availability").json()
        for pos, blk in panel["positions"].items():
            for c in blk["candidates"]:
                row = rows.get(c["player_id"])
                if row is None or row["is_kdst"]:
                    continue
                assert c["p_avail"] == pytest.approx(row["p_avail"], abs=0.02), f"{c['name']} P(avail)"
                assert c["vona"] == pytest.approx(row["vona"], abs=0.2), f"{c['name']} VONA in {pos}"
    finally:
        _undo_all(client)


def test_kdst_appear_in_the_panel_only_once_they_are_worth_a_pick():
    """Spec 12: K/DST carry no VBD, so they are ranked by ADP and hidden until the K/DST rounds."""
    early = client.get("/api/availability").json()["positions"]
    assert "K" not in early and "DEF" not in early, "a kicker in round 1 is a wasted pick"
    try:
        # drive the draft to the round where kickers become real
        while True:
            st = client.get("/api/state").json()
            nxt = st["my_next_pick"]
            if nxt is None or nxt["round"] >= 12:
                break
            if not _fill_board(client, 10, set()):
                break
        late = client.get("/api/availability").json()["positions"]
        if client.get("/api/state").json()["my_next_pick"]:
            assert "K" in late or "DEF" in late, "K/DST must be offered once the draft reaches them"
            for pos in ("K", "DEF"):
                if pos in late:
                    adps = [c["player_id"] for c in late[pos]["candidates"]]
                    assert adps, f"{pos} block should not be empty"
    finally:
        _undo_all(client)


def test_racing_submissions_lose_cleanly_rather_than_500():
    """Two picks in flight both read the same picks_made and aim at the same slot.

    The partial unique index keeps the board correct -- exactly one wins -- but the loser surfaced as a bare 500,
    which on a double-tapped Enter in QuickPick leaves you unable to tell whether your pick landed.
    """
    import threading

    board = client.get("/api/rankings", params={"limit": 60}).json()["players"]
    ids = [p["player_id"] for p in board if not p["drafted"]][:4]
    assert len(ids) == 4, "setup: need undrafted players"
    results: list[int] = []

    def go(pid: int) -> None:
        results.append(client.post("/api/draft/picks", json={"player_id": pid}).status_code)

    try:
        threads = [threading.Thread(target=go, args=(i,)) for i in ids]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert 500 not in results, f"a losing racer returned 500: {results}"
        assert all(c in (200, 409) for c in results), results
        assert 200 in results, "at least one submission must win"
        # whatever happened, the board must not have double-booked a slot
        dupes = _q_dupes()
        assert not dupes, f"two active picks share an overall_pick: {dupes}"
    finally:
        _undo_all(client)


def _q_dupes() -> list:
    from sqlalchemy import text

    from app.db import session_scope

    with session_scope() as s:
        return [dict(r) for r in s.execute(text(
            "select overall_pick, count(*) n from draft_picks where undone_at is null "
            "group by overall_pick having count(*) > 1")).mappings()]


def test_reset_clears_the_draft_but_never_the_keepers():
    """Practice runs need a way back to an untouched board without pressing undo N times.

    Keepers are what cut the holes in the pick schedule and move the VBD baselines the board was frozen with, so
    a reset that took them with it would silently change the model, not just the picks.
    """
    keepers_before = client.get("/api/keepers").json()["keepers"]
    sched_before = client.get("/api/schedule").json()
    run_before = client.get("/api/run").json()["run_id"]
    try:
        made = _fill_board(client, 12, {"Josh Allen"})
        assert made > 0, "setup: some picks should be recorded"
        assert client.get("/api/state").json()["picks_made"] == made

        bare = client.post("/api/draft/reset", json={})
        assert bare.status_code == 409, "a reset without confirm must be refused"
        assert client.get("/api/state").json()["picks_made"] == made, "the refused reset must change nothing"

        r = client.post("/api/draft/reset", json={"confirm": True})
        assert r.status_code == 200
        assert r.json()["cleared"] == made
        st = r.json()["state"]
        assert st["picks_made"] == 0
        # the keeper is a roster slot, not a pick: it survives
        assert [p["name"] for p in st["my_roster"]] == [
            p["name"] for p in client.get("/api/state").json()["my_roster"]]
        assert all(p["is_keeper"] for p in st["my_roster"]), "only keepers should remain on my roster"
    finally:
        client.post("/api/draft/reset", json={"confirm": True})

    assert client.get("/api/keepers").json()["keepers"] == keepers_before, "keepers must be untouched"
    assert client.get("/api/schedule").json() == sched_before, "the pick schedule must be unchanged"
    assert client.get("/api/run").json()["run_id"] == run_before, "a reset must not re-rank or re-freeze"


def test_reset_soft_deletes_so_a_practice_run_stays_auditable():
    from sqlalchemy import text

    from app.db import session_scope

    try:
        made = _fill_board(client, 3, set())
        with session_scope() as s:
            before = s.execute(text("select count(*) from draft_picks")).scalar_one()
        client.post("/api/draft/reset", json={"confirm": True})
        with session_scope() as s:
            after = s.execute(text("select count(*) from draft_picks")).scalar_one()
            active = s.execute(text("select count(*) from draft_picks where undone_at is null")).scalar_one()
        assert after == before, f"reset deleted {before - after} rows — it must soft-delete like undo"
        assert active == 0
        assert made == 3
    finally:
        client.post("/api/draft/reset", json={"confirm": True})
