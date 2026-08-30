# Data model

Every Postgres table the plan names, with columns, keys and provenance, so Phase 1 code and Alembic migrations can be written from this page without re-deriving anything.

Status: Not started

Source of truth: `docs/PLAN.md` (plan v2, 2026-08-29) — "Data model" section plus the per-phase notes. Column names for ingested tables are the verified upstream column names (research 2026-08-29); nothing here is renamed on the way in.

## Conventions

- Postgres 17 (docker, `:5432`), database `fantasy_football`; SQLAlchemy 2 + Alembic; every schema change is a migration.
- Timestamps are `timestamptz` in UTC. Dates are `date`. Money/points are `numeric`, never `float`.
- `season` is always explicit (2023–2026). `season_type` (`REG`/`POST`) is **kept** on every weekly table; consumers filter `season_type = 'REG'`. 2025 upstream files include postseason weeks 19–22 — stored, never used in features.
- `player_id` (internal `int`) is the only join key between tables; every external id lives on `players` (the hub). Vendor fantasy-point columns are never surfaced (see `docs/spec/scoring.md`); where an upstream file carries them they are stored under a `vendor_` prefix and excluded from every API model.
- Every ingested row carries `snapshot_id → raw_snapshots.id`. Every derived row carries `run_id → ranking_runs.run_id`. That is what makes WHY bullets reproducible.
- Naming: snake_case tables and columns; `_at` for timestamps, `_id` for foreign keys, `is_` for booleans.
- Table groups (from the plan): registry · identity · historical · 2026 context · market · curated · derived · draft.

## Registry

### `raw_snapshots` (full detail)

One row per network pull, per source, per endpoint. Files are immutable and hash-deduped under `data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}`. Ingest is per-source isolated: one failing source never fails the job, and the failure is still a row here.

| column | type | notes |
|---|---|---|
| `id` | `bigserial` PK | referenced by every ingested row and by `why_bullets.snapshot_ids` |
| `source` | `text` | `nflverse` · `ffopportunity` · `dynastyprocess` · `sleeper` · `yahoo_pub` · `yahoo` · `ffc` · `espn` (post-MVP) · `fantasypros` (post-MVP) |
| `endpoint` | `text` | e.g. `stats_player_week`, `ff_opportunity_weekly`, `projections_2026_regular`, `players_nfl`, `adp_half-ppr_10`, `players_draft_analysis_p{N}`, `draftresults`, `settings` |
| `url` | `text` | exact URL fetched (release asset URL for nflverse) |
| `params` | `jsonb` | request params: `seasons`, `format`, `teams`, `start`/`count`, `season_type`, `position[]` |
| `fetched_at` | `timestamptz` | wall clock at request time |
| `upstream_as_of` | `timestamptz` null | freshness of the upstream data: GitHub release per-asset `updated_at` (one `releases/tags/{tag}` call per tag, optional `GITHUB_TOKEN`); Sleeper `last_modified`; FFC `meta.end_date`; DynastyProcess `scrape_date`; Yahoo pub — null |
| `meta` | `jsonb` | source-specific: FFC `meta.start_date`/`meta.end_date`/`meta.total_drafts`; Sleeper `company`, `last_modified`, `ETag`; nflverse asset name + `updated_at`; Yahoo pub `game_key`, page index |
| `path` | `text` | repo-relative file path (`data/raw/...`) |
| `sha256` | `text` | hash of the file bytes |
| `bytes` | `bigint` | file size |
| `content_type` | `text` | `parquet` · `csv` · `json` |
| `row_count` | `int` null | rows parsed (null when `status != 'ok'`) |
| `status` | `text` | `ok` · `dedup` (same `sha256` already registered — file not rewritten, `path` points at the existing file) · `failed` |
| `error` | `text` null | exception text on failure |
| `post_kickoff` | `bool` | `true` when fetched on/after 2026-09-10 with `--post-kickoff` (upstream semantics change to ROS) |
| `shape_ok` | `bool` null | parser assertions passed (FP `week == 0`, Sleeper `week` null, `page_type == 'redraft-overall'`) |

Keys / indexes: unique `(source, endpoint, sha256)`; index `(source, endpoint, fetched_at desc)`; index `(status)`.

Rules: never `UPDATE` a row except `row_count`/`status`/`error` during the same ingest; never delete; a frozen `ranking_runs` row may reference any snapshot forever.

### `ranking_runs` (full detail)

One row per `recompute` (no network; must finish in < 5 min). The draft board serves a **pinned** `run_id` and refuses to serve if the config hash changed without an explicit re-freeze.

| column | type | notes |
|---|---|---|
| `run_id` | `uuid` PK | |
| `created_at` | `timestamptz` | |
| `finished_at` | `timestamptz` null | |
| `status` | `text` | `running` · `ok` · `failed` |
| `git_sha` | `text` | repo commit at run time (`+dirty` suffix when the tree is dirty) |
| `league_config_hash` | `text` | sha256 of canonicalised `config/league.yaml` |
| `league_config_source` | `text` | `league.yaml.source` at run time (e.g. `yahoo_default_public_league_scoring` until the real table lands) |
| `seed_hashes` | `jsonb` | `{coaching_changes: sha256, qb_situations: …, ol_changes: …, known_missed_weeks: …, id_overrides: …, yahoo_team_defense_ids: …}` |
| `input_snapshot_ids` | `bigint[]` | every `raw_snapshots.id` read by the run (latest `ok` snapshot per `(source, endpoint)`) |
| `model_version` | `text` | version string of the ranking package (blend/tier/flag code) |
| `weights` | `jsonb` | the constants actually used (blend weights, age steps, E[games] bases, tier `k`, flag thresholds) so a run is self-describing |
| `keepers_hash` | `text` | sha256 of the `keepers` rows used (baselines depend on them) |
| `spearman_top150` | `numeric` null | Spearman(our overall rank, ECR) on top-150 — the ≥ 0.8 guard |
| `n_players_ranked` | `int` null | |
| `n_why_bullets` | `int` null | |
| `duration_s` | `numeric` null | |
| `error` | `text` null | |
| `notes` | `text` null | free text (e.g. "candidate freeze v1") |

Keys / indexes: index `(created_at desc)`; index `(status)`.

## Identity

### `players` (id hub)

nflverse `players` + `ff_playerids` (`db_playerids.csv`) + Yahoo pub pool + Sleeper `players/nfl` resolved into one row per real player (plus 32 DEF rows). `yahoo_id = coalesce(yahoo_id, stats_id)` (verified 100/100 of Yahoo's top-100). Yahoo pub pool pre-resolved by id, then by normalised name + team + pos; `seeds/id_overrides.yaml` wins over both.

| column | type | notes |
|---|---|---|
| `player_id` | `serial` PK | internal |
| `display_name` | `text` | nflverse `display_name` |
| `merge_name` | `text` | normalised (lowercase, no punctuation, suffixes stripped — FFC spells "James Cook III") |
| `position` | `text` | `QB` `RB` `WR` `TE` `K` `DEF` |
| `team` | `text` | 2026 team-of-record from `rosters_2026` (`FA` if none); Yahoo title-case abbreviations mapped to nflverse codes |
| `gsis_id` | `text` null | `00-00xxxxx` |
| `esb_id` | `text` null | needed for 2026 `draft_picks` join |
| `sleeper_id` | `text` null | |
| `espn_id` | `text` null | |
| `yahoo_id` | `text` null | `coalesce(ff_playerids.yahoo_id, ff_playerids.stats_id)`; for DEF from `seeds/yahoo_team_defense_ids.yaml` |
| `yahoo_player_key` | `text` null | `470.p.{yahoo_id}` (game_key 470 = 2026) |
| `fantasypros_id` | `text` null | `db_fpecr_latest.id` |
| `pfr_id` | `text` null | |
| `otc_id` | `text` null | post-MVP contracts join |
| `ffc_player_id` | `int` null | FFC `players[].player_id`, learned at first match |
| `birth_date` | `date` null | |
| `age_at_kickoff` | `numeric` null | age on 2026-09-10 |
| `years_exp` | `int` null | |
| `entry_year` | `int` null | rookie ⇔ `entry_year = 2026` |
| `draft_year` / `draft_round` / `draft_pick` / `draft_team` | `int`/`int`/`int`/`text` null | draft capital (`draft_pick` = overall) |
| `is_rookie` | `bool` | |
| `status` | `text` null | nflverse `status` (ACT/CUT/RES/DEV/RSN/NWT/PUP/RSR/SUS/RET) |
| `injury_status` | `text` null | Sleeper `/v1/players/nfl` `injury_status` (observed 2026-08-29: Questionable / IR / PUP / Sus / Doubtful / DNR / NA / null), refreshed once/day; IR/PUP/Out feed `known_missed_weeks` (see `docs/spec/ranking-model.md` §4) |
| `injury_body_part` | `text` null | Sleeper `injury_body_part` (e.g. "Knee - ACL"; structural-injury detection input) |
| `injury_status_as_of` | `timestamptz` null | `fetched_at` of the Sleeper players snapshot that set the two columns above |
| `resolution` | `jsonb` | per external id: `{method: id|name_team_pos|override|unmatched, snapshot_id}` |
| `updated_at` | `timestamptz` | |

Keys: unique partial indexes on each external id where not null; unique `(merge_name, position, team)` is **not** enforced (used only as a fallback matcher). `ingest check-ids` writes `unmatched.csv` (must be < 3 % and reviewed).

## Historical (2023–2025, REG only for features; POST rows kept)

### `player_week_stats`
Source: nflverse `stats_player_week_{season}` (150 columns; only the ones below are loaded). Key: unique `(player_id, season, week, team)`.

Columns: `player_id`, `gsis_id`, `season`, `week`, `season_type`, `game_id`, `team`, `opponent_team`, `position`, `completions`, `attempts`, `passing_yards`, `passing_tds`, `passing_interceptions`, `sacks_suffered`, `sack_fumbles`, `sack_fumbles_lost`, `passing_air_yards`, `passing_2pt_conversions`, `carries`, `rushing_yards`, `rushing_tds`, `rushing_fumbles`, `rushing_fumbles_lost`, `rushing_2pt_conversions`, `receptions`, `targets`, `receiving_yards`, `receiving_tds`, `receiving_fumbles`, `receiving_fumbles_lost`, `receiving_air_yards`, `receiving_yards_after_catch`, `receiving_2pt_conversions`, `target_share`, `air_yards_share`, `wopr`, `racr`, `special_teams_tds`, `fumbles_total`, `fumbles_lost_total`, `vendor_fantasy_points`, `vendor_fantasy_points_ppr` (stored, never surfaced), `snapshot_id`.

### `player_season_stats`
Source: nflverse `stats_player_reg_{season}` (has `recent_team` + `games` instead of week columns). Key: unique `(player_id, season)`. Columns: same counting stats as above plus `recent_team`, `games`, `snapshot_id`.

### `player_expected_stats`
Source: ffopportunity `ep_weekly_{season}` (159 columns; weeks 1–22). Key: unique `(player_id, season, week, posteam)`.

Columns: `player_id`, `gsis_id` (upstream `player_id`), `season`, `week`, `game_id`, `posteam`, `position`, `pass_attempt`, `pass_completions_exp`, `pass_yards_gained_exp`, `pass_touchdown_exp`, `rec_attempt` (targets), `rec_air_yards`, `receptions`, `receptions_exp`, `rec_yards_gained`, `rec_yards_gained_exp`, `rec_touchdown`, `rec_touchdown_exp`, `rec_first_down_exp`, `rush_attempt`, `rush_yards_gained_exp`, `rush_touchdown_exp`, team totals `rec_attempt_team`, `rec_air_yards_team`, `vendor_total_fantasy_points_exp` (stored, never used — luck is `score(actual) − score(expected)` under league scoring), `snapshot_id`. `season_type` derived from `week ≤ 18 → REG`.

### `roster_weeks`
Source: nflverse `roster_weekly_{season}` 2023–2025 (+ 2026 as published). Key: unique `(gsis_id, season, week, game_type, team)`. Columns: `player_id`, `gsis_id`, `season`, `week`, `game_type`, `team`, `position`, `depth_chart_position`, `status` (ACT/DEV/RES/INA/CUT/RET/EXE/TRD/TRC/SUS), `status_description_abbr` (A01, P01, R01, R04, …), `snapshot_id`. Feeds `games_missed` (on 53/IR/PUP = status not DEV/CUT/SUS/RET/EXE).

### `injury_weeks`
Source: nflverse `injuries_{season}` 2023–2025 (in-season only; no 2026 file). Key: unique `(gsis_id, season, week, team)`. Columns: `player_id`, `gsis_id`, `season`, `season_type`, `week`, `team`, `position`, `report_status` (Out/Questionable/Doubtful/blank), `report_primary_injury`, `report_secondary_injury`, `practice_status`, `practice_primary_injury`, `practice_secondary_injury`, `date_modified`, `snapshot_id`.

## 2026 context

### `rosters_2026`
Source: nflverse `roster_2026` (canonical team-of-record; rebuilt daily). Key: unique `(gsis_id)` on the latest snapshot; history kept by `snapshot_id`. Columns: `player_id`, `gsis_id`, `esb_id`, `team`, `position`, `depth_chart_position`, `status` (ACT/RES/E14/RET/CUT), `status_description_abbr`, `full_name`, `birth_date`, `college`, `years_exp`, `entry_year`, `rookie_year`, `draft_club`, `draft_number`, `espn_id`, `sleeper_id`, `yahoo_id`, `pfr_id`, `snapshot_id`.

### `depth_chart_snapshots`
Source: nflverse `depth_charts_2026` (timestamp-based `dt`, daily 07:00 UTC, all snapshots kept to detect camp movement). Key: unique `(dt, team, pos_abb, pos_slot, gsis_id)`. Columns: `dt`, `team`, `gsis_id`, `espn_id`, `player_id`, `player_name`, `pos_grp`, `pos_name`, `pos_abb`, `pos_slot`, `pos_rank`, `snapshot_id`. Current chart = `max(dt)` per team.

### `games` and `team_bye`
Source: nflverse `games.csv` 2023–2026. Key: unique `(game_id)`. Columns: `game_id`, `season`, `game_type`, `week`, `gameday`, `weekday`, `gametime`, `away_team`, `home_team`, `away_score`, `home_score`, `roof`, `surface`, `div_game`, `snapshot_id`. Coach columns are **not** loaded (2026 values stale for 3 teams — never derive HC changes from them).
`team_bye(season, team, bye_week)` derived: the REG week 1–18 with no game. 2026 week 11 has six teams on bye (bye-stack warning input).

### `draft_picks_nfl`
Source: nflverse `draft_picks` (2026 rows updated 2026-05-05). Key: unique `(season, round, pick)`. Columns: `season`, `round`, `pick`, `team`, `upstream_gsis_id` (for 2026 rows this holds ESB-format ids — joined on `rosters_2026.esb_id`, fallback `pfr_player_id`, then name + college), `pfr_player_id`, `pfr_player_name`, `position`, `college`, `age`, `player_id` (resolved), `resolution_method`, `snapshot_id`.

## Market

### `projections`
Source: Sleeper `api.sleeper.com/projections/nfl/2026?season_type=regular` (Rotowire lines; QB/RB/WR/TE/K/DEF with ≥ 1 counting stat). Key: unique `(player_id, source, snapshot_id)`; "current" = latest `ok` snapshot.

| column | type | notes |
|---|---|---|
| `player_id` | FK | via `sleeper_id` |
| `source` | `text` | `sleeper_rotowire` (ESPN kona post-MVP, gated) |
| `company` | `text` | upstream `company` (`rotowire`) |
| `upstream_as_of` | `timestamptz` | upstream `last_modified` |
| `stat_line` | `jsonb` | the raw `stats.*` counting keys: `pass_att`, `pass_cmp`, `pass_yd`, `pass_td`, `pass_int`, `rush_att`, `rush_yd`, `rush_td`, `rec`, `rec_yd`, `rec_td`, `fum_lost`, `pass_2pt`, `rush_2pt`, `rec_2pt` (when present); K/DEF keys stored but unscored |
| `vendor_pts` | `jsonb` | `pts_ppr`, `pts_half_ppr`, `pts_std` — stored, never surfaced |
| `gp_upstream` | `int` | stored for audit; **never used** (constant 18) |
| `snapshot_id` | FK | |

### `rank_snapshots`
One row per (player, source, format, snapshot). Key: unique `(player_id, source, format, snapshot_id)`; index `(source, format, snapshot_id)`.

| column | type | notes |
|---|---|---|
| `player_id` | FK | |
| `source` | `text` | `fantasypros_mirror` · `yahoo_pub` · `ffc` · `sleeper` (`fantasypros_direct`, `espn` post-MVP) |
| `format` | `text` | `ppr` · `half-ppr` · `standard` · `yahoo_default` (Yahoo site-wide, no per-format split — labelled as such) |
| `kind` | `text` | `ecr` or `adp` |
| `rank` | `numeric` null | ECR avg (`ecr`) |
| `adp` | `numeric` null | FFC `adp`; Yahoo `average_pick`; Sleeper `adp_ppr`/`adp_half_ppr`/`adp_std` by format. Sentinels nulled (Sleeper ≥ 999; Yahoo blank) |
| `std` | `numeric` null | FP `sd`; FFC `stdev` |
| `min` / `max` | `numeric` null | FP `best`/`worst`; FFC `high`/`low` |
| `n` | `int` null | FFC `times_drafted` |
| `pct_drafted` | `numeric` null | Yahoo `percent_drafted` |
| `bye` | `int` null | FP `bye`; FFC `bye`; Yahoo `bye_weeks.week` |
| `as_of` | `timestamptz` | = `raw_snapshots.upstream_as_of` or `fetched_at` |
| `snapshot_id` | FK | |

## Curated (YAML under `backend/seeds/`, loaded into tables on `recompute`; edited as YAML + reload)

Every curated row has `source_url` (required), `confidence` (`numeric` 0–1; fansports "Authority" percentages are stored as-is, e.g. 0.72 — see `docs/phases/05-team-context.md`), `last_checked` (date), `notes`. 32 rows each for the three team tables.

| table | key | columns |
|---|---|---|
| `coaching_changes` | `team` | `hc`, `hc_new` (bool), `oc`, `oc_new` (bool), `play_caller`, `play_caller_new` (bool), `source_url`, `confidence`, `last_checked`, `notes` |
| `qb_situations` | `team` | `projected_qb1` (player ref: name + `player_id`), `status` (`settled`/`competition`/`injury_return`), `changed_from_2025` (bool), `source_url`, `confidence`, `last_checked`, `notes` |
| `ol_changes` | `team` | `delta` (int, −2..+2), `notes`, `source_url`, `confidence`, `last_checked` |
| `known_missed_weeks` | `gsis_id` (YAML rows carry `player` name + `gsis_id`; resolved to `player_id` on load) | `weeks` (int, expected REG games missed from Week 1), `reason`, `source_url`, `confidence`, `last_checked` |
| `id_overrides` | `(source, source_id)` | `player_id` (or `gsis_id`), `reason`, `source_url` |
| `yahoo_team_defense_ids` | `team` | `yahoo_id`, `yahoo_player_key` (32 rows) |

Seed hashes go into `ranking_runs.seed_hashes`.

## Derived (all keyed on `run_id`)

### `player_features`
Key: unique `(run_id, player_id)`. Rookies: every historical column null, no errors.

Columns (Phase 3): production `ppg_2023`, `ppg_2024`, `ppg_2025`, `games_2023..2025`, `pos_ppg_rank_2023..2025`, `ppg_yoy_delta`, `ppg_trend3` (0.5/0.3/0.2, same team + role seasons only); opportunity `targets_pg_{season}`, `target_share_{season}`, `air_yards_share_{season}`, `wopr_{season}`, `carries_pg_{season}`, `opportunity_trend`; luck `td_diff_2025`, `ppg_diff_2025` (league-scored actual − expected); durability `games_missed_{season}`, `games_eligible_{season}`, `missed_rate_2023_25`, `injury_events` (jsonb: season, cause), `soft_tissue_seasons`, `structural_event` (jsonb: type, date), `is_injury_prone`, `is_structural_injury_return`, `known_missed_weeks`, `known_missed_source`; consistency (display only) `mean_{season}`, `sd_{season}`, `floor25_{season}`, `ceiling90_{season}`, `pct_weeks_above_starter_{season}`; bio `age_at_kickoff`, `years_exp`, `draft_round`, `draft_pick`, `is_rookie`; `depth_slot` (from `depth_chart_snapshots` max `dt`), `depth_rank_30d_ago`.

### `team_context`
Key: unique `(run_id, team)`. Columns: `hc_new`, `oc_new`, `play_caller_new`, `play_caller`, `qb_status`, `projected_qb1_player_id`, `qb_changed_from_2025`, `ol_delta`, `bye_week`, `tags` (`text[]`: `new_play_caller`, `qb_uncertain_team`, …), `source_urls` (jsonb). Tags only — **no multipliers in MVP**.

### `rankings`
Key: unique `(run_id, player_id)`; index `(run_id, overall_rank)`.

Columns: `overall_rank`, `pos_rank`, `tier`, `value_tier`, `ppg_vendor`, `ppg_inhouse`, `ppg_inhouse_raw` (before age step), `w_vendor`, `w_inhouse`, `ppg_blend`, `e_games`, `replacement_ppg`, `season_value`, `baseline_rank`, `vols`, `vorp`, `ecr`, `ecr_sd`, `ecr_n`, `disagreement`, `yahoo_adp`, `ffc_adp`, `sleeper_adp`, `composite_adp`, `room_adp`, `sd_adp`, `sd_adp_source` (`ffc`/`fit`), `our_pick_equivalent`, `gap`, `gap_z`, `p_avail_next`, `vona`, `flags` (`text[]`: `sleeper`, `bust`, `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team`), `signals` (jsonb: the supporting/risk signals that fired), `is_kdst` (VBD 0, sorted by consensus ADP).

### `why_bullets` (full detail)

One row per rendered bullet. Auditable: a bullet can be recomputed from its referenced snapshots (gate: recompute 5 top-50 bullets).

| column | type | notes |
|---|---|---|
| `id` | `bigserial` PK | |
| `run_id` | `uuid` FK `ranking_runs` | |
| `player_id` | `int` FK `players` | |
| `ordinal` | `int` | display order 1..N (≤ ~6 per player) |
| `rule_id` | `text` | from the catalogue in `docs/spec/why-rules.md` |
| `template_version` | `text` | e.g. `v1`; bump when wording or inputs change |
| `polarity` | `text` | `positive` · `negative` · `neutral` · `tag` |
| `text` | `text` | rendered bullet, e.g. "Target share 24% → 28% (2024→2025)" |
| `metric_keys` | `text[]` | feature/metric names used, e.g. `{target_share_2024, target_share_2025}` |
| `inputs` | `jsonb` | the numeric inputs, e.g. `{"target_share_2024": 0.24, "target_share_2025": 0.28}` |
| `season_from` / `season_to` | `int` null | season range the inputs cover |
| `week_from` / `week_to` | `int` null | week range (null = full REG season) |
| `snapshot_ids` | `bigint[]` | `raw_snapshots.id` rows the inputs came from |
| `source_url` | `text` null | for curated rows (`coaching_changes`, `qb_situations`, `ol_changes`, `known_missed_weeks`) |
| `as_of` | `timestamptz` null | freshness shown in the drawer ("Aug 29") |
| `created_at` | `timestamptz` | |

Keys / indexes: unique `(run_id, player_id, ordinal)`; index `(run_id, rule_id)`.

### `draft_snapshot`
The frozen run the board serves. Key: `id` PK; at most one row with `is_active = true` (partial unique index).

Columns: `id`, `run_id` FK, `league_config_hash`, `keepers_hash`, `frozen_at`, `frozen_by` (`cli`), `reason` (`candidate freeze v1`, `hard freeze`, `re-freeze: <why>`), `is_active`, `superseded_at`. Serving rule: if `sha256(config/league.yaml) != league_config_hash` the API returns 409 until an explicit re-freeze (logged in `docs/decisions.md`).

## Draft

### `leagues`
Key: `id` PK; unique `(league_key)`. Columns: `league_key` (`{game_key}.l.{league_id}`, e.g. `470.l.12345` — 2026 NFL `game_key` is 470; from `config/league.yaml`), `name`, `num_teams` (10), `rounds`, `draft_type` (`snake`), `draft_time` (`timestamptz`; from `league.yaml`, later diffed against Yahoo `settings.draft_time`), `draft_status` (`predraft`/`draft`/`postdraft`), `draft_order` (jsonb: `{team_slot: {team_key, name}}`; manual until Yahoo pre-draft `draftresults` supplies it), `my_team_slot` (int null; late-bound), `keeper_max_per_team`, `keeper_deadline`, `settings_snapshot_id` (8b), `updated_at`.

### `keepers` (full detail)

`keepers(team_slot, player, cost_round, status, source)` — entered manually (primary) or captured from Yahoo pre-draft `draftresults` if OAuth works. Every edit recomputes `pick_schedule`, baselines, room ADP and P(avail) (pure numpy).

| column | type | notes |
|---|---|---|
| `id` | `serial` PK | |
| `league_id` | FK `leagues` | |
| `team_slot` | `int` | 1..10 draft slot of the keeping team |
| `player_id` | FK `players` | |
| `cost_round` | `int` | the round the player was drafted in last year; that team is skipped in that round |
| `status` | `text` | `declared` · `approved` (commissioner) · `removed` |
| `source` | `text` | `manual` · `yahoo` (pre-filled `draftresults` row / `is_keeper`) |
| `yahoo_player_key` | `text` null | |
| `yahoo_team_key` | `text` null | |
| `snapshot_id` | FK null | the `draftresults` snapshot when `source = 'yahoo'` |
| `created_at` / `updated_at` | `timestamptz` | |

Keys: unique `(league_id, player_id)` where `status != 'removed'`; unique `(league_id, team_slot, cost_round)` where `status != 'removed'` (one keeper per team per round hole). Check: `1 ≤ cost_round ≤ leagues.rounds`; count per `team_slot` ≤ `keeper_max_per_team` when set.

### `pick_schedule` (full detail)

`pick_schedule(overall_pick, round, team_slot, is_keeper_slot)` = `num_teams × rounds` snake with keeper-consumed slots marked. Rebuilt (not edited) from `leagues.draft_order` + `keepers` on every keeper edit and whenever the draft order changes. "My next pick in N", availability, baselines and room ADP all read it.

| column | type | notes |
|---|---|---|
| `league_id` | FK `leagues` | |
| `overall_pick` | `int` | 1..`num_teams × rounds` |
| `round` | `int` | 1..`rounds` |
| `pick_in_round` | `int` | 1..`num_teams` |
| `team_slot` | `int` | snake: odd rounds slot 1→10, even rounds slot 10→1 |
| `is_keeper_slot` | `bool` | `true` when a keeper with `cost_round = round` belongs to `team_slot` (team skipped that round) |
| `keeper_id` | FK `keepers` null | the keeper consuming the slot |
| `is_my_pick` | `bool` | `team_slot = leagues.my_team_slot` |
| `built_at` | `timestamptz` | |
| `keepers_hash` | `text` | hash of the keeper set used to build it |

Keys: PK `(league_id, overall_pick)`; unique `(league_id, round, team_slot)`. Pick numbers include keeper slots (a keeper hole still counts as a pick number) — room ADP maps re-ranked ADP onto **non-keeper** slots in `overall_pick` order.

### `draft_picks` (full detail)

`draft_picks(pick, round, team_slot, player nullable, is_keeper, source manual|yahoo)`. One current row per `overall_pick`; undo keeps history. Each team's roster is pre-populated with its keepers as `is_keeper = true` rows on their keeper slots.

| column | type | notes |
|---|---|---|
| `id` | `bigserial` PK | |
| `league_id` | FK `leagues` | |
| `overall_pick` | `int` | FK `pick_schedule (league_id, overall_pick)` |
| `round` | `int` | copied from `pick_schedule` |
| `team_slot` | `int` | copied from `pick_schedule` |
| `player_id` | FK `players` null | null = slot exists but unfilled (Yahoo returns unfilled rows; on-the-clock = lowest unfilled pick) |
| `is_keeper` | `bool` | |
| `source` | `text` | `manual` · `yahoo` |
| `yahoo_player_key` | `text` null | raw from `draftresults` (nullable upstream) |
| `yahoo_team_key` | `text` null | |
| `picked_at` | `timestamptz` | |
| `is_current` | `bool` | `false` after undo |
| `undone_at` | `timestamptz` null | |
| `snapshot_id` | FK null | the `draftresults` poll that produced the row (8b) |

Keys: unique `(league_id, overall_pick)` where `is_current`; unique `(league_id, player_id)` where `is_current and player_id is not null`; index `(league_id, picked_at desc)`. Rule: manual mode and Yahoo mode write identical rows; a Yahoo row never overwrites a newer manual row for the same pick without a logged conflict.

## Post-MVP tables (not created in MVP)

`snap_counts`, `ngs_*`, `pfr_advstats_*`, `contracts`, `espn_injuries`, `skill_movement`, `team_points_allowed_2025` (display-only SoS), `draft_sim_runs` (8c Monte Carlo). Each requires a README source-table row + snapshot parser before it exists.

## Checklist

- [ ] Alembic baseline creates `raw_snapshots` and `ranking_runs` exactly as specified above (Phase 0).
- [ ] `players` hub migration with the partial unique indexes on every external id (Phase 1a).
- [ ] Historical tables `player_week_stats`, `player_season_stats`, `player_expected_stats`, `roster_weeks`, `injury_weeks` with `season_type` kept and `snapshot_id` on every row (Phase 1a).
- [ ] 2026 context tables `rosters_2026`, `depth_chart_snapshots`, `games` + `team_bye`, `draft_picks_nfl` (ESB join for 2026 rows) (Phase 1a).
- [ ] Market tables `projections` (stat line as jsonb, `gp_upstream` never read) and `rank_snapshots` (sentinels nulled) (Phase 1a / 4-lite).
- [ ] Curated tables loaded from `backend/seeds/*.yaml` with `source_url` NOT NULL (Phase 5).
- [ ] Derived tables `player_features`, `team_context`, `rankings`, `why_bullets`, `draft_snapshot` keyed on `run_id` (Phase 6).
- [ ] Draft tables `leagues`, `keepers`, `pick_schedule`, `draft_picks` with the partial unique constraints above (Phase 6.4 / 7).
- [ ] `vendor_*` columns excluded from every Pydantic response model (test).
- [ ] Unit tests on real fixtures: `pick_schedule` build with keeper holes; `draft_picks` undo keeps history; `draft_snapshot` refuses to serve on config-hash mismatch.

## Gate

From the plan (Phase 0): "`/health` 200; shell renders; `alembic upgrade head`; docs exist; Yahoo app created + application submitted (date logged); day-1 inputs received or explicitly marked pending." — this document is the "docs exist" input for the data model; `alembic upgrade head` must create `raw_snapshots` + `ranking_runs` as specified here.

From the plan (Phase 1a, players hub): "top-300 ECR, top-300 Sleeper projection rows, top-400 Yahoo pool, every 2026 R1–R4 QB/RB/WR/TE pick resolve; `unmatched.csv` < 3% and reviewed."

## Derek's actions

- `league_key`, draft date/time, draft slot and keeper rules (day-1 inputs) populate `leagues` via `config/league.yaml`.
- Review `unmatched.csv` after the first `ingest check-ids` run.
