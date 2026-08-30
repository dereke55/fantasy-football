# Phase 2 — League scoring engine (day 2)

One deterministic `score(stat_line, scoring)` function, driven by `config/league.yaml`, applied identically to historical weekly stats, expected stats and projection stat lines — so no vendor fantasy-point number ever reaches a ranking or the UI.

**Status:** Not started

**Calendar:** Day 2 — Tue Sep 1 — "Ingest 1a + scoring gate + market composite".

**Plan reference:** `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 2 — League scoring engine (day 2)". Spec lives in `docs/spec/scoring.md` (schema, canonical keys, Yahoo `stat_id` map, flags); stat-line columns come from `docs/spec/data-model.md` (`player_week_stats`, `player_expected_stats`, `projections.stat_line`).

**Blocked by:** day-1 input (1), the scoring table copied from Yahoo League → Settings (incl. fractional points on/off, negative points on/off, yardage bonuses). Until it lands, `config/league.yaml` carries Yahoo default public-league scoring with its source URL and is labeled as such (`source: yahoo_default_public_league_scoring`); the engine is built and tested against that placeholder and re-validated the moment the real table arrives.

## `config/league.yaml` schema (as in `docs/spec/scoring.md`; the file already exists in the repo)

- [ ] `scoring` block with the canonical stat keys for QB/RB/WR/TE (`pass_yd`, `pass_td`, `pass_int`, `rush_yd`, `rush_td`, `rec`, `rec_yd`, `rec_td`), plus `fum_lost`, the 2-pt keys `pass_2pt` / `rush_2pt` / `rec_2pt` (Yahoo uses one category — all three get the same value) and `ret_td`; every value is points per unit (yardage per yard, e.g. 25 yds/pt = 0.04); `bonuses: [{stat, threshold, points}]` for Yahoo yardage bonuses copied from the settings page; `position_overrides: {}` (no TE premium).
- [ ] `scoring.uses_fractional_points: true|false` and `scoring.uses_negative_points: true|false` (both come from the Yahoo settings page; also exposed by `league/{key}/settings` as `uses_fractional_points` / `uses_negative_points`).
- [ ] `roster` block: `slots` per position (QB, RB, WR, TE, FLEX, K, DEF), `flex_eligible: [RB, WR, TE]`, `bench` count, `ir`; standard 1-QB (no superflex / TE premium / IDP).
- [ ] `league` block: `platform: yahoo`, `num_teams: 10`, `draft_type: snake`, `league_key` (null until day-1 input 5), `draft_datetime` (null until input 6), `my_draft_slot` (late-bound; null until input 3), `keepers.{max_per_team, cost_rule: round_drafted, deadline, assigned_in_yahoo}` (input 4).
- [ ] **No K/DST scoring in MVP** — the schema has no K or DEF stat keys; K/DST are ranked by consensus ADP only (Phase 6).
- [ ] Top-level provenance: `source` (`yahoo_default_public_league_scoring` until input (1) lands, then `yahoo_settings_page`), `source_url`, `as_of`; `source` is copied into `ranking_runs.league_config_source`.
- [ ] Loader validates the file with a pydantic model, rejects unknown keys, and computes the canonical config hash (sha256 of the YAML with sorted keys, comments stripped) used by `ranking_runs.league_config_hash` and the frozen `draft_snapshot` (Phase 9).

## Stat-key crosswalk (one internal key per stat, mapped to every stat-line source)

| Internal key | `player_week_stats` (nflverse) | `player_expected_stats` (ff_opportunity) | Sleeper projection `stats.*` | Yahoo `stat_id` |
|---|---|---|---|---|
| `pass_yd` | `passing_yards` | pass yards `*_exp` column (confirm exact name in the file header) | `pass_yd` | 4 (PassYd) |
| `pass_td` | `passing_tds` | `pass_touchdown_exp` | `pass_td` | 5 (PassTD) |
| `pass_int` | `passing_interceptions` | — | `pass_int` | 6 (INT) |
| `rush_yd` | `rushing_yards` | `rush_yards_gained_exp` | `rush_yd` | 9 (RushYd) |
| `rush_td` | `rushing_tds` | `rush_touchdown_exp` | `rush_td` | 10 (RushTD) |
| `rec` | `receptions` | `receptions_exp` | `rec` | 11 (Rec) |
| `rec_yd` | `receiving_yards` | `rec_yards_gained_exp` | `rec_yd` | 12 (RecYd) |
| `rec_td` | `receiving_tds` | `rec_touchdown_exp` | `rec_td` | 13 (RecTD) |
| `fum_lost` | `fumbles_lost_total` (= `rushing_fumbles_lost` + `receiving_fumbles_lost` + `sack_fumbles_lost`) | — | `fum_lost` | 18 (FumLost) |
| `pass_2pt` / `rush_2pt` / `rec_2pt` | `passing_2pt_conversions` / `rushing_2pt_conversions` / `receiving_2pt_conversions` | — | `pass_2pt` / `rush_2pt` / `rec_2pt` (when present in the raw payload) | 16 (2-Point Conversions — expected, confirm from settings payload) |
| `ret_td` | `special_teams_tds` | — | not provided → 0 | 15 (Return Touchdowns — expected, confirm from settings payload) |

The Yahoo ids named in the plan (4 PassYd, 5 PassTD, 6 INT, 9 RushYd, 10 RushTD, 11 Rec, 12 RecYd, 13 RecTD, 18 FumLost, …) are the verified core; ids marked "expected" and every remaining id in the league's `stat_categories` are taken from the raw settings payload, never guessed (`docs/spec/scoring.md` → Yahoo `stat_id` map).

- [ ] `scoring/keys.py` holds the crosswalk above as data (one row per internal key with the four source column names); unit test asserts every internal key in `league.yaml` has a mapping for all three stat-line sources.
- [ ] Missing stat in a stat line ⇒ contributes 0 points, never raises; a stat present in the line but absent from `league.yaml` is ignored and counted in a `unscored_keys` diagnostic.

## `score(stat_line, scoring)`

- [ ] Pure function in `backend/app/scoring/engine.py`: input is a dict of internal stat keys → float (or a polars row), output is points; no I/O, no DB.
- [ ] Vectorised variant `score_frame(df, scoring)` (polars expressions) used by Phase 3 and Phase 6 for whole tables; both variants share one implementation of the rules and agree to 1e-9 on real fixture rows.
- [ ] Applied uniformly to (a) historical weekly stats from `player_week_stats`, (b) `*_exp` expected stats from `player_expected_stats` (never its precomputed `*_fantasy_points*`), (c) projection stat lines from `projections` (Sleeper `stats.*`; never `pts_ppr` / `pts_half_ppr` / `pts_std`).
- [ ] Yardage bonuses (if the league has them) evaluated per game on weekly rows and per season on season-total projection lines exactly as configured; the difference is documented in `docs/spec/scoring.md`.
- [ ] `uses_fractional_points` semantics implemented as Yahoo applies them (confirm from the settings page / raw payload which values are rounded and how) and covered by a test on real fixture rows; `uses_negative_points` semantics likewise (whether a negative game total is floored at 0).
- [ ] `recompute`-friendly: scoring every row of 2023–2025 `player_week_stats` + `player_expected_stats` + all projection lines completes well inside the `recompute` budget (< 5 min total for the whole pipeline).
- [ ] CLI `uv run score player --name "<name>" --season 2025` prints the per-stat breakdown and total under the current `league.yaml` (used for the gate).

## Yahoo settings validation (diff-only; wired in 8b)

- [ ] `scoring/yahoo_settings_diff.py` parses a raw `league/{key}/settings?format=json` snapshot (`stat_categories[{stat_id, name, display_name, position_type}]`, `stat_modifiers[{stat_id, value}]`, `roster_positions[{position, count}]`, `uses_fractional_points`, `uses_negative_points`, `draft_time`) into the same internal shape as `league.yaml` and prints a diff.
- [ ] The diff **never overwrites** `league.yaml`; it is report-only and its output is pasted into `docs/decisions.md` when run (in 8b, per the plan).

## Fixtures and tests (real data only)

- [ ] `backend/tests/fixtures/nflverse/stats_player_week_2025_sample.parquet` (rows for the 5 gate players, all weeks incl. POST) with `PROVENANCE.md` entry (url, fetched_at, sha256).
- [ ] `backend/tests/fixtures/ffopportunity/ep_weekly_2025_sample.parquet` (same players) with provenance.
- [ ] `backend/tests/fixtures/sleeper/projections_2026_sample.json` (≥ 20 projection records incl. one K and one DEF row) with provenance.
- [ ] `test_score_weekly_totals.py`: 2025 REG season totals for the 5 named players under the real scoring equal the totals on the Yahoo league's 2025 pages (expected values recorded in the test with the page URL and the date they were read).
- [ ] `test_fractional.py`: a real fixture week whose raw total is non-integer scores correctly with `uses_fractional_points` on and off.
- [ ] `test_negative.py`: a real fixture week whose raw total is negative (e.g. INTs + fumbles, no yards) scores correctly with `uses_negative_points` on and off.
- [ ] `test_expected_stats_scoring.py`: `score(*_exp)` for a fixture row differs from ffopportunity's `total_fantasy_points_exp` (proves the engine is not passing vendor points through) and matches a hand computation.
- [ ] `test_projection_scoring.py`: Sleeper stat line scored under league scoring; `pts_ppr` is never read.
- [ ] `docs/spec/scoring.md` filled in: schema, crosswalk, fractional/negative semantics, bonus handling, validation procedure.

## Gate

Recompute 2025 season totals for 5 named players under the real scoring and match the totals on the Yahoo league's 2025 pages; fractional/negative tests on real fixture rows.

## Derek's actions

- Paste the scoring table from Yahoo League → Settings (every stat category with its point value, fractional points on/off, negative points on/off, yardage bonuses) — this is day-1 input (1) and it blocks the gate.
- Provide roster slots + bench count, keeper rules, `league_key`, and the exact draft date/time (day-1 inputs 2–6) so `league.yaml` is complete.
- Name 5 players who were on rosters in your league in 2025 and read their 2025 season totals off the Yahoo league's 2025 pages (only you can open the league); send name + Yahoo total for each.
