"""`ff` command line: ingestion, checks, recompute, freeze."""
from __future__ import annotations

import typer

app = typer.Typer(no_args_is_help=True, help="Fantasy football draft tool CLI")
ingest_app = typer.Typer(no_args_is_help=True, help="Ingest external sources into snapshots + Postgres")
app.add_typer(ingest_app, name="ingest")


@app.command()
def recompute(freeze: bool = typer.Option(False, help="Freeze the resulting run as the draft-day board")) -> None:
    """Rebuild everything downstream of the raw tables: features -> market -> ranking (no network).

    The runbook has always described this step, but it was never a command, so the daily job was three separate
    invocations and it was possible -- and easy -- to run `ingest all` then `rank run` and silently rebuild the
    board on the PREVIOUS pull's ADP: `rank run` reads `rank_snapshots`, and only `market build` refreshes it
    from the raw tables. Doing it in one command removes the chance of half-refreshing the board on draft day.
    """
    import time

    from app.features import build as features_build
    from app.market import build as market_build
    from app.ranking import pipeline as ranking_pipeline

    t0 = time.time()
    # pass real values: calling a typer-decorated function bare hands it the OptionInfo defaults
    typer.echo("features ..."); features_build.build(seasons=None)
    typer.echo("market   ..."); market_build.build()
    typer.echo("ranking  ..."); ranking_pipeline.run(freeze=freeze)
    typer.echo({"recompute_seconds": round(time.time() - t0, 1), "frozen": freeze})


@app.command()
def health() -> None:
    """Check database connectivity."""
    from app.main import health as _health

    typer.echo(_health())


def _mount() -> None:
    from app.context import build as context_build
    from app.features import build as features_build
    from app.ingest import ffc, nflverse_ref, nflverse_stats, players_hub, sleeper, yahoo_pub
    from app.market import build as market_build
    from app.ranking import keeper_cli, league_cli
    from app.ranking import pipeline as ranking_pipeline

    ingest_app.add_typer(nflverse_stats.cli, name="nflverse-stats")
    ingest_app.add_typer(nflverse_ref.cli, name="nflverse-ref")
    ingest_app.add_typer(sleeper.cli, name="sleeper")
    ingest_app.add_typer(ffc.cli, name="ffc")
    ingest_app.add_typer(yahoo_pub.cli, name="yahoo-pub")
    ingest_app.add_typer(players_hub.cli, name="players")
    app.add_typer(market_build.cli, name="market")
    app.add_typer(keeper_cli.cli, name="keeper")
    app.add_typer(league_cli.cli, name="league")
    app.add_typer(context_build.cli, name="context")
    app.add_typer(features_build.cli, name="features")
    app.add_typer(ranking_pipeline.cli, name="rank")


_mount()


@ingest_app.command("check-ids")
def check_ids() -> None:
    """Phase 1a gate: crosswalk resolves the top-N of every source (alias of `ingest players check-ids`)."""
    from app.ingest.players_hub import check_ids as _check

    _check()


@ingest_app.command("all")
def ingest_all(post_kickoff: bool = typer.Option(False, help="Required after 2026-09-10 (upstream semantics change)")) -> None:
    """Run every 1a loader (each isolated), then rebuild the players hub and run the id gate."""
    from datetime import UTC, datetime

    from app.config import settings

    today = datetime.now(UTC).date().isoformat()
    if today >= settings.kickoff_date and not post_kickoff:
        typer.echo(f"Refusing: today {today} >= kickoff {settings.kickoff_date}; pass --post-kickoff (see docs/runbook-draft-week.md)")
        raise typer.Exit(code=2)
    import subprocess
    import sys

    for mod in ("nflverse_stats", "nflverse_ref", "sleeper", "ffc", "yahoo_pub"):
        typer.echo(f"== {mod}")
        subprocess.run([sys.executable, "-m", f"app.ingest.{mod}", "all"], check=False)
    subprocess.run([sys.executable, "-m", "app.ingest.players_hub", "build"], check=False)
    subprocess.run([sys.executable, "-m", "app.ingest.players_hub", "check-ids"], check=False)


if __name__ == "__main__":
    app()
