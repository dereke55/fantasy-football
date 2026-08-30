# Phase 3 — Historical features, REG only (day 3)

Turn 2023–2025 regular-season data into one `player_features` row per player: production, opportunity, luck, durability, consistency and bio — every number computed under league scoring, every rookie returning nulls cleanly.

**Status:** Not started

**Calendar:** Day 3 — Wed Sep 2 — "Phase 3 features gate".

**Plan reference:** `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 3 — Historical features, REG only (day 3)". Depends on Phase 1a tables (`player_week_stats`, `player_season_stats`, `player_expected_stats`, `roster_weeks`, `injury_weeks`, `games` / `team_bye`, `rosters_2026`, `depth_chart_snapshots`, `draft_picks_nfl`, Sleeper injury fields) and the Phase 2 `score()` engine.

## Scope rules

- [x] Every feature reads only `season_type == 'REG'` rows (weeks 1–18); POST rows (weeks 19–22 in the 2025 files) are excluded by filter, never by deletion.
- [x] Seasons are 2023, 2024, 2025 (explicit); 2022 only if it was ingested at zero cost in Phase 1a.
- [x] All points are `score()` outputs under `config/league.yaml`; vendor `fantasy_points*` / `*_fantasy_points_exp` columns are never read.
- [x] `player_features` is written per run, keyed `(run_id, player_id)` as in `docs/spec/data-model.md` (config hash and input snapshot ids live on the `ranking_runs` row), so WHY bullets can cite the exact inputs.
- [x] Rookies (2026 `entry_year == 2026`; 682 players on the 2026-08-29 roster file, 257 drafted + 425 UDFA): all historical features are `null`, no exceptions raised, `rookie = true`.

## Production

- [x] Per season: `games` (REG weeks with a `player_week_stats` row), `points` (Σ `score(week)`), `ppg = points / games`.
- [x] Positional PPG rank per season among players with ≥ 1 game (rank within `position`).
- [x] YoY deltas: `ppg_delta_24_25`, `ppg_delta_23_24`, `pos_rank_delta_24_25`.
- [x] 3-season weighted trend with weights **0.5 / 0.3 / 0.2** (2025 / 2024 / 2023), **restricted to same team + role seasons** (role = depth-chart slot / usage tier; a season on a different team or in a different role is excluded and the weights renormalised over the remaining seasons; if none remain the trend is null).
- [x] Cross-check: per-season `games`, carries, rushing_yards, targets, receptions match `player_season_stats` (the `stats_player_reg` file) for every player.

## Opportunity (from `player_week_stats` columns)

- [x] `targets_pg` (targets / games), `target_share` (mean of weekly `target_share`), `air_yards_share` (mean of weekly `air_yards_share`), `wopr` (mean of weekly `wopr`), `carries_pg` (carries / games) — per season, REG only.
- [x] Opportunity trend: 2024 → 2025 change in `target_share` and `carries_pg` (used by Phase 6 flags: "opportunity gain").
- [x] Route / red-zone metrics are **deferred** with their sources (participation, snap_counts, pbp — Phase 1b); no placeholder columns.

## Luck (from `player_expected_stats`, re-scored)

- [x] Per season: `points_actual = Σ score(actual stat line)` and `points_expected = Σ score(*_exp stat line)` under league scoring, using ffopportunity's `receptions_exp`, `rec_yards_gained_exp`, `rush_yards_gained_exp`, `rec_touchdown_exp`, `rush_touchdown_exp`, `pass_touchdown_exp` (and the pass-yards `*_exp` column) — **never its precomputed points**.
- [x] `luck_points = score(actual) − score(expected)`; `ppg_diff = luck_points / games`.
- [x] `td_diff = (rush_td + rec_td + pass_td) − (rush_touchdown_exp + rec_touchdown_exp + pass_touchdown_exp)` per season.
- [x] Phase 6 thresholds these as flag signals: negative luck if `|td_diff| ≥ 3` or `|ppg_diff| ≥ 1.0`; store the raw values here, not the flag.

## Durability

- [x] `games_missed(season)` = team REG games (excl. bye, from `games` / `team_bye`) where the player was on 53/IR/PUP (roster status **not** DEV/CUT/SUS/RET/EXE in `roster_weeks`) minus weeks present in `player_week_stats` with ≥ 1 opportunity (target or carry or pass attempt).
- [x] Roster status mapping documented in `docs/spec/data-model.md` against the values actually observed in `roster_weekly_2025` (ACT / DEV / RES / INA / CUT / RET / EXE / TRD / TRC; `status_description_abbr` R01 reserve/injured, R04 reserve/PUP): eligible = ACT, RES, INA; excluded = DEV, CUT, RET, EXE; TRD/TRC are logged in `decisions.md` with the choice made.
- [x] `eligible_games(season)` = the count of eligible team-weeks above; player-weeks with no roster row or an unmapped status are **"unknown"**, never "missed".
- [x] Cause per missed week from `injury_weeks.report_primary_injury` for that week (blank → `unspecified`); stored per (player, season, week) as `missed_weeks` rows: `season`, `week`, `status`, `primary_injury`, `practice_status`.
- [x] Distinct injury events: consecutive missed weeks with the same `report_primary_injury` collapse into one event.
- [x] `injury_prone` = (`missed / eligible` over 2023–25 ≥ **0.20** AND ≥ **2** distinct injury events across ≥ **2** seasons) OR ≥ **2** soft-tissue listings in different seasons (soft-tissue = `report_primary_injury` in {Hamstring, Groin, Calf}; the string set lives in one constant and is listed in `docs/spec/ranking-model.md`).
- [x] `structural_injury_return` tag for a single season-ending ACL / Achilles (from `report_primary_injury` strings and Sleeper `injury_body_part` such as "Knee - ACL"), with the return-season discount applied only if the injury date is **< 12 months before Week 1** (2026-09-10).
- [x] `known_missed_weeks` = `players.injury_status` (Sleeper, once/day) in {IR, PUP, Out} (observed values on 2026-08-29: Questionable / IR / PUP / Sus / Doubtful / DNR / NA / null) mapped to a week count, **plus** `backend/seeds/known_missed_weeks.yaml` rows (`player`, `gsis_id`, `weeks`, `reason`, `source_url`, `confidence`, `last_checked` — per `docs/spec/data-model.md`) for announced multi-week absences; the seed row wins when both exist.
- [x] `E[games]` = `min(17 − known_missed_weeks, 17 − expected_missed)` where `expected_missed` = positional base by ADP band **[RB 2.4 / 3.3 / 3.8, WR 2.2 / 2.8 / 3.3 games missed for rounds 1–2 / 3–5 / 6–8]** + **1.0 game per 20 % historical rate above base** (historical rate = `missed / eligible` 2023–25; base rate = base / 17); this is the **ONE** `E[games]` used everywhere downstream (Phase 6 season value, Phase 8 availability).
- [x] QB/TE (and RB/WR outside rounds 1–8) use the nearest band documented in `docs/spec/ranking-model.md`; the choice is recorded, not silently defaulted.
- [x] ADP band for the base rate comes from the Phase 4-lite composite ADP (room-adjusted once keepers exist); until then, raw composite.

## Consistency (display only)

- [x] Per season, over REG weeks **excluding weeks with < 3 opportunities**: `mean`, `sd`, `floor` (25th percentile), `ceiling` (90th percentile) of weekly `score()` points.
- [x] Starter threshold per week = weekly points of the (**teams × starters[pos]**)-th player at that position that week (10 teams × `roster.starters[pos]` from `league.yaml`); `pct_weeks_above_starter` per season.
- [x] These columns are marked `display_only` in the spec and are not inputs to ranking, value or flags.

## Bio

- [x] `age` = age at **2026-09-10** from `rosters_2026.birth_date` (fallback `players.birth_date`).
- [x] `years_exp` from `rosters_2026.years_exp`.
- [x] Draft capital: `draft_year`, `draft_round`, `draft_pick` from `draft_picks_nfl` (2026 rows joined on `esb_id`; earlier years on `gsis_id`), fallback `rosters_2026.draft_club` / `draft_number`; UDFA ⇒ `draft_round = null`, `udfa = true`.
- [x] `rookie = (rosters_2026.entry_year == 2026)`.
- [x] 2026 team-of-record from `rosters_2026.team`; current depth-chart slot from `depth_chart_snapshots` at `max(dt)` per team (`pos_abb`, `pos_rank`), with the `dt` stored for WHY bullets (e.g. "RB1 on ARI depth chart (Aug 29)").

## Output, CLI, tests

- [x] `player_features` table columns enumerated in `docs/spec/data-model.md` (one column per bullet above, with `season`-suffixed variants for 2023/2024/2025; keyed `(run_id, player_id)`).
- [x] `uv run features build` computes everything for all players from Postgres (no network) within the `recompute` budget (the whole pipeline < 5 min) and records the snapshot ids it read on the `ranking_runs` row.
- [x] `uv run features show --name "<name>"` prints the profile (production / opportunity / luck / durability / consistency / bio) for the gate checks.
- [x] `test_profiles_match_nflverse_reg.py`: 5 named-player profiles match nflverse REG totals from `player_season_stats` (e.g. Bijan Robinson 2025 rushing attempts / yards; ESPN's independent 2025 REG figures for him — 287 attempts, 1,478 yards, 7 rushing TDs, 103 targets, 820 receiving yards — recorded in the test as a cross-check, with the source URL).
- [x] `test_games_missed.py`: games-missed correct for 3 players with known 2024/2025 IR stints, on real `roster_weekly` fixture rows (candidates verified in the research: Zach Ertz 2025 — ACT weeks 1–14 then RES weeks 15–18; Mike Evans 2025 — ACT 1–3, INA 4–6, ACT 7, RES 8–14, ACT 15–18; third player chosen from a 2024 IR stint), each fixture with PROVENANCE.
- [x] `test_rookie_profile.py`: a 2026 rookie (e.g. Jeremiyah Love, ARI, R1 #3, `entry_year` 2026) returns nulls for every historical feature, `rookie = true`, draft capital populated, no exception.
- [x] `test_injury_prone.py` and `test_e_games.py`: rule and formula checks on real fixture rows (one player above the 0.20 threshold, one below, one soft-tissue repeat; one `E[games]` per band).
- [x] `docs/spec/ranking-model.md` durability section filled in with the definitions above.

## Gate

5 named-player profiles match nflverse REG totals (e.g. Bijan Robinson 2025 rushing attempts/yards); games-missed correct for 3 players with known 2024/2025 IR stints; rookie profile returns nulls cleanly.

## Derek's actions

None.


## Results (2026-08-30)

```
uv run ff features build
{'seasons': [2023, 2024, 2025], 'player_season_features': 1443, 'player_features': 961,
 'league_config': 'yahoo_default_public_league_scoring', 'no_history_players': 387}

uv run ff features check
[PASS] Bijan Robinson / Ja'Marr Chase / Puka Nacua / Josh Allen / Jahmyr Gibbs 2025 totals reconcile with nflverse REG
[PASS] player_features covers the whole QB/RB/WR/TE hub (961 rows, 387 without history)
[PASS] rookies return null history with populated depth/bio
GATE PASSED
```

`player_features` and `player_season_features` are **derived tables**: dropped and rebuilt wholesale by
`ff features build`, so their schema follows the feature modules rather than a hand-written model. Alembic is told to
ignore them (`alembic/env.py` `DERIVED_TABLES`) exactly as it ignores the `raw_*` mirrors.

### E[games] is computed once, from both inputs

`durability.compute_summary` runs before the market exists (so `adp_round=None`, everyone in the middle band) and
`projections.with_expected_games` has the ADP band but no injury history — neither is complete. The assembler
(`_final_expected_games` in `app/features/build.py`) recomputes it once from the ADP band **and** the player's own
miss rate **and** announced absences, which is the single application the plan requires.

History is only applied when the player actually has usage (≥ 8 games played across 2023–25). Without that gate a
healthy backup reads as catastrophically injury-prone, because `games_played` requires an opportunity
(durability.py quirk 1: Skylar Thompson 47/49 "missed", Andy Dalton 39/51).

### Carried-forward quirks that Phase 6 must respect

1. `miss_rate_3yr` is only meaningful for players with real usage — gate it (the assembler already does for E[games]).
2. A player on IR **disappears from the weekly injury report**, so `injury_causes` under-reports season-enders;
   `games_missed` is the reliable signal. `structural_injury_return` therefore has a second detection path via
   Sleeper's `injury_body_part` + a ≥4-week trailing 2025 absence (catches Nabers, Hill, Kraft, Penix, Dell, Gibson).
3. `compute()` is hub-limited, so 2023 has only 392 player-seasons and positional ranks are "within surviving
   players" — true historical positional ranks would have to be computed before the hub join.
4. Expected points carry **no fumble penalty** (ffopportunity ships no `*_fumble_lost_exp`), biasing league-wide
   `ppg_diff` by −0.20.
5. `pct_weeks_above_starter` and `bust_rate` are exact complements — not independent signals.
