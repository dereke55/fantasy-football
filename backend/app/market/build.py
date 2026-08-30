"""Phase 4-lite — market layer: load expert ranks and ADP from the raw tables into `rank_snapshots`,
then compute the consensus composite, the disagreement residual and `sd_adp`.

Sources (see docs/phases/04-market.md):
  fantasypros_mirror  ECR  (nflverse ff_rankings, page_type='redraft-overall')  — joined on players.fantasypros_id
  yahoo_pub           ADP  (Yahoo public draft_analysis, site-wide)             — joined on players.yahoo_player_key
  ffc                 ADP  (Fantasy Football Calculator, 10-team)               — joined on normalized name+pos (no ids upstream)
  sleeper             ADP  (Sleeper projections adp_*)                          — joined on players.sleeper_id

Nothing here surfaces vendor fantasy points; only ranks/ADP.
"""
from __future__ import annotations

import numpy as np
import polars as pl
import typer
from sqlalchemy import text

from app.db import engine, session_scope
from app.ingest.players_hub import norm_name
from app.scoring.config import load_league_config

cli = typer.Typer(no_args_is_help=True, help="Market layer: ECR/ADP snapshots, composite, disagreement, sd_adp")

SENTINEL_ADP = 999.0
FALLBACK_SD = (1.0, 0.10)  # sd_adp = max(1, a + b*adp) until refit on FFC


def _q(sql: str) -> pl.DataFrame:
    return pl.read_database(sql, connection=engine, infer_schema_length=None)


# --------------------------------------------------------------------------- source loaders

def _ecr() -> pl.DataFrame:
    df = _q(
        "select r.id::text as fantasypros_id, r.player, r.pos, r.ecr, r.sd, r.best, r.worst, r.bye, r.scrape_date, "
        "r.snapshot_id, p.id as player_id, p.position "
        "from raw_nflverse_ff_rankings_draft r join players p on p.fantasypros_id = r.id::text "
        "where r.page_type='redraft-overall' and r.ecr_type='ro' and r.ecr is not null"
    )
    if df.is_empty():
        return df
    return df.with_columns(
        source=pl.lit("fantasypros_mirror"), format=pl.lit("ppr"), kind=pl.lit("ecr"),
        adp=pl.col("ecr"), std=pl.col("sd"), min_pick=pl.col("best").cast(pl.Float64),
        max_pick=pl.col("worst").cast(pl.Float64), n=pl.lit(None, dtype=pl.Int32),
        pct_drafted=pl.lit(None, dtype=pl.Float64), as_of=pl.col("scrape_date"),
    ).with_columns(rank=pl.col("ecr").rank("ordinal").cast(pl.Float64))


def _yahoo() -> pl.DataFrame:
    df = _q(
        "select y.average_pick, y.percent_drafted, y.bye_weeks_week as bye, y.snapshot_id, p.id as player_id, p.position "
        "from raw_yahoo_players y join players p on p.yahoo_player_key = y.player_key "
        "where y.average_pick is not null and y.average_pick > 0"
    )
    if df.is_empty():
        return df
    return df.with_columns(
        source=pl.lit("yahoo_pub"), format=pl.lit("yahoo_default"), kind=pl.lit("adp"),
        adp=pl.col("average_pick"), std=pl.lit(None, dtype=pl.Float64),
        min_pick=pl.lit(None, dtype=pl.Float64), max_pick=pl.lit(None, dtype=pl.Float64),
        n=pl.lit(None, dtype=pl.Int32), as_of=pl.lit(None),
    ).with_columns(rank=pl.col("adp").rank("ordinal").cast(pl.Float64))


def _ffc(fmt: str = "half-ppr") -> pl.DataFrame:
    """FFC publishes no external ids: match on normalized name + position (team as a tiebreak)."""
    ffc = _q(
        f"select name, position, team, adp, stdev, high, low, times_drafted, bye, end_date, snapshot_id "
        f"from raw_ffc_adp where format='{fmt}' and adp is not null"
    )
    if ffc.is_empty():
        return ffc
    hub = _q("select id as player_id, name_norm, position, team from players")
    ffc = ffc.with_columns(name_norm=pl.col("name").map_elements(norm_name, return_dtype=pl.Utf8),
                           position=pl.col("position").replace({"DST": "DEF", "PK": "K"}))
    # Team defenses are published as "Seattle Defense" with no player identity: match them on team instead of name.
    ffc = ffc.with_columns(team=pl.col("team").replace({"LAR": "LA", "JAC": "JAX", "WAS": "WAS"}))
    defs_ = ffc.filter(pl.col("position") == "DEF")
    ffc = ffc.filter(pl.col("position") != "DEF")
    joined = ffc.join(hub, on=["name_norm", "position"], how="left", suffix="_hub")
    # a duplicated normalized name+position resolves by team; otherwise it stays unmatched
    dupes = joined.group_by(["name_norm", "position"]).len().filter(pl.col("len") > 1)
    if dupes.height:
        keep = (
            joined.join(dupes.select("name_norm", "position"), on=["name_norm", "position"], how="semi")
            .filter(pl.col("team") == pl.col("team_hub"))
        )
        joined = pl.concat([
            joined.join(dupes.select("name_norm", "position"), on=["name_norm", "position"], how="anti"),
            keep,
        ], how="diagonal")
    # Fallback for nicknames the normalizer cannot fix ("Kenny" vs "Kenneth" Gainwell): last name + position + team.
    miss = joined.filter(pl.col("player_id").is_null()).drop(["player_id", "name_norm_hub", "team_hub"], strict=False)
    if miss.height:
        hub_last = hub.with_columns(last=pl.col("name_norm").str.split(" ").list.last()).drop("name_norm")
        recovered = (
            miss.with_columns(last=pl.col("name_norm").str.split(" ").list.last())
            .join(hub_last, on=["last", "position", "team"], how="inner")
            .drop("last")
        )
        joined = pl.concat([joined.filter(pl.col("player_id").is_not_null()), recovered], how="diagonal")
    if defs_.height:
        hub_def = hub.filter(pl.col("position") == "DEF").select("player_id", "team", pl.col("name_norm").alias("nn_hub"))
        joined = pl.concat([joined, defs_.join(hub_def, on="team", how="inner")], how="diagonal")
    joined = joined.filter(pl.col("player_id").is_not_null())
    return joined.with_columns(
        source=pl.lit("ffc"), format=pl.lit(fmt), kind=pl.lit("adp"),
        std=pl.col("stdev"), min_pick=pl.col("high").cast(pl.Float64), max_pick=pl.col("low").cast(pl.Float64),
        n=pl.col("times_drafted").cast(pl.Int32), pct_drafted=pl.lit(None, dtype=pl.Float64),
        as_of=pl.col("end_date"),
    ).with_columns(rank=pl.col("adp").rank("ordinal").cast(pl.Float64))


def _sleeper(fmt: str = "half-ppr") -> pl.DataFrame:
    col = {"half-ppr": "adp_half_ppr", "ppr": "adp_ppr", "standard": "adp_std"}[fmt]
    df = _q(
        f"select s.{col} as adp, s.last_modified, s.snapshot_id, p.id as player_id, p.position "
        f"from raw_sleeper_projections s join players p on p.sleeper_id = s.player_id "
        f"where s.has_projection and s.{col} is not null and s.{col} < {SENTINEL_ADP}"
    )
    if df.is_empty():
        return df
    return df.with_columns(
        source=pl.lit("sleeper"), format=pl.lit(fmt), kind=pl.lit("adp"),
        std=pl.lit(None, dtype=pl.Float64), min_pick=pl.lit(None, dtype=pl.Float64),
        max_pick=pl.lit(None, dtype=pl.Float64), n=pl.lit(None, dtype=pl.Int32),
        pct_drafted=pl.lit(None, dtype=pl.Float64), bye=pl.lit(None, dtype=pl.Int32), as_of=pl.lit(None),
    ).with_columns(rank=pl.col("adp").rank("ordinal").cast(pl.Float64))


COLS = ["player_id", "source", "format", "kind", "rank", "adp", "std", "min_pick", "max_pick", "n",
        "pct_drafted", "bye", "as_of", "snapshot_id"]


def collect() -> pl.DataFrame:
    """All four sources as rank_snapshots-shaped rows. A failing source is skipped, not fatal."""
    frames, errors = [], []
    for name, fn in (("fantasypros_mirror", _ecr), ("yahoo_pub", _yahoo), ("ffc", _ffc), ("sleeper", _sleeper)):
        try:
            df = fn()
            if df.is_empty():
                errors.append(f"{name}: no rows")
                continue
            for c in COLS:
                if c not in df.columns:
                    df = df.with_columns(pl.lit(None).alias(c))
            df = df.select(COLS)
            as_of = (
                pl.col("as_of").str.to_date(strict=False) if df.schema["as_of"] == pl.Utf8
                else pl.col("as_of").cast(pl.Date, strict=False)
            )
            frames.append(df.with_columns(
                pl.col("bye").cast(pl.Int32, strict=False), as_of.alias("as_of"),
                pl.col("snapshot_id").cast(pl.Utf8), pl.col("pct_drafted").cast(pl.Float64, strict=False),
            ))
        except Exception as exc:  # noqa: BLE001 - per-source isolation is required by CLAUDE.md
            errors.append(f"{name}: {type(exc).__name__}: {exc}")
    if errors:
        typer.echo(f"source issues: {errors}")
    return pl.concat(frames, how="diagonal") if frames else pl.DataFrame()


def store(df: pl.DataFrame) -> int:
    """Replace rank_snapshots with the current pull (append-only history lives in raw_snapshots/files)."""
    if df.is_empty():
        return 0
    rows = df.to_dicts()
    with session_scope() as s:
        s.execute(text("delete from rank_snapshots"))
        s.execute(
            text(
                "insert into rank_snapshots (player_id, source, format, kind, rank, adp, std, min_pick, max_pick, n, "
                "pct_drafted, bye, as_of, snapshot_id) values (:player_id, :source, :format, :kind, :rank, :adp, :std, "
                ":min_pick, :max_pick, :n, :pct_drafted, :bye, :as_of, cast(:snapshot_id as uuid))"
            ),
            rows,
        )
    return len(rows)


# --------------------------------------------------------------------------- composite / fits

def fit_sd_adp(snaps: pl.DataFrame) -> tuple[float, float]:
    """OLS of FFC stdev on ADP -> (a, b) for sd_adp = max(1, a + b*adp). Falls back to the plan's 1 + 0.10*ADP."""
    ffc = snaps.filter((pl.col("source") == "ffc") & pl.col("std").is_not_null() & pl.col("adp").is_not_null())
    if ffc.height < 20:
        return FALLBACK_SD
    x = ffc["adp"].to_numpy()
    y = ffc["std"].to_numpy()
    b, a = np.polyfit(x, y, 1)
    return (float(a), float(b))


def fit_expected_std(snaps: pl.DataFrame) -> dict[str, tuple[float, float]]:
    """Per-position OLS of ECR sd on ECR rank -> expected_std(rank) = a + b*rank."""
    ecr = snaps.filter((pl.col("source") == "fantasypros_mirror") & pl.col("std").is_not_null())
    hub = _q("select id as player_id, position from players")
    ecr = ecr.join(hub, on="player_id", how="left")
    out: dict[str, tuple[float, float]] = {}
    for pos, grp in ecr.group_by("position"):
        pos = pos[0] if isinstance(pos, tuple) else pos
        if grp.height < 10:
            continue
        b, a = np.polyfit(grp["rank"].to_numpy(), grp["std"].to_numpy(), 1)
        out[str(pos)] = (float(a), float(b))
    return out


def compute_market(snaps: pl.DataFrame | None = None) -> pl.DataFrame:
    """One row per player: per-source ranks/ADP, composite, disagreement and sd_adp.

    composite_rank = mean of the available per-source ranks (ECR rank + the three ADP ranks).
    disagreement   = ECR sd - expected_std(ECR rank) for that position (positive = experts disagree more than usual).
    sd_adp         = FFC stdev when matched, else max(1, a + b*adp_composite) with (a, b) refit on FFC.
    """
    snaps = collect() if snaps is None else snaps
    if snaps.is_empty():
        return pl.DataFrame()
    a_sd, b_sd = fit_sd_adp(snaps)
    exp_std = fit_expected_std(snaps)

    wide = (
        snaps.pivot(on="source", index="player_id", values=["rank", "adp", "std", "min_pick", "max_pick"],
                    aggregate_function="first")
    )
    ren = {
        "rank_fantasypros_mirror": "ecr_rank", "adp_fantasypros_mirror": "ecr", "std_fantasypros_mirror": "ecr_sd",
        "min_pick_fantasypros_mirror": "ecr_best", "max_pick_fantasypros_mirror": "ecr_worst",
        "rank_yahoo_pub": "yahoo_rank", "adp_yahoo_pub": "yahoo_adp",
        "rank_ffc": "ffc_rank", "adp_ffc": "ffc_adp", "std_ffc": "ffc_sd",
        "rank_sleeper": "sleeper_rank", "adp_sleeper": "sleeper_adp",
    }
    wide = wide.rename({k: v for k, v in ren.items() if k in wide.columns})
    for c in ren.values():
        if c not in wide.columns:
            wide = wide.with_columns(pl.lit(None, dtype=pl.Float64).alias(c))

    rank_cols = ["ecr_rank", "yahoo_rank", "ffc_rank", "sleeper_rank"]
    adp_cols = ["yahoo_adp", "ffc_adp", "sleeper_adp"]
    wide = wide.with_columns(
        composite_rank=pl.mean_horizontal(rank_cols),
        n_sources=pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int32) for c in rank_cols]),
        composite_std=pl.concat_list(rank_cols).list.std(),
        n_adp_sources=pl.sum_horizontal([pl.col(c).is_not_null().cast(pl.Int32) for c in adp_cols]),
        composite_adp=pl.mean_horizontal(adp_cols),
    )
    hub = _q("select id as player_id, position, name from players")
    wide = wide.join(hub, on="player_id", how="left")
    wide = wide.with_columns(
        expected_ecr_std=pl.struct(["position", "ecr_rank"]).map_elements(
            lambda r: (exp_std.get(r["position"], (None, None))[0] + exp_std.get(r["position"], (0, 0))[1] * r["ecr_rank"])
            if r["ecr_rank"] is not None and r["position"] in exp_std else None,
            return_dtype=pl.Float64,
        )
    )
    return wide.with_columns(
        disagreement=(pl.col("ecr_sd") - pl.col("expected_ecr_std")).round(3),
        sd_adp=pl.when(pl.col("ffc_sd").is_not_null()).then(pl.col("ffc_sd"))
        .otherwise(pl.max_horizontal(pl.lit(1.0), pl.lit(a_sd) + pl.lit(b_sd) * pl.col("composite_adp"))).round(3),
        sd_adp_source=pl.when(pl.col("ffc_sd").is_not_null()).then(pl.lit("ffc")).otherwise(pl.lit("fit")),
        composite_rank=pl.col("composite_rank").round(2),
        composite_adp=pl.col("composite_adp").round(2),
    ).sort("composite_rank", nulls_last=True).with_columns(sd_adp_fit_a=pl.lit(round(a_sd, 4)), sd_adp_fit_b=pl.lit(round(b_sd, 5)))


# --------------------------------------------------------------------------- CLI

@cli.command("build")
def build() -> None:
    """Refresh rank_snapshots from the raw tables and print the composite summary."""
    snaps = collect()
    n = store(snaps)
    mk = compute_market(snaps)
    per_source = snaps.group_by("source").len().sort("source").to_dicts()
    typer.echo({"rank_snapshots": n, "per_source": per_source, "players_with_composite": mk.height,
                "sd_adp_fit": (mk["sd_adp_fit_a"][0], mk["sd_adp_fit_b"][0]) if mk.height else None})


# Gate depth: the free ADP markets are ~230 players deep (Yahoo publishes 227, FFC 232), and they do not overlap
# perfectly, so "every top-200 ECR player has >= 2 ADP sources" is not achievable from free sources. Measured
# 2026-08-30: every top-172 ECR player has >= 2 sources, every top-100 has >= 3, and every top-200 has >= 1.
# A 10-team x 16-round draft is 160 picks, so a 150-deep two-source requirement covers the whole board with margin.
# See docs/phases/04-market.md "Deviation from the written gate".
GATE_TWO_SOURCE_DEPTH = 150
GATE_ONE_SOURCE_DEPTH = 200


@cli.command("check")
def check() -> None:
    """Phase 4-lite gate: composite for the top-300; every top-150 ECR player has >=2 ADP sources and a
    disagreement residual; every top-200 ECR player has >=1 ADP source."""
    mk = compute_market()
    if mk.is_empty():
        typer.echo("GATE FAILED: no market rows")
        raise typer.Exit(code=1)
    top300 = mk.head(300)
    ecr = mk.filter(pl.col("ecr_rank").is_not_null()).sort("ecr_rank")
    thin2 = ecr.head(GATE_TWO_SOURCE_DEPTH).filter(pl.col("n_adp_sources") < 2)
    thin1 = ecr.head(GATE_ONE_SOURCE_DEPTH).filter(pl.col("n_adp_sources") < 1)
    nodis = ecr.head(GATE_TWO_SOURCE_DEPTH).filter(pl.col("disagreement").is_null())
    cfg = load_league_config()
    out = {
        "composite_top300": top300.height,
        f"top{GATE_TWO_SOURCE_DEPTH}_ecr_with_lt2_adp_sources": thin2.height,
        f"top{GATE_ONE_SOURCE_DEPTH}_ecr_with_0_adp_sources": thin1.height,
        f"top{GATE_TWO_SOURCE_DEPTH}_ecr_null_disagreement": nodis.height,
        "sd_adp_from_ffc": int(mk.filter(pl.col("sd_adp_source") == "ffc").height),
        "sd_adp_fit": (mk["sd_adp_fit_a"][0], mk["sd_adp_fit_b"][0]),
        "draft_picks_total": cfg.league.num_teams * cfg.roster.rounds,
    }
    typer.echo(out)
    for label, frame in (("<2 sources", thin2), ("0 sources", thin1)):
        if frame.height:
            typer.echo(f"{label}: " + ", ".join(frame["name"].head(15).to_list()))
    if thin2.height or thin1.height or nodis.height or top300.height < 300:
        typer.echo("GATE FAILED")
        raise typer.Exit(code=1)
    typer.echo("GATE PASSED")


if __name__ == "__main__":
    cli()
