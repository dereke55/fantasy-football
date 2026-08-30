"""League configuration (config/league.yaml) — scoring, roster, keeper and draft parameters."""
from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.config import settings

STAT_KEYS: tuple[str, ...] = (
    "pass_yd", "pass_td", "pass_int", "pass_2pt",
    "rush_yd", "rush_td", "rush_2pt",
    "rec", "rec_yd", "rec_td", "rec_2pt",
    "fum_lost", "ret_td",
)
YARDAGE_KEYS = frozenset({"pass_yd", "rush_yd", "rec_yd"})


class Bonus(BaseModel):
    stat: str
    threshold: float
    points: float


class Scoring(BaseModel):
    uses_fractional_points: bool = True
    uses_negative_points: bool = True
    pass_yd: float = 0.0
    pass_td: float = 0.0
    pass_int: float = 0.0
    pass_2pt: float = 0.0
    rush_yd: float = 0.0
    rush_td: float = 0.0
    rush_2pt: float = 0.0
    rec: float = 0.0
    rec_yd: float = 0.0
    rec_td: float = 0.0
    rec_2pt: float = 0.0
    fum_lost: float = 0.0
    ret_td: float = 0.0
    bonus_mode: str = "cumulative"   # cumulative = every threshold crossed fires; highest = only the top tier
    bonuses: list[Bonus] = Field(default_factory=list)
    position_overrides: dict[str, dict[str, float]] = Field(default_factory=dict)
    kicker: dict[str, float] = Field(default_factory=dict)
    defense: dict[str, object] = Field(default_factory=dict)

    def weights_for(self, position: str | None) -> dict[str, float]:
        w = {k: getattr(self, k) for k in STAT_KEYS}
        if position and position in self.position_overrides:
            w.update(self.position_overrides[position])
        return w


class Keepers(BaseModel):
    max_per_team: int | None = None
    cost_rule: str = "round_drafted"
    deadline: str | None = None
    assigned_in_yahoo: bool | None = None


class League(BaseModel):
    platform: str = "yahoo"
    league_key: str | None = None
    num_teams: int = 10
    draft_type: str = "snake"
    draft_datetime: str | None = None
    my_draft_slot: int | None = None
    keepers: Keepers = Field(default_factory=Keepers)


class Roster(BaseModel):
    slots: dict[str, int]
    flex_eligible: list[str] = Field(default_factory=lambda: ["RB", "WR", "TE"])
    bench: int = 6
    ir: int = 0

    @property
    def rounds(self) -> int:
        return sum(self.slots.values()) + self.bench


class LeagueConfig(BaseModel):
    source: str
    source_url: str | None = None
    as_of: str | date | None = None
    league: League
    roster: Roster
    scoring: Scoring


def load_league_config(path: Path | None = None) -> LeagueConfig:
    p = path or settings.league_config
    with open(p) as f:
        data = yaml.safe_load(f)
    return LeagueConfig.model_validate(data)


def league_config_sha256(path: Path | None = None) -> str:
    p = path or settings.league_config
    return hashlib.sha256(p.read_bytes()).hexdigest()
