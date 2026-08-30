# Handoff — state as of 2026-08-30 (Phases 3, 4-lite and 5 complete; keeper helper shipped)

Read `CLAUDE.md` → `docs/PLAN.md` → this file → the phase checklist you are working on. Progress is tracked by ticking
`docs/phases/NN-*.md`; decisions go in `docs/decisions.md`. Draft is **before Sep 10**; the calendar in PLAN.md starts day 1 = Aug 31.

## Done (verified)
- **Phase 0**: repo scaffold, `uv` backend (FastAPI `/health` + `/api/health`), Vite/React/TS/Tailwind dark shell (`pnpm build` ok),
  Postgres db `fantasy_football` + Alembic (3 migrations: provenance, players hub, draft tables), README/CLAUDE/PLAN/phases/specs/runbook/decisions.
- **Phase 1a**: snapshot-first ingestion (`backend/app/ingest/snapshots.py`, `loaders.py`, `nflverse_base.py`) and loaders for nflverse stats
  (2023–25 weekly/season stats, ff_opportunity, weekly rosters, injuries), nflverse reference (players, ff_playerids, 2026 rosters/depth charts/
  schedules/team_bye/draft_picks, ff_rankings), Sleeper (2026 projections + players), FFC ADP (3 formats), Yahoo public ADP pool.
  `uv run ff ingest all` runs everything; raw tables are `raw_<source>_<dataset>` with `snapshot_id` per row.
- **Players hub / crosswalk** (`app/ingest/players_hub.py`): 1,052 players; **gate PASSED** (`uv run ff ingest check-ids`): ECR top-300 100%,
  Yahoo pool 100% of the 376 fantasy-position rows, Sleeper top-300 100%, 2026 R1–R4 skill picks 43/43.
- **Phase 2 scoring engine** (`app/scoring/`): `load_league_config()`, `score()`, `breakdown()`, adapters for nflverse weekly rows,
  ff_opportunity expected rows, Sleeper projections. Tests on the real Nacua 2025 fixture reproduce nflverse `fantasy_points` for every week
  (cross-check only). Yahoo fractional/negative-point semantics implemented. **Real scoring from Derek is still pending** (config/league.yaml
  is a labeled Yahoo-default placeholder).
- **Pure ranking math** (`app/ranking/`): `pick_schedule.py` (snake + keeper holes, live numbering), `vbd.py` (keeper-aware VOLS/VORP, greedy
  FLEX, man-games season value), `tiers.py` (1-D fixed-k GMM + value tiers), `availability.py` (closed-form P(avail), expected-best, VONA),
  `adjustments.py` (age steps, E[games]), `room_adp.py`. Tests: `tests/test_pick_schedule.py`, `tests/test_ranking_math.py`.
- **WHY framework** (`app/why/rules.py`): 18 rule templates with provenance; `render(signals)`.
- Draft models exist (`leagues`, `keepers`, `pick_schedule`, `draft_picks`) — no API/UI yet.

## In flight when this session ended (check results before redoing)
- Phase 1a verifier (idempotency re-run, REG-weeks gate, full pytest/ruff) — output in the session task file; re-run
  `uv run pytest -q && uv run ruff check app tests` to confirm.
- Curated seeds: **DONE** — `backend/seeds/{coaching_changes,qb_situations,ol_changes}.yaml` (32 rows each) and `known_missed_weeks.yaml`
  (43 rows, 42/43 gsis_ids resolve; Brandon Aiyuk on reserve/DNR is the exception). Every row has source_url + confidence + last_checked;
  verified against fansports play-callers (all 32), SI's starting-QB list (all 32) and PFF's Aug 12 OL ranks (all 32). Note: `confidence` is
  high|medium|low (map to a number in the Phase 5 loader). Day-9 re-check list (still uncertain on 8/29): NYG caller (Nagy vs Callahan),
  DEN (Webb primary, Payton 'some plays'), BUF play_caller_new=false (Brady kept play-calling from his OC year), LV/ATL/KC QB rooms,
  HOU (+2)/CLE (+1)/LA/NO/KC OL deltas, Charbonnet/Tyson/Conner/Kirk/Kittle missed-week estimates.
- Phase 3 features: **stopped before any code was written** (to save tokens for the model switch). `app/features/` is empty. Implement per
  `docs/phases/03-features.md`: modules production / luck / consistency / durability / depth / team_tendencies, each `compute(seasons) -> polars`,
  an assembler writing `player_season_features` + `player_features` (Alembic migration), `GET /api/players/{id}/profile`, and the gate.

## Added 2026-08-30
- **Phase 4-lite market layer** (`app/market/build.py`, `rank_snapshots`): 4 sources → 1,519 rows, composite rank,
  disagreement residual, `sd_adp` (OLS on FFC = 1.04 + 0.105·ADP). `ff market build` / `ff market check` (GATE PASSED,
  depth reconciled to measured coverage — see docs/phases/04-market.md).
- **Vendor projections** (`app/ranking/projections.py`): Sleeper stat lines re-scored under league config, plus E[games].
- **Keeper helper** (`app/ranking/keeper_value.py`, `ff keeper rounds|table|value`) — pulled forward for the Aug 31 deadline.
- Confirmed inputs: `league_key = 470.l.335180`, draft Sun Sep 6 8:45pm CDT, keeper deadline Aug 31, Yahoo app submitted.
- Still pending from Derek: **real scoring table** (screenshot never arrived), roster slots/bench, max keepers, draft slot.

## Added later on 2026-08-30
- **Phase 3 complete**: six feature modules (production, luck, consistency, durability, depth, team_tendencies)
  assembled by `ff features build` into `player_features` (961) and `player_season_features` (1,443).
  `ff features check` GATE PASSED — five named players' 2025 totals reconcile with nflverse exactly.
  E[games] is computed once from ADP band + injury history + announced absences, with history gated on real usage.
- **Phase 5 complete**: `ff context check|load|review` → `team_context` (32 teams, 10 new HC, 18 new play-callers,
  5 unsettled QB rooms, 21 non-zero OL deltas). Validation refuses to load unsourced/invalid rows; every row carries
  source URLs, confidence and a seed sha256; a `warning` column auto-flags stale/low-confidence rows for the day-9 pass.
- **API**: `GET /api/players`, `/api/players/{id}/profile` (history + summary + market + team context + provenance),
  `/api/teams/context`.
- Suite: **95 tests green**, ruff clean, 6 commits pushed.

## Next (in order — see docs/PLAN.md calendar)
1. Get Derek's day-1 inputs into `config/league.yaml` (scoring incl. fractional/negative flags, roster, keeper count/deadline, league_key,
   draft date/time, slot) — blocks the Phase 2 gate (5 named players' 2025 totals vs Yahoo pages). Derek creates the Yahoo app + submits
   the access application (docs/phases/00-scaffold.md, Yahoo section) and runs the day-1 OAuth smoke test.
2. Phase 4-lite market composite (`rank_snapshots`, composite, disagreement, `sd_adp` from FFC) — `docs/phases/04-market.md`.
3. Phase 6 ranking pipeline: in-house projection component, blend, adjustments, VBD via `app/ranking/vbd.py`, tiers, room ADP, flags,
   WHY bullets (`app/why`), `ranking_runs` manifest, `ff recompute`, CSV export, Spearman ≥ 0.8 guard — `docs/phases/06-ranking-why.md`.
4. Phase 5 loader for the curated seeds → `team_context` API + flags (tags only).
5. Phase 7 board UI (day 6), then 8a/8b/9 per the plan.

## Phase 1a verifier results (2026-08-29)
- All gates PASS (REG weeks 1–18 × 32 teams × 3 seasons; POST distinguishable; ff_opportunity 3 seasons; depth charts 162 daily snapshots;
  272 REG games 2026; 32 byes; 257 draft picks; Sleeper 554 QB/RB/WR/TE projections; FFC 3 formats; idempotent reruns; 35 tests, ruff clean).
- Yahoo public ADP exists for only **227 players** (max pick ≈ 145) — inherent; deeper ADP comes from Sleeper (548 with adp_half_ppr) / FFC.
- Fixed after the verifier: Alembic autogenerate had emitted `drop_table('raw_*')` (that is why `raw_nflverse_teams` vanished) → `alembic/env.py`
  now excludes `raw_*` via `include_object`, and the drops were removed from the two migrations; `loaders.replace_partition` with an empty
  partition list now does a full replace (was append).
- Known, not fixed: `yahoo_pub` pages embed a server `time` field so byte-hash dedupe never triggers (11 new snapshots per run) — hash the parsed
  payload instead; ~18 orphan files under `data/raw/` from rolled-back first attempts (harmless); ff_opportunity `season` is TEXT and `week`
  DOUBLE (cast on join); injuries: filter REG with `game_type` (not `season_type`, null for 2023–24); `stats_player_reg` uses `recent_team`.

## Gotchas learned this session
- Postgres user is `local-master` (no `postgres` role). `raw_nflverse_teams` was dropped by an ingest job; nothing depends on it (DEF names fall back).
- `pl.read_database(..., infer_schema_length=None)` is required on raw tables (mixed-type id columns).
- Yahoo public pool exposes `average_pick` for only ~227 players (max ≈ 145); use page order for the rest.
- ruff config is strict (perf/ruff rules); `alembic/` is excluded.
