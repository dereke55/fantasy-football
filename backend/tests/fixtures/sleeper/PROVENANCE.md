# Sleeper fixtures — provenance

Both files are verbatim extracts (whole records, no edits) from real snapshots pulled by
`app/ingest/sleeper.py` on 2026-08-29. Expected values in `tests/test_ingest_sleeper.py` were read by hand
from the records below.

## projections_2026_regular_sample.json (21 records)

| field | value |
|---|---|
| source URL | `https://api.sleeper.com/projections/nfl/2026?season_type=regular` (no position filter; 9,418 records) |
| fetched_at | 2026-08-29T23:24:31.477908+00:00 |
| snapshot_id (`raw_snapshots.id`) | `c15b81cd-a872-4aba-9a5c-aa98ac6ba2d1` |
| snapshot path | `data/raw/sleeper/projections_2026_regular/20260829T232431Z_8ef8ac6f.json` |
| sha256 (full snapshot, 8,604,591 bytes) | `8ef8ac6f432ba6ba7e9823f0c72d6341d0131dd439656d601dd0dd2d683e726c` |
| upstream_as_of | `2026-08-29T07:51:06+00:00` (= max `last_modified` 1787989866171 ms) |
| ETag | `W/"4c1463df6f6a1e3a49282801e3946def"` |

Selection: the 12 lowest `stats.adp_half_ppr` among QB/RB/WR/TE/K/DEF records with >= 1 counting stat
(Gibbs, Bijan, Chase, Nacua, McCaffrey, Taylor, Smith-Njigba, St. Brown, Cook, Lamb, Barkley, Jefferson),
plus edge cases: `DET` and `ARI` (DEF rows; `player_id` == team abbr), `3321` Tyreek Hill (projected, `team` null),
`12484` Jayden Higgins (ADP only, no counting stat), `1000` Albert McClellan (LB — non-fantasy position),
`4984` Josh Allen (QB stat keys), `11533` Brandon Aubrey (top K), `11604` Brock Bowers (top TE),
`2901` Malcome Kennedy (`player.position` null).

## players_nfl_sample.json (17 entries)

| field | value |
|---|---|
| source URL | `https://api.sleeper.app/v1/players/nfl` (dict keyed by player_id; 12,225 entries) |
| fetched_at | 2026-08-29T23:24:33.830606+00:00 |
| snapshot_id (`raw_snapshots.id`) | `b5e3eb2c-a780-48d5-849a-50f49ab829c7` |
| snapshot path | `data/raw/sleeper/players_nfl/20260829T232433Z_67f7b58d.json` |
| sha256 (full snapshot, 14,649,696 bytes) | `67f7b58da5f8bb90aab044b87c119a44b106b7827476924165a3f88d98ca1347` |
| upstream_as_of | `2026-08-29T23:00:50+00:00` (= max `news_updated`) |
| ETag | `W/"3de2c8b1a8e0dbe7a2531871d407c888"` |

Selection: `9221` Gibbs, `11564` Maye, `4034` McCaffrey (Questionable; has espn/yahoo/gsis ids), `DET` (DEF),
`3321` Tyreek Hill (Active, team null, injury_status Out), `2196` Brandon Coleman (PUP status, team null),
`13175` Kinkead Dent and `2881` Tyler Slavin (Inactive, team null -> dropped by the loader filter),
`7593` Trey Sermon (Inactive but on ATL -> kept), `6462` Ellis Richardson (Active, team null -> kept;
`gsis_id` has a leading space upstream), `13940` Bruno Fina (OL) and `8733` Jake Hummel (LB) (non-fantasy
positions -> dropped), `11533` Aubrey (K), `4046` Mahomes and `4219` McNichols (Questionable), `11651`
Guerendo (PUP injury_status), `14034` Rechsteiner (Sus).
