# Phase 1a — Crosswalk first, then MVP ingestion (days 1–2)

Build the players id hub first (so every later table joins on one key), then pull every MVP source into Postgres as registered, immutable raw snapshots — explicit seasons everywhere, one failing source never fails the job.

**Status:** Not started

**Calendar:** Day 1 — Sun Aug 30 / Mon Aug 31 — crosswalk gate (players hub by end of day 1). Day 2 — Tue Sep 1 — "Ingest 1a + scoring gate + market composite".

**Plan reference:** `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 1a — Crosswalk first, then MVP ingestion (days 1–2)" and "Phase 1b — Post-MVP sources (only after day 6)". Verified source facts below come from the 2026-08-29 research pass (every endpoint was exercised live that day).

## Ground rules for every ingest job

- [x] Every nflreadpy call passes explicit `seasons=[...]` (never `seasons=None`; `get_current_season()` flips to 2026 on 2026-09-10 and 2026 stat files 404 until nflverse publishes them).
- [x] Every pull writes an immutable, hash-deduped snapshot to `data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}` and a `raw_snapshots` row (source, endpoint, fetched_at, sha256, path, row_count, upstream_as_of, status, error).
- [x] Per-source isolation: `ingest all` runs each source in its own try/except, records the failure in `raw_snapshots.status/error`, continues, and exits non-zero only if **every** source failed.  _exit code: `ingest all` per-module isolation; each module `all` exits 0 if ≥1 dataset succeeded_
- [ ] The app loads from the last good snapshot of each source when a pull fails (unofficial endpoints can change or block before draft day).
- [x] 2025 nflverse files include postseason weeks 19–22: rows are loaded with `season_type` kept and filtered to `season_type == 'REG'` downstream — never dropped at ingest.
- [x] Vendor fantasy-point columns (`fantasy_points`, `fantasy_points_ppr`, ffopportunity `*_fantasy_points*`, Sleeper `pts_*`, ESPN `appliedTotal`) are stored raw but never surfaced; every point value shown is computed by the Phase 2 scorer.
- [x] New source ⇒ README "Data sources / cadence / licensing" row + snapshot parser + `raw_snapshots` registration (CLAUDE.md rule).

## 1a.1 — Players hub (end of day 1)

Hub table `players` (columns in `docs/spec/data-model.md` → Identity) with the plan's id set — gsis, esb, sleeper, espn, yahoo, fantasypros, pfr, otc — stored as `gsis_id`, `esb_id`, `sleeper_id`, `espn_id`, `yahoo_id`, `fantasypros_id`, `pfr_id`, `otc_id` (plus `display_name`, `merge_name`, `position`, `team` = team-of-record, `birth_date`).

Sources and the columns they contribute (verified 2026-08-29):

| Source | Loader / URL | Id columns used |
|---|---|---|
| nflverse `players` (release tag `players`, refreshed 2026-08-29) | `nflreadpy.load_players()` | `gsis_id`, `esb_id`, `espn_id`, `pfr_id`, `pff_id`, `otc_id`, `smart_id`, `display_name`, `position`, `latest_team`, `birth_date`, `rookie_season`, `draft_year`, `draft_round`, `draft_pick`, `draft_team`, `status` |
| DynastyProcess `ff_playerids` (`db_playerids.csv`, CSV only) | `nflreadpy.load_ff_playerids()` | `gsis_id`, `sleeper_id`, `espn_id`, `yahoo_id`, `stats_id`, `fantasypros_id`, `pfr_id`, `pff_id`, `mfl_id`, `sportradar_id`, `merge_name`, `position`, `team`, `draft_year`, `draft_ovr` |
| nflverse `roster_2026` (refreshed daily in preseason) | `nflreadpy.load_rosters(seasons=[2026])` | `gsis_id`, `esb_id`, `sleeper_id`, `espn_id`, `yahoo_id`, `pfr_id`, `team` (canonical team-of-record), `status` (ACT/RES/E14/RET/CUT), `birth_date`, `years_exp`, `entry_year`, `rookie_year`, `draft_club`, `draft_number` |
| Yahoo public pool (no OAuth) | `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;start=N;count=100;out=draft_analysis?format=json` | `player_id` (== Yahoo id), `player_key` (`470.p.{id}`; 2026 game_key is 470), `name.full`, `editorial_team_abbr`, `display_position`, `eligible_positions`, `bye_weeks.week`, `is_keeper` |

- [x] Load nflverse `players` and `ff_playerids`; join on `gsis_id`; `yahoo_id = coalesce(yahoo_id, stats_id)` (ff_playerids `yahoo_id` is NA for the whole 2025–26 rookie classes but `stats_id` == Yahoo id; 100/100 of Yahoo's top-100 verified).
- [x] Load `roster_2026` and set `players.team` from it (canonical team-of-record); carry `esb_id` (needed for the 2026 `draft_picks` join).
- [x] Pull the Yahoo public pool: ~6 pages of 100 sorted `AR`, plus one pass each for `DEF` and `K` (position filter), **2 s spacing** between requests, once/day, **never during the draft**; store every page as a raw snapshot (`yahoo_pub/players`); cast string values to float (`average_pick`, `average_round`, `average_cost`, `percent_drafted`, `preseason_*` are strings).
- [x] Map Yahoo title-case team abbreviations to nflverse abbreviations in one table (`ingest/team_abbr.py`), unit-tested on the 32 teams.  _mapping lives in app/ingest/players_hub.py (YAHOO_TEAM_MAP) and yahoo_pub.py_
- [x] Resolve Yahoo pool rows to `players` **by id first** (`yahoo_id`), then by normalized name + team + position; write unresolved rows to `data/derived/unmatched.csv` (columns: source, source_id, name, team, pos, reason).  _unresolved rows go to data/reports/unmatched.csv_
- [x] `backend/seeds/id_overrides.yaml` (rows: `source`, `source_id`, `gsis_id` (or `player_id`), `reason`, `source_url` — per `docs/spec/data-model.md`) applied last and logged; expect ~1–3 % of players to need overrides.
- [ ] `backend/seeds/yahoo_team_defense_ids.yaml` with exactly 32 rows (`team`, `yahoo_id`, `yahoo_player_key` — per `docs/spec/data-model.md`) populated from the DEF pass of the pool pull.
- [x] CLI `uv run ingest check-ids` prints: resolved/unresolved counts per source, the four gate coverages below, and the unmatched percentage; it is re-run after every ingest and its output is pasted into this file under "Results".  _command is `uv run ff ingest check-ids`; results pasted below_
- [x] Rookie coverage check: every 2026 R1–R4 QB/RB/WR/TE pick from `draft_picks` resolves — 2026 rows carry ESB ids in the `gsis_id` column (e.g. `MEN516487`, `LOV121782`), so join `draft_picks.gsis_id == roster_2026.esb_id` (256/257 match) with name + college fallback for the blanks.

**Crosswalk gate (from the plan):** top-300 ECR, top-300 Sleeper projection rows, top-400 Yahoo pool, every 2026 R1–R4 QB/RB/WR/TE pick resolve; `unmatched.csv` < 3% and reviewed.

## 1a.2 — MVP sources (explicit seasons; 2022 optional at zero cost)

| # | Source → table | Loader / URL (verified) | Seasons / filter | Key columns | Gotchas |
|---|---|---|---|---|---|
| 1 | `stats_player_week` → `player_week_stats` | `load_player_stats(seasons=[2023,2024,2025], summary_level='week')` (release `stats_player`, 150 cols) | 2023–2025; keep `season_type`, use `REG` downstream | `player_id` (= gsis), `season`, `week`, `season_type`, `team`, `opponent_team`, `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`, `carries`, `rushing_yards`, `rushing_tds`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `receiving_air_yards`, `target_share`, `air_yards_share`, `wopr`, `racr`, `fumbles_lost_total`, `rushing_fumbles_lost`, `receiving_fumbles_lost`, `sack_fumbles_lost`, `passing_2pt_conversions`, `rushing_2pt_conversions`, `receiving_2pt_conversions`, `special_teams_tds` | A row exists only if the player recorded a stat (DNP weeks are absent — use `roster_weekly`). No red-zone columns. Legacy `player_stats` tag is frozen at 2024 — do not use. |
| 2 | `stats_player_reg` → `player_season_stats` | `load_player_stats(seasons=[2023,2024,2025], summary_level='reg')` | 2023–2025 | same counting columns + `recent_team`, `games` | REG-only aggregate; used for Phase 3 gate cross-checks. |
| 3 | `roster_weekly` → `roster_weeks` | `load_rosters_weekly(seasons=[2023,2024,2025])` | weeks 1–22; `game_type` REG/WC/DIV/CON/SB | `gsis_id`, `season`, `week`, `game_type`, `team`, `position`, `status`, `status_description_abbr` | 2025 status values: ACT / DEV / RES / INA / CUT / RET / EXE / TRD / TRC; `status_description_abbr` R01 = reserve/injured, R04 = reserve/PUP. Drives Phase 3 games-missed. |
| 4 | `injuries` → `injury_weeks` | `load_injuries(seasons=[2023,2024,2025])` | REG + POST, weeks 1–22 | `gsis_id`, `season`, `season_type`, `week`, `team`, `report_primary_injury`, `report_secondary_injury`, `report_status` ('' / Out / Questionable / Doubtful), `practice_status` | In-season only; **no 2026 file** (404) and no preseason reports. Schema differs before 2023 (2009 lacks `season_type`) — restrict to 2023–2025. IR players drop off the report, so never count games missed from this table alone. |
| 5 | `ff_opportunity` weekly → `player_expected_stats` | `load_ff_opportunity(seasons=[2023,2024,2025], stat_type='weekly')` (ffverse release `latest-data`, `ep_weekly_{season}`, 159 cols) | weeks 1–22; exclude postseason via `game_id` → `games.game_type == 'REG'` | `player_id` (gsis), `season`, `week`, `game_id`, `posteam`, `position`, `pass_attempt`, `rec_attempt`, `rush_attempt`, `receptions`, `receptions_exp`, `rec_yards_gained`, `rec_yards_gained_exp`, `rush_yards_gained_exp`, `rec_touchdown`, `rec_touchdown_exp`, `rush_touchdown_exp`, `pass_touchdown_exp`, `*_diff`, `*_team` | Its `*_fantasy_points*` columns use ffverse default scoring — never use them; Phase 3 re-scores `*_exp` under league scoring. |
| 6 | `rosters` 2026 → `rosters_2026` | `load_rosters(seasons=[2026])` | current | see hub table above | Canonical team-of-record; 2,930 rows on 2026-08-29 (pre-cutdown); re-pull daily. |
| 7 | `depth_charts` 2026 → `depth_chart_snapshots` | `load_depth_charts(seasons=[2026])` | **all `dt`** snapshots (162 daily snapshots 2026-03-22 → 2026-08-29) | `dt`, `team`, `gsis_id`, `espn_id`, `player_name`, `pos_grp`, `pos_abb`, `pos_slot`, `pos_rank` | New format is timestamp-based `dt`, not week-based; current chart = `max(dt)` per team; history is kept to detect camp competitions. Updates daily 07:00 UTC. |
| 8 | `schedules` → `games` + `team_bye` | `load_schedules(seasons=[2023,2024,2025,2026])` (`nfldata games.csv`) | 2023–2026; 2026 = 272 REG games, week 1 begins 2026-09-09 | `game_id`, `season`, `game_type`, `week`, `gameday`, `home_team`, `away_team`, `home_score`, `away_score` | Derive `team_bye(season, team, bye_week)` = the REG week each team has no game. **Never derive HC changes from the 2026 `home_coach`/`away_coach` columns** (stale for 3 teams, name typo for LV). |
| 9 | `draft_picks` → `draft_picks_nfl` | `load_draft_picks()` (updated 2026-05-05; 257 picks for 2026) | 2023–2026 | `season`, `round`, `pick`, `team`, `gsis_id`, `pfr_player_id`, `pfr_player_name`, `position`, `college`, `age` | 2026 rows hold ESB ids in `gsis_id` → join `roster_2026.esb_id`; name + college fallback (230/257 also resolve via `players.esb_id`). |
| 10 | `ff_rankings('draft')` → `rank_snapshots` (source `fantasypros_mirror`) | `load_ff_rankings(type='draft')` (DynastyProcess `db_fpecr_latest.csv`, scraped 2026-08-28, 5,552 rows across 31 pages) | filter `page_type == 'redraft-overall'` and `ecr_type == 'ro'`; choose the `fp_page` that matches the league's reception scoring (`/nfl/rankings/ppr-cheatsheets.php`, `/nfl/rankings/half-point-ppr-cheatsheets.php`, or `/nfl/rankings/consensus-cheatsheets.php` for STD) and record the choice in `league.yaml` | `id` (= fantasypros_id), `player`, `pos`, `team`, `ecr` (avg), `sd`, `best`, `worst`, `bye`, `yahoo_id`, `scrape_date` | There is no `page_type` literally named `ppr-cheatsheets`. Weekly-ish cadence: `scrape_date` is `upstream_as_of`. Re-pull daily until the draft. |
| 11 | Sleeper projections → `projections` (source `sleeper_rotowire`, company `rotowire`; ADP fields also → `rank_snapshots` source `sleeper`, see Phase 4-lite) | `https://api.sleeper.com/projections/nfl/2026?season_type=regular&position[]=QB&position[]=RB&position[]=WR&position[]=TE&position[]=K&position[]=DEF&order_by=adp_ppr` | 3,303 records on 2026-08-29; keep QB/RB/WR/TE/K/DEF rows with **≥ 1 counting stat** | `player_id` (= sleeper_id), `team`, `company`, `last_modified`, `updated_at`, `stats.pass_att`, `pass_cmp`, `pass_yd`, `pass_td`, `pass_int`, `rush_att`, `rush_yd`, `rush_td`, `rec`, `rec_yd`, `rec_td`, `fum_lost`, `fgm_40_49`, `fgm_50p`, `xpm`, `sack`, `int`, `pts_allow_0`, `stats.adp_ppr`, `adp_half_ppr`, `adp_std`, `adp_2qb` | `stats.gp` is a constant 18 — **never use**. ADP `999`/`1000` = undrafted sentinel → store as null (rule: null any ADP ≥ 999). Store `company` + `last_modified` as `upstream_as_of`. Cached upstream 1 h (`s-maxage=3600`); pull once/day. Undocumented endpoint — may be blocked; run on last good snapshot. |
| 12 | Sleeper players → `players.injury_status`, `players.injury_body_part`, `players.injury_status_as_of` | `https://api.sleeper.app/v1/players/nfl` (14.6 MB, 12,225 objects) | once/day, conditional on `ETag` (`If-None-Match`; upstream `s-maxage=600`) | `player_id`, `full_name`, `team`, `position`, `status`, `injury_status`, `injury_body_part`, `injury_notes`, `injury_start_date`, `practice_participation`, `depth_chart_order`, `depth_chart_position`, `yahoo_id`, `espn_id`, `gsis_id`, `stats_id`, `news_updated` | `injury_status` values observed 2026-08-29: Questionable / IR / PUP / Sus / Doubtful / DNR / NA / null. `gsis_id` is often null on Sleeper — join via `sleeper_id` from the hub, not `gsis_id`. Sleeper asks for at most one fetch per day. |
| 13 | FFC ADP × 3 formats → `rank_snapshots` (source `ffc`, format ppr / half-ppr / standard) | `https://fantasyfootballcalculator.com/api/v1/adp/{ppr|half-ppr|standard}?teams=10&year=2026` | once/day (data updates once per day) | `meta.start_date`, `meta.end_date`, `meta.total_drafts`, `players[].player_id` (FFC-internal), `name`, `position`, `team`, `adp`, `stdev`, `high`, `low`, `times_drafted`, `bye` | No external ids → join by normalized name + team + position (suffix normalisation). Store `meta.start_date/end_date/total_drafts` per snapshot (the window is not always 7 days). Attribution link required in README. |
| 14 | Yahoo pub ADP → `rank_snapshots` (source `yahoo_pub`, format `yahoo_default`, kind `adp`) | same pull as the players hub (`out=draft_analysis`) | once/day, never during the draft | `player_id`, `draft_analysis.average_pick`, `average_round`, `average_cost`, `percent_drafted`, `preseason_average_pick` | Site-wide ADP across all Yahoo leagues (label it as such); no stdev/min/max. |

- [x] Sources 1–14 implemented as `ingest <name>` subcommands sharing the snapshot writer; `ingest all` runs them in the order above (hub sources first).  _1a sources done: nflverse stats/ref, Sleeper, FFC, Yahoo pub; `ff ingest all` runs them hub-first_
- [ ] 2022 seasons for sources 1–5 are pulled only if they add zero effort (same loader, extra season value); otherwise skipped without a code path.
- [x] Freshness: one `https://api.github.com/repos/nflverse/nflverse-data/releases/tags/{tag}` call per tag (`stats_player`, `weekly_rosters`, `injuries`, `rosters`, `depth_charts`, `schedules`, `draft_picks`, `players`) and `https://api.github.com/repos/ffverse/ffopportunity/releases/tags/latest-data`, optional `GITHUB_TOKEN` (60 req/hr unauthenticated); compare **per-asset `updated_at`** (not the tag-level `timestamp.json`, which moved on 2026-08-26 for a 2020 re-push while the 2025 assets were last rebuilt 2026-08-13); store as `raw_snapshots.upstream_as_of`; skip the download when unchanged.  _per-asset updated_at via asset_updated_at(tag, asset) stored as upstream_as_of; unchanged-skip is by content hash (skipped_dupe), not pre-download_
- [x] `upstream_as_of` for non-GitHub sources: Sleeper projections `last_modified`; Sleeper players `ETag` + fetch time; FFC `meta.end_date`; Yahoo pub fetch time; ff_rankings `scrape_date`.
- [ ] `uv run ingest reg-weeks-check` asserts REG weeks 1–18 present for 2023, 2024 and 2025 for all 32 teams in `player_week_stats` and `roster_weeks` (POST rows present but excluded) and prints a per-season/team matrix.
- [ ] `uv run ingest snapshots` lists every `raw_snapshots` row (source, endpoint, fetched_at, row_count, upstream_as_of, status).
- [ ] Test: a static check (AST or grep in `tests/test_explicit_seasons.py`) fails if any `nflreadpy.load_*` call site that accepts `seasons` omits an explicit list.
- [ ] Test: `ingest all` runs green with the clock mocked to **2026-09-11** (every loader still requests 2023–2025 / 2026 explicitly; nothing calls `get_current_season()`), against real fixture extracts under `backend/tests/fixtures/{source}/` with `PROVENANCE.md` (url, fetched_at, sha256).
- [ ] Test: per-source isolation — with one source's fixture replaced by an HTTP 500 stub, `ingest all` still ingests the other sources and records the failure.
- [x] README "Data sources / cadence / licensing" table rows exist for every source above (nflverse CC-BY-4.0 attribution; ffverse; DynastyProcess mirror; FFC attribution; Sleeper documented + undocumented; Yahoo pub unofficial).
- [ ] `docs/spec/data-model.md` updated with the final columns of every table written in this phase.

## Results (fill in as gates are run)

### 2026-08-29 — `uv run ff ingest check-ids`
```
{'ecr_top300': {'n': 300, 'resolved': 300, 'unmatched_pct': 0.0},
 'yahoo_top400': {'n': 376, 'resolved': 376, 'unmatched_pct': 0.0},   # only 376 QB/RB/WR/TE/K rows exist in the Yahoo pool (633 incl. IDP/DEF)
 'sleeper_top300': {'n': 300, 'resolved': 300, 'unmatched_pct': 0.0},
 'draft2026_r1_r4_skill': {'n': 43, 'resolved': 43, 'unmatched_pct': 0.0},
 'players_total': 1052}
GATE PASSED
```
Unlinked-to-nflverse rows (kept as name-keyed hub rows so they can still be drafted): 8 fringe kickers / practice-squad players (data/reports/unmatched.csv).
Raw table row counts: stats_player_week 57,048 · stats_player_reg 5,960 · ff_opportunity_weekly 18,140 · roster_weekly 139,083 · injuries 17,882 · players 25,066 · ff_playerids 12,484 · rosters_2026 2,930 · depth_charts_2026 482,188 (daily dt snapshots) · schedules 1,127 · team_bye 32 · draft_picks 12,927 · ff_rankings_draft 5,552 · sleeper_projections 631 · sleeper_players 3,078 · ffc_adp 726 (3 formats) · yahoo_players 633.

- `ingest check-ids` output (date, coverages, unmatched %):
- `ingest reg-weeks-check` output (date):
- `ingest all` with clock mocked to 2026-09-11: pass/fail (date):

---

# Phase 1b — Post-MVP sources (only after day 6)

Additional sources that only start after the MVP checkpoint (end of day 6, Sat Sep 5); nothing here is required for draft day.

**Status:** Not started

- [ ] `snap_counts` 2023–2025: `load_snap_counts(seasons=[2023,2024,2025])`; keyed by `pfr_player_id` → `players.pfr_id`; columns `game_id`, `season`, `game_type`, `week`, `team`, `opponent`, `offense_snaps`, `offense_pct` (2025 complete through week 22; no 2026 file).
- [ ] NGS: `load_nextgen_stats(seasons=[2023,2024,2025], stat_type='receiving'|'rushing'|'passing')`; one combined file per type covering 2016–2025; `week == 0` rows are season summaries; key `player_gsis_id`; receiving columns `avg_separation`, `avg_cushion`, `avg_intended_air_yards`, `percent_share_of_intended_air_yards`, `avg_yac_above_expectation`.
- [ ] PFR advstats: `load_pfr_advstats(seasons=[2023,2024,2025], stat_type='rec'|'rush'|'pass', summary_level='week')`; keyed by `pfr_player_id`; rec columns `receiving_broken_tackles`, `receiving_drop`, `receiving_drop_pct`, `receiving_int`, `receiving_rat`; rush columns `rushing_yards_before_contact`, `rushing_yards_after_contact`, `rushing_broken_tackles`.
- [ ] Contracts (**parquet only** — `historical_contracts.csv.gz` is frozen at 2022-05-29): `load_contracts()`; keep `is_active`; **dedupe on `otc_id` / `year_signed` / `team` / `years` / `value` / `apy`** (52,103 rows but only 48,317 distinct; nested `season_history` / `contract_history` elements are duplicated too — dedupe by `year` / (`year_signed`, `contract_type`) after exploding); `contract_year = max(season_history.year) == 2026` with overrides for 2023 R1 picks (5th-year option); exclude rookie and tag deals from `just_paid`; **informational tags only**. `team` is the OTC nickname (e.g. "Lions"), `date_of_birth` is null for most active rows (use rosters), 58 active rows have null `gsis_id` → fall back to `otc_id` → `players.otc_id`. Values are in $M.
- [ ] ESPN injuries: `https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries` (live snapshot, 32 teams, 800 entries on 2026-08-29); `espn_id` parsed from `athlete.links[].href` (`/id/{espn_id}/`; there is no top-level athlete id); fields `status`, `type.abbreviation` (A/Q/IR/O/SUSP), `details.fantasyStatus.abbreviation` (QUESTIONABLE / IR / PUP-P / RESERVE-SUS / OUT / NFI-A — PUP/NFI only appear here), `details.type`, `details.detail`, `details.returnDate`, `date`, `shortComment`, `longComment`; core per-team fallback endpoint; retry on the occasional non-JSON response.
- [ ] ESPN kona: `https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl/seasons/2026/segments/0/leaguedefaults/3?view=kona_player_info` with desktop User-Agent and header `X-Fantasy-Filter: {"players":{"limit":600,"sortDraftRanks":{"sortPriority":100,"sortAsc":true,"value":"PPR"},"filterStatsForTopScoringPeriodIds":{"value":2,"additionalValue":["002026","102026","002025"]}}}` (without the header only 50 players return); 2026 projection = `stats[]` entry with `id == '102026'`, `statSourceId == 1`, stat line in `stats{statId: value}`; **adopt the espn-api stat-id constants and reproduce `appliedTotal` for ≥ 20 players within 0.1 before any blend weight**; `player.id == Sleeper espn_id`; `defaultPositionId` 1 QB / 2 RB / 3 WR / 4 TE / 5 K / 16 D/ST.
- [ ] FantasyPros `ecrData` direct scrape: pages `/nfl/rankings/ppr-cheatsheets.php`, `/nfl/rankings/half-point-ppr-cheatsheets.php`, `/nfl/rankings/consensus-cheatsheets.php` (STD; `standard-cheatsheets.php` does not exist); **≤ 1 page/day**, desktop UA, **5 s spacing** (robots Crawl-delay 5); parse `var ecrData = ({...});` with regex + `json.loads`; fields `last_updated_ts` (as `as_of`), `total_experts`, `players[].player_id` (== fantasypros_id), `rank_ecr`, `rank_min`, `rank_max`, `rank_ave`, `rank_std`, `pos_rank`, `tier`, `player_bye_week`, `player_owned_avg`; personal use only.
- [ ] ESPN ADP: from the same kona call — `player.ownership.averageDraftPosition`, `averageDraftPositionPercentChange`, `auctionValueAverage`, `percentOwned`, `ownership.date`; stored as `rank_snapshots` source `espn`.
- [ ] pbp **2025 only**: `load_pbp(seasons=[2025])` (372 columns); keep a ~40-column subset (`game_id`, `play_id`, `posteam`, `defteam`, `week`, `season_type`, `yardline_100`, `goal_to_go`, `qb_dropback`, `air_yards`, `passer_player_id`, `receiver_player_id`, `rusher_player_id`, `fantasy_player_id`, `epa`, `pass_oe`, …) for red-zone (`yardline_100 <= 20`) / goal-line (`<= 10`, `<= 5`) opportunity splits.
- [ ] Each 1b source gets a README table row, a snapshot parser, a `raw_snapshots` registration, a real fixture with PROVENANCE, and an entry in `docs/spec/data-model.md` before it feeds any feature.

Phase 1b has no gate in the plan beyond the ESPN kona validation above (≥ 20 players' `appliedTotal` reproduced within 0.1 before any blend weight) and the ordering rule: only after day 6.

## Gate

Crosswalk (end of day 1): top-300 ECR, top-300 Sleeper projection rows, top-400 Yahoo pool, every 2026 R1–R4 QB/RB/WR/TE pick resolve; `unmatched.csv` < 3% and reviewed.

Ingest 1a: REG weeks 1–18 present for 2023–2025 for all 32 teams (POST rows present but excluded); each source writes a snapshot + row count; one source failing doesn't fail the job; test: every nflreadpy call passes explicit seasons and `ingest all` runs green with the clock mocked to 2026-09-11.

## Derek's actions

None. (Optional: glance at `data/derived/unmatched.csv` after the crosswalk gate — the implementer reviews it; your eyes are only needed if a player you care about is listed.)
