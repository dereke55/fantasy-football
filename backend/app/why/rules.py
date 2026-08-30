"""WHY rule framework: deterministic templates over stored signals. Each rendered bullet is auditable
(rule_id, template_version, numeric inputs, season/week range, snapshot ids, source_url).

A rule is a pure function `signals -> Bullet | None`. Signals is a flat mapping assembled by the ranking pipeline
from player_features / team_context / market tables, plus a `provenance` mapping {signal_key: {snapshot_id, source_url}}.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

TEMPLATE_VERSION = "2026.1"


@dataclass(frozen=True)
class Bullet:
    rule_id: str
    text: str
    kind: str                     # opportunity | efficiency | regression | durability | context | market | bio | value | rookie
    polarity: int                 # +1 positive, -1 negative, 0 informational
    priority: int                 # lower shows first
    inputs: dict = field(default_factory=dict)
    seasons: str | None = None
    snapshot_ids: list[str] = field(default_factory=list)
    source_url: str | None = None
    template_version: str = TEMPLATE_VERSION


Rule = Callable[[Mapping], Bullet | None]
_REGISTRY: dict[str, tuple[Rule, int]] = {}


def rule(rule_id: str, priority: int) -> Callable[[Rule], Rule]:
    def deco(fn: Rule) -> Rule:
        _REGISTRY[rule_id] = (fn, priority)
        return fn
    return deco


def _prov(signals: Mapping, *keys: str) -> tuple[list[str], str | None]:
    prov = signals.get("provenance", {}) or {}
    ids, url = [], None
    for k in keys:
        p = prov.get(k)
        if p:
            if p.get("snapshot_id") and p["snapshot_id"] not in ids:
                ids.append(str(p["snapshot_id"]))
            url = url or p.get("source_url")
    return ids, url


def _pct(x: float | None) -> str:
    return "—" if x is None else f"{100 * x:.0f}%"


# ---------------------------------------------------------------- headline (always available)

@rule("projection", 5)
def projection(s: Mapping) -> Bullet | None:
    """The headline: what we actually project, and where that ranks. Always present for a ranked player."""
    ppg, pos = s.get("blend_ppg"), s.get("position")
    if ppg is None:
        return None
    ids, url = _prov(s, "vendor_ppg")
    bits = [f"Projects {ppg:.1f} pts/game"]
    if s.get("pos_rank"):
        bits.append(f"({pos}{s['pos_rank']})")
    if s.get("vorp") is not None:
        bits.append(f"— {s['vorp']:.0f} over replacement")
    if s.get("e_games") is not None:
        bits.append(f"over {s['e_games']:.1f} expected games")
    return Bullet("projection", " ".join(bits), "value", 0, 5,
                  {"ppg": ppg, "vorp": s.get("vorp"), "e_games": s.get("e_games")}, "2026", ids, url)


@rule("market_position", 55)
def market_position(s: Mapping) -> Bullet | None:
    """Where the room takes him versus where we have him — shown even when the gap is unremarkable."""
    room, ours = s.get("room_adp"), s.get("our_pick")
    if room is None or ours is None:
        return None
    ids, url = _prov(s, "room_adp")
    delta = room - ours
    if abs(delta) < 6:
        tail = "in line with our value"
    else:
        tail = f"{abs(delta):.0f} picks {'later' if delta > 0 else 'earlier'} than our value"
    return Bullet("market_position", f"Room takes him around pick {room:.0f}; we have him at {ours:.0f} — {tail}",
                  "market", 0, 55, {"room_adp": room, "our_pick": ours}, "2026", ids, url)


@rule("usage_level", 18)
def usage_level(s: Mapping) -> Bullet | None:
    """Absolute opportunity, for players whose usage did not move enough to trigger the trend rule."""
    pos = s.get("position")
    ts, cs = s.get("target_share_2025"), s.get("carry_share_2025")
    ids, url = _prov(s, "target_share_2025", "carry_share_2025")
    if pos == "RB" and cs is not None and float(cs) > 0:
        return Bullet("usage_level", f"Handled {_pct(float(cs))} of team carries in 2025", "opportunity",
                      1 if float(cs) >= 0.5 else 0, 18, {"carry_share": float(cs)}, "2025", ids, url)
    if ts is not None and float(ts) > 0:
        return Bullet("usage_level", f"Commanded {_pct(float(ts))} of team targets in 2025", "opportunity",
                      1 if float(ts) >= 0.20 else 0, 18, {"target_share": float(ts)}, "2025", ids, url)
    return None


@rule("experience", 62)
def experience(s: Mapping) -> Bullet | None:
    if s.get("is_rookie"):
        return None
    yrs, age = s.get("years_exp"), s.get("age")
    if yrs is None:
        return None
    ids, url = _prov(s, "age")
    label = "Second NFL season" if yrs == 1 else f"{int(yrs) + 1}th NFL season"
    extra = f", age {age:.0f}" if age is not None else ""
    return Bullet("experience", f"{label}{extra}", "bio", 1 if yrs == 1 else 0, 62,
                  {"years_exp": yrs, "age": age}, "2026", ids, url)


# ---------------------------------------------------------------- opportunity / production

@rule("target_share_trend", 10)
def target_share_trend(s: Mapping) -> Bullet | None:
    cur, prev = s.get("target_share_2025"), s.get("target_share_2024")
    if cur is None or prev is None or s.get("position") not in ("WR", "TE", "RB"):
        return None
    delta = cur - prev
    if abs(delta) < 0.03:
        return None
    ids, url = _prov(s, "target_share_2025", "target_share_2024")
    return Bullet("target_share_trend", f"Target share {_pct(prev)} → {_pct(cur)} (2024→2025)", "opportunity",
                  1 if delta > 0 else -1, 10, {"prev": prev, "cur": cur, "delta": round(delta, 3)}, "2024-2025", ids, url)


@rule("ppg_trend", 12)
def ppg_trend(s: Mapping) -> Bullet | None:
    cur, prev = s.get("ppg_2025"), s.get("ppg_2024")
    if cur is None or prev is None or prev == 0:
        return None
    delta = cur - prev
    if abs(delta) < 1.5:
        return None
    ids, url = _prov(s, "ppg_2025", "ppg_2024")
    return Bullet("ppg_trend", f"{cur:.1f} PPG in 2025 vs {prev:.1f} in 2024 (your scoring)", "opportunity",
                  1 if delta > 0 else -1, 12, {"prev": prev, "cur": cur}, "2024-2025", ids, url)


@rule("carries_share", 14)
def carries_share(s: Mapping) -> Bullet | None:
    """Workhorse usage only; the general case is covered by `usage_level` so the two never duplicate."""
    share = s.get("carry_share_2025")
    if share is None or s.get("position") != "RB" or float(share) < 0.55:
        return None
    ids, url = _prov(s, "carry_share_2025")
    return Bullet("carries_share", f"Workhorse back: {_pct(float(share))} of team carries in 2025", "opportunity",
                  1, 14, {"carry_share": float(share)}, "2025", ids, url)


# ---------------------------------------------------------------- regression / luck

@rule("td_regression", 20)
def td_regression(s: Mapping) -> Bullet | None:
    diff = s.get("td_diff_2025")
    if diff is None or abs(diff) < 3:
        return None
    ids, url = _prov(s, "td_diff_2025")
    if diff > 0:
        text = f"Scored {diff:.1f} TDs above expected in 2025 — regression risk"
    else:
        text = f"Scored {abs(diff):.1f} TDs below expected in 2025 — positive regression candidate"
    return Bullet("td_regression", text, "regression", -1 if diff > 0 else 1, 20, {"td_diff": diff}, "2025", ids, url)


@rule("ppg_luck", 22)
def ppg_luck(s: Mapping) -> Bullet | None:
    diff = s.get("ppg_diff_2025")
    if diff is None or abs(diff) < 1.0:
        return None
    ids, url = _prov(s, "ppg_diff_2025")
    text = (f"Outperformed expected points by {diff:.1f} PPG in 2025 (your scoring)" if diff > 0
            else f"Underperformed expected points by {abs(diff):.1f} PPG in 2025 (your scoring)")
    return Bullet("ppg_luck", text, "regression", -1 if diff > 0 else 1, 22, {"ppg_diff": diff}, "2025", ids, url)


# ---------------------------------------------------------------- durability

@rule("games_missed", 30)
def games_missed(s: Mapping) -> Bullet | None:
    missed, elig = s.get("games_missed_3yr"), s.get("games_eligible_3yr")
    if missed is None or not elig or missed < 3:
        return None
    parts = [f"Missed {missed} of {elig} games 2023–25"]
    causes = s.get("injury_causes") or []
    if causes:
        parts.append("(" + ", ".join(causes[:3]) + ")")
    eg = s.get("e_games")
    if eg is not None:
        parts.append(f"→ E[games] {eg:.1f}")
    ids, url = _prov(s, "games_missed_3yr")
    return Bullet("games_missed", " ".join(parts), "durability", -1, 30,
                  {"missed": missed, "eligible": elig, "e_games": eg}, "2023-2025", ids, url)


@rule("current_injury", 28)
def current_injury(s: Mapping) -> Bullet | None:
    st = s.get("injury_status")
    if not st or st in ("Active", "ACT"):
        return None
    ids, url = _prov(s, "injury_status")
    body = s.get("injury_body_part")
    text = f"Currently listed {st}" + (f" ({body})" if body else "")
    known = s.get("known_missed_weeks") or 0
    if known:
        text += f" — {known} week(s) expected missed"
    return Bullet("current_injury", text, "durability", -1, 28, {"status": st, "known_missed_weeks": known}, "2026", ids, url)


# ---------------------------------------------------------------- context (tags only)

@rule("new_play_caller", 40)
def new_play_caller(s: Mapping) -> Bullet | None:
    if not s.get("play_caller_new"):
        return None
    ids, url = _prov(s, "play_caller_new")
    who = s.get("play_caller") or "new play-caller"
    return Bullet("new_play_caller", f"New offensive play-caller ({who}) — tag only, no projection change", "context", 0, 40,
                  {"play_caller": who}, "2026", ids, url)


@rule("qb_situation", 41)
def qb_situation(s: Mapping) -> Bullet | None:
    st = s.get("qb_status")
    if not st or st == "settled":
        return None
    ids, url = _prov(s, "qb_status")
    qb = s.get("projected_qb1") or "TBD"
    label = {"competition": "unsettled QB competition", "injury_return": "QB returning from injury"}.get(st, st)
    return Bullet("qb_situation", f"Team has an {label} (projected QB1: {qb})", "context", -1, 41,
                  {"qb_status": st, "projected_qb1": qb}, "2026", ids, url)


@rule("ol_delta", 42)
def ol_delta(s: Mapping) -> Bullet | None:
    d = s.get("ol_delta")
    if d is None or d == 0:
        return None
    ids, url = _prov(s, "ol_delta")
    text = f"Offensive line {'upgraded' if d > 0 else 'downgraded'} this offseason ({d:+d})"
    note = s.get("ol_notes")
    if note:
        text += f": {note}"
    return Bullet("ol_delta", text, "context", 1 if d > 0 else -1, 42, {"ol_delta": d}, "2026", ids, url)


@rule("new_head_coach", 43)
def new_head_coach(s: Mapping) -> Bullet | None:
    if not s.get("hc_new"):
        return None
    ids, url = _prov(s, "hc_new")
    return Bullet("new_head_coach", f"New head coach ({s.get('hc') or 'new'}) in 2026", "context", 0, 43, {"hc": s.get("hc")}, "2026", ids, url)


# ---------------------------------------------------------------- market / value

@rule("adp_gap", 50)
def adp_gap(s: Mapping) -> Bullet | None:
    gap, z = s.get("gap"), s.get("gap_z")
    if gap is None or z is None or abs(gap) < 6 or abs(z) < 1.0:
        return None
    ids, url = _prov(s, "room_adp")
    if gap > 0:
        text = f"Room ADP {s.get('room_adp'):.0f} vs our value pick {s.get('our_pick'):.0f} — {gap:.0f} picks of value (z={z:.1f})"
    else:
        text = f"Room ADP {s.get('room_adp'):.0f} is {abs(gap):.0f} picks ahead of our value (z={z:.1f}) — likely overpay"
    return Bullet("adp_gap", text, "market", 1 if gap > 0 else -1, 50, {"gap": gap, "gap_z": z}, "2026", ids, url)


@rule("expert_disagreement", 52)
def expert_disagreement(s: Mapping) -> Bullet | None:
    r = s.get("ecr_std_residual")
    if r is None or r < 1.0:
        return None
    ids, url = _prov(s, "ecr_std")
    return Bullet("expert_disagreement", f"Experts disagree more than usual at this rank (ECR std {s.get('ecr_std'):.1f}, best {s.get('ecr_best'):.0f} / worst {s.get('ecr_worst'):.0f})",
                  "market", -1, 52, {"ecr_std": s.get("ecr_std"), "residual": r}, "2026", ids, url)


@rule("projection_sources", 54)
def projection_sources(s: Mapping) -> Bullet | None:
    v, h = s.get("vendor_ppg"), s.get("inhouse_ppg")
    if v is None or h is None:
        return None
    gap = h - v
    if abs(gap) < 1.0:
        return None
    ids, url = _prov(s, "vendor_ppg")
    return Bullet("projection_sources", f"Our opportunity model says {h:.1f} PPG vs {v:.1f} from Rotowire/Sleeper (blend {s.get('blend_ppg'):.1f})",
                  "value", 1 if gap > 0 else -1, 54, {"vendor": v, "inhouse": h, "blend": s.get("blend_ppg")}, "2026", ids, url)


# ---------------------------------------------------------------- bio / rookie / contract

@rule("age", 60)
def age(s: Mapping) -> Bullet | None:
    a, f = s.get("age"), s.get("age_factor")
    if a is None or f is None or f == 1.0:
        return None
    ids, url = _prov(s, "age")
    return Bullet("age", f"Age {a:.0f} at kickoff — {s.get('position')} year-over-year factor {f:.2f} applied to our model", "bio",
                  -1 if f < 1 else 1, 60, {"age": a, "factor": f}, "2026", ids, url)


@rule("rookie_draft_capital", 8)
def rookie_draft_capital(s: Mapping) -> Bullet | None:
    if not s.get("is_rookie"):
        return None
    rnd, pick, team = s.get("draft_round"), s.get("draft_pick"), s.get("draft_team")
    ids, url = _prov(s, "draft_pick")
    if rnd is None:
        return Bullet("rookie_draft_capital", "Undrafted 2026 rookie", "rookie", -1, 8, {}, "2026", ids, url)
    return Bullet("rookie_draft_capital", f"2026 rookie: round {rnd}, pick #{pick} overall ({team})", "rookie",
                  1 if rnd == 1 else 0, 8, {"round": rnd, "pick": pick}, "2026", ids, url)


@rule("depth_chart", 16)
def depth_chart(s: Mapping) -> Bullet | None:
    rank, dt = s.get("depth_rank"), s.get("depth_dt")
    if rank is None:
        return None
    ids, url = _prov(s, "depth_rank")
    pos = s.get("position")
    text = f"{pos}{rank} on the {s.get('team')} depth chart" + (f" ({dt})" if dt else "")
    move = s.get("depth_rank_change_30d")
    if move:
        text += f", moved {'up' if move < 0 else 'down'} {abs(move)} in the last 30 days"
    return Bullet("depth_chart", text, "opportunity", 1 if rank == 1 else (0 if rank == 2 else -1), 16,
                  {"depth_rank": rank, "change_30d": move}, "2026", ids, url)


@rule("contract", 70)
def contract(s: Mapping) -> Bullet | None:
    if s.get("contract_year"):
        ids, url = _prov(s, "contract_year")
        return Bullet("contract", "Contract year (informational — evidence shows no positive effect once age is controlled)",
                      "bio", 0, 70, {}, "2026", ids, url)
    if s.get("just_paid"):
        ids, url = _prov(s, "just_paid")
        return Bullet("contract", "Signed a new top-of-position contract in 2025–26 (informational)", "bio", 0, 70, {}, "2026", ids, url)
    return None


def render(signals: Mapping, *, max_bullets: int = 6) -> list[Bullet]:
    out: list[Bullet] = []
    for fn, _prio in _REGISTRY.values():
        b = fn(signals)
        if b is not None:
            out.append(b)
    out.sort(key=lambda b: (b.priority, b.rule_id))
    # usage_level and carries_share describe the same thing; keep the more specific one
    ids_present = {b.rule_id for b in out}
    if {"usage_level", "carries_share"} <= ids_present:
        out = [b for b in out if b.rule_id != "usage_level"]
    return out[:max_bullets]


def registry() -> dict[str, int]:
    return {k: v[1] for k, v in _REGISTRY.items()}
