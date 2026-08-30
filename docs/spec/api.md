# API spec — FastAPI endpoints

Purpose: the HTTP contract between the FastAPI backend (`backend/app/api`) and the React board / CLI / CSV consumers, covering rankings + runs, player profile, team context, keepers, draft picks + undo, pick schedule, availability, SSE, CSV export and health.

Status: Not started

Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` (Architecture, MVP cut line, Phases 5/6/7/8). Anything here that is not in the plan is an implementation detail of the plan's stated behavior and is marked *(impl detail)*.

## 1. Conventions

- Base path `/api`; `/health` is served at the root (plan: "uv init backend (FastAPI `/health`)").
- Local, single-user, no auth. The board and CLI talk to `http://127.0.0.1:8000` (`uv run fastapi dev`).
- JSON everywhere except `/api/export/board.csv` (CSV) and `/api/draft/stream` (`text/event-stream`).
- **Pinned run.** Every ranking read serves the run pinned in `draft_snapshot` (pinned `run_id` + league-config hash). Plan: "the draft board serves a **pinned run_id** and refuses to serve if the config hash changed without an explicit re-freeze." When the current `config/league.yaml` hash differs from the pinned `config_hash`, ranking endpoints return **409** with `{"error": "config_hash_mismatch", "pinned": "<hash>", "current": "<hash>"}` until a re-freeze is run via the CLI (never via the API).
- **Vendor fantasy points are never surfaced.** Every points/PPG number in a response is `score(stat_line, league scoring)`. Responses carry `scoring_source: "league.yaml"` plus the config hash so this is auditable.
- Every derived number is traceable: responses include `run_id`; WHY bullets include `snapshot_ids` and `source_url`.
- Errors: `{"error": "<slug>", "detail": "<human text>"}` with 400 (bad input), 404 (unknown id), 409 (state conflict: config hash, duplicate pick, pick slot already filled), 503 (no pinned run yet).
- Mutations (keepers, picks, undo) synchronously recompute the keeper-aware baselines, `pick_schedule`, room ADP and P(avail) (plan: "recomputed on every keeper edit (pure numpy)"; Phase 7 gate: "drafted/undo/keeper edits recompute best-available and P(avail) without reload") and return the refreshed `DraftState` so the client needs no second request.
- Time values are ISO-8601 UTC strings. Player ids are the internal `players.player_id` hub id (`docs/spec/data-model.md`); `run_id` is the `ranking_runs.run_id` uuid; every player object also carries the external ids (gsis, esb, sleeper, espn, yahoo, fantasypros, pfr, otc) that are known.

## 2. Endpoint index

| Method | Path | Phase | Purpose |
|---|---|---|---|
| GET | `/health` | 0 | Liveness + DB + pinned-run summary |
| GET | `/api/runs/current` | 6 | The pinned `ranking_runs` row + `draft_snapshot` |
| GET | `/api/runs/{run_id}` | 6 | Any `ranking_runs` row (provenance) |
| GET | `/api/rankings` | 6 | Board rows for the pinned run |
| GET | `/api/players/{player_id}` | 3/6 | Player profile (drawer) |
| GET | `/api/team_context` | 5 | All three curated tables, 32 teams |
| GET | `/api/team_context/{team}` | 5 | One team |
| GET / POST | `/api/keepers` | 6 | List / add keeper |
| PUT / DELETE | `/api/keepers/{keeper_id}` | 6 | Edit / remove keeper |
| GET | `/api/pick_schedule` | 6 | Snake schedule with keeper-consumed slots |
| GET | `/api/draft/state` | 7 | On-the-clock, my next pick, mode, my roster, bye-stack warnings |
| GET / POST | `/api/draft/picks` | 5 | List / record a pick (manual) |
| PUT / DELETE | `/api/draft/picks/{overall_pick}` | 5 | Correct / clear a pick |
| POST | `/api/draft/undo` | 5 | Undo the most recent manual pick |
| GET | `/api/availability` | 8a | P(avail at my next pick) + VONA |
| GET | `/api/draft/stream` | 8b | SSE: picks, keepers, schedule, mode changes |
| GET | `/api/export/board.csv` | 5 | CSV of the board |

Draft-day minimum (end of day 5, Fri Sep 4): rankings, players, keepers, picks, undo, pick_schedule, availability, export, health — usable from the CLI/`curl` before the board exists (plan: "manual pick/keeper entry via API/CLI"). MVP checkpoint (day 6, Sat Sep 5) adds `/api/draft/state` for the board. `/api/draft/stream` is Phase 8b only (day 8, gated).

## 3. Endpoints

### 3.1 `GET /health`

Returns 200 when the app is up and the database answers.

```json
{
  "status": "ok",
  "db": "ok",
  "git_sha": "abc1234",
  "pinned_run_id": "6f1c2a8e-…",
  "config_hash": "sha256:…",
  "config_hash_matches": true,
  "draft_mode": "manual"
}
```

`pinned_run_id` is null before the first freeze; `/health` still returns 200 (the Phase 0 gate is `/health` 200 before any data exists). `draft_mode` is `manual` or `yahoo` (8b).

### 3.2 `GET /api/runs/current`, `GET /api/runs/{run_id}`

A `ranking_runs` row. Plan: "Every ranking run is a `ranking_runs` row (git sha, league-config hash, seed hashes, input snapshot ids)".

```json
{
  "run_id": "6f1c2a8e-…",
  "created_at": "2026-09-05T02:10:00Z",
  "git_sha": "abc1234",
  "league_config_hash": "sha256:…",
  "league_config_source": "yahoo_settings_page",
  "seed_hashes": {"coaching_changes": "…", "qb_situations": "…", "ol_changes": "…", "known_missed_weeks": "…", "id_overrides": "…", "yahoo_team_defense_ids": "…"},
  "input_snapshot_ids": [101, 102, 103],
  "keepers_hash": "sha256:…",
  "spearman_top150": 0.87,
  "status": "ok",
  "pinned": true,
  "frozen_at": "2026-09-09T22:55:00Z"
}
```

Keys are the `ranking_runs` columns from `docs/spec/data-model.md` (plus `pinned`/`frozen_at` from `draft_snapshot`). `spearman_top150` is the model guard from the Phase 6 gate ("Spearman(our overall rank, ECR) on top-150 ≥ 0.8"); a run that fails it is stored but cannot be pinned.

### 3.3 `GET /api/rankings`

Board rows for the pinned run. Query params *(impl detail)*: `pos` (QB|RB|WR|TE|K|DST), `preset` (`sleeper` | `bust`), `include_drafted` (default true — the board dims drafted rows rather than hiding them), `limit` (default 400).

One row per player, columns exactly as the Phase 7 board: "rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags".

```json
{
  "run_id": "6f1c2a8e-…",
  "config_hash": "sha256:…",
  "scoring_source": "league.yaml",
  "rows": [
    {
      "player_id": 4321,
      "name": "…",
      "pos": "RB",
      "team": "DET",
      "bye": 8,
      "rank": 1,
      "pos_rank": 1,
      "tier": 1,
      "value_tier": 1,
      "proj_ppg": 21.4,
      "e_games": 15.6,
      "proj_season": 318.2,
      "value": 141.0,
      "vorp": 152.3,
      "ecr": 1.0,
      "ecr_sd": 0.6,
      "adp_yahoo_site": 1.4,
      "adp_composite": 1.5,
      "room_adp": 1.0,
      "sd_adp": 1.1,
      "gap": 0.0,
      "gap_z": 0.0,
      "p_avail": 0.02,
      "flags": ["rookie"],
      "tags": ["new_play_caller"],
      "drafted": false,
      "drafted_by_slot": null,
      "is_keeper": false,
      "is_mine": false
    }
  ]
}
```

Notes:
- `proj_ppg` is the blended per-game number under league scoring (Phase 6 §1); `proj_season` = `E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]` (Phase 6 §3); `value` is keeper-aware VOLS and `vorp` the VORP variant (Phase 6 §3); K/DST have `value = 0` and are sorted by consensus ADP.
- `adp_yahoo_site` is labeled site-wide Yahoo ADP (plan: "Yahoo site-wide ADP (labeled as such)"); `room_adp` is the keeper-removed, `pick_schedule`-mapped ADP (Phase 6 §5); raw and room-adjusted are both returned so the board shows them side by side.
- `gap` = `room_adp − our_pick_equivalent`; `gap_z = gap / sd_adp` (Phase 6 §7). `flags` ⊆ {sleeper, bust, injury_prone, structural_injury_return, rookie, new_play_caller, qb_uncertain_team}.
- `p_avail` is the closed-form value from §3.10 evaluated at my next pick; null before a draft slot is configured.

### 3.4 `GET /api/players/{player_id}`

Everything the Player drawer needs: "WHY bullets with source/as_of, 3-season PPG line, key metrics, tags".

```json
{
  "run_id": "6f1c2a8e-…",
  "player": {"player_id": 4321, "name": "…", "pos": "RB", "team": "DET", "bye": 8,
             "ids": {"gsis_id": "00-00…", "esb_id": "…", "sleeper_id": "…", "espn_id": null, "yahoo_id": "40059", "fantasypros_id": null, "pfr_id": null, "otc_id": null}},
  "bio": {"age_at_2026_09_10": 24.4, "years_exp": 3, "draft_year": 2023, "draft_round": 1, "draft_pick": 12, "rookie": false},
  "ranking": { "…same row as /api/rankings…" },
  "ppg_by_season": [
    {"season": 2023, "games": 15, "ppg": 14.2, "pos_ppg_rank": 9, "same_team_role": true},
    {"season": 2024, "games": 17, "ppg": 19.8, "pos_ppg_rank": 2, "same_team_role": true},
    {"season": 2025, "games": 16, "ppg": 21.0, "pos_ppg_rank": 1, "same_team_role": true}
  ],
  "features": {
    "production": {"trend_weighted_ppg": 19.1, "yoy_delta_ppg": 1.2},
    "opportunity": {"targets_per_game": 4.9, "target_share": 0.14, "air_yards_share": 0.04, "wopr": 0.24, "carries_per_game": 16.1, "opportunity_trend": "+"},
    "luck": {"td_diff": 3.9, "ppg_diff": 1.1},
    "durability": {"games_missed_2023_25": 3, "eligible_games": 51, "events": [{"season": 2024, "cause": "hamstring", "weeks": 2}], "e_games": 15.6, "known_missed_weeks": 0},
    "consistency": {"2025": {"mean": 21.0, "sd": 7.4, "floor_p25": 15.1, "ceiling_p90": 31.2, "starter_weeks": 14}}
  },
  "projection": {"sleeper_ppg_league_scoring": 21.9, "inhouse_ppg": 20.2, "blend_weights": {"sleeper": 0.70, "inhouse": 0.30}, "age_step": 1.00},
  "market": [
    {"source": "fantasypros_mirror", "kind": "ecr", "format": "half-ppr", "rank": 1.0, "std": 0.6, "min": 1, "max": 3, "as_of": "2026-08-28"},
    {"source": "yahoo_pub", "kind": "adp", "format": "yahoo_default", "adp": 1.4, "as_of": "2026-08-29"},
    {"source": "ffc", "kind": "adp", "format": "half-ppr", "adp": 1.6, "std": 0.8, "min": 1, "max": 4, "as_of": "2026-08-29"},
    {"source": "sleeper", "kind": "adp", "format": "half-ppr", "adp": 1.4, "as_of": "2026-08-29"}
  ],
  "tags": ["new_play_caller"],
  "context": {"coaching": {"…row from coaching_changes…"}, "qb": {"…"}, "ol": {"…"}},
  "why": [
    {"ordinal": 2, "rule_id": "OPP_TARGET_SHARE", "template_version": "v1", "polarity": "positive",
     "text": "Target share 24% → 28% (2024→2025)",
     "metric_keys": ["target_share_2024", "target_share_2025"], "inputs": {"target_share_2024": 0.24, "target_share_2025": 0.28},
     "season_from": 2024, "season_to": 2025, "week_from": null, "week_to": null,
     "snapshot_ids": [101], "source_url": "https://github.com/nflverse/nflverse-data/…", "as_of": "2026-08-26", "run_id": "6f1c2a8e-…"}
  ]
}
```

- `market` rows are `rank_snapshots` rows (source / format / kind vocabulary from `docs/spec/data-model.md`); `yahoo_pub` is labeled "Yahoo (site-wide)" in the UI.
- `why` rows are the stored `why_bullets` (plan: "Each `why_bullets` row stores rule_id, template_version, metric keys, numeric inputs, season/week range, snapshot_ids, source_url, run_id"); `rule_id` values are the catalogue in `docs/spec/why-rules.md`; ordered by `ordinal`; ≤ ~6 bullets.
- Rookies: every historical block is null and the endpoint returns 200 (Phase 3 gate: "rookie profile returns nulls cleanly").
- Vendor fantasy points (`pts_ppr` etc.) are never included; `sleeper_ppg_league_scoring` is the Sleeper stat line re-scored under league scoring.

### 3.5 `GET /api/team_context`, `GET /api/team_context/{team}`

Phase 5: "`team_context` API returns all three for 32 teams; every row has a source_url".

```json
{
  "seed_hashes": {"coaching_changes": "…", "qb_situations": "…", "ol_changes": "…"},
  "teams": [
    {
      "team": "ARI",
      "coaching_changes": {"hc": "Mike LaFleur", "hc_new": true, "oc": "…", "oc_new": true, "play_caller": "…", "play_caller_new": true,
                           "source_url": "https://…", "confidence": 0.95, "last_checked": "2026-08-29"},
      "qb_situations": {"projected_qb1": "Jacoby Brissett", "status": "settled", "changed_from_2025": true,
                        "source_url": "https://…", "confidence": 0.90, "last_checked": "2026-08-29"},
      "ol_changes": {"delta": 0, "notes": "…", "source_url": "https://…", "confidence": 0.75, "last_checked": "2026-08-29"},
      "flags": {"new_play_caller": true, "qb_uncertain_team": false}
    }
  ]
}
```

`status` ∈ {settled, competition, injury_return}; `delta` ∈ −2..+2; `confidence` is numeric 0–1 (`docs/spec/data-model.md`, curated tables). Read-only in MVP (plan: "Edited as YAML + reload"; settings/curated editors are deferred). The response is also what Derek reviews as one markdown table (Phase 5 gate) — the CLI renders it from this payload.

### 3.6 Keepers — `GET|POST /api/keepers`, `PUT|DELETE /api/keepers/{keeper_id}`

Table: `keepers(team_slot, player, cost_round, status, source)`.

POST body:

```json
{"team_slot": 3, "player_id": 4321, "cost_round": 4, "status": "declared", "source": "manual"}
```

- `team_slot` 1–10; `cost_round` 1..rounds ("keepers cost the round they were drafted in"); `status` ∈ {declared, approved} on write (`approved` = commissioner-approved; DELETE sets `removed` — the `keepers.status` values in `docs/spec/data-model.md`); `source` ∈ {manual, yahoo} (Yahoo rows come from pre-filled `draftresults` rows in 8b; manual is primary).
- 409 if that team already has a keeper in that round, if the player is already kept by another team, or if the team exceeds the league's max keepers (`config/league.yaml`, day-1 input 4).
- On every change: rebuild `pick_schedule` (keeper-consumed slot marked, team skipped that round), pre-populate that team's roster with the keeper, recompute baselines (`baseline_rank[pos] = teams × starters[pos] − keepers_at[pos]`, FLEX greedy, VORP bench share), room ADP and P(avail). Response = `{"keeper": {...}, "state": DraftState}`.
- GET returns all keepers grouped by `team_slot`, plus `max_keepers` and the keeper deadline from league.yaml.

### 3.7 `GET /api/pick_schedule`

Table: `pick_schedule(overall_pick, round, team_slot, is_keeper_slot)` = "10 × rounds snake with keeper-consumed slots marked (team skipped that round)".

```json
{
  "num_teams": 10, "rounds": 15, "my_slot": 7,
  "draft_order": [1,2,3,4,5,6,7,8,9,10],
  "picks": [
    {"overall_pick": 1, "round": 1, "team_slot": 1, "is_keeper_slot": false, "filled": false, "player_id": null, "is_mine": false},
    {"overall_pick": 38, "round": 4, "team_slot": 3, "is_keeper_slot": true, "filled": true, "player_id": 4321, "is_mine": false}
  ],
  "my_picks": [7, 14, 27, 34]
}
```

`filled`/`player_id` are joined from `draft_picks` so one call gives the board the full grid. "my next pick in N", availability, baselines and room ADP all read this table. `draft_order` defaults to slot order; 8b overwrites it from the Yahoo `predraft` poll (draft order + keeper rows). `my_slot` is null until day-1 input 3 (draft slot) is set — then `my_picks`, `is_mine`, `p_avail` and VONA are null and the board shows "set your draft slot".

### 3.8 `GET /api/draft/state`

The board's single status object (`DraftState`), also embedded in every mutation response.

```json
{
  "mode": "manual",
  "banner": null,
  "draft_status": "draft",
  "draft_time": "2026-09-08T00:00:00Z",
  "on_the_clock": {"overall_pick": 23, "round": 3, "team_slot": 3},
  "my_slot": 7,
  "my_next_pick": 27,
  "picks_until_mine": 4,
  "picks_made": 22,
  "my_roster": [{"player_id": 4321, "pos": "RB", "bye": 8, "slot": "RB1", "is_keeper": true}],
  "open_slots": {"QB": 1, "RB": 1, "WR": 2, "TE": 1, "FLEX": 1, "K": 1, "DST": 1, "BN": 6},
  "bye_stack_warnings": [{"bye": 11, "projected_starters": ["…", "…", "…"]}],
  "last_pick": {"overall_pick": 22, "player_id": 999, "source": "manual", "picked_at": "…"}
}
```

- `mode` ∈ {manual, yahoo}; `banner` is the text shown when 8b falls back to manual after 3 consecutive poll failures, otherwise null.
- `draft_status` ∈ {predraft, draft, postdraft} (Yahoo vocabulary; manual mode sets it from picks made).
- `on_the_clock` = lowest unfilled pick in `pick_schedule` (keeper slots count as filled).
- `bye_stack_warnings`: ≥3 projected starters sharing a bye (plan notes 2026 week 11 has six teams on bye).
- `open_slots` drives VONA weighting (open starter → full VBD, bench only → 0.5×).

### 3.9 Draft picks — `GET|POST /api/draft/picks`, `PUT|DELETE /api/draft/picks/{overall_pick}`, `POST /api/draft/undo`

Table: `draft_picks (pick, round, team_slot, player nullable, is_keeper, source manual|yahoo)`.

POST body (mark drafted / my pick):

```json
{"player_id": 4321, "team_slot": null, "overall_pick": null, "my_pick": false}
```

- `team_slot`/`overall_pick` omitted → the pick is recorded at `on_the_clock`. `my_pick: true` is sugar for `team_slot = my_slot` and is what the board's **m** key sends; **d** sends the plain form.
- 409 if the player is already drafted or kept, or the target slot is already filled / is a keeper slot; 400 if the slot is not the lowest unfilled and `overall_pick` was not given explicitly (out-of-order entry must be deliberate).
- `source` is always `manual` for API-entered picks. The 8b poller writes `source: "yahoo"` rows through the same service function, never through HTTP.
- PUT replaces the player on a filled non-keeper slot (correction); DELETE clears it (player nullable) — keeper slots are only changed via `/api/keepers`.
- `POST /api/draft/undo` removes the most recently recorded **manual** pick (LIFO by `picked_at`), returns `{"undone": {...}, "state": DraftState}`; 409 when there is nothing to undo or the latest pick is `source: "yahoo"` (Yahoo picks are corrected by the next poll, not by undo).
- Every mutation recomputes best-available, room ADP, P(avail) and VONA and returns `state`.
- GET lists every row incl. keeper rows, ordered by `overall_pick`, with `source` and `picked_at`. This is also the dry-run/pick-feed replay target (Phase 9 day 9: "scripted pick feed in real Yahoo-ADP order").

### 3.10 `GET /api/availability`

Phase 8a: "closed-form `P(available at my next pick) = 1 − Φ((my_next_pick − room_adp) / sd_adp)`; VONA = value_now − Σ P(avail) × value of best same-position candidates at my next pick, weighted by my open slots (open starter → full VBD, bench only → 0.5×); K/DST excluded before round 12."

Query params *(impl detail)*: `pick` (override `my_next_pick`, e.g. to look two picks ahead), `top` (default 3).

```json
{
  "run_id": "6f1c2a8e-…",
  "my_next_pick": 27,
  "method": "closed_form_normal",
  "players": [{"player_id": 4321, "room_adp": 21.0, "sd_adp": 3.1, "p_avail": 0.03}],
  "vona": {
    "RB": [{"player_id": 4321, "value_now": 61.0, "expected_value_at_next": 44.2, "vona": 16.8, "weight": 1.0}],
    "WR": [ "…top 3…" ], "QB": [ "…" ], "TE": [ "…" ],
    "K": [], "DST": []
  },
  "sd_adp_fit": {"source": "ffc_ols", "a": 1.0, "b": 0.10, "fitted_at": "2026-09-04T…"}
}
```

`players` covers the undrafted pool; `vona` is the "VONA top-3 per position" draft-day control. `K`/`DST` are empty until round 12. Monte Carlo (8c) is post-MVP; `method` will change to `monte_carlo` only when that ships.

### 3.11 `GET /api/draft/stream` (Phase 8b, gated)

`text/event-stream`. Emitted by the live poller and by manual mutations so a second browser tab stays in sync. Event names: `pick`, `undo`, `keeper`, `schedule`, `state`, `heartbeat` (every 15 s). Each `data:` payload is the corresponding object from §3.8/§3.9 (`state` carries the full `DraftState`). Clients reconnect with `Last-Event-ID`; the server replays events with a higher id from an in-memory ring buffer *(impl detail)*. Not required for the MVP checkpoint; in MVP the board updates from mutation responses and a TanStack Query refetch.

### 3.12 `GET /api/export/board.csv`

The board (§3.3 columns, same order, plus `name`, `player_id`, `yahoo_id`, `run_id`) for the pinned run, one row per player, UTF-8, header row, `Content-Disposition: attachment; filename="board_run{run_id}_{YYYYMMDD}.csv"`. Query params as §3.3. Drafted players are included with `drafted=true` so a mid-draft export is a full record. This is a draft-day-minimum deliverable (day 5).

## 4. Checklist

- [ ] `GET /health` returns 200 with `db: ok` on a fresh database (no runs, no config hash) — Phase 0 gate
- [ ] Config-hash guard: change `config/league.yaml`, call `GET /api/rankings`, receive 409 `config_hash_mismatch`; run the CLI re-freeze, receive 200
- [ ] `GET /api/rankings` returns every §3.3 column for ≥400 players from the pinned run in one response
- [ ] Grep the JSON schema / response models: no field named `pts_ppr`, `pts_half_ppr`, `pts_std` or any other vendor points key is exposed
- [ ] `GET /api/players/{id}` for a rookie returns 200 with null historical blocks and ≥3 WHY bullets
- [ ] `GET /api/players/{id}` for a veteran returns 3 `ppg_by_season` rows and WHY rows that each have `rule_id`, `snapshot_ids`, `source_url`, `run_id`
- [ ] `GET /api/team_context` returns 32 teams × 3 tables and every row has a non-empty `source_url`
- [ ] `POST /api/keepers` then `GET /api/pick_schedule`: the keeper's `(round, team_slot)` slot is `is_keeper_slot: true`, `filled: true`, and `my_picks` / `picks_until_mine` skip it
- [ ] `POST /api/keepers` twice for the same `(team_slot, cost_round)` returns 409
- [ ] `POST /api/draft/picks` with no slot fills `on_the_clock`; the response `state.on_the_clock` advances to the next unfilled non-keeper pick
- [ ] `POST /api/draft/undo` reverses the last manual pick and restores `p_avail` for that player; a second undo with nothing left returns 409
- [ ] `GET /api/availability` values equal `1 − Φ((my_next_pick − room_adp)/sd_adp)` for 5 hand-checked players (pytest with real fixture rows)
- [ ] `GET /api/availability` returns empty `K` and `DST` VONA lists while `on_the_clock.round < 12`
- [ ] `GET /api/export/board.csv` opens in a spreadsheet with the §3.3 columns and ≥400 rows
- [ ] Mutation round-trip (`POST /api/draft/picks` → refreshed `state`) completes in < 500 ms locally with 400 players *(impl target supporting the Phase 7 gate)*
- [ ] 8b only: `GET /api/draft/stream` delivers a `pick` event to a connected client within one poll interval of a new `draft_picks` row

## Gate

Phase 0: "`/health` 200; shell renders; `alembic upgrade head`; docs exist; Yahoo app created + application submitted (date logged); day-1 inputs received or explicitly marked pending."

Phase 5: "`team_context` API returns all three for 32 teams; every row has a source_url; Derek reviews them in one markdown table (day 9 re-check)."

Phase 7: "400 players render < 2 s; drafted/undo/keeper edits recompute best-available and P(avail) without reload."

Phase 8b: "fixture test with unfilled + keeper rows; OAuth round-trip survives an hour; new pick detected within 15 s in the harness; SSE delivers; manual mode identical."

## Derek's actions

- Provide day-1 inputs 2, 3, 4 and 6 (roster slots + bench count; draft slot or "TBD by <date>"; keeper rules: max keepers per team, whether "Assign Keeper Players" has been run, keeper deadline; exact draft date/time) — without the draft slot, `my_next_pick`, `p_avail` and VONA are null.
- Enter the keeper list (manual is primary) via `POST /api/keepers` / the board form once it is known.
