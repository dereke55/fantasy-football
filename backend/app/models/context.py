"""Curated 2026 team context. Hand-maintained YAML under backend/seeds/, loaded verbatim with provenance.

These rows produce WHY tags and the `new_play_caller` / `qb_uncertain_team` flags. They deliberately apply
NO multiplier to any projection (docs/decisions.md, 2026-08-29): vendor projections already embed 2026 context.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class TeamContext(Base):
    __tablename__ = "team_context"

    team: Mapped[str] = mapped_column(String(4), primary_key=True)

    # coaching_changes.yaml
    hc: Mapped[str | None] = mapped_column(Text)
    hc_new: Mapped[bool] = mapped_column(Boolean, default=False)
    hc_since: Mapped[int | None] = mapped_column(Integer)
    oc: Mapped[str | None] = mapped_column(Text)
    oc_new: Mapped[bool] = mapped_column(Boolean, default=False)
    dc: Mapped[str | None] = mapped_column(Text)
    dc_new: Mapped[bool] = mapped_column(Boolean, default=False)
    play_caller: Mapped[str | None] = mapped_column(Text)
    play_caller_role: Mapped[str | None] = mapped_column(String(16))
    play_caller_2025: Mapped[str | None] = mapped_column(Text)
    play_caller_new: Mapped[bool] = mapped_column(Boolean, default=False)

    # qb_situations.yaml
    projected_qb1: Mapped[str | None] = mapped_column(Text)
    qb1_2025: Mapped[str | None] = mapped_column(Text)
    qb_changed_from_2025: Mapped[bool] = mapped_column(Boolean, default=False)
    qb_status: Mapped[str | None] = mapped_column(String(16))          # settled | competition | injury_return
    qb_quality_tier: Mapped[int | None] = mapped_column(Integer)       # 1 elite .. 4 below/unknown (editorial)
    qb_backup: Mapped[str | None] = mapped_column(Text)

    # ol_changes.yaml
    ol_delta: Mapped[int | None] = mapped_column(Integer)              # -2..+2
    ol_rank_2026: Mapped[int | None] = mapped_column(Integer)
    ol_adds: Mapped[list | None] = mapped_column(JSONB)
    ol_losses: Mapped[list | None] = mapped_column(JSONB)
    ol_injuries: Mapped[list | None] = mapped_column(JSONB)
    ol_r1_pick: Mapped[str | None] = mapped_column(Text)

    # provenance (one row can cite up to three seeds)
    sources: Mapped[dict] = mapped_column(JSONB, default=dict)         # {seed: {source_url, confidence, last_checked}}
    notes: Mapped[dict] = mapped_column(JSONB, default=dict)           # {seed: notes}
    last_checked: Mapped[date | None] = mapped_column(Date)
    loaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    seed_hashes: Mapped[dict] = mapped_column(JSONB, default=dict)
    warning: Mapped[str | None] = mapped_column(Text)
