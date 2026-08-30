# Fantasy Football Draft Board / Monitor / Prediction Tool

A draft-prep and draft-day tool for a 10-team Yahoo keeper league (snake, standard 1-QB). It ranks every draftable
player under the league's own scoring with a justified **WHY** built from real, auditable signals — 2023–2025
performance and trends, 2026 team context (coaching / play-caller changes, QB rooms, offensive line), injury history,
sleeper/bust flags — and runs a draft-day board with best-available, tiers, keeper-aware pick schedule and
"will they be there at my next pick" odds. Yahoo live sync is optional; manual pick entry is first-class.

Plan and progress: [`docs/PLAN.md`](docs/PLAN.md) (overview, MVP cut line, calendar) and the per-phase checklists in
[`docs/phases/`](docs/phases/). Specs in [`docs/spec/`](docs/spec/). Decisions in [`docs/decisions.md`](docs/decisions.md).

## Stack

- **Backend** `backend/` — Python 3.12, FastAPI, SQLAlchemy 2 + Alembic, polars, httpx, typer CLI; managed with `uv`.
- **Frontend** `frontend/` — Vite + React + TypeScript, Tailwind v4, TanStack Query/Table; dark theme only.
- **Database** — local Postgres 17 (docker container `postgres`, database `fantasy_football`).
- **Data** — `data/raw/{source}/{endpoint}/{timestamp}_{sha8}.{ext}` immutable snapshots (gitignored), registered in `raw_snapshots`.

## Quick start

```bash
# backend (from repo root)
cd backend
cp .env.example .env            # set DATABASE_URL (local docker postgres) and, later, Yahoo client id/secret
uv sync
uv run alembic upgrade head
uv run ff health                # {'status': 'ok', 'db': True}
uv run uvicorn app.main:app --reload --port 8000

# frontend
cd frontend
pnpm install
pnpm dev                        # http://localhost:5173 (proxies /api -> :8000)
```

League configuration lives in [`config/league.yaml`](config/league.yaml) (scoring, roster, teams, keeper rules, draft
date/slot). It is currently a **labeled placeholder** (Yahoo default scoring) until the real league settings are pasted in.

## CLI (`uv run ff …`)

| Command | Purpose |
|---|---|
| `ff health` | DB connectivity |
| `ff ingest …` | Pull sources into snapshots + Postgres (Phase 1a) |
| `ff ingest check-ids` | Crosswalk gate: top-N of every source resolves to a player id |
| `ff recompute` | Scoring → features → rankings → WHY from stored snapshots, no network (< 5 min) |
| `ff freeze` | Pin the draft-day snapshot to a run id + config hash |

(Commands are added as their phase lands; see `docs/phases/`.)

## Data sources, cadence, licensing

| Source | What | Access | Cadence | Terms / notes |
|---|---|---|---|---|
| nflverse via `nflreadpy` | 2023–2025 weekly/season player stats, expected fantasy stats (`ff_opportunity`), injuries, weekly rosters; 2026 rosters, depth charts, schedule, draft picks; `ff_playerids` crosswalk; `ff_rankings` (FantasyPros ECR mirror) | Python package / GitHub release assets | daily during draft week | CC-BY-4.0 — "Data from nflverse" attribution. Always pass explicit seasons. |
| Sleeper | 2026 season projections (Rotowire stat lines) + ADP; player master with injury status | unofficial public JSON | projections ≤ hourly cache; players once/day | Undocumented endpoints; snapshot every pull |
| Yahoo (public) | Site-wide ADP (`draft_analysis`) incl. rookies, bye weeks | unofficial public JSON (`pub-api-ro`) | once/day, never during the draft | Unofficial; sanctioned equivalent is the OAuth API |
| Yahoo Fantasy Sports API | League settings diff, live draft results (Phase 8b) | OAuth2 (reviewed access application) | 10–15 s during the draft | Yahoo API Terms; "Fantasy data provided by Yahoo Fantasy" |
| Fantasy Football Calculator | ADP with stdev/high/low | official free API | daily | Attribution: ADP data from fantasyfootballcalculator.com |
| FantasyPros | Expert consensus (via nflverse mirror) | mirror only in MVP | daily | Personal use only; never exported or redistributed |

Rule: a new source is added to this table together with its snapshot parser before it is used anywhere.

## Testing

`uv run pytest` — tests use only real snapshot extracts under `backend/tests/fixtures/{source}/` with a `PROVENANCE.md`
(URL, fetched_at, sha256). No mock or invented data.
