"""FFC ADP parser against a real snapshot extract (see tests/fixtures/ffc/PROVENANCE.md). No network, no DB."""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from app.ingest import ffc

FIXTURE = Path(__file__).parent / "fixtures" / "ffc" / "adp_half-ppr_10.json"
EXPECTED_COLUMNS = [*ffc.PLAYER_SCHEMA, "format", *ffc.META_FIELDS, "year"]


@pytest.fixture(scope="module")
def payload() -> dict:
    return json.loads(FIXTURE.read_text())


def test_parse_adp_shape_and_meta(payload: dict) -> None:
    df = ffc.parse_adp(payload, fmt="half-ppr", teams=10, year=2026)
    assert df.height == 40
    assert df.columns == EXPECTED_COLUMNS
    # meta broadcast onto every row (partition keys + window) — values read from the raw snapshot
    assert df.select(ffc.PARTITION).unique().to_dicts() == [{"format": "half-ppr", "teams": 10, "year": 2026}]
    assert df["type"].unique().to_list() == ["Half-PPR"]
    assert df["rounds"].unique().to_list() == [15]
    assert df["total_drafts"].unique().to_list() == [3302]
    assert df["start_date"].unique().to_list() == ["2026-08-24"]
    assert df["end_date"].unique().to_list() == ["2026-08-29"]
    assert df["adp"].is_sorted()  # upstream order is ascending ADP


def test_parse_adp_hand_verified_rows(payload: dict) -> None:
    df = ffc.parse_adp(payload, fmt="half-ppr", teams=10, year=2026)
    gibbs = df.filter(df["player_id"] == 5672).to_dicts()
    assert len(gibbs) == 1
    assert gibbs[0] == {
        "player_id": 5672, "name": "Jahmyr Gibbs", "position": "RB", "team": "DET",
        "adp": 1.5, "adp_formatted": "1.01", "times_drafted": 589, "high": 1, "low": 4, "stdev": 0.7, "bye": 6,
        "format": "half-ppr", "type": "Half-PPR", "teams": 10, "rounds": 15, "total_drafts": 3302,
        "start_date": "2026-08-24", "end_date": "2026-08-29", "year": 2026,
    }
    mcbride = df.filter(df["name"] == "Trey McBride").row(0, named=True)
    assert (mcbride["player_id"], mcbride["position"], mcbride["team"]) == (5656, "TE", "ARI")
    assert (mcbride["adp"], mcbride["adp_formatted"], mcbride["high"], mcbride["low"]) == (38.3, "4.08", 19, 53)
    assert (mcbride["stdev"], mcbride["times_drafted"], mcbride["bye"]) == (7.1, 341, 14)
    # names arrive with generational suffixes intact (crosswalk must normalise, not the raw table)
    assert df.filter(df["player_id"] == 5652)["name"].to_list() == ["James Cook III"]


def test_parse_adp_rejects_mismatch_and_empty(payload: dict) -> None:
    with pytest.raises(ValueError, match="meta.teams"):
        ffc.parse_adp(payload, fmt="half-ppr", teams=12, year=2026)
    with pytest.raises(ValueError, match="empty players"):
        ffc.parse_adp({"status": "Success", "meta": payload["meta"], "players": []}, fmt="ppr", teams=10, year=2026)


def test_compare_payloads_flags_only_real_differences(payload: dict) -> None:
    same = ffc.compare_payloads(payload, payload)
    assert same["differs"] is False and same["players_with_adp_diff"] == 0 and same["max_abs_adp_diff"] == 0.0

    reformatted = copy.deepcopy(payload)  # what teams=12 actually does: only adp_formatted changes
    reformatted["meta"]["teams"] = 12
    for p in reformatted["players"]:
        pick = round(p["adp"])
        p["adp_formatted"] = f"{(pick - 1) // 12 + 1}.{(pick - 1) % 12 + 1:02d}"
    only_fmt = ffc.compare_payloads(payload, reformatted)
    assert only_fmt["fields_differ"]["adp_formatted"] is True and only_fmt["differs"] is False

    other_drafts = copy.deepcopy(payload)
    other_drafts["meta"]["total_drafts"] = 1
    assert ffc.compare_payloads(payload, other_drafts)["differs"] is True
