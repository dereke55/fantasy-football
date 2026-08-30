"""Provenance tables: every external pull and every ranking run is recorded here."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, Index, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RawSnapshot(Base):
    """One immutable file under data/raw/{source}/{endpoint}/{ts}_{sha8}.{ext}."""

    __tablename__ = "raw_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(64), nullable=False)      # nflverse | sleeper | yahoo_pub | ffc | ...
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)   # dataset / URL path identifier
    params: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    upstream_as_of: Mapped[str | None] = mapped_column(String(64))       # asset updated_at / last_modified / end_date
    path: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok | failed | skipped_dupe
    row_count: Mapped[int | None] = mapped_column(Integer)
    note: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_raw_snapshots_source_endpoint_fetched", "source", "endpoint", "fetched_at"),
        Index("ix_raw_snapshots_sha", "source", "endpoint", "sha256"),
    )


class RankingRun(Base):
    """Manifest for one recompute: which code, config, seeds and snapshots produced the rankings."""

    __tablename__ = "ranking_runs"

    run_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    git_sha: Mapped[str | None] = mapped_column(String(40))
    league_config_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    seed_hashes: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)   # {seed_file: sha256}
    input_snapshot_ids: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    is_frozen: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str | None] = mapped_column(Text)
