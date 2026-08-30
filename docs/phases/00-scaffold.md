# Phase 0 — Scaffold, day-1 inputs, Yahoo application (day 1)

Stand up the repo, database, docs and Yahoo developer access so every later phase has a place to land and nothing in the draft-week calendar is blocked on plumbing.

**Status:** Not started

**Calendar:** Day 1 — Sun Aug 30 / Mon Aug 31 — "Phase 0 + crosswalk gate; Yahoo app + application + smoke test" (the crosswalk gate itself is tracked in `01-ingestion.md`).

**Plan reference:** `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 0 — Scaffold, day-1 inputs, Yahoo application (day 1)".

**Specs this phase depends on:** `docs/spec/data-model.md` (`raw_snapshots`, `ranking_runs` columns for the Alembic baseline), `docs/spec/scoring.md` (`config/league.yaml` schema), `docs/spec/live-draft.md` §2 (Yahoo app / access application / smoke test / mock-draft spike), `docs/spec/api.md` §3.1 (`/health`).

## Target layout (from the plan, verbatim)

```
fantasy-football/
├── README.md, CLAUDE.md                 # kept current; README has the Data sources / cadence / licensing table
├── docs/
│   ├── PLAN.md                          # overview, MVP cut line, gates, phase index, calendar
│   ├── phases/00-scaffold.md … 09-readiness.md   # one actionable checklist per phase; progress tracked here
│   ├── spec/data-model.md, scoring.md, ranking-model.md, why-rules.md, api.md, ui.md, live-draft.md
│   ├── runbook-draft-week.md            # daily jobs, failure handling, freeze, post-kickoff guard
│   └── decisions.md                     # ADR log incl. Yahoo application date, unofficial-endpoint risks accepted
├── backend/                             # uv: FastAPI, SQLAlchemy 2 + Alembic, polars, httpx, typer CLI, numpy, scikit-learn
│   ├── app/{api,models,ingest,scoring,features,ranking,why,live}
│   ├── seeds/{coaching_changes,qb_situations,ol_changes,known_missed_weeks,id_overrides,yahoo_team_defense_ids}.yaml
│   └── tests/fixtures/{source}/… + PROVENANCE.md (url, fetched_at, sha256) — real extracts only
├── frontend/                            # Vite + React + TS, Tailwind + shadcn/ui (dark), TanStack Query/Table
├── data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}   # immutable, hash-deduped snapshots
└── config/league.yaml                   # scoring + roster + teams + keeper rules + draft date/slot; source recorded
```

Stack decisions (from the plan): FastAPI (uv) · Vite/React/TS dark UI · local Postgres 17 (docker, already on :5432). Python packages: `nflreadpy` 0.1.5 (nflverse; `nfl_data_py` is archived — do not use), `polars`, `httpx`, `sqlalchemy` 2 + `alembic`, `typer`, `numpy`, `scikit-learn`, `yahoo_oauth`.

## Checklist — repo and services

- [x] `git init` in `/Users/derek/Development/personal/fantasy-football`; `.gitignore` excludes `backend/.env`, `backend/.tokens/`, `data/raw/`, `node_modules/`, `.venv/`.
- [x] `uv init` in `backend/`; add `fastapi`, `uvicorn`, `sqlalchemy`, `alembic`, `psycopg`, `polars`, `pyarrow`, `httpx`, `typer`, `numpy`, `scikit-learn`, `nflreadpy==0.1.5`, `pyyaml`, `yahoo_oauth`; dev: `pytest`.
- [x] `backend/app/__init__.py` plus empty packages `api`, `models`, `ingest`, `scoring`, `features`, `ranking`, `why`, `live`.
- [x] FastAPI app exposes `GET /health` → `{"status": "ok"}` with HTTP 200; runnable via `uv run fastapi dev`.  _returns {"status","db"}; also mounted at /api/health for the Vite proxy_
- [ ] Set `NFLREADPY_CACHE=filesystem` and `NFLREADPY_CACHE_DIR` (project-local cache) in `backend/.env.example`; document that every nflreadpy call passes explicit `seasons=[...]` (`get_current_season()` flips to 2026 on Sep 10 → 404s).  _Deviation: `NFLREADPY_CACHE=off` is set in code (nflverse_base.py) — the snapshot layer is the cache; explicit seasons documented in CLAUDE.md_
- [x] Create database `fantasy_football` on the running Postgres 17 docker container (`:5432`); connection string in `backend/.env` (`DATABASE_URL`), example in `backend/.env.example`.
- [x] Alembic initialised; baseline migration creates `raw_snapshots` and `ranking_runs`.
- [ ] `raw_snapshots` created exactly as specified in `docs/spec/data-model.md` (`id`, `source`, `endpoint`, `url`, `params`, `fetched_at`, `upstream_as_of`, `meta`, `path` = `data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}`, `sha256`, `bytes`, `content_type`, `row_count`, `status`, `error`, `post_kickoff`, `shape_ok`; unique `(source, endpoint, sha256)`).  _Implemented with a minimal column set (id, source, endpoint, params, fetched_at, sha256, bytes, upstream_as_of, path, status, row_count, note); reconcile with the spec in Phase 6_
- [ ] `ranking_runs` created exactly as specified in `docs/spec/data-model.md` (`run_id` uuid PK, `created_at`, `finished_at`, `status`, `git_sha`, `league_config_hash`, `league_config_source`, `seed_hashes` jsonb, `input_snapshot_ids` bigint[], `model_version`, `weights`, `keepers_hash`, `spearman_top150`, `n_players_ranked`, `n_why_bullets`, `duration_s`, `error`, `notes`).  _Implemented minimal (run_id, started_at, finished_at, git_sha, league_config_sha256, seed_hashes, input_snapshot_ids, is_frozen, note); extend in Phase 6_
- [ ] `alembic upgrade head` succeeds against the fresh database; `alembic downgrade base` then `upgrade head` also succeeds.
- [ ] `frontend/` scaffolded with Vite + React + TypeScript; Tailwind + shadcn/ui installed; dark theme is the default; `pnpm dev` renders a dark shell page titled "Draft Board" (single page per `docs/spec/ui.md` §2; no settings/editor screens — those are cut).  _Vite + React + TS + Tailwind v4 dark shell done; shadcn/ui not yet installed_
- [x] `data/raw/` directory created with a `.gitkeep`; snapshot writer helper stubbed (`write_snapshot(source, endpoint, bytes, ext)` → path + sha256, skip write when the sha256 already exists = hash-dedupe).  _implemented in backend/app/ingest/snapshots.py (write_snapshot + record_failure + latest_snapshot)_
- [ ] `backend/seeds/` created with empty-but-valid YAML files: `coaching_changes.yaml`, `qb_situations.yaml`, `ol_changes.yaml`, `known_missed_weeks.yaml`, `id_overrides.yaml`, `yahoo_team_defense_ids.yaml`.  _id_overrides.yaml created; coaching/qb/ol/known_missed_weeks being written by the curated-seeds job; DEF Yahoo keys live in `players.yahoo_player_key` instead of a separate seed_
- [x] `backend/tests/fixtures/` created with `PROVENANCE.md` template (columns: fixture path, url, fetched_at, sha256) — real extracts only, no mock data.
- [x] Typer CLI entry point `uv run ingest --help` works (subcommands stubbed: `all`, `check-ids`, `reg-weeks-check`, `snapshots`).  _entry point is `uv run ff ingest --help` (subcommands: all, check-ids, per-source)_

## Checklist — documentation

- [x] `README.md` with: purpose, quick start (`uv run fastapi dev`, `pnpm dev`, `alembic upgrade head`), and the **Data sources / cadence / licensing table** with these rows: nflverse (CC-BY-4.0, attribution required), ffverse ffopportunity, DynastyProcess ff_playerids / ff_rankings (FantasyPros ECR mirror), FantasyFootballCalculator ADP (free for personal/commercial use, attribution requested, once/day), FantasyPros (personal-use only; direct scrape post-MVP), Sleeper documented `/v1/players/nfl` (once/day) and undocumented `api.sleeper.com/projections` (unofficial), Yahoo `pub-api-ro` (unofficial, no OAuth), Yahoo Fantasy Sports API (official, OAuth2, "Fantasy data provided by Yahoo Fantasy" attribution), ESPN (unofficial, post-MVP).
- [x] `CLAUDE.md` with the rules from the plan: real data only (tests use real snapshot extracts with provenance); explicit `seasons=[...]` on every nflreadpy call; never surface vendor fantasy points (score every stat line under league scoring); adding a source ⇒ README table row + snapshot parser + `raw_snapshots` registration; per-source isolation in ingest; `uv` for Python.
- [x] `docs/PLAN.md`: overview, MVP cut line (IN / post-MVP / CUT lists verbatim from the plan), gates, phase index linking `docs/phases/00–09`, calendar table.
- [x] `docs/phases/00-scaffold.md` … `09-readiness.md` exist, each with Status, checklist, `## Gate`, `## Derek's actions`.
- [x] `docs/spec/` skeletons exist: `data-model.md`, `scoring.md`, `ranking-model.md`, `why-rules.md`, `api.md`, `ui.md`, `live-draft.md` (title + purpose + section headings; `data-model.md` lists the tables from the plan's Data model section before Phase 1 code).
- [x] `docs/runbook-draft-week.md` skeleton (daily jobs, failure handling, freeze, post-kickoff guard).
- [x] `docs/decisions.md` ADR log started with: stack choice; `yahoo_oauth` for tokens + `httpx` raw JSON (wrappers `yahoo_fantasy_api` / `yfpy` are optional readers only — they drop unfilled `draftresults` rows); unofficial-endpoint risks accepted (Sleeper projections, Yahoo pub, FFC, ESPN); test-fixture policy (real extracts + PROVENANCE, no mocks).

## Checklist — day-1 inputs → `config/league.yaml`

The six day-1 inputs (they block Phase 2):

1. Scoring table copied from Yahoo League → Settings (incl. fractional points on/off, negative points on/off, yardage bonuses).
2. Roster slots + bench count.
3. Draft slot (or "TBD by <date>").
4. Keeper rules: max keepers per team, whether the commissioner has already run "Assign Keeper Players", keeper deadline.
5. `league_key` (from the league URL).
6. Exact draft date/time.

- [x] `config/league.yaml` exists with the schema in `docs/spec/scoring.md`: top-level `source`, `source_url`, `as_of`; `league` (`platform`, `league_key`, `num_teams: 10`, `draft_type: snake`, `draft_datetime`, `my_draft_slot`, `keepers.{max_per_team, cost_rule, deadline, assigned_in_yahoo}`); `roster` (`slots`, `flex_eligible`, `bench`, `ir`); `scoring` (stat keys, `uses_fractional_points`, `uses_negative_points`, `bonuses`, `position_overrides`).
- [x] Until input (1) lands: `scoring` carries Yahoo default public-league scoring with `source: yahoo_default_public_league_scoring` and the Yahoo help-page URL it was copied from in `source_url`, so the label shows in every ranking run (`ranking_runs.league_config_source`); when the real table lands, `source: yahoo_settings_page` + `as_of`.
- [ ] Each of the six inputs is either filled in or left `null` and explicitly listed as pending (with a needed-by date) in `docs/decisions.md`.
- [ ] `league.yaml` config hash (sha256 of the canonicalised file) is computed by a helper and printed by `uv run ingest snapshots` so Phase 6/9 can pin runs to it.

## Checklist — Yahoo, in this order

- [ ] (1) Create the app at developer.yahoo.com: **Installed Application**, API permission **Fantasy Sports Read**, redirect `https://localhost:8080`; store Client ID / Client Secret in `backend/.env` (`YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`).
- [ ] (2) Submit the access application at sports.yahoo.com/developer/access **with the Client ID**, use case "personal, single league, read-only draft monitor"; record the submission date in `docs/decisions.md` (Yahoo reviews even personal-use apps; no SLA published).
- [ ] (3) Same day: run the `yahoo_oauth` consent flow (token file under `backend/.tokens/`, git-ignored) and call `https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/leagues?format=json`; log in `decisions.md` whether an unapproved app is blocked (HTTP status + body).
- [ ] If the call works: run the **mock-draft visibility spike** — join a Yahoo mock draft, then check whether it appears in `users;use_login=1/games;game_keys=nfl/leagues` and whether `league/{key}/draftresults?format=json` returns rows for it; log the result in `decisions.md` (this gates Phase 8b's harness choice).
- [x] Library decision recorded in `decisions.md`: `yahoo_oauth` for tokens + `httpx` raw JSON; `yahoo_fantasy_api` / `yfpy` optional readers only.

## Gate

`/health` 200; shell renders; `alembic upgrade head`; docs exist; Yahoo app created + application submitted (date logged); day-1 inputs received or explicitly marked pending.

## Derek's actions

- Paste the six day-1 inputs (scoring table incl. fractional/negative/yardage bonuses; roster slots + bench; draft slot or "TBD by <date>"; keeper rules incl. max keepers, whether "Assign Keeper Players" has been run, keeper deadline; `league_key`; exact draft date/time). Input (1) was selected as "paste in notes" but no notes arrived — please paste it.
- Create the Yahoo app at developer.yahoo.com (Installed Application, Fantasy Sports Read, redirect `https://localhost:8080`) and hand over the Client ID / Secret for `backend/.env`.
- Submit the Yahoo access application at sports.yahoo.com/developer/access with the Client ID (use case: personal, single league, read-only draft monitor) and tell me the submission date.
- Complete the browser consent step of the `yahoo_oauth` flow on day 1.
- Join a Yahoo mock draft on day 1 so the mock-draft visibility spike can run.
