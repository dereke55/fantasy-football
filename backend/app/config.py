"""Application settings (env / .env). Never hardcode credentials here."""
from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / "backend" / ".env", extra="ignore")

    database_url: str
    data_dir: Path = REPO_ROOT / "data"
    league_config: Path = REPO_ROOT / "config" / "league.yaml"
    seeds_dir: Path = REPO_ROOT / "backend" / "seeds"
    yahoo_client_id: str | None = None
    yahoo_client_secret: str | None = None
    github_token: str | None = None
    # Guard: after NFL kickoff (2026-09-10) upstream sources change semantics; ingest requires --post-kickoff.
    kickoff_date: str = "2026-09-10"
    # Seasons are ALWAYS explicit (nflreadpy's default flips on kickoff day).
    history_seasons: list[int] = [2023, 2024, 2025]
    current_season: int = 2026


settings = Settings()
