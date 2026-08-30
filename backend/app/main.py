from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api import board, players
from app.db import engine

app = FastAPI(title="Fantasy Football Draft Board", version="0.1.0")
app.include_router(players.router)
app.include_router(board.router)


@app.get("/health")
@app.get("/api/health")
def health() -> dict:
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
        db_ok = True
    except SQLAlchemyError:  # reported in the payload, not raised
        db_ok = False
    return {"status": "ok" if db_ok else "degraded", "db": db_ok}
