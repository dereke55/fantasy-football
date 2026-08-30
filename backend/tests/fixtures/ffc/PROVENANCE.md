# FFC fixtures — provenance

Real extracts from Fantasy Football Calculator's official ADP REST API (free; attribution requested:
https://fantasyfootballcalculator.com/adp). Never edited by hand beyond truncating the `players` list.

## `adp_half-ppr_10.json`

| field | value |
|---|---|
| source URL | `https://fantasyfootballcalculator.com/api/v1/adp/half-ppr?teams=10&year=2026` |
| params | `{"format": "half-ppr", "teams": 10, "year": 2026}` |
| fetched_at (UTC) | `2026-08-29T23:21:04Z` |
| raw_snapshots.id | `db7f5f33-9b02-4d2f-bd74-e0087818bc27` |
| snapshot path | `data/raw/ffc/adp_half-ppr_10/20260829T232104Z_ba1a4595.json` (44,025 bytes, 232 players) |
| sha256 (full snapshot) | `ba1a45953d7dbdfac8e5df9f4c8cb6226cfa0610abd5de478b2ecefc2cc8af24` |
| upstream_as_of (meta.end_date) | `2026-08-29` (window `2026-08-24` .. `2026-08-29`, `total_drafts` 3302, `rounds` 15) |
| extract | `status` + full `meta` + the first 40 entries of `players` (upstream order = ascending `adp`), re-serialised with `indent=1` |

Hand-verified rows used by `tests/test_ingest_ffc.py` (read directly from the raw JSON above):

- `players[0]`: Jahmyr Gibbs, RB, DET, player_id 5672, adp 1.5, adp_formatted "1.01", times_drafted 589, high 1, low 4, stdev 0.7, bye 6
- `players[39]`: Trey McBride, TE, ARI, player_id 5656, adp 38.3, adp_formatted "4.08", times_drafted 341, high 19, low 53, stdev 7.1, bye 14
  (10-team check: pick 38 -> round 4, pick 8 -> "4.08")
- `players[8]`: James Cook III, RB, BUF, player_id 5652 (suffix kept verbatim in the raw table)
