"""Market layer: one immutable row per (player, source, format, snapshot) of expert ranks and ADP."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RankSnapshot(Base):
    __tablename__ = "rank_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[int] = mapped_column(ForeignKey("players.id", ondelete="CASCADE"), nullable=False)
    source: Mapped[str] = mapped_column(String(24), nullable=False)   # fantasypros_mirror | yahoo_pub | ffc | sleeper
    format: Mapped[str] = mapped_column(String(16), nullable=False)   # ppr | half-ppr | standard | yahoo_default
    kind: Mapped[str] = mapped_column(String(8), nullable=False)      # ecr | adp
    rank: Mapped[float | None] = mapped_column(Float)                 # rank within the source (1 = best)
    adp: Mapped[float | None] = mapped_column(Float)                  # raw ADP / ECR average as published
    std: Mapped[float | None] = mapped_column(Float)
    min_pick: Mapped[float | None] = mapped_column(Float)
    max_pick: Mapped[float | None] = mapped_column(Float)
    n: Mapped[int | None] = mapped_column(Integer)                    # experts / drafts behind the number
    pct_drafted: Mapped[float | None] = mapped_column(Float)
    bye: Mapped[int | None] = mapped_column(Integer)
    as_of: Mapped[date | None] = mapped_column(Date)
    snapshot_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("player_id", "source", "format", "snapshot_id", name="uq_rank_snapshots_player_source_snap"),
        Index("ix_rank_snapshots_source_asof", "source", "format", "as_of"),
    )
