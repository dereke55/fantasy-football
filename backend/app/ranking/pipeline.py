"""Phase 6 — the ranking pipeline: projections -> value -> tiers -> flags -> WHY, persisted as one auditable run.

Order of operations (docs/spec/ranking-model.md):
  1. blend the vendor and in-house per-game projections (adjustments live in the in-house half only)
  2. add the per-game yardage bonus estimated from real weekly history
  3. one E[games] at the per-game -> season conversion, keeper-aware VBD baselines
  4. tiers (fixed-k GMM on ECR, plus value tiers from our own projection drop-offs)
  5. room ADP -> gap / gap_z -> sleeper & bust flags
  6. availability and VONA against my next pick
  7. WHY bullets from stored signals

Every run is a `ranking_runs` row recording the git sha, the league-config hash, the curated-seed hashes and the
weights, so a frozen draft board can be audited without recomputing it.
"""
from __future__ import annotations

import hashlib
import subprocess
import time
import uuid
from datetime import UTC, datetime

import polars as pl
import typer
from scipy.stats import spearmanr
from sqlalchemy import text

from app.config import settings
from app.db import engine, session_scope
from app.ranking.availability import Candidate, expected_best_value, p_available
from app.ranking.pick_schedule import KeeperSpec, build_pick_schedule, next_live_pick
from app.ranking.projections import projection_pool
from app.ranking.room_adp import gap_z, our_pick_equivalent, room_adp
from app.ranking.signals import build_signals
from app.ranking.tiers import ecr_tiers, value_tiers
from app.ranking.vbd import NO_VBD_POSITIONS, Projection, compute_baselines, value_pool
from app.scoring.config import LeagueConfig, league_config_sha256, load_league_config
from app.why.rules import render

cli = typer.Typer(no_args_is_help=True, help="Ranking model: recompute, inspect and freeze the board")

MODEL_VERSION = "2026.1"
W_VENDOR, W_INHOUSE = 0.70, 0.30
W_VENDOR_NOHIST, W_INHOUSE_NOHIST = 0.90, 0.10
SLEEPER_GAP_Z, SLEEPER_GAP = 1.0, 6.0
# 10 teams x 16 rounds = 160 picks; allow margin for ADP noise before calling anyone a sleeper or a bust
DRAFTABLE_ADP = 220.0
# how many positional places apart our rank and the market's must be before a negative gap is player-specific
POS_GAP_MIN = 5.0
SPEARMAN_FLOOR = 0.80


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, timeout=5).strip()
    except (subprocess.SubprocessError, OSError):
        return None


def _seed_hashes() -> dict:
    out = {}
    for p in sorted(settings.seeds_dir.glob("*.yaml")):
        out[p.name] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def load_keepers(cfg: LeagueConfig) -> list[KeeperSpec]:
    """Keepers entered in the DB (manual or Yahoo). Empty until Derek enters them."""
    try:
        rows = _q("select team_slot, cost_round, player_id from keepers order by team_slot, cost_round").to_dicts()
    except Exception:  # noqa: BLE001 - table may not be populated yet
        return []
    return [KeeperSpec(team_slot=r["team_slot"], cost_round=r["cost_round"], player_id=r["player_id"])
            for r in rows]


def _inhouse() -> pl.DataFrame | None:
    """The in-house opportunity model, when it is available (Phase 6 step 1)."""
    try:
        from app.ranking.inhouse import compute_inhouse
    except ImportError:
        return None
    try:
        df = compute_inhouse()
    except Exception as exc:  # noqa: BLE001 - the blend degrades to vendor-only rather than failing the run
        typer.secho(f"in-house component unavailable ({type(exc).__name__}: {exc}); using vendor-only weights",
                    fg=typer.colors.YELLOW)
        return None
    return df


def build_board(cfg: LeagueConfig | None = None) -> tuple[pl.DataFrame, dict]:
    """Compute the whole board. Returns (rankings frame, run metadata)."""
    cfg = cfg or load_league_config()
    pool = projection_pool(cfg)
    feats = _q("select * from player_features")
    inhouse = _inhouse()

    df = pool.join(feats.drop("position", "team", "name", strict=False), on="player_id", how="left")
    if inhouse is not None and not inhouse.is_empty():
        keep = [c for c in ("player_id", "inhouse_ppg", "inhouse_ppg_raw", "age_factor", "share_source")
                if c in inhouse.columns]
        df = df.join(inhouse.select(keep), on="player_id", how="left")
    for col in ("inhouse_ppg", "inhouse_ppg_raw", "age_factor", "share_source"):
        if col not in df.columns:
            df = df.with_columns(pl.lit(None).alias(col))

    # ---- 1/2. blend (weights fall back to vendor-only when there is no in-house estimate) ----
    has_hist = pl.col("has_8game_same_role_season").fill_null(False) if "has_8game_same_role_season" in df.columns \
        else pl.lit(False)
    df = df.with_columns(
        w_inhouse=pl.when(pl.col("inhouse_ppg").is_null()).then(0.0)
        .when(has_hist).then(W_INHOUSE).otherwise(W_INHOUSE_NOHIST)
    ).with_columns(w_vendor=1.0 - pl.col("w_inhouse"))
    df = df.with_columns(
        ppg_blend=(pl.col("w_vendor") * pl.col("vendor_ppg_no_bonus").fill_null(pl.col("vendor_ppg"))
                   + pl.col("w_inhouse") * pl.col("inhouse_ppg").fill_null(0.0)
                   + pl.col("bonus_pg").fill_null(0.0)).round(3)
    )

    # ---- 3. value, keeper-aware ----
    keepers = load_keepers(cfg)
    kept_ids = {k.player_id for k in keepers if k.player_id}
    open_rows = df.filter(~pl.col("player_id").is_in(list(kept_ids))) if kept_ids else df
    projections = [Projection(r["player_id"], r["position"], r["ppg_blend"], r["e_games"])
                   for r in open_rows.to_dicts() if r["ppg_blend"] is not None and r["e_games"] is not None]
    kept_pairs = [(r["player_id"], r["position"]) for r in df.to_dicts() if r["player_id"] in kept_ids]
    baselines = compute_baselines(projections, num_teams=cfg.league.num_teams, slots=cfg.roster.slots,
                                  flex_eligible=cfg.roster.flex_eligible, bench=cfg.roster.bench,
                                  keepers=kept_pairs)
    vals = {v.player_id: v for v in value_pool(projections, baselines)}
    df = df.with_columns(
        vorp=pl.col("player_id").map_elements(lambda i: vals[i].vorp if i in vals else None, return_dtype=pl.Float64),
        season_value=pl.col("player_id").map_elements(
            lambda i: vals[i].season_value if i in vals else None, return_dtype=pl.Float64),
        vols=pl.col("player_id").map_elements(
            lambda i: vals[i].vols_ppg_gap if i in vals else None, return_dtype=pl.Float64),
        replacement_ppg=pl.col("position").map_elements(
            lambda p: baselines.replacement_ppg.get(p), return_dtype=pl.Float64),
        baseline_rank=pl.col("position").map_elements(
            lambda p: baselines.vols_rank.get(p), return_dtype=pl.Int64),
        is_kdst=pl.col("position").is_in(list(NO_VBD_POSITIONS)),
    )

    # ---- 4. ranks and tiers ----
    df = df.sort("vorp", descending=True, nulls_last=True).with_columns(
        overall_rank=pl.int_range(1, pl.len() + 1),
    ).with_columns(pos_rank=pl.col("overall_rank").rank("ordinal").over("position").cast(pl.Int64))
    tier_map: dict[int, int] = {}
    for pos in df["position"].unique().to_list():
        sub = df.filter((pl.col("position") == pos) & pl.col("ecr").is_not_null()).sort("ecr")
        if sub.height:
            for pid, t in zip(sub["player_id"].to_list(), ecr_tiers(sub["ecr"].to_list(), pos), strict=False):
                tier_map[pid] = t
    vtier_map: dict[int, int] = {}
    for pos in df["position"].unique().to_list():
        sub = df.filter((pl.col("position") == pos) & pl.col("vorp").is_not_null()).sort("vorp", descending=True)
        sd = sub["weekly_sd_2025"].drop_nulls().median() if "weekly_sd_2025" in sub.columns else None
        sd = float(sd) if sd else 5.0
        if sub.height:
            for pid, t in zip(sub["player_id"].to_list(), value_tiers(sub["vorp"].to_list(), sd), strict=False):
                vtier_map[pid] = t
    df = df.with_columns(
        tier=pl.col("player_id").map_elements(tier_map.get, return_dtype=pl.Int64),
        value_tier=pl.col("player_id").map_elements(vtier_map.get, return_dtype=pl.Int64),
    )

    # ---- 5. room ADP, gap, flags ----
    adp = {r["player_id"]: r["composite_adp"] for r in df.to_dicts() if r["composite_adp"] is not None}
    room = room_adp(adp, kept_ids)
    ours = our_pick_equivalent(df["player_id"].to_list(), kept_ids)
    df = df.with_columns(
        room_adp=pl.col("player_id").map_elements(room.get, return_dtype=pl.Float64),
        our_pick_equivalent=pl.col("player_id").map_elements(ours.get, return_dtype=pl.Float64),
    )
    gz = [gap_z(r["room_adp"], r["our_pick_equivalent"], r["sd_adp"] or 10.0) for r in df.to_dicts()]
    df = df.with_columns(gap=pl.Series([g[0] for g in gz], dtype=pl.Float64),
                         gap_z=pl.Series([g[1] for g in gz], dtype=pl.Float64))
    # Overall gap mixes two different things: disagreement about the PLAYER, and disagreement about how much the
    # POSITION is worth. In a 1-QB league every quarterback ranks far below his ADP on overall value, which is a
    # statement about positional scarcity, not about the player. The within-position gap isolates the first.
    # rank() returns UInt32: cast BEFORE subtracting or every negative difference wraps to ~4.29e9.
    df = df.with_columns(
        mkt_pos_rank=pl.col("composite_adp").rank("ordinal").over("position").cast(pl.Int64),
        our_pos_rank=pl.col("overall_rank").rank("ordinal").over("position").cast(pl.Int64),
    ).with_columns(pos_gap=(pl.col("mkt_pos_rank") - pl.col("our_pos_rank")).cast(pl.Float64))

    # ---- 6. availability / VONA at my next pick ----
    rounds = cfg.roster.rounds
    sched = build_pick_schedule(cfg.league.num_teams, rounds, keepers)
    my_slot = cfg.league.my_draft_slot
    next_slot, _ = next_live_pick(sched, my_slot, 0) if my_slot else (None, 0)
    my_next = next_slot.live_pick_no if next_slot else cfg.league.num_teams  # unknown slot -> end of round 1
    cands = [Candidate(r["player_id"], r["position"], max(0.0, r["vorp"] or 0.0), r["room_adp"], r["sd_adp"] or 10.0)
             for r in df.to_dicts() if r["vorp"] is not None]
    by_pos: dict[str, list[Candidate]] = {}
    for c in cands:
        by_pos.setdefault(c.position, []).append(c)
    exp_best = {pos: expected_best_value(cs, my_next) for pos, cs in by_pos.items()}
    df = df.with_columns(
        p_avail_next=pl.struct(["room_adp", "sd_adp"]).map_elements(
            lambda r: round(p_available(r["room_adp"], r["sd_adp"] or 10.0, my_next), 4), return_dtype=pl.Float64),
        vona=pl.struct(["position", "vorp"]).map_elements(
            lambda r: None if r["vorp"] is None else round(r["vorp"] - exp_best.get(r["position"], 0.0), 2),
            return_dtype=pl.Float64),
    )
    return _flags_and_why(df, cfg, baselines), {
        "weights": {"vendor": W_VENDOR, "inhouse": W_INHOUSE, "vendor_no_history": W_VENDOR_NOHIST,
                    "inhouse_no_history": W_INHOUSE_NOHIST, "inhouse_available": inhouse is not None},
        "my_next_pick": my_next, "keepers": len(keepers), "baselines": baselines.vols_rank,
    }


def _signal_sets(r: dict, c: dict, dis_cut: float) -> tuple[list[str], list[str]]:
    """Support and risk signals behind the sleeper / bust flags.

    Team-level context (new play-caller, unsettled QB room, offensive-line change) is shared by every player on a
    roster: 18 of 32 teams changed play-caller and 21 have a non-zero line delta, so counting each separately made
    58% of the league carry >= 2 "risk" signals and flagged 147 busts. Team context therefore collapses into a
    SINGLE aggregate signal per side, and the discriminating work is done by player-level evidence.
    """
    support, risk = [], []
    # --- player-level support ---
    ts, ts_prev = r.get("target_share_2025"), r.get("target_share_2024")
    if ts is not None and ts_prev is not None and float(ts) - float(ts_prev) >= 0.03:
        support.append("opportunity_gain")
    td = r.get("td_diff_2025")
    if td is not None and td <= -3:
        support.append("negative_td_luck")
    if (r.get("depth_rank_change_30d") or 0) < 0:
        support.append("depth_chart_rise")
    if (r.get("yoy_ppg_delta") or 0) >= 2.0:
        support.append("ppg_trend_up")
    cs = r.get("carry_share_2025")
    if (ts is not None and float(ts) >= 0.25) or (cs is not None and float(cs) >= 0.55):
        support.append("elite_opportunity")
    age, pos = r.get("age_2026"), r.get("position")
    if age is not None and pos in ("RB", "WR", "TE") and float(age) <= 24.0 and (r.get("ppg_2025") or 0) > 0:
        support.append("young_with_role")
    # --- player-level risk ---
    if td is not None and td >= 3:
        risk.append("positive_td_luck")
    if r.get("injury_prone"):
        risk.append("injury_prone")
    if r.get("structural_injury_return"):
        risk.append("structural_injury_return")
    cliff = {"RB": 29, "WR": 31, "TE": 32}
    if age is not None and pos in cliff and float(age) >= cliff[pos]:
        risk.append("age_cliff")
    dis = r.get("disagreement")
    if dis is not None and dis >= dis_cut:
        risk.append("expert_disagreement")
    if (r.get("known_missed_weeks") or 0) >= 2:
        risk.append("announced_absence")
    # --- team context, collapsed to one signal per side ---
    neg = [k for k, v in (("new play-caller", c.get("play_caller_new")),
                          ("unsettled QB room", c.get("qb_status") not in (None, "settled")),
                          ("offensive line downgrade", (c.get("ol_delta") or 0) <= -1)) if v]
    if neg:
        risk.append("team_context:" + ", ".join(neg))
    if (c.get("ol_delta") or 0) >= 1:
        support.append("team_context:offensive line upgrade")
    return support, risk


def _flags_and_why(df: pl.DataFrame, cfg: LeagueConfig, baselines) -> pl.DataFrame:
    ctx = {r["team"]: r for r in _q("select * from team_context").to_dicts()}
    # "experts disagree more than usual" should mean unusual, not common: use the top decile of the residual.
    dis = df["disagreement"].drop_nulls()
    dis_cut = float(dis.quantile(0.90)) if dis.len() > 50 else 1.0
    rows, bullets = [], []
    for r in df.to_dicts():
        flags = []
        c = ctx.get(r.get("team") or "", {})
        support, risk = _signal_sets(r, c, dis_cut)
        if r.get("injury_prone"):
            flags.append("injury_prone")
        if r.get("structural_injury_return"):
            flags.append("structural_injury_return")
        if r.get("is_rookie"):
            flags.append("rookie")
        if c.get("play_caller_new"):
            flags.append("new_play_caller")
        if c.get("qb_status") and c["qb_status"] != "settled":
            flags.append("qb_uncertain_team")

        gz, gp, pg = r.get("gap_z"), r.get("gap"), r.get("pos_gap")
        adp = r.get("composite_adp")
        # Only flag players who are actually draftable in this league: 10 teams x 16 rounds = 160 picks, with a
        # margin for ADP noise. Beyond that a huge "gap" just means nobody drafts them.
        draftable = adp is not None and adp <= DRAFTABLE_ADP
        if gz is not None and gp is not None and not r["is_kdst"] and draftable:
            if gz >= SLEEPER_GAP_Z and gp >= SLEEPER_GAP and len(support) >= 2:
                flags.append("sleeper")
            if gz <= -SLEEPER_GAP_Z and gp <= -SLEEPER_GAP and len(risk) >= 2:
                # a negative overall gap that disappears within the position is positional value, not a bust
                if pg is not None and pg > -POS_GAP_MIN:
                    flags.append("positional_reach")
                else:
                    flags.append("bust")
        signals = {"support": support, "risk": risk, "disagreement_cut": round(dis_cut, 3),
                   "pos_gap": pg, "draftable": draftable}

        sig = build_signals(r, r, c, cfg.source)
        for b in render(sig, max_bullets=6):
            bullets.append({"player_id": r["player_id"], "rule_id": b.rule_id, "template_version": b.template_version,
                            "text": b.text, "kind": b.kind, "polarity": b.polarity, "priority": b.priority,
                            "inputs": b.inputs, "seasons": b.seasons, "snapshot_ids": b.snapshot_ids,
                            "source_url": b.source_url})
        rows.append({**r, "flags": flags, "signals": signals})
    out = pl.DataFrame(rows, infer_schema_length=None)
    out._why_bullets = bullets  # carried alongside; persisted by save()
    return out


RANK_COLS = ("player_id", "position", "team", "overall_rank", "pos_rank", "tier", "value_tier", "ppg_vendor",
             "ppg_inhouse", "ppg_inhouse_raw", "w_vendor", "w_inhouse", "bonus_pg", "ppg_blend", "e_games",
             "replacement_ppg", "baseline_rank", "season_value", "vols", "vorp", "ecr", "ecr_sd", "disagreement",
             "yahoo_adp", "ffc_adp", "sleeper_adp", "composite_adp", "room_adp", "sd_adp", "sd_adp_source",
             "our_pick_equivalent", "gap", "gap_z", "p_avail_next", "vona", "flags", "signals", "is_kdst")
ALIASES = {"ppg_vendor": "vendor_ppg", "ppg_inhouse": "inhouse_ppg", "ppg_inhouse_raw": "inhouse_ppg_raw"}


def save(board: pl.DataFrame, meta: dict, cfg: LeagueConfig, *, duration: float, spearman: float | None) -> uuid.UUID:
    import json as _json

    run_id = uuid.uuid4()
    keepers_hash = hashlib.sha256(str(sorted((k.team_slot, k.cost_round, k.player_id)
                                             for k in load_keepers(cfg))).encode()).hexdigest()
    payload = []
    for r in board.to_dicts():
        rec = {}
        for c in RANK_COLS:
            src = ALIASES.get(c, c)
            v = r.get(src, r.get(c))
            rec[c] = _json.dumps(v) if c == "signals" else v
        rec["run_id"] = str(run_id)
        payload.append(rec)
    bullets = getattr(board, "_why_bullets", [])
    with session_scope() as s:
        s.execute(text(
            "insert into ranking_runs (run_id, started_at, finished_at, git_sha, league_config_sha256, seed_hashes, "
            "input_snapshot_ids, is_frozen, status, model_version, weights, keepers_hash, spearman_top150, "
            "n_players_ranked, n_why_bullets, duration_s) values (:run_id, now(), now(), :git, :cfg, "
            "cast(:seeds as jsonb), cast('[]' as jsonb), false, 'ok', :mv, cast(:w as jsonb), :kh, :sp, :n, :nb, :d)"),
            {"run_id": str(run_id), "git": _git_sha(), "cfg": league_config_sha256(),
             "seeds": _json.dumps(_seed_hashes()), "mv": MODEL_VERSION, "w": _json.dumps(meta["weights"]),
             "kh": keepers_hash, "sp": spearman, "n": len(payload), "nb": len(bullets), "d": duration})
        cols = ", ".join(("run_id", *RANK_COLS))
        ph = ", ".join([":run_id"] + [f"cast(:{c} as jsonb)" if c == "signals" else f":{c}" for c in RANK_COLS])
        s.execute(text(f"insert into rankings ({cols}) values ({ph})"), payload)
        if bullets:
            for b in bullets:
                b["run_id"] = str(run_id)
                b["inputs"] = _json.dumps(b["inputs"])
                b["snapshot_ids"] = _json.dumps(b["snapshot_ids"])
            s.execute(text(
                "insert into why_bullets (run_id, player_id, rule_id, template_version, text, kind, polarity, "
                "priority, inputs, seasons, snapshot_ids, source_url) values (:run_id, :player_id, :rule_id, "
                ":template_version, :text, :kind, :polarity, :priority, cast(:inputs as jsonb), :seasons, "
                "cast(:snapshot_ids as jsonb), :source_url)"), bullets)
    return run_id


def spearman_vs_market(board: pl.DataFrame, n: int = 150) -> float | None:
    sub = (board.filter(pl.col("ecr").is_not_null() & pl.col("overall_rank").is_not_null() & ~pl.col("is_kdst"))
           .sort("ecr").head(n))
    if sub.height < 30:
        return None
    return float(spearmanr(sub["overall_rank"].to_list(), sub["ecr"].to_list()).statistic)


@cli.command("run")
def run(freeze: bool = typer.Option(False, help="Mark this run frozen (the draft-day board)")) -> None:
    """Recompute the board from stored data (no network) and persist it as a ranking run."""
    t0 = time.time()
    cfg = load_league_config()
    board, meta = build_board(cfg)
    sp = spearman_vs_market(board)
    run_id = save(board, meta, cfg, duration=round(time.time() - t0, 2), spearman=sp)
    if freeze:
        with session_scope() as s:
            s.execute(text("update ranking_runs set is_frozen = true where run_id = :r"), {"r": str(run_id)})
    typer.echo({"run_id": str(run_id), "players": board.height,
                "why_bullets": len(getattr(board, "_why_bullets", [])),
                "spearman_top150": None if sp is None else round(sp, 3),
                "flags": {f: int(board.filter(pl.col("flags").list.contains(f)).height)
                          for f in ("sleeper", "bust", "injury_prone", "rookie", "new_play_caller",
                                    "qb_uncertain_team")},
                "duration_s": round(time.time() - t0, 2), "frozen": freeze,
                "scoring": cfg.source, "weights": meta["weights"]})


@cli.command("check")
def check() -> None:
    """Phase 6 gate: Spearman(our rank, ECR) on the top 150 >= 0.80 and every top-100 player has >= 3 WHY bullets."""
    row = _q("select run_id, spearman_top150, n_players_ranked, n_why_bullets from ranking_runs "
             "where status='ok' order by started_at desc limit 1")
    if row.is_empty():
        typer.echo("GATE FAILED: no completed run — run `ff rank run` first")
        raise typer.Exit(code=1)
    r = row.to_dicts()[0]
    thin = _q(f"""select p.name, count(w.id) n from rankings k join players p on p.id = k.player_id
                  left join why_bullets w on w.run_id = k.run_id and w.player_id = k.player_id
                  where k.run_id = '{r['run_id']}' and k.overall_rank <= 100
                  group by p.name having count(w.id) < 3 order by n""")
    ok_sp = r["spearman_top150"] is not None and r["spearman_top150"] >= SPEARMAN_FLOOR
    typer.secho(f"[{'PASS' if ok_sp else 'FAIL'}] Spearman(our rank, ECR) top-150 = "
                f"{r['spearman_top150']:.3f} (floor {SPEARMAN_FLOOR})",
                fg=typer.colors.GREEN if ok_sp else typer.colors.RED)
    ok_b = thin.is_empty()
    typer.secho(f"[{'PASS' if ok_b else 'FAIL'}] every top-100 player has >= 3 WHY bullets "
                f"({thin.height} short: {thin['name'].head(8).to_list()})",
                fg=typer.colors.GREEN if ok_b else typer.colors.RED)
    typer.echo({"players": r["n_players_ranked"], "why_bullets": r["n_why_bullets"]})
    if not (ok_sp and ok_b):
        typer.echo("GATE FAILED")
        raise typer.Exit(code=1)
    typer.echo("GATE PASSED")


@cli.command("export")
def export(path: str = "draft_board.csv", limit: int = 300) -> None:
    """Cheat-sheet CSV from the latest run (works offline on draft day)."""
    df = _q(f"""select k.overall_rank, k.pos_rank, p.name, k.position, k.team, k.tier, k.value_tier,
                round(k.ppg_blend::numeric,2) ppg, round(k.season_value::numeric,1) season_value,
                round(k.vorp::numeric,1) vorp, k.ecr, k.composite_adp, k.room_adp, k.gap, k.gap_z,
                k.p_avail_next, k.vona, array_to_string(k.flags, '|') flags, f.depth_rank, f.e_games
                from rankings k join players p on p.id = k.player_id
                left join player_features f on f.player_id = k.player_id
                where k.run_id = (select run_id from ranking_runs where status='ok' order by started_at desc limit 1)
                order by k.overall_rank limit {limit}""")
    df.write_csv(path)
    typer.echo({"rows": df.height, "path": path, "generated_at": datetime.now(UTC).isoformat()})


if __name__ == "__main__":
    cli()
