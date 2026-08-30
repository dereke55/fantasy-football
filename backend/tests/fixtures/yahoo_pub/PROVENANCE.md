# yahoo_pub fixtures — provenance

Real extracts from the Yahoo Fantasy public read-only API ("pub-api-ro", no auth), pulled by
`uv run python -m app.ingest.yahoo_pub all` on **2026-08-29T23:25:07Z** (game_key `470` = NFL 2026).
Each fixture is the first N `players["0".."N-1"]` records of one page, byte-for-byte as returned (only the trailing
records were dropped and `players.count` set to N); `fantasy_content.game[0]` metadata is kept verbatim.
Parse with `app.ingest.yahoo_pub.parse_players_page`.

| fixture | records | source URL (params) | full snapshot sha256 | raw_snapshots.id |
|---|---|---|---|---|
| `players_DA_AP_p0.json` | 40 of 100 | `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=DA_AP;start=0;count=100;out=draft_analysis?format=json` | `93bff1254c0e87af903c56c9ce69596a113df9e01fc48df95772dc3ec262bd3a` (590,950 bytes) | `630311b8-a5b8-41e6-be98-016b85187741` |
| `players_AR_K_p0.json` | 30 of 56 | `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;position=K;start=0;count=100;out=draft_analysis?format=json` | `b44c9f46a0617ba0618cb6311ccba4850033be3270c434cce1ad5fd7d3c52a40` (327,575 bytes) | `2db5ead5-0523-4131-86c4-0c1aa797c618` |
| `players_AR_DEF_p0.json` | 8 of 32 | `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;position=DEF;start=0;count=100;out=draft_analysis?format=json` | `2214f2f4fcaf26e503bfcc71f98c561e0eab110038138a0224a5be7bf3c31c90` (172,373 bytes) | `c8716546-38a8-4604-9eb7-7853c81e1a72` |

Full snapshot files: `data/raw/yahoo_pub/{endpoint}/20260829T232507Z_{sha8}.json` (e.g.
`data/raw/yahoo_pub/players_DA_AP_p0/20260829T232507Z_93bff125.json`).

## Hand-verified values (read directly from the fixture JSON)

`players_DA_AP_p0.json`
- record `"0"`: `player_key` `470.p.40059`, `player_id` `"40059"`, Jahmyr Gibbs, `editorial_team_abbr` `Det` (-> nflverse `DET`),
  `display_position` RB, `position_type` O, `bye_weeks.week` `"6"`, `uniform_number` `"0"`, `eligible_positions` `[RB]`,
  `draft_analysis`: average_pick `"1.4"`, average_round `"1.0"`, average_cost `"73.6"`, percent_drafted `"1.00"`,
  preseason_average_pick `"1.4"`, preseason_average_round `"1.0"`, preseason_average_cost `"73.7"`, preseason_percent_drafted `"1.0"`; no `status`.
- record `"3"`: Puka Nacua `470.p.40168`, `editorial_team_abbr` `LAR` (-> nflverse `LA`), `status` `Q`, `status_full` `Questionable`,
  `injury_note` `Groin`, average_pick `"4.8"`, bye `"11"`.
- record `"26"`: Jeremiyah Love (2026 rookie) `470.p.42625`, `player_id` `"42625"`, `Ari` -> `ARI`, RB, average_pick `"29.1"`, bye `"14"`.

`players_AR_K_p0.json`
- record `"0"`: Brandon Aubrey `470.p.40819`, `Dal`, K / position_type K, average_pick `"85.9"`, average_round `"9.2"`, average_cost `"4.5"`.
- record `"17"`: Charlie Smyth `470.p.40873` (`NO`, K) with **all eight draft_analysis fields `"-"`** (-> null); 10 of the 30 records have `"-"`.

`players_AR_DEF_p0.json`
- record `"0"`: Texans `470.p.100034`, `player_id` `"100034"`, `name.full`/`first`/`last` = `Texans`, `Hou` -> `HOU`, `display_position` DEF,
  `position_type` DT, `eligible_positions` `[DEF]`, `uniform_number` JSON `false` (-> null), bye `"8"`, average_pick `"93.1"`.
- record `"1"`: Rams `470.p.100014`, `LAR` -> `LA`, average_pick `"88.9"`.
- record `"7"`: Jaguars `470.p.100030`, `Jax` -> `JAX`, percent_drafted `"0.87"`, preseason_percent_drafted `"0.9"`.
