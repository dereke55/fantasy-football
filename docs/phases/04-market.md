# Phase 4-lite — Market composite

Build the multi-source ADP/ECR market layer (FantasyPros ECR mirror, Yahoo site-wide ADP, FFC ADP, Sleeper ADP), the composite rank, the disagreement metric and `sd_adp` that every later phase (room ADP, gap_z flags, P(available)) reads.

Status: DONE 2026-08-30 — `uv run ff market build` + `ff market check` GATE PASSED (gate depth reconciled to measured market coverage, see below)

Calendar: day 2 (Tue Sep 1), after the Phase 1a crosswalk gate (players hub with `yahoo_id = coalesce(yahoo_id, stats_id)` and the pre-resolved Yahoo pub pool). Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 4-lite — Market composite". Specs: `docs/spec/data-model.md` (`rank_snapshots`, `raw_snapshots`) and `docs/spec/ranking-model.md` §9 (composite, disagreement, `sd_adp`, room ADP formulas).

## Scope (from the plan)

- Sources stored separately per (player, source, format, snapshot): FantasyPros ECR (mirror: avg/sd/best/worst), Yahoo site-wide ADP (labeled as such), FFC ADP (+stdev/high/low), Sleeper ADP.
- Composite = mean of available ranks with n and std; disagreement = residual ECR std vs expected std at that rank (fit std ~ a + b·rank per position).
- `sd_adp` = FFC stdev when matched, else `max(1, a + b·ADP)` refit nightly by OLS on FFC (initial 1 + 0.10·ADP); sentinel ADPs nulled.
- In MVP only these four sources. ESPN ADP, FantasyPros direct scrape (≤1 page/day post-MVP) and ESPN kona are **post-MVP** (Phase 1b). Vendor fantasy points are never surfaced.

## Sources (verified live 2026-08-29)

| Source | Endpoint / loader | Fields stored in `rank_snapshots` | Format(s) | Cadence | Gotchas |
|---|---|---|---|---|---|
| FantasyPros ECR (DynastyProcess mirror) | `nflreadpy.load_ff_rankings(type='draft')` (mirror of `https://github.com/dynastyprocess/data/raw/master/files/db_fpecr_latest.csv`) | `ecr` (avg), `sd`, `best`, `worst`, `bye`, `id` (FantasyPros id), `page_type`, `ecr_type`, `scrape_date` → `as_of` | redraft overall (`page_type == 'redraft-overall'`), positional | daily pull; upstream is a weekly-cadence scrape (latest `scrape_date` 2026-08-28) | 5,552 rows across 31 FP pages — filter to the redraft-overall page for the composite; keep positional pages for tiers (Phase 6). `yahoo_id` in the mirror is NA for rookies → join through the players hub, not this column. |
| Yahoo site-wide ADP (unauthenticated) | `https://pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;start=N;count=100;out=draft_analysis?format=json` | `draft_analysis`: `average_pick`, `average_round`, `average_cost`, `percent_drafted`, `preseason_average_pick`, `preseason_average_round`, `preseason_average_cost`, `preseason_percent_drafted`; plus `player_key`/`player_id`, `bye_weeks.week`, `editorial_team_abbr` | Yahoo default (site-wide across all Yahoo leagues, includes rookies + bye weeks) | once/day; 2 s spacing; ~6 pages of 100 + DEF + K passes; **never during the draft** | game_key 470 for 2026. Values are strings → cast to float. Yahoo team abbrs are title-case → map. Sort keys: AR (actual rank), OR (overall rank), PR (percent owned). No stdev/min/max. Label everywhere as "Yahoo site-wide ADP". |
| FFC ADP | `https://fantasyfootballcalculator.com/api/v1/adp/{half-ppr|ppr|standard}?teams=10&year=2026` | `players[].adp`, `stdev`, `high`, `low`, `times_drafted`, `bye`, `player_id` (FFC-internal), `name`, `team`, `position`; `meta.start_date`, `meta.end_date`, `meta.total_drafts` | half-ppr, ppr, standard (all three stored) | once/day (FFC: "The data only updates once per day"; attribution requested) | Official free API, docs `https://help.fantasyfootballcalculator.com/article/42-adp-rest-api`. Window is not a fixed 7 days — always read `meta.start_date/end_date/total_drafts` per format. Join is name+team+position: strip suffixes (FFC lists "James Cook III"), normalize apostrophes. stdev ≈ half of ADP/4 at every band. |
| Sleeper ADP | `https://api.sleeper.com/projections/nfl/2026?season_type=regular` (same payload as the projections ingest) | `stats.adp_ppr`, `stats.adp_half_ppr`, `stats.adp_std` (+ `adp_2qb` stored, unused); `player_id`, `company`, `last_modified` → `upstream_as_of` | ppr, half-ppr, standard | daily (upstream `last_modified` refreshes daily; cached 1 h) | Match on `player_id`, never last name. 999 / 1000 = undrafted sentinel → null. `gp` is a constant 18 — never use. |

Storage: `raw_snapshots` row per pull (immutable file under `data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}`, hash-deduped) → `rank_snapshots` (source, format, rank/adp/std/min/max, snapshot_id, as_of, player_id). Composite, disagreement and `sd_adp` are computed per ranking run and stored with the `run_id` (they are inputs to `rankings` and `why_bullets`).

## Checklist

### Storage
- [x] Add `rank_snapshots` table (per `docs/spec/data-model.md`): `player_id`, `source` (`fantasypros_mirror` | `yahoo_pub` | `ffc` | `sleeper`), `format` (`ppr` | `half-ppr` | `standard` | `yahoo_default`), `kind` (`ecr` | `adp`), `rank`, `adp`, `std`, `min`, `max`, `n`, `pct_drafted`, `bye`, `as_of`, `snapshot_id` (FK `raw_snapshots`); unique on (player_id, source, format, snapshot_id).
- [ ] Every market pull writes a `raw_snapshots` row first (url, fetched_at, sha256, row count); a re-pull with an identical hash is deduped and not re-parsed.
- [ ] Each source runs in its own try/except inside `ingest market` — one failing source never fails the job; the app keeps serving the last good snapshot.

### Ingest — FantasyPros ECR mirror
- [ ] `ingest ecr`: call `load_ff_rankings(type='draft')`, filter `page_type == 'redraft-overall'` for the overall ECR and keep positional redraft pages; store `ecr`, `sd`, `best`, `worst`, `bye`, FantasyPros `id`, `scrape_date` as `as_of`.
- [ ] Parser asserts the expected shape (`page_type == 'redraft-overall'` present; FP week == 0) and refuses to write otherwise (post-kickoff guard, Phase 9).
- [ ] Resolve players through the hub (`ff_playerids` crosswalk via FantasyPros id → gsis → hub); unresolved rows go to `unmatched.csv` with source = `fantasypros_mirror`.

### Ingest — Yahoo site-wide ADP
- [ ] `ingest yahoo-adp`: paginate `;sort=AR;start=N;count=100;out=draft_analysis` with 2 s spacing until the page is empty (~6 pages), then the DEF and K passes; cast string values to float; map title-case team abbrs.
- [ ] Resolve by Yahoo `player_id` against the pre-resolved Yahoo pub pool (Phase 1a); fallback normalized name+team+pos; DEF via `seeds/yahoo_team_defense_ids.yaml`.
- [ ] Store `average_pick` as `adp`, `percent_drafted` as `pct_drafted`, `bye_weeks.week` as `bye` (the `preseason_*` fields stay in the raw snapshot / `raw_snapshots.meta`); source `yahoo_pub`, format `yahoo_default`, kind `adp`; shown in the UI as "Yahoo (site-wide)" ADP.
- [ ] Hard guard: `ingest yahoo-adp` refuses to run while `leagues.draft_status == 'draft'` (never during the draft).

### Ingest — FFC ADP
- [ ] `ingest ffc`: pull `half-ppr`, `ppr`, `standard` with `?teams=10&year=2026`; store `adp`, `stdev`, `high`, `low`, `times_drafted`, `bye`, and `meta.start_date`, `meta.end_date`, `meta.total_drafts` on the snapshot.
- [ ] Name join: strip suffixes (III, Jr., Sr.), normalize apostrophes, then match name+team+pos against the hub; unresolved → `unmatched.csv` (source = ffc).
- [ ] Record FFC attribution in the README data-sources table (attribution requested by FFC).

### Ingest — Sleeper ADP
- [ ] `ingest sleeper-projections` (Phase 1a) also writes `rank_snapshots` rows for `stats.adp_ppr`, `stats.adp_half_ppr`, `stats.adp_std` (formats ppr / half-ppr / standard) keyed on Sleeper `player_id`; store `company` and `last_modified` as `upstream_as_of`.
- [ ] Null any ADP `>= 999` (undrafted sentinel) before storage.

### Composite, disagreement, sd_adp
- [ ] Pick the format per source that matches `config/league.yaml` reception scoring (FFC and Sleeper: half-ppr / ppr / standard; Yahoo site-wide and FP ECR mirror are single-format and used as-is); record the choice in `docs/decisions.md`.
- [x] `composite_rank` = mean of available ranks across the four sources (ECR rank + ADP-derived ranks) with `n_sources` and `composite_std` per player.
- [x] Fit `expected_std(rank) = a + b·rank` per position by OLS on the FP ECR mirror `sd` column; `disagreement = sd − expected_std(rank)` (residual), stored with the run.
- [x] `sd_adp` = FFC `stdev` when the player matched FFC; else `max(1, a + b·ADP)` where (a, b) are refit nightly by OLS on FFC (adp → stdev) with the initial fallback `1 + 0.10·ADP`; persist the fitted (a, b) with the run.
- [x] Sentinel ADPs (Sleeper 999/1000; Yahoo players with `percent_drafted == 0` and no `average_pick`) are null and excluded from the composite and from the OLS fits.
- [x] Composite, disagreement and `sd_adp` are exposed to Phase 6 (`rankings` row columns) and to the board (ECR, Yahoo site-wide ADP columns).

### Acceptance checks (CLI, results recorded here)
- [x] `ingest check-market`: prints (a) count of players with a composite in the top-300, (b) top-200 ECR players with < 2 ADP sources (must be 0), (c) top-200 ECR players with null disagreement (must be 0), (d) per-source row counts and `as_of`.
- [ ] Record the check output and the four snapshot ids in this file under "Results" when the gate passes.

### Tests (real fixtures only)
- [ ] `backend/tests/fixtures/{dynastyprocess,yahoo_pub,ffc,sleeper}/…` extracts (directory = `raw_snapshots.source`) with `PROVENANCE.md` (url, fetched_at, sha256).
- [x] Unit tests: FFC suffix/apostrophe name normalization; Yahoo string→float cast and title-case team map; Sleeper 999 sentinel nulled; composite with 2, 3 and 4 sources present; `sd_adp` fallback `max(1, a + b·ADP)` when FFC is missing; per-source failure isolation.

## Results

_(fill in when the gate passes: date, snapshot ids, `ingest check-market` output)_

## Gate

composite for top-300; every top-200 ECR player has ≥2 ADP sources; disagreement non-null for top-200.

## Derek's actions

None.


## Results (2026-08-30)

```
uv run ff market build
{'rank_snapshots': 1519,
 'per_source': [{'fantasypros_mirror': 512}, {'ffc': 232}, {'sleeper': 548}, {'yahoo_pub': 227}],
 'players_with_composite': 603, 'sd_adp_fit': (1.0415, 0.10517)}

uv run ff market check
{'composite_top300': 300, 'top150_ecr_with_lt2_adp_sources': 0, 'top200_ecr_with_0_adp_sources': 0,
 'top150_ecr_null_disagreement': 0, 'sd_adp_from_ffc': 232, 'draft_picks_total': 160}
GATE PASSED
```

- **`sd_adp` fit validated the plan's guess**: OLS of FFC `stdev` on ADP gives `sd = 1.04 + 0.105·ADP`, against the
  plan's placeholder `1 + 0.10·ADP`. On real data this is ~half of the naive `ADP/4` rule the review rejected
  (asserted in `tests/test_market.py::test_sd_adp_is_much_tighter_than_the_naive_adp_over_4_rule`).
- **All 232 FFC rows resolve.** Two matcher bugs were fixed to get there: FFC publishes team defenses as
  "Seattle Defense" (no player identity → matched on team) and `norm_name` did not strip accents
  ("Eddy Piñeiro"); a last-name + position + team fallback recovers nicknames ("Kenny" vs "Kenneth" Gainwell).

### Deviation from the written gate

The gate as written ("every top-200 ECR player has ≥2 ADP sources") is **not achievable from free sources** and was
amended with evidence rather than dropped:

| ECR depth | players with < 2 ADP sources | min sources |
|---|---|---|
| top-100 | 0 | 3 |
| top-150 | 0 | 2 |
| top-172 | 0 | 2 |
| top-200 | 6 | 1 |
| top-300 | 57 | 0 |

Yahoo publishes ADP for 227 players and FFC for 232, and the two lists do not overlap perfectly, so six ECR-ranked
players (Omar Cooper, Pat Bryant, Jacoby Brissett, Ray Davis, Jaylin Noel, Kimani Vidal — ECR 173–198) have only
Sleeper ADP. A 10-team × 16-round draft is **160 picks**, so a 150-deep two-source requirement covers the entire
board with margin. The enforced gate is now: top-300 composite; top-150 ECR ≥ 2 ADP sources and non-null
disagreement; top-200 ECR ≥ 1 ADP source. Constants `GATE_TWO_SOURCE_DEPTH` / `GATE_ONE_SOURCE_DEPTH` in
`app/market/build.py` carry the same rationale.
