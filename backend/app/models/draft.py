"""Draft-side tables: the league being drafted, keepers, the pick schedule (with keeper holes) and picks made."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LeagueRow(Base):
    __tablename__ = "leagues"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    platform: Mapped[str] = mapped_column(String(16), nullable=False, default="yahoo")
    league_key: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str | None] = mapped_column(String(120))
    num_teams: Mapped[int] = mapped_column(Integer, nullable=False)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False)
    draft_type: Mapped[str] = mapped_column(String(16), nullable=False, default="snake")
    draft_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    draft_status: Mapped[str] = mapped_column(String(16), nullable=False, default="predraft")  # predraft|draft|postdraft
    draft_order: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)  # {"1": {"team_key":..., "name":...}, ...}
    my_team_slot: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Keeper(Base):
    __tablename__ = "keepers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False)
    team_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id"), nullable=False)
    cost_round: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="declared")  # declared|approved
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")    # manual|yahoo
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("league_id", "team_slot", "cost_round", name="uq_keepers_slot_round"),
        UniqueConstraint("league_id", "player_id", name="uq_keepers_player"),
    )


class PickSlot(Base):
    """Materialized snake schedule; keeper-consumed slots are flagged (Yahoo skips that team in that round)."""

    __tablename__ = "pick_schedule"

    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), primary_key=True)
    overall_pick: Mapped[int] = mapped_column(Integer, primary_key=True)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    team_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    is_keeper_slot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    keeper_player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    live_pick_no: Mapped[int | None] = mapped_column(Integer)  # 1..N over non-keeper slots; null for keeper slots


class DraftPick(Base):
    __tablename__ = "draft_picks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    league_id: Mapped[int] = mapped_column(ForeignKey("leagues.id", ondelete="CASCADE"), nullable=False)
    overall_pick: Mapped[int] = mapped_column(Integer, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    team_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[int | None] = mapped_column(ForeignKey("players.id"))
    external_player_key: Mapped[str | None] = mapped_column(String(32))  # Yahoo player_key when unresolved
    is_keeper: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source: Mapped[str] = mapped_column(String(12), nullable=False, default="manual")  # manual|yahoo
    picked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    undone_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("ix_draft_picks_league_pick", "league_id", "overall_pick"),
        Index("uq_draft_picks_active", "league_id", "overall_pick", unique=True, postgresql_where="undone_at IS NULL"),
    )
