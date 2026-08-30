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
