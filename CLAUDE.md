# CLAUDE.md — working rules for this repo

Read `docs/PLAN.md` first; it has the MVP cut line, gates and calendar. Track progress by ticking the checklists in
`docs/phases/NN-*.md` and log non-obvious choices in `docs/decisions.md`. Keep this file and `README.md` current.

## Hard rules
- **Real data only.** No mock/fake players, stat lines or fixtures. Tests use real snapshot extracts under
  `backend/tests/fixtures/{source}/` with a `PROVENANCE.md` (URL, fetched_at, sha256); expected values are hand-computed from those rows.
- **Explicit seasons everywhere.** Every `nflreadpy.load_*` call passes `seasons=[...]`; `get_current_season()` flips to 2026 on
  2026-09-10 and would 404. Historical features use `season_type == 'REG'` only (raw tables keep POST rows).
- **Never surface vendor fantasy points.** All points come from `app/scoring` applied to raw stat lines (historical, expected, projections) under `config/league.yaml`.
- **Snapshot first.** Every external pull is written to `data/raw/{source}/{endpoint}/{ts}_{sha8}.{ext}` and registered in `raw_snapshots`
  (content-hash dedupe) before it is loaded. One failing source never fails the whole ingest. The app runs on the last good snapshot.
- **Auditable WHY.** Every `why_bullets` row stores rule_id, template version, numeric inputs, snapshot ids and source_url; rankings carry a `ranking_runs.run_id`.
- **New data source ⇒** a row in the README sources table + a snapshot parser + a fixture, before use. Do not scrape Pro Football Reference or Spotrac (blocked, ToS).
- **Model decisions are fixed for this draft** (see `docs/decisions.md`): per-game blend, adjustments only on the in-house component, one E[games], keepers as
  `pick_schedule` holes, room ADP, FFC stdev, 1-D fixed-k GMM tiers, SoS display-only, contract tags informational.
- After 2026-09-10 ingest requires `--post-kickoff`; the frozen `draft_snapshot` is never overwritten implicitly.

## Layout
`backend/app/{api,models,ingest,scoring,features,ranking,why,live}` · `backend/seeds/*.yaml` (curated tables with source_url per row) ·
`backend/alembic` · `config/league.yaml` · `docs/{PLAN.md,phases,spec,runbook-draft-week.md,decisions.md}`.

`frontend/src`: `api/{types,client,queries}.ts` (typed contract mirror, fetch layer that preserves the FastAPI `detail`
string, TanStack Query keys from `docs/spec/ui.md` §10) · `lib/{format,positions,flags,boardModel,teamsModel}.ts` (number rules,
position hues, flag registry, filter/sort/tier-band assembly, per-team roster reconstruction + drift check) · `components/*` (one concern per file; `App.tsx` is the
composition root and owns filters, sort, highlight, drawer and the keyboard).

Frontend rules: dark theme only, extend the CSS variables in `src/index.css` rather than replacing them. Numbers are
right-aligned tabular figures — one decimal for PPG/ECR/ADP, integers for season points and gap, percent for P(avail),
em dash for null. Flags always render as icon + label, never colour alone. The board never computes points and never
references a vendor points field (`grep -r 'pts_ppr\|pts_half_ppr\|pts_std' frontend/src` must stay empty).
Keyboard: `j`/`k` move, `d` drafted, `m` my pick, `u` undo, `Enter`/`Esc` drawer, `/` search — all disabled while a
text input or select has focus.

## Commands
- Backend: `cd backend && uv sync && uv run alembic upgrade head && uv run uvicorn app.main:app --reload --port 8000`; CLI `uv run ff --help`; tests `uv run pytest`; lint `uv run ruff check .`
- Frontend: `cd frontend && pnpm dev` (proxies `/api` → `:8000`, add `--port NNNN` if 5173 is taken); `pnpm build` (tsc + vite, must pass clean); `pnpm lint`.
- Database: docker container `postgres` (user `local-master`), db `fantasy_football`; `docker exec postgres psql -U local-master -d fantasy_football`.
- Use `uv` for Python, `pnpm` for Node. Python >=3.12 (venv currently 3.13).
