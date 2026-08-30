# Provenance — nflverse reference fixtures

Real extracts from the snapshots pulled by `app/ingest/nflverse_ref.py` on 2026-08-29 (nflreadpy 0.1.5). No rows were edited.
Each fixture is a filtered subset of the full snapshot parquet registered in `raw_snapshots`; sha256 is of the FULL snapshot file.

## schedules_2026_SEA_DET.csv
- rows: 34 of 1127 in snapshot
- source: https://github.com/nflverse/nflverse-data/releases/download/schedules/games.parquet
- nflreadpy call: `load_schedules(seasons=[2023, 2024, 2025, 2026])`
- fetched_at: 2026-08-29T23:22:50Z
- upstream_as_of: 2026-08-29T23:06:24Z
- snapshot_id: 5bc5096d-349a-4f72-a003-99c6b87ae2c1
- snapshot path: data/raw/nflverse/schedules/20260829T232250Z_b0ce09e1.parquet
- snapshot sha256: b0ce09e143d7f76f20b87d4c93b3596deb2491e8294da375eb166a05f0fbe9a7
- selection: season == 2026 & (home_team in (SEA, DET) | away_team in (SEA, DET)); columns game_id, season, game_type, week, gameday, away_team, home_team

## ff_rankings_draft_sample.csv
- rows: 50 of 5552 in snapshot
- source: https://github.com/dynastyprocess/data/raw/master/files/db_fpecr_latest.csv
- nflreadpy call: `load_ff_rankings(type='draft')`
- fetched_at: 2026-08-29T23:22:28Z
- upstream_as_of: 2026-08-28 (max scrape_date)
- snapshot_id: ba75fe73-1887-41e6-9e22-8ddd5b65ac04
- snapshot path: data/raw/nflverse/ff_rankings_draft/20260829T232228Z_f2b888ee.parquet
- snapshot sha256: f2b888eecc31ee0716ce86344e889105af8cf232f598487e374f0f01628ad38a
- selection: top 40 rows of page_type == redraft-overall by ecr, + first 5 rows by ecr of redraft-qb and of dynasty-overall; all columns

## ff_playerids_sample.csv
- rows: 33 of 12484 in snapshot
- source: https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv
- nflreadpy call: `load_ff_playerids()`
- fetched_at: 2026-08-29T23:22:42Z
- upstream_as_of: 2026-08-28T11:36:28Z (last commit touching the file)
- snapshot_id: 6b0b658d-8462-426c-a4cc-6296d68f1008
- snapshot path: data/raw/nflverse/ff_playerids/20260829T232242Z_f379aa59.parquet
- snapshot sha256: f379aa592797e6b53a99e96f7408386bbabd2d9e98eba541d26b512f18e66949
- selection: rows where name in (Ja'Marr Chase, Jahmyr Gibbs, Puka Nacua) + rows with draft_year == 2026 sorted by draft_ovr, first 30; all columns

## draft_picks_2026_r1_2025_top3.csv
- rows: 35 of 12927 in snapshot
- source: https://github.com/nflverse/nflverse-data/releases/download/draft_picks/draft_picks.parquet
- nflreadpy call: `load_draft_picks(seasons=True)`
- fetched_at: 2026-08-29T23:22:47Z
- upstream_as_of: 2026-05-05T07:26:30Z
- snapshot_id: cd5352af-8c0b-4e47-b610-5431bd55ec76
- snapshot path: data/raw/nflverse/draft_picks/20260829T232247Z_6be2a640.parquet
- snapshot sha256: 6be2a6404ae480bcb0c292d1c7af9d7f69ce4005f6f9264cfa35f8b6a3cf93d2
- selection: season == 2026 & round == 1 (32 rows) + season == 2025 picks 1-3; columns season, round, pick, team, gsis_id, pfr_player_id, pfr_player_name, position, college

## depth_charts_2026_SEA_QB_first_last_dt.csv
- rows: 6 of 482188 in snapshot
- source: https://github.com/nflverse/nflverse-data/releases/download/depth_charts/depth_charts_2026.parquet
- nflreadpy call: `load_depth_charts(seasons=[2026])`
- fetched_at: 2026-08-29T23:23:16Z
- upstream_as_of: 2026-08-29T12:56:15Z
- snapshot_id: e2a84611-d9a8-4e51-b0bd-d42e9be96bdb
- snapshot path: data/raw/nflverse/depth_charts/20260829T232316Z_18b8e166.parquet
- snapshot sha256: 18b8e166aa82a910dddebf7ce28e4a08a4f2650a2fd75572ab11d18f5b9a896b
- selection: team == SEA & pos_abb == QB at dt == min(dt) (2026-03-22T06:38:42Z) and dt == max(dt) (2026-08-29T12:56:08Z); all columns
