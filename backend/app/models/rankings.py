"""The output of one ranking run: a board row per player and the auditable WHY bullets behind it."""
from __future__ import annotations

import uuid

from sqlalchemy import Boolean, Float, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Ranking(Base):
    __tablename__ = "rankings"

    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ranking_runs.run_id", ondelete="CASCADE"), primary_key=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), primary_key=True)

    position: Mapped[str] = mapped_column(String(4), nullable=False)
    team: Mapped[str | None] = mapped_column(String(4))
    overall_rank: Mapped[int | None] = mapped_column(Integer)
    pos_rank: Mapped[int | None] = mapped_column(Integer)
    tier: Mapped[int | None] = mapped_column(Integer)
    value_tier: Mapped[int | None] = mapped_column(Integer)

    # projection components (all points under config/league.yaml; vendor points are never stored)
    ppg_vendor: Mapped[float | None] = mapped_column(Float)
    ppg_inhouse: Mapped[float | None] = mapped_column(Float)
    ppg_inhouse_raw: Mapped[float | None] = mapped_column(Float)
    w_vendor: Mapped[float | None] = mapped_column(Float)
    w_inhouse: Mapped[float | None] = mapped_column(Float)
    bonus_pg: Mapped[float | None] = mapped_column(Float)
    ppg_blend: Mapped[float | None] = mapped_column(Float)

    # value
    e_games: Mapped[float | None] = mapped_column(Float)
    replacement_ppg: Mapped[float | None] = mapped_column(Float)
    baseline_rank: Mapped[int | None] = mapped_column(Integer)
    season_value: Mapped[float | None] = mapped_column(Float)
    vols: Mapped[float | None] = mapped_column(Float)
    vorp: Mapped[float | None] = mapped_column(Float)

    # market
    ecr: Mapped[float | None] = mapped_column(Float)
    ecr_sd: Mapped[float | None] = mapped_column(Float)
    disagreement: Mapped[float | None] = mapped_column(Float)
    yahoo_adp: Mapped[float | None] = mapped_column(Float)
    ffc_adp: Mapped[float | None] = mapped_column(Float)
    sleeper_adp: Mapped[float | None] = mapped_column(Float)
    composite_adp: Mapped[float | None] = mapped_column(Float)
    room_adp: Mapped[float | None] = mapped_column(Float)
    sd_adp: Mapped[float | None] = mapped_column(Float)
    sd_adp_source: Mapped[str | None] = mapped_column(String(8))
    our_pick_equivalent: Mapped[float | None] = mapped_column(Float)
    gap: Mapped[float | None] = mapped_column(Float)
    gap_z: Mapped[float | None] = mapped_column(Float)

    # draft-day
    p_avail_next: Mapped[float | None] = mapped_column(Float)
    vona: Mapped[float | None] = mapped_column(Float)

    flags: Mapped[list | None] = mapped_column(ARRAY(String(32)))
    signals: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    is_kdst: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    __table_args__ = (Index("ix_rankings_run_overall", "run_id", "overall_rank"),)


class WhyBullet(Base):
    """One rendered WHY line, with everything needed to reproduce it from stored inputs."""

    __tablename__ = "why_bullets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("ranking_runs.run_id", ondelete="CASCADE"), nullable=False)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    rule_id: Mapped[str] = mapped_column(String(48), nullable=False)
    template_version: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    polarity: Mapped[int] = mapped_column(Integer, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    inputs: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    seasons: Mapped[str | None] = mapped_column(String(24))
    snapshot_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    source_url: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (Index("ix_why_bullets_run_player", "run_id", "player_id", "priority"),)
