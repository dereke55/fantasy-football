"""Snapshot-first ingestion primitives.

Every external pull goes through `write_snapshot`: bytes are written to
data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext} and registered in `raw_snapshots`.
Identical content (same sha256 for the same source/endpoint) is recorded as `skipped_dupe` and not re-written.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.models.core import RawSnapshot

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(s: str) -> str:
    return _SAFE.sub("_", s).strip("_")[:120]


@dataclass(frozen=True)
class SnapshotResult:
    snapshot: RawSnapshot
    path: Path
    is_new: bool


def write_snapshot(
    session: Session,
    *,
    source: str,
    endpoint: str,
    content: bytes,
    ext: str,
    params: dict | None = None,
    upstream_as_of: str | None = None,
    row_count: int | None = None,
    fetched_at: datetime | None = None,
    note: str | None = None,
) -> SnapshotResult:
    fetched_at = fetched_at or datetime.now(UTC)
    sha = hashlib.sha256(content).hexdigest()
    existing = session.execute(
        select(RawSnapshot).where(
            RawSnapshot.source == source,
            RawSnapshot.endpoint == endpoint,
            RawSnapshot.sha256 == sha,
            RawSnapshot.status == "ok",
        ).order_by(RawSnapshot.fetched_at.desc())
    ).scalars().first()
    if existing is not None:
        dupe = RawSnapshot(
            source=source, endpoint=endpoint, params=params or {}, fetched_at=fetched_at, sha256=sha,
            bytes=len(content), upstream_as_of=upstream_as_of, path=existing.path, status="skipped_dupe",
            row_count=row_count, note=f"identical to {existing.id}",
        )
        session.add(dupe)
        session.flush()
        return SnapshotResult(existing, Path(existing.path), False)

    directory = settings.data_dir / "raw" / _safe(source) / _safe(endpoint)
    directory.mkdir(parents=True, exist_ok=True)
    fname = f"{fetched_at.strftime('%Y%m%dT%H%M%SZ')}_{sha[:8]}.{ext.lstrip('.')}"
    path = directory / fname
    path.write_bytes(content)
    snap = RawSnapshot(
        source=source, endpoint=endpoint, params=params or {}, fetched_at=fetched_at, sha256=sha,
        bytes=len(content), upstream_as_of=upstream_as_of, path=str(path), status="ok",
        row_count=row_count, note=note,
    )
    session.add(snap)
    session.flush()
    return SnapshotResult(snap, path, True)


def record_failure(session: Session, *, source: str, endpoint: str, params: dict | None, error: str) -> None:
    session.add(
        RawSnapshot(
            source=source, endpoint=endpoint, params=params or {}, fetched_at=datetime.now(UTC),
            sha256="", bytes=0, path="", status="failed", note=error[:2000],
        )
    )
    session.flush()


def latest_snapshot(session: Session, source: str, endpoint: str) -> RawSnapshot | None:
    return session.execute(
        select(RawSnapshot)
        .where(RawSnapshot.source == source, RawSnapshot.endpoint == endpoint, RawSnapshot.status == "ok")
        .order_by(RawSnapshot.fetched_at.desc())
    ).scalars().first()


DEFAULT_HEADERS = {
    "User-Agent": "ff-draft-board/0.1 (personal, single-league draft tool; contact via GitHub)",
    "Accept": "application/json, */*;q=0.5",
}


def http_get(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: float = 60.0) -> httpx.Response:
    """GET with sane defaults and retries on transient errors (429/5xx/network)."""
    import time

    last: Exception | None = None
    for attempt in range(4):
        try:
            with httpx.Client(timeout=timeout, follow_redirects=True, headers={**DEFAULT_HEADERS, **(headers or {})}) as c:
                r = c.get(url, params=params)
            if r.status_code in (429, 500, 502, 503, 504):
                raise httpx.HTTPStatusError(f"{r.status_code} from {url}", request=r.request, response=r)
            r.raise_for_status()
            return r
        except (httpx.TransportError, httpx.HTTPStatusError) as e:
            last = e
            time.sleep(2 ** attempt)
    assert last is not None
    raise last


def dumps(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
