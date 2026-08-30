"""nflverse via nflreadpy: fetch a dataset with EXPLICIT seasons, snapshot it as parquet, register, return the frame.

Rule (see CLAUDE.md): never call a load_* function without `seasons=`; nflreadpy's default season flips on kickoff day.
Freshness: `asset_updated_at` reads the GitHub release asset timestamp so re-ingest can be skipped when unchanged.
"""
from __future__ import annotations

import io
import os
from collections.abc import Callable
from typing import Any

import polars as pl
from sqlalchemy.orm import Session

from app.config import settings
from app.ingest.snapshots import SnapshotResult, http_get, write_snapshot

os.environ.setdefault("NFLREADPY_CACHE", "off")  # our snapshot layer is the cache

SOURCE = "nflverse"
RELEASES_API = "https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}"


def asset_updated_at(tag: str, asset_name: str) -> str | None:
    """GitHub release asset `updated_at` (ISO) or None. Uses GITHUB_TOKEN when present (60/h unauthenticated)."""
    headers = {"Accept": "application/vnd.github+json"}
    if settings.github_token:
        headers["Authorization"] = f"Bearer {settings.github_token}"
    try:
        r = http_get(RELEASES_API.format(tag=tag), headers=headers, timeout=30)
    except Exception:  # noqa: BLE001 - freshness is advisory
        return None
    for a in r.json().get("assets", []):
        if a.get("name") == asset_name:
            return a.get("updated_at")
    return None


def snapshot_frame(
    session: Session,
    *,
    endpoint: str,
    df: pl.DataFrame,
    params: dict[str, Any],
    upstream_as_of: str | None = None,
) -> SnapshotResult:
    buf = io.BytesIO()
    df.write_parquet(buf)
    return write_snapshot(
        session, source=SOURCE, endpoint=endpoint, content=buf.getvalue(), ext="parquet",
        params=params, upstream_as_of=upstream_as_of, row_count=df.height,
    )


def fetch_dataset(
    session: Session,
    *,
    endpoint: str,
    loader: Callable[..., pl.DataFrame],
    seasons: list[int] | None,
    upstream_as_of: str | None = None,
    **kwargs: Any,
) -> tuple[pl.DataFrame, SnapshotResult]:
    """Call `loader(seasons=..., **kwargs)` (or `loader(**kwargs)` for season-less datasets) and snapshot the result."""
    if seasons is not None:
        df = loader(seasons=seasons, **kwargs)
        params = {"seasons": seasons, **kwargs}
    else:
        df = loader(**kwargs)
        params = dict(kwargs)
    if not isinstance(df, pl.DataFrame):
        df = pl.DataFrame(df)
    snap = snapshot_frame(session, endpoint=endpoint, df=df, params=params, upstream_as_of=upstream_as_of)
    return df, snap
