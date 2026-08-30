"""Assemble the flat signal mapping that `app.why.rules.render` turns into WHY bullets.

Every value here comes from a stored table (player_features, team_context, rankings inputs), and every key that a
rule cites carries a provenance entry so the rendered bullet can be traced back to the data that produced it.
"""
from __future__ import annotations

from typing import Any

NFLVERSE = "https://github.com/nflverse/nflverse-data"
SLEEPER = "https://api.sleeper.com/projections/nfl/2026"


def _prov(url: str, snapshot_id: str | None = None) -> dict:
    return {"source_url": url, "snapshot_id": snapshot_id}


def build_signals(feat: dict, rank: dict, context: dict, cfg_source: str) -> dict[str, Any]:
    """feat = player_features row, rank = the in-progress rankings row, context = team_context row."""
    s: dict[str, Any] = {
        "position": rank.get("position"),
        "team": rank.get("team"),
        # production / opportunity
        "ppg_2025": feat.get("ppg_2025"),
        "ppg_2024": feat.get("ppg_2024"),
        "target_share_2025": feat.get("target_share_2025"),
        "target_share_2024": feat.get("target_share_2024"),
        "carry_share_2025": feat.get("carry_share_2025"),
        # regression
        "td_diff_2025": feat.get("td_diff_2025"),
        "ppg_diff_2025": feat.get("ppg_diff_2025"),
        # durability
        "games_missed_3yr": feat.get("games_missed_3yr"),
        "games_eligible_3yr": feat.get("games_eligible_3yr"),
        "injury_causes": (feat.get("injury_causes") or "").split("; ") if feat.get("injury_causes") else [],
        "e_games": rank.get("e_games"),
        "injury_status": feat.get("current_injury_status"),
        "injury_body_part": feat.get("current_injury_body_part"),
        "known_missed_weeks": feat.get("known_missed_weeks"),
        # depth / bio
        "depth_rank": feat.get("depth_rank"),
        "depth_dt": str(feat.get("depth_dt"))[:10] if feat.get("depth_dt") else None,
        "depth_rank_change_30d": feat.get("depth_rank_change_30d"),
        "age": feat.get("age_2026"),
        "age_factor": rank.get("age_factor"),
        "is_rookie": feat.get("is_rookie"),
        "draft_round": feat.get("draft_round"),
        "draft_pick": feat.get("draft_pick"),
        "draft_team": feat.get("draft_team"),
        # market / value
        "room_adp": rank.get("room_adp"),
        "our_pick": rank.get("our_pick_equivalent"),
        "gap": rank.get("gap"),
        "gap_z": rank.get("gap_z"),
        "ecr_std": rank.get("ecr_sd"),
        "ecr_best": rank.get("ecr_best"),
        "ecr_worst": rank.get("ecr_worst"),
        "ecr_std_residual": rank.get("disagreement"),
        "vendor_ppg": rank.get("ppg_vendor"),
        "inhouse_ppg": rank.get("ppg_inhouse"),
        "blend_ppg": rank.get("ppg_blend"),
        "pos_rank": rank.get("pos_rank"),
        "vorp": rank.get("vorp"),
        "years_exp": feat.get("years_exp"),
    }
    if context:
        s.update({
            "hc": context.get("hc"), "hc_new": context.get("hc_new"),
            "play_caller": context.get("play_caller"), "play_caller_new": context.get("play_caller_new"),
            "qb_status": context.get("qb_status"), "projected_qb1": context.get("projected_qb1"),
            "ol_delta": context.get("ol_delta"),
            "ol_notes": (context.get("ol_injuries") or [None])[0] if context.get("ol_injuries") else None,
        })
    ctx_url = None
    if context and context.get("sources"):
        ctx_url = (context["sources"].get("coaching_changes") or {}).get("source_url")
    s["provenance"] = {
        k: _prov(NFLVERSE) for k in (
            "ppg_2025", "ppg_2024", "target_share_2025", "target_share_2024", "carry_share_2025",
            "td_diff_2025", "ppg_diff_2025", "games_missed_3yr", "depth_rank", "age", "draft_pick")
    }
    s["provenance"].update({
        "injury_status": _prov("https://api.sleeper.app/v1/players/nfl"),
        "vendor_ppg": _prov(SLEEPER),
        "room_adp": _prov("https://fantasyfootballcalculator.com/api/v1/adp"),
        "ecr_std": _prov("https://github.com/dynastyprocess/data (FantasyPros ECR mirror)"),
    })
    for key in ("play_caller_new", "qb_status", "ol_delta", "hc_new"):
        s["provenance"][key] = _prov(ctx_url or "backend/seeds/*.yaml")
    s["scoring_source"] = cfg_source
    return s
