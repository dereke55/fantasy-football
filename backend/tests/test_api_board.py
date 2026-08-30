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
    assert st["my_next_pick"]["live_pick"] == cfg.league.my_draft_slot
    assert st["picks_until_mine"] == cfg.league.my_draft_slot - 1


def test_availability_weights_by_open_slots():
    a = client.get("/api/availability").json()
    assert a["my_next_pick"]
    for pos, blk in a["positions"].items():
        assert blk["slot_weight"] in (0.5, 1.0)
        assert (blk["slot_weight"] == 1.0) == (blk["open_slots"] > 0), pos
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
    add = client.post("/api/keepers", json={"player_id": target["player_id"], "team_slot": 4, "cost_round": 7})
    assert add.status_code == 200 and add.json()["run_id"], "a keeper edit must produce a new ranking run"
    try:
        after_rows = client.get("/api/rankings", params={"limit": 700}).json()["players"]
        after = next(p for p in after_rows if p["name"] == probe_name)
        assert after["room_adp"] != before["room_adp"], "room ADP must re-rank around the removed player"
        assert next(p for p in after_rows if p["player_id"] == target["player_id"])["drafted"] is True
    finally:
        kid = next(k["id"] for k in client.get("/api/keepers").json()["keepers"] if k["team_slot"] == 4)
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
