"""`ff keeper …` — the keeper decision helper."""
from __future__ import annotations

import polars as pl
import typer
import yaml

from app.config import settings
from app.ingest.players_hub import norm_name
from app.ranking.keeper_value import expected_best_by_round, keeper_table
from app.scoring.config import load_league_config

cli = typer.Typer(no_args_is_help=True, help="Keeper decision helper (surplus vs the pick a keeper costs)")

CANDIDATES = "my_keeper_candidates.yaml"


def _banner() -> None:
    cfg = load_league_config()
    if cfg.source != "yahoo_settings_page":
        typer.secho(
            f"NOTE: scoring is the placeholder '{cfg.source}' — values will shift once the real Yahoo scoring is loaded.",
            fg=typer.colors.YELLOW,
        )
    if cfg.league.my_draft_slot is None:
        typer.secho("NOTE: draft slot unknown — every round's pick is averaged over all slots (min/max shown).",
                    fg=typer.colors.YELLOW)


@cli.command("rounds")
def rounds(slot: int = typer.Option(None, help="Your draft slot 1..N; defaults to averaging every slot")) -> None:
    """What each round's pick is worth (the bar a keeper at that cost has to clear)."""
    _banner()
    pl.Config.set_tbl_rows(30)
    typer.echo(expected_best_by_round(slot=slot))


@cli.command("table")
def table(limit: int = 40, position: str = typer.Option(None, help="QB|RB|WR|TE"),
          slot: int = typer.Option(None)) -> None:
    """Every projected player's VORP and break-even keeper round (keep if cost_round >= break_even_round)."""
    _banner()
    kt = keeper_table(slot=slot)
    if position:
        kt = kt.filter(pl.col("position") == position.upper())
    pl.Config.set_tbl_rows(limit)
    pl.Config.set_tbl_width_chars(160)
    cols = ["name", "position", "team", "vendor_ppg", "e_games", "vorp", "composite_adp", "break_even_round"]
    cols += [c for c in ("ppg_2025", "td_diff_2025", "ppg_diff_2025") if c in kt.columns]
    typer.echo(kt.select(cols).head(limit))
    if "td_diff_2025" in kt.columns:
        typer.echo("\ntd_diff_2025 = 2025 touchdowns minus expected touchdowns; large positive = regression risk.")


@cli.command("value")
def value(slot: int = typer.Option(None)) -> None:
    """Evaluate the candidates in backend/seeds/my_keeper_candidates.yaml (name + cost_round)."""
    _banner()
    path = settings.seeds_dir / CANDIDATES
    doc = yaml.safe_load(path.read_text()) if path.exists() else {}
    rows = (doc or {}).get("rows") or []
    if not rows:
        typer.secho(f"No candidates yet — add rows to {path} (name + cost_round), then re-run.", fg=typer.colors.YELLOW)
        raise typer.Exit(code=0)
    kt = keeper_table(slot=slot).with_columns(nn=pl.col("name").map_elements(norm_name, return_dtype=pl.Utf8))
    out, missing = [], []
    for r in rows:
        nn = norm_name(r.get("name"))
        cost = int(r["cost_round"])
        hit = kt.filter(pl.col("nn") == nn)
        if hit.is_empty():
            missing.append(r.get("name"))
            continue
        h = hit.to_dicts()[0]
        surplus = h.get(f"surplus_r{cost}")
        out.append({
            "name": h["name"], "pos": h["position"], "team": h["team"], "cost_round": cost,
            "vorp": h["vorp"], "surplus": surplus, "break_even_round": h["break_even_round"],
            "verdict": "KEEP" if surplus is not None and surplus > 0 else "DRAFT INSTEAD",
            "adp": h["composite_adp"], "ppg_2025": h.get("ppg_2025"), "td_diff_2025": h.get("td_diff_2025"),
        })
    if missing:
        typer.secho(f"not found (check spelling against `ff keeper table`): {missing}", fg=typer.colors.RED)
    if out:
        df = pl.DataFrame(out).sort("surplus", descending=True, nulls_last=True)
        pl.Config.set_tbl_rows(50)
        pl.Config.set_tbl_width_chars(160)
        typer.echo(df)
        typer.echo("\nsurplus = VORP(player) - VORP you'd expect from the pick that keeping him costs. "
                   "Keep when surplus > 0, i.e. when cost_round >= break_even_round.")


if __name__ == "__main__":
    cli()
