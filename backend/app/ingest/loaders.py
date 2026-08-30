"""Load polars frames into Postgres "raw_*" tables that mirror upstream schemas.

Raw tables are created/extended by the loader (not Alembic) so upstream column sets are preserved verbatim.
Idempotency = partition replace: rows matching the partition key values are deleted, then the frame is appended.
Every row carries `snapshot_id` (raw_snapshots.id) so any number is traceable to the file it came from.
"""
from __future__ import annotations

import uuid
from collections.abc import Sequence

import polars as pl
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session


def _pg_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def _pg_type(dtype: pl.DataType) -> str:
    if dtype in (pl.Int8, pl.Int16, pl.Int32, pl.UInt8, pl.UInt16):
        return "integer"
    if dtype in (pl.Int64, pl.UInt32, pl.UInt64):
        return "bigint"
    if dtype in (pl.Float32, pl.Float64):
        return "double precision"
    if dtype == pl.Boolean:
        return "boolean"
    if dtype == pl.Date:
        return "date"
    if isinstance(dtype, pl.Datetime):
        return "timestamp with time zone" if dtype.time_zone else "timestamp"
    if isinstance(dtype, (pl.List, pl.Struct, pl.Array)):
        return "jsonb"
    return "text"


def _normalize(df: pl.DataFrame) -> pl.DataFrame:
    """Nested columns -> JSON strings (stored as jsonb); categoricals -> text; Null dtype -> text."""
    exprs = []
    for name, dtype in df.schema.items():
        if isinstance(dtype, (pl.List, pl.Struct, pl.Array)):
            exprs.append(pl.col(name).map_elements(lambda v: pl.Series([v]).to_list()[0], return_dtype=pl.Object).alias(name))
        elif dtype in (pl.Categorical, pl.Enum, pl.Null):
            exprs.append(pl.col(name).cast(pl.Utf8).alias(name))
    if exprs:
        df = df.with_columns(exprs)
    return df


def ensure_table(session: Session, table: str, df: pl.DataFrame) -> None:
    """Create the table if missing; add any new columns (never drops/changes existing ones)."""
    insp = inspect(session.get_bind())
    if not insp.has_table(table):
        cols = ", ".join(f"{_pg_ident(c)} {_pg_type(t)}" for c, t in df.schema.items())
        session.execute(text(f"CREATE TABLE {_pg_ident(table)} ({cols})"))
        return
    existing = {c["name"] for c in insp.get_columns(table)}
    for c, t in df.schema.items():
        if c not in existing:
            session.execute(text(f"ALTER TABLE {_pg_ident(table)} ADD COLUMN {_pg_ident(c)} {_pg_type(t)}"))


def replace_partition(
    session: Session,
    table: str,
    df: pl.DataFrame,
    *,
    partition: Sequence[str],
    snapshot_id: uuid.UUID | None,
    batch_size: int = 5000,
) -> int:
    """Delete rows whose partition-key values appear in `df`, then insert `df`. Returns inserted row count."""
    import json

    if snapshot_id is not None:
        df = df.with_columns(pl.lit(str(snapshot_id)).alias("snapshot_id"))
    ensure_table(session, table, df)
    if not partition:
        session.execute(text(f"DELETE FROM {_pg_ident(table)}"))  # empty partition key = full replace
    elif df.height:
        keys = df.select(partition).unique()
        where = " AND ".join(f"{_pg_ident(k)} = :{k}" for k in partition)
        for row in keys.iter_rows(named=True):
            session.execute(text(f"DELETE FROM {_pg_ident(table)} WHERE {where}"), row)
    if not df.height:
        return 0
    cols = list(df.columns)
    json_cols = {c for c, t in df.schema.items() if isinstance(t, (pl.List, pl.Struct, pl.Array))}
    col_sql = ", ".join(_pg_ident(c) for c in cols)
    val_sql = ", ".join(f"CAST(:{c} AS jsonb)" if c in json_cols else f":{c}" for c in cols)
    stmt = text(f"INSERT INTO {_pg_ident(table)} ({col_sql}) VALUES ({val_sql})")
    n = 0
    for start in range(0, df.height, batch_size):
        chunk = df.slice(start, batch_size)
        rows = chunk.to_dicts()
        if json_cols:
            for r in rows:
                for c in json_cols:
                    r[c] = json.dumps(r[c], default=str) if r[c] is not None else None
        session.execute(stmt, rows)
        n += len(rows)
    return n


def read_snapshot_parquet(path: str) -> pl.DataFrame:
    return pl.read_parquet(path)
