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
- **Frontend** `frontend/` — Vite + React 19 + TypeScript, Tailwind v4, TanStack Query, `@tanstack/react-virtual`; dark theme only.
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
pnpm dev                        # http://localhost:5190 (proxies /api -> :8000)
pnpm build                      # tsc -b && vite build
```

`vite.config.ts` pins the dev server to **5190** with `strictPort`, so a stale instance fails loudly instead of
silently moving to another port. The board needs the API on :8000; without it the page shows the "API is not
answering" state with the uvicorn command and a Retry button.

League configuration lives in [`config/league.yaml`](config/league.yaml) (scoring, roster, teams, keeper rules, draft
date/slot). It is currently a **labeled placeholder** (Yahoo default scoring) until the real league settings are pasted in.

## Draft board (Phase 7)

Single dark page at the Vite dev URL. Three regions: the **top bar** (mode, on-the-clock, "my next pick in N" with the
back-to-back pair for slot 10 of 10, picks made/total, run id + config hash, CSV export), the **board** (all 631 ranked
players, virtualised) with a filter rail on the left, and a **right panel** with a Draft tab, a Teams tab and a Keepers
tab. Selecting a row and pressing Enter slides the **player drawer** over the panel: WHY bullets with rule id / period /
source link, the 3-season PPG line, key metrics, the market table and the curated team context.

The **Teams tab** is the anti-drift check for a hand-entered draft. It reconstructs all ten rosters in pick order —
round/pick, position, name, NFL team, `K` badge for keepers — plus each team's starters filled against the league's slot
requirements, and compares every team's pick count with what the snake says it should be by now (`T4 has 3, expected 4`).
A team's roster comes from `/api/rankings` grouped on `drafted_by`; the round and pick of each entry come from
`/api/schedule`, because a pick is always stamped with the next unfilled live slot, so the n-th pick recorded is the
n-th live slot of the snake. Keepers come from `/api/keepers` and sit in the schedule hole their cost round cut, so they
show up before pick 1. The one fact the app cannot derive — how many picks Yahoo has actually completed — is a small
input in the header; typing it turns "picks recorded" into a real comparison. Clicking any player highlights him on the
board.

Board columns, left to right: rank (+ positional rank), player, tier, value tier, pos, team, bye, proj PPG · season,
value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags. Tier bands rule the board while it is sorted by rank;
value-tier breaks are a dashed rule. Drafted rows stay in place, dimmed and struck through, with the drafting team
(`→ T3`), a `K` badge for keepers and a filled marker for my own picks — "hide drafted" is off by default.

### Keyboard

| Key | Action |
|---|---|
| `j` / `k` | move the highlight down / up |
| `d` | mark the highlighted player drafted |
| `m` | mark the highlighted player as my pick |
| `u` | undo the last manual pick |
| `Enter` | open / close the player drawer |
| `Esc` | close the drawer, or leave the search box |
| `/` | focus the search box |

Shortcuts are ignored while focus is in a text input or a select, so typing a player's name never drafts anyone.
`d` and `m` never prompt — undo is the recovery path.

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
