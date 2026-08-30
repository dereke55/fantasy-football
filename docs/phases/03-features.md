# Phase 3 — Historical features, REG only (day 3)

Turn 2023–2025 regular-season data into one `player_features` row per player: production, opportunity, luck, durability, consistency and bio — every number computed under league scoring, every rookie returning nulls cleanly.

**Status:** Not started

**Calendar:** Day 3 — Wed Sep 2 — "Phase 3 features gate".

**Plan reference:** `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 3 — Historical features, REG only (day 3)". Depends on Phase 1a tables (`player_week_stats`, `player_season_stats`, `player_expected_stats`, `roster_weeks`, `injury_weeks`, `games` / `team_bye`, `rosters_2026`, `depth_chart_snapshots`, `draft_picks_nfl`, Sleeper injury fields) and the Phase 2 `score()` engine.

## Scope rules

- [ ] Every feature reads only `season_type == 'REG'` rows (weeks 1–18); POST rows (weeks 19–22 in the 2025 files) are excluded by filter, never by deletion.
- [ ] Seasons are 2023, 2024, 2025 (explicit); 2022 only if it was ingested at zero cost in Phase 1a.
- [ ] All points are `score()` outputs under `config/league.yaml`; vendor `fantasy_points*` / `*_fantasy_points_exp` columns are never read.
- [ ] `player_features` is written per run, keyed `(run_id, player_id)` as in `docs/spec/data-model.md` (config hash and input snapshot ids live on the `ranking_runs` row), so WHY bullets can cite the exact inputs.
- [ ] Rookies (2026 `entry_year == 2026`; 682 players on the 2026-08-29 roster file, 257 drafted + 425 UDFA): all historical features are `null`, no exceptions raised, `rookie = true`.

## Production

- [ ] Per season: `games` (REG weeks with a `player_week_stats` row), `points` (Σ `score(week)`), `ppg = points / games`.
- [ ] Positional PPG rank per season among players with ≥ 1 game (rank within `position`).
- [ ] YoY deltas: `ppg_delta_24_25`, `ppg_delta_23_24`, `pos_rank_delta_24_25`.
- [ ] 3-season weighted trend with weights **0.5 / 0.3 / 0.2** (2025 / 2024 / 2023), **restricted to same team + role seasons** (role = depth-chart slot / usage tier; a season on a different team or in a different role is excluded and the weights renormalised over the remaining seasons; if none remain the trend is null).
- [ ] Cross-check: per-season `games`, carries, rushing_yards, targets, receptions match `player_season_stats` (the `stats_player_reg` file) for every player.

## Opportunity (from `player_week_stats` columns)

- [ ] `targets_pg` (targets / games), `target_share` (mean of weekly `target_share`), `air_yards_share` (mean of weekly `air_yards_share`), `wopr` (mean of weekly `wopr`), `carries_pg` (carries / games) — per season, REG only.
- [ ] Opportunity trend: 2024 → 2025 change in `target_share` and `carries_pg` (used by Phase 6 flags: "opportunity gain").
- [ ] Route / red-zone metrics are **deferred** with their sources (participation, snap_counts, pbp — Phase 1b); no placeholder columns.

## Luck (from `player_expected_stats`, re-scored)

- [ ] Per season: `points_actual = Σ score(actual stat line)` and `points_expected = Σ score(*_exp stat line)` under league scoring, using ffopportunity's `receptions_exp`, `rec_yards_gained_exp`, `rush_yards_gained_exp`, `rec_touchdown_exp`, `rush_touchdown_exp`, `pass_touchdown_exp` (and the pass-yards `*_exp` column) — **never its precomputed points**.
- [ ] `luck_points = score(actual) − score(expected)`; `ppg_diff = luck_points / games`.
- [ ] `td_diff = (rush_td + rec_td + pass_td) − (rush_touchdown_exp + rec_touchdown_exp + pass_touchdown_exp)` per season.
- [ ] Phase 6 thresholds these as flag signals: negative luck if `|td_diff| ≥ 3` or `|ppg_diff| ≥ 1.0`; store the raw values here, not the flag.

## Durability

- [ ] `games_missed(season)` = team REG games (excl. bye, from `games` / `team_bye`) where the player was on 53/IR/PUP (roster status **not** DEV/CUT/SUS/RET/EXE in `roster_weeks`) minus weeks present in `player_week_stats` with ≥ 1 opportunity (target or carry or pass attempt).
- [ ] Roster status mapping documented in `docs/spec/data-model.md` against the values actually observed in `roster_weekly_2025` (ACT / DEV / RES / INA / CUT / RET / EXE / TRD / TRC; `status_description_abbr` R01 reserve/injured, R04 reserve/PUP): eligible = ACT, RES, INA; excluded = DEV, CUT, RET, EXE; TRD/TRC are logged in `decisions.md` with the choice made.
- [ ] `eligible_games(season)` = the count of eligible team-weeks above; player-weeks with no roster row or an unmapped status are **"unknown"**, never "missed".
- [ ] Cause per missed week from `injury_weeks.report_primary_injury` for that week (blank → `unspecified`); stored per (player, season, week) as `missed_weeks` rows: `season`, `week`, `status`, `primary_injury`, `practice_status`.
- [ ] Distinct injury events: consecutive missed weeks with the same `report_primary_injury` collapse into one event.
- [ ] `injury_prone` = (`missed / eligible` over 2023–25 ≥ **0.20** AND ≥ **2** distinct injury events across ≥ **2** seasons) OR ≥ **2** soft-tissue listings in different seasons (soft-tissue = `report_primary_injury` in {Hamstring, Groin, Calf}; the string set lives in one constant and is listed in `docs/spec/ranking-model.md`).
- [ ] `structural_injury_return` tag for a single season-ending ACL / Achilles (from `report_primary_injury` strings and Sleeper `injury_body_part` such as "Knee - ACL"), with the return-season discount applied only if the injury date is **< 12 months before Week 1** (2026-09-10).
- [ ] `known_missed_weeks` = `players.injury_status` (Sleeper, once/day) in {IR, PUP, Out} (observed values on 2026-08-29: Questionable / IR / PUP / Sus / Doubtful / DNR / NA / null) mapped to a week count, **plus** `backend/seeds/known_missed_weeks.yaml` rows (`player`, `gsis_id`, `weeks`, `reason`, `source_url`, `confidence`, `last_checked` — per `docs/spec/data-model.md`) for announced multi-week absences; the seed row wins when both exist.
- [ ] `E[games]` = `min(17 − known_missed_weeks, 17 − expected_missed)` where `expected_missed` = positional base by ADP band **[RB 2.4 / 3.3 / 3.8, WR 2.2 / 2.8 / 3.3 games missed for rounds 1–2 / 3–5 / 6–8]** + **1.0 game per 20 % historical rate above base** (historical rate = `missed / eligible` 2023–25; base rate = base / 17); this is the **ONE** `E[games]` used everywhere downstream (Phase 6 season value, Phase 8 availability).
- [ ] QB/TE (and RB/WR outside rounds 1–8) use the nearest band documented in `docs/spec/ranking-model.md`; the choice is recorded, not silently defaulted.
- [ ] ADP band for the base rate comes from the Phase 4-lite composite ADP (room-adjusted once keepers exist); until then, raw composite.

## Consistency (display only)

- [ ] Per season, over REG weeks **excluding weeks with < 3 opportunities**: `mean`, `sd`, `floor` (25th percentile), `ceiling` (90th percentile) of weekly `score()` points.
- [ ] Starter threshold per week = weekly points of the (**teams × starters[pos]**)-th player at that position that week (10 teams × `roster.starters[pos]` from `league.yaml`); `pct_weeks_above_starter` per season.
- [ ] These columns are marked `display_only` in the spec and are not inputs to ranking, value or flags.

## Bio

- [ ] `age` = age at **2026-09-10** from `rosters_2026.birth_date` (fallback `players.birth_date`).
- [ ] `years_exp` from `rosters_2026.years_exp`.
- [ ] Draft capital: `draft_year`, `draft_round`, `draft_pick` from `draft_picks_nfl` (2026 rows joined on `esb_id`; earlier years on `gsis_id`), fallback `rosters_2026.draft_club` / `draft_number`; UDFA ⇒ `draft_round = null`, `udfa = true`.
- [ ] `rookie = (rosters_2026.entry_year == 2026)`.
- [ ] 2026 team-of-record from `rosters_2026.team`; current depth-chart slot from `depth_chart_snapshots` at `max(dt)` per team (`pos_abb`, `pos_rank`), with the `dt` stored for WHY bullets (e.g. "RB1 on ARI depth chart (Aug 29)").

## Output, CLI, tests

- [ ] `player_features` table columns enumerated in `docs/spec/data-model.md` (one column per bullet above, with `season`-suffixed variants for 2023/2024/2025; keyed `(run_id, player_id)`).
- [ ] `uv run features build` computes everything for all players from Postgres (no network) within the `recompute` budget (the whole pipeline < 5 min) and records the snapshot ids it read on the `ranking_runs` row.
- [ ] `uv run features show --name "<name>"` prints the profile (production / opportunity / luck / durability / consistency / bio) for the gate checks.
- [ ] `test_profiles_match_nflverse_reg.py`: 5 named-player profiles match nflverse REG totals from `player_season_stats` (e.g. Bijan Robinson 2025 rushing attempts / yards; ESPN's independent 2025 REG figures for him — 287 attempts, 1,478 yards, 7 rushing TDs, 103 targets, 820 receiving yards — recorded in the test as a cross-check, with the source URL).
- [ ] `test_games_missed.py`: games-missed correct for 3 players with known 2024/2025 IR stints, on real `roster_weekly` fixture rows (candidates verified in the research: Zach Ertz 2025 — ACT weeks 1–14 then RES weeks 15–18; Mike Evans 2025 — ACT 1–3, INA 4–6, ACT 7, RES 8–14, ACT 15–18; third player chosen from a 2024 IR stint), each fixture with PROVENANCE.
- [ ] `test_rookie_profile.py`: a 2026 rookie (e.g. Jeremiyah Love, ARI, R1 #3, `entry_year` 2026) returns nulls for every historical feature, `rookie = true`, draft capital populated, no exception.
- [ ] `test_injury_prone.py` and `test_e_games.py`: rule and formula checks on real fixture rows (one player above the 0.20 threshold, one below, one soft-tissue repeat; one `E[games]` per band).
- [ ] `docs/spec/ranking-model.md` durability section filled in with the definitions above.

## Gate

5 named-player profiles match nflverse REG totals (e.g. Bijan Robinson 2025 rushing attempts/yards); games-missed correct for 3 players with known 2024/2025 IR stints; rookie profile returns nulls cleanly.

## Derek's actions

None.
