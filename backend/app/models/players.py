"""Player identity hub: one row per player, keyed by our id, with every external id we can resolve."""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Player(Base):
    __tablename__ = "players"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    gsis_id: Mapped[str | None] = mapped_column(String(16), unique=True)
    esb_id: Mapped[str | None] = mapped_column(String(16))
    sleeper_id: Mapped[str | None] = mapped_column(String(16))
    espn_id: Mapped[str | None] = mapped_column(String(16))
    yahoo_id: Mapped[str | None] = mapped_column(String(16))
    fantasypros_id: Mapped[str | None] = mapped_column(String(16))
    pfr_id: Mapped[str | None] = mapped_column(String(16))
    otc_id: Mapped[str | None] = mapped_column(String(16))
    stats_id: Mapped[str | None] = mapped_column(String(16))
    yahoo_player_key: Mapped[str | None] = mapped_column(String(24))   # e.g. 461.p.12345 (DEF: 461.p.1000NN)

    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_norm: Mapped[str] = mapped_column(String(80), nullable=False)  # lowercase, no punctuation/suffix
    first_name: Mapped[str | None] = mapped_column(String(40))
    last_name: Mapped[str | None] = mapped_column(String(40))
    position: Mapped[str] = mapped_column(String(4), nullable=False)      # QB RB WR TE K DEF
    team: Mapped[str | None] = mapped_column(String(4))                   # nflverse abbr from the 2026 roster (canonical)
    status: Mapped[str | None] = mapped_column(String(8))                 # roster status (ACT/RES/...)
    birth_date: Mapped[date | None] = mapped_column(Date)
    years_exp: Mapped[int | None] = mapped_column(Integer)
    draft_year: Mapped[int | None] = mapped_column(Integer)
    draft_round: Mapped[int | None] = mapped_column(Integer)
    draft_pick: Mapped[int | None] = mapped_column(Integer)               # overall
    draft_team: Mapped[str | None] = mapped_column(String(4))
    is_rookie: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    college: Mapped[str | None] = mapped_column(String(80))
    match_sources: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {source: how_matched}
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        Index("ix_players_name_norm_pos", "name_norm", "position"),
        Index("ix_players_yahoo_id", "yahoo_id"),
        Index("ix_players_sleeper_id", "sleeper_id"),
        Index("ix_players_fantasypros_id", "fantasypros_id"),
    )
