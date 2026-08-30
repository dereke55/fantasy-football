"""API tests against the real database (read-only)."""
import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(scope="module")
def a_running_back() -> dict:
    r = client.get("/api/players", params={"position": "RB", "limit": 5})
    assert r.status_code == 200
    body = r.json()
    assert body["count"] > 0
    return body["players"][0]


def test_health():
    assert client.get("/api/health").json()["db"] is True


def test_list_filters_and_orders_by_ecr(a_running_back):
    assert a_running_back["position"] == "RB"
    r = client.get("/api/players", params={"q": "gibbs"})
    names = [p["name"] for p in r.json()["players"]]
    assert any("Gibbs" in n for n in names)


def test_profile_has_history_summary_market_and_context(a_running_back):
    r = client.get(f"/api/players/{a_running_back['id']}/profile")
    assert r.status_code == 200
    body = r.json()
    assert body["player"]["id"] == a_running_back["id"]
    assert body["summary"], "player_features row expected for a top RB"
    assert body["seasons"], "per-season history expected for a top RB"
    assert {m["source"] for m in body["market"]} & {"fantasypros_mirror", "ffc", "sleeper", "yahoo_pub"}
    assert body["team_context"]["team"] == body["player"]["team"]
    assert body["provenance"]["team_context_sources"]


def test_profile_404_for_unknown_player():
    assert client.get("/api/players/999999999/profile").status_code == 404


def test_team_context_endpoints():
    one = client.get("/api/teams/den/context")
    assert one.status_code == 200 and one.json()["play_caller"] == "Davis Webb"
    assert len(client.get("/api/teams/context").json()["teams"]) == 32
