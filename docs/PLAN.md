# Plan — Fantasy Football Draft Board / Monitor / Prediction Tool (v2)

<!-- Mirror of the approved plan (2026-08-29). Progress is tracked in docs/phases/NN-*.md; decisions in docs/decisions.md. -->

## Phase index
| Phase | Doc | Day |
|---|---|---|
| 0 Scaffold, day-1 inputs, Yahoo application | [phases/00-scaffold.md](phases/00-scaffold.md) | 1 |
| 1a Crosswalk + MVP ingestion (1b post-MVP) | [phases/01-ingestion.md](phases/01-ingestion.md) | 1–2 |
| 2 League scoring engine | [phases/02-scoring.md](phases/02-scoring.md) | 2 |
| 3 Historical features (REG only) | [phases/03-features.md](phases/03-features.md) | 3 |
| 4-lite Market composite | [phases/04-market.md](phases/04-market.md) | 2 |
| 5 Curated team context | [phases/05-team-context.md](phases/05-team-context.md) | 5 |
| 6 Ranking model, flags, WHY | [phases/06-ranking-why.md](phases/06-ranking-why.md) | 4–5 |
| 7 Board UI (MVP) | [phases/07-board-ui.md](phases/07-board-ui.md) | 6 |
| 8 Availability (8a) / Yahoo live (8b) / Monte Carlo (8c) | [phases/08-availability-live.md](phases/08-availability-live.md) | 5 / 8 / post |
| 9 Keeper helper, review, freeze, readiness | [phases/09-readiness.md](phases/09-readiness.md) | 7–10 |

Runbook: [runbook-draft-week.md](runbook-draft-week.md). Specs: [spec/](spec/).


## Context

Derek's 10-team Yahoo keeper league (snake; keepers cost the round they were drafted in; standard 1-QB lineup) drafts
**before the Sep 10 NFL kickoff** — i.e. within ~5–10 days of today (Sat Aug 29). The goal is a tool that ranks every
draftable player with a justified **WHY**, going well beyond "average the ranking sites": 2023–2025 performance and
trends, 2026 team context (new HC/OC/play-caller, QB competitions, OL changes), injury history, contract situation,
sleeper/bust flags, strength of schedule — all scored under the league's custom scoring — plus a draft-day board that
syncs from Yahoo live (manual pick entry always available).

This plan was researched (15 read-only agents verified every data source live on 2026-08-29) and then adversarially
reviewed (4 lenses, ~55 findings, synthesized). The main consequence: the original phase layout was ~2× over-committed
for the window, so the plan is now organized around a **hard MVP cut line** with two gates:

- **Draft-day minimum (end of day 5)**: rankings + WHY + CSV export + manual pick/keeper entry via API/CLI.
- **MVP checkpoint (end of day 6)**: board UI with drafted/keeper/my-pick/undo and availability odds.
- Day 10 is buffer. If the draft lands early (≤ day 6), the board-lite is pulled into day 5 and WHY polish is dropped.

### Decisions (from Q&A)

| Topic | Decision |
|---|---|
| Platform | Yahoo. OAuth2 app + **reviewed access application** submitted day 1 (Yahoo now reviews even personal-use apps; no SLA) |
| Draft | Snake, 10 teams, keeper league; keeper cost = round drafted last year (Yahoo assigns each keeper to a round; that team is skipped in that round) |
| Keeper list | **Declaration deadline Mon Aug 31**; entered manually (primary) or captured from Yahoo pre-draft `draftresults` if OAuth works |
| Live scope | Live auto-sync from Yahoo **gated** on approval + a verified test harness; manual mode is first-class and identical |
| Timing | **Draft Sun Sep 6, 8:45pm CDT** (confirmed 2026-08-30); snapshot frozen Sat Sep 5 |
| Roster | Standard 1-QB (no superflex / TE premium / IDP); K and DST ranked by consensus ADP only |
| WHY text | Rule-based, deterministic templates over stored, auditable signals (no LLM) |
| Data | Free stack only; real data only (tests use real snapshot extracts with provenance) |
| Stack | FastAPI (uv) · Vite/React/TS dark UI · local Postgres 17 (docker, already on :5432) |

### Day-1 inputs still needed from Derek (block Phase 2)

1. **Scoring table** — ⏳ STILL PENDING (a screenshot was mentioned on 2026-08-30 but no image arrived). Blocks the Phase 2 gate.
2. Roster slots + bench count — ⏳ pending (placeholder: QB/RB2/WR3/TE/FLEX/K/DEF + 6 bench = 16 rounds).
3. Draft slot — ⏳ pending (may be assigned late; the model runs for any slot).
4. Keeper rules: max keepers per team + whether the commissioner has run "Assign Keeper Players" — ⏳ pending; **deadline Mon Aug 31** ✅ recorded.
5. `league_key` — ✅ `470.l.335180` (2026 game key 470 + league 335180, "shirtlesschugsonly").
6. Draft date/time — ✅ Sun Sep 6, 8:45pm CDT.
7. Yahoo developer app + access application — ✅ submitted 2026-08-30 (awaiting review; no SLA).

Until (1) lands, `config/league.yaml` carries Yahoo default public-league scoring with its source URL and is labeled as such.

## Research that shapes the plan (verified live 2026-08-29)

- **nflreadpy 0.1.5** (nflverse; `nfl_data_py` is archived — do not use). 2023–2025 complete: weekly player stats (targets, target_share, air_yards_share, wopr, carries, receptions, TDs, fumbles, 2pt …), `ff_opportunity` expected fantasy stats, injuries, weekly rosters; 2026 rosters/depth charts (daily `dt` snapshots)/schedule/draft picks; `ff_rankings` (DynastyProcess mirror of FantasyPros ECR: ecr/sd/best/worst/bye, daily); `ff_playerids` crosswalk. License CC-BY-4.0. Gotchas: explicit `seasons=[...]` everywhere (`get_current_season()` flips to 2026 on Sep 10 → 404s); 2025 files include postseason weeks 19–22 (filter `season_type == 'REG'`); 2026 `draft_picks.gsis_id` holds ESB ids (join on `roster_2026.esb_id`); `ff_playerids.yahoo_id` is NA for the whole 2025–26 rookie classes but `stats_id` == Yahoo id (100/100 of Yahoo's top-100 verified) → `yahoo_id = coalesce(yahoo_id, stats_id)`.
- **Projections with stat lines (re-scorable)**: Sleeper `api.sleeper.com/projections/nfl/2026?season_type=regular` (Rotowire lines; also carries `adp_half_ppr` etc.; `gp` is a constant 18 — never use; 999 = undrafted sentinel; cached 1 h). ESPN kona projections exist but the stat-id map is unverified → excluded from MVP.
- **ADP/ECR**: Yahoo `pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;start=N;count=100;out=draft_analysis?format=json` works unauthenticated (site-wide ADP across all Yahoo leagues, includes rookies + bye weeks); FFC `api/v1/adp/{half-ppr|ppr|standard}?teams=10&year=2026` (adp, **stdev**, high, low — official free API; stdev ≈ half of ADP/4 at every band); FantasyPros ECR via the mirror (direct scrape ≤1 page/day post-MVP).
- **Team context has no structured source** → three curated YAML tables. Verified seeds: 10 new HCs (ARI LaFleur, ATL Stefanski, BAL Minter, BUF Brady, CLE Monken, LV Kubiak, MIA Hafley, NYG Harbaugh, PIT McCarthy, TEN Saleh); 18–21 new OCs; ~9 teams with a new play-caller despite the same HC (DEN Webb, CAR Idzik, PHI Mannion, DET Petzing, SEA Fleury, WAS Blough, TB Robinson, LAC McDaniel, NYJ Reich — re-check); QB rooms as of 8/29: ATL (Tua/Penix undecided), LV (Cousins expected, not announced), KC (Mahomes ACL, cleared for camp, listed Questionable); announced: MIN Murray, CLE Watson, ARI Brissett, NYJ Geno, MIA Willis, PIT Rodgers, NO Shough. Nine R1 OL picks; Linderbaum → LV; notable OL injuries WAS Tunsil, CAR Ekwonu, LAC Biadasz. `games.csv` 2026 coach columns are stale for 3 teams — never derive HC changes from it.
- **Injuries**: nflverse injuries are in-season only (no 2026 file). Current IR/PUP/Out from Sleeper `/v1/players/nfl` (once/day) + a curated `known_missed_weeks.yaml` (e.g. players with announced multi-week absences) in MVP; ESPN injuries feed post-MVP (athlete id must be parsed from `links[].href`).
- **Methodology evidence**: opportunity is stickier than efficiency; TD/yardage luck via expected stats; contract-year effect is neutral-to-negative once age is controlled → informational tag only; OL matters more for QBs than RBs; season-long SoS is a weak tiebreaker (positional points-allowed YoY r ≈ 0.16–0.26) → display-only; Boris Chen tiers are a 1-D GMM with fixed k; vendor projections already embed 2026 context/age/injury → context adjustments must not multiply vendor numbers.
- **Yahoo API**: `league/{key}/settings` (roster_positions, stat_categories, stat_modifiers, uses_fractional_points, uses_negative_points, draft_time); `league/{key}/draftresults` returns every pick slot incl. **unfilled** rows (the live pick schedule: draft order, keeper holes, who is on the clock) — wrappers (`yahoo_fantasy_api`, `yfpy`) drop unfilled rows, so poll raw JSON. Keepers are not in settings; they appear as pre-filled draftresults rows and as `is_keeper` on league-scoped player objects. Yahoo mock drafts are not verified API-visible → test harness must be proven (see Phase 8).

## Architecture

```
fantasy-football/
├── README.md, CLAUDE.md                 # kept current; README has the Data sources / cadence / licensing table
├── docs/
│   ├── PLAN.md                          # overview, MVP cut line, gates, phase index, calendar
│   ├── phases/00-scaffold.md … 09-readiness.md   # one actionable checklist per phase; progress tracked here
│   ├── spec/data-model.md, scoring.md, ranking-model.md, why-rules.md, api.md, ui.md, live-draft.md
│   ├── runbook-draft-week.md            # daily jobs, failure handling, freeze, post-kickoff guard
│   └── decisions.md                     # ADR log incl. Yahoo application date, unofficial-endpoint risks accepted
├── backend/                             # uv: FastAPI, SQLAlchemy 2 + Alembic, polars, httpx, typer CLI, numpy, scikit-learn
│   ├── app/{api,models,ingest,scoring,features,ranking,why,live}
│   ├── seeds/{coaching_changes,qb_situations,ol_changes,known_missed_weeks,id_overrides,yahoo_team_defense_ids}.yaml
│   └── tests/fixtures/{source}/… + PROVENANCE.md (url, fetched_at, sha256) — real extracts only
├── frontend/                            # Vite + React + TS, Tailwind + shadcn/ui (dark), TanStack Query/Table
├── data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}   # immutable, hash-deduped snapshots
└── config/league.yaml                   # scoring + roster + teams + keeper rules + draft date/slot; source recorded
```

Data flow: `ingest` CLI (per-source isolation: one failing source never fails the job; every pull registered in
`raw_snapshots`) → Postgres → `scoring` (league config applied to every stat line; vendor fantasy points never
surfaced) → `features` → `ranking` (blend → value → tiers → flags) → `why` (rule rows with inputs + snapshot ids) →
FastAPI JSON (+ SSE in 8b) → React board. Every ranking run is a `ranking_runs` row (git sha, league-config hash,
seed hashes, input snapshot ids); the draft board serves a **pinned run_id** and refuses to serve if the config hash
changed without an explicit re-freeze. `recompute` (no network) must finish in < 5 min.

## MVP cut line

**IN (by end of day 6; draft-day minimum subset by end of day 5)**: real league config; players hub + crosswalk (Yahoo id
via `coalesce(yahoo_id, stats_id)`, Yahoo pub pool pre-resolution, DEF id table, 2026 draft_picks ESB join); ingest 1a;
scoring engine validated against 5 real 2025 totals; REG-only historical features; composite market (ECR + Yahoo
site-wide ADP + FFC + Sleeper ADP) with FFC-based sd; ranking model (per-game blend Sleeper 0.70 / in-house 0.30,
rookies 0.90/0.10 with draft-capital prior; age step on in-house only; ONE E[games]; man-games season value;
keeper-aware VOLS/VORP with FLEX allocation; K/DST VBD = 0); 1-D fixed-k GMM tiers + value tiers; room ADP from
`pick_schedule`; z-gap sleeper/bust flags; tags (injury_prone, structural_injury_return, rookie, new_play_caller,
qb_uncertain_team); three curated context tables as WHY tags; WHY generator (auditable rows, rookie templates);
closed-form P(available at my next pick) + VONA vs my open slots; Board + Player drawer + draft-day controls + keeper
entry + CSV export; Spearman ≥ 0.8 guard; frozen `draft_snapshot`.

**Post-MVP tracks (priority order, only after day 6)**: keeper-value helper (day 7, first); Yahoo live sync 8b (gated);
ESPN injuries; programmatic skill_movement; display-only 2025 SoS columns; sparklines/polish; snap_counts / NGS / PFR /
contracts / ESPN kona (gated on stat-id validation) / FantasyPros direct scrape / ESPN ADP; Monte Carlo availability 8c;
boom/bust rates.

**CUT for this draft**: Kalshi, win totals, implied totals, offense-environment score, opponent-adjusted SoS or any SoS
multiplier, context multipliers on vendor projections, 2-D GMM/BIC tiers, pbp 2023–24, ESPN depth charts/HC endpoint,
RotoWire RSS, Sleeper trending, news table, combine, Team view, settings/curated editors (edit YAML + reload), printable
sheet, Sleeper mock harness, ECR calibration study, backtest-fitted weights.

## Phases (each becomes `docs/phases/NN-*.md` with a checkbox list)

### Phase 0 — Scaffold, day-1 inputs, Yahoo application (day 1)
- Repo layout above; `uv init` backend (FastAPI `/health`), Vite React TS dark shell, `git init`; database `fantasy_football` on the running Postgres; Alembic baseline; `raw_snapshots` + `ranking_runs` tables; README (with sources/licensing table: nflverse CC-BY-4.0 attribution, FFC attribution, FantasyPros personal-use only, Sleeper/Yahoo-pub/ESPN unofficial), CLAUDE.md (rules: real data only, explicit seasons, never surface vendor points, new source ⇒ table row + snapshot parser), docs/PLAN.md, all phase checklists, spec skeletons, decisions.md, test-fixture policy.
- Day-1 inputs checklist (above) → `config/league.yaml` (`source: yahoo_settings_page`).
- Yahoo, in order: (1) create app at developer.yahoo.com (Installed Application, Fantasy Sports Read, redirect `https://localhost:8080`), store Client ID/Secret in `backend/.env`; (2) submit sports.yahoo.com/developer/access **with the Client ID** and use case "personal, single league, read-only draft monitor" — record date in decisions.md; (3) same day, run the `yahoo_oauth` consent flow and call `users;use_login=1/games;game_keys=nfl/leagues` to learn whether an unapproved app is blocked; if calls work, run the **mock-draft visibility spike** (join a Yahoo mock, check whether it appears in leagues/draftresults) and log the result.
- Library decision: `yahoo_oauth` for tokens + `httpx` raw JSON (archived); wrappers optional readers only.
- **Gate**: `/health` 200; shell renders; `alembic upgrade head`; docs exist; Yahoo app created + application submitted (date logged); day-1 inputs received or explicitly marked pending.

### Phase 1a — Crosswalk first, then MVP ingestion (days 1–2)
- **Players hub (end of day 1)**: nflverse `players` + `ff_playerids`; `yahoo_id = coalesce(yahoo_id, stats_id)`; Yahoo pub pool (~6 pages of 100 + DEF + K passes, 2 s spacing, once/day, never during the draft; map Yahoo title-case team abbrs) pre-resolved by id then normalized name+team+pos; `seeds/id_overrides.yaml`; `yahoo_team_defense_ids.yaml` (32 rows). CLI `ingest check-ids` (re-run after every ingest). **Gate**: top-300 ECR, top-300 Sleeper projection rows, top-400 Yahoo pool, every 2026 R1–R4 QB/RB/WR/TE pick resolve; `unmatched.csv` < 3% and reviewed.
- Ingest (explicit seasons; 2022 optional at zero cost): `stats_player_week` + `stats_player_reg` 2023–2025, `roster_weekly` 2023–2025, `injuries` 2023–2025, `ff_opportunity` weekly 2023–2025, `rosters` 2026 (canonical team-of-record), `depth_charts` 2026 (all `dt`), `schedules` 2023–2026 (derive `team_bye`), `draft_picks` (ESB join, name+college fallback), `ff_rankings('draft')`, Sleeper projections (filter to QB/RB/WR/TE/K/DEF with ≥1 counting stat; null ADP ≥ 999; store `company` + `last_modified`), Sleeper players (injury_status, once/day, ETag), FFC ADP × 3 formats (store `meta.start_date/end_date/total_drafts`), Yahoo pub ADP.
- Freshness: one `releases/tags/{tag}` call per tag (optional `GITHUB_TOKEN`), compare per-asset `updated_at`, stored as `upstream_as_of`.
- **Gate**: REG weeks 1–18 present for 2023–2025 for all 32 teams (POST rows present but excluded); each source writes a snapshot + row count; one source failing doesn't fail the job; test: every nflreadpy call passes explicit seasons and `ingest all` runs green with the clock mocked to 2026-09-11.

### Phase 1b — Post-MVP sources (only after day 6)
snap_counts, NGS, PFR advstats, contracts (parquet only, `is_active`, dedupe on otc_id/year_signed/team/years/value/apy; contract_year = max(season_history.year) == 2026 with overrides for 2023 R1 picks; exclude rookie/tag deals from just_paid; informational tags only), ESPN injuries (espn_id from `links[].href`; core per-team fallback), ESPN kona (adopt espn-api stat-id constants; reproduce `appliedTotal` for ≥20 players within 0.1 before any blend weight), FantasyPros ecrData (≤1 page/day, desktop UA, 5 s spacing, `last_updated_ts` as as_of), ESPN ADP, pbp 2025 only.

### Phase 2 — League scoring engine (day 2)
- `config/league.yaml` schema: QB/RB/WR/TE stat keys + fumbles lost + 2-pt, `uses_fractional_points`, `uses_negative_points`, roster slots, bench, teams, keeper rules, draft date/slot (slot late-bound). No K/DST scoring in MVP.
- `score(stat_line, scoring)` applied uniformly to historical weekly stats, `*_exp` expected stats, and projection stat lines. Yahoo stat_id map (4 PassYd, 5 PassTD, 6 INT, 9 RushYd, 10 RushTD, 11 Rec, 12 RecYd, 13 RecTD, 18 FumLost, …) validated against the raw settings payload in 8b (diff-only; never overwrites league.yaml).
- **Gate**: recompute 2025 season totals for 5 named players under the real scoring and match the totals on the Yahoo league's 2025 pages; fractional/negative tests on real fixture rows.

### Phase 3 — Historical features, REG only (day 3)
- Production: PPG, games, positional PPG rank, YoY deltas, 3-season weighted trend (0.5/0.3/0.2) restricted to same team+role seasons.
- Opportunity (from `stats_player_week` columns): targets/game, target share, air-yards share, WOPR, carries/game, opportunity trend. (Route/RZ metrics deferred with their sources.)
- Luck: `score(actual) − score(expected)` under league scoring from `ff_opportunity` (never its precomputed points); TD diff and PPG diff.
- Durability: `games_missed(season)` = team REG games (excl. bye) where the player was on 53/IR/PUP (roster status not DEV/CUT/SUS/RET/EXE) minus weeks present in `stats_player_week` with ≥1 opportunity; unmapped → "unknown", never "missed". Cause from `injuries.report_primary_injury` (blank → unspecified). `injury_prone` = (missed/eligible 2023–25 ≥ 0.20 AND ≥2 distinct injury events across ≥2 seasons) OR ≥2 soft-tissue listings in different seasons. `structural_injury_return` tag for a single season-ending ACL/Achilles with return-season discount only if < 12 months before Week 1. `E[games]` = min(17 − known_missed_weeks, positional base by ADP band [RB 2.4/3.3/3.8, WR 2.2/2.8/3.3 games missed for rounds 1–2/3–5/6–8] + 1.0 game per 20% historical rate above base); `known_missed_weeks` from Sleeper injury_status (IR/PUP/Out) + `seeds/known_missed_weeks.yaml` (source_url per row).
- Consistency (display only): per-season mean/SD/floor(25th)/ceiling(90th), excluding weeks with < 3 opportunities; starter threshold = weekly points of the (teams × starters[pos])-th player that week.
- Bio: age at 2026-09-10, years_exp, draft capital, rookie flag. Rookies: all historical features null, no errors.
- **Gate**: 5 named-player profiles match nflverse REG totals (e.g. Bijan Robinson 2025 rushing attempts/yards); games-missed correct for 3 players with known 2024/2025 IR stints; rookie profile returns nulls cleanly.

### Phase 4-lite — Market composite (day 2, after crosswalk)
- Sources stored separately per (player, source, format, snapshot): FantasyPros ECR (mirror: avg/sd/best/worst), Yahoo site-wide ADP (labeled as such), FFC ADP (+stdev/high/low), Sleeper ADP. Composite = mean of available ranks with n and std; disagreement = residual ECR std vs expected std at that rank (fit std ~ a + b·rank per position).
- `sd_adp` = FFC stdev when matched, else `max(1, a + b·ADP)` refit nightly by OLS on FFC (initial 1 + 0.10·ADP); sentinel ADPs nulled.
- **Gate**: composite for top-300; every top-200 ECR player has ≥2 ADP sources; disagreement non-null for top-200.

### Phase 5 — Curated team context (day 5)
- Three YAML tables, 32 rows each, every row with `source_url`, `confidence`, `last_checked`, seeded from the verified research: `coaching_changes` (hc, hc_new, oc, oc_new, play_caller, play_caller_new), `qb_situations` (projected_qb1, status: settled/competition/injury_return, changed_from_2025), `ol_changes` (delta −2..+2, notes). They produce WHY tag bullets and feed only the `new_play_caller` / `qb_uncertain_team` flags — **no multipliers in MVP**. Edited as YAML + reload.
- **Gate**: `team_context` API returns all three for 32 teams; every row has a source_url; Derek reviews them in one markdown table (day 9 re-check).

### Phase 6 — Ranking model, flags, WHY (days 4–5) — spec in `docs/spec/ranking-model.md`
1. **Per-game blend**: Sleeper PPG = points(stat line under league scoring) / 17 (or / (17 − known_missed) when IR/PUP/Out or listed in known_missed_weeks); in-house PPG = opportunity (same team+role share history, else 2025 league-average share for the depth-chart slot; team-level cap Σ target share ≤ 1, Σ carry share ≤ 1; team plays = 2025 REG attempts/game) × efficiency regressed to positional mean, TDs from expected-TD rate. Weights 0.70/0.30 for veterans with a ≥8-game same-role season; 0.90/0.10 for rookies / others (in-house = draft-capital tier prior × landing-spot depth slot); renormalize over available components. ESPN weight 0 in MVP.
2. **Adjustments apply to the in-house component only**: age YoY step (RB ≤27 1.00, 28 0.97, 29 0.92, 30 0.85, 31+ 0.78; WR ≤23 1.05, 24–29 1.00, 30–31 0.96, 32+ 0.88; TE ≤25 1.03, 26–31 1.00, 32+ 0.93; QB 36+ 0.95). Context tables → tags only. The vendor-vs-in-house gap is logged as a WHY bullet, never used to move the vendor number.
3. **Season value**: `E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]` (a missed week costs PPG − replacement). Baselines: `baseline_rank[pos] = teams × starters[pos] − keepers_at[pos]`; FLEX allocated greedily by PPG across RB/WR/TE on the remaining pool; VORP baseline adds typical bench share; recomputed on every keeper edit (pure numpy). K/DST: VBD 0, sorted by consensus ADP, "last two rounds" rule.
4. **Keepers & pick schedule**: `keepers(team_slot, player, cost_round, status, source)`; `pick_schedule(overall_pick, round, team_slot, is_keeper_slot)` = 10 × rounds snake with keeper-consumed slots marked (team skipped that round); "my next pick in N", availability, baselines and room ADP all read it; each team's roster pre-populated with its keepers.
5. **Room ADP**: each ADP source re-ranked after removing kept players and mapped to pick numbers via `pick_schedule`; raw and room-adjusted shown side by side; flags, gap column and availability use room ADP.
6. **Tiers**: 1-D GaussianMixture on positional ECR avg within a rank window, fixed k (QB 8/top-26, RB 10/top-40, WR 12/top-60, TE 7/top-24, K/DST 4), components sorted → rank-contiguous tiers. Separate **value tier** from drop-offs in our projection (break when gap ≥ 0.5 × positional weekly SD); cliffs and VONA use value tiers.
7. **Flags**: `gap_z = (room_adp − our_pick_equivalent) / sd_adp`. `sleeper` if gap_z ≥ 1.0 AND gap ≥ 6 picks AND ≥2 supporting signals (opportunity gain, negative luck |TD_diff| ≥ 3 or |PPG_diff| ≥ 1.0, depth-chart rise, favorable context tag). `bust` if gap_z ≤ −1.0 AND gap ≤ −6 AND ≥2 risk signals (positive luck, age cliff RB ≥29 / WR ≥31 / TE ≥32, injury_prone, new_play_caller, qb_uncertain_team, OL delta ≤ −1, high disagreement). Plus `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team`.
8. **WHY generator**: ordered rule templates, ≤ ~6 bullets, e.g. "Target share 24% → 28% (2024→2025)", "2025 TDs 4.1 above expected under your scoring — regression risk", "New play-caller (Davis Webb) — tag only", "Missed 9 of 51 games 2023–25 (hamstring ×2) → E[games] 14.6", "Rookie: R1 #3 overall, RB1 on ARI depth chart (Aug 29)". Each `why_bullets` row stores rule_id, template_version, metric keys, numeric inputs, season/week range, snapshot_ids, source_url, run_id.
- **Gate**: Spearman(our overall rank, ECR) on top-150 ≥ 0.8; every top-100 player incl. rookies has ≥3 bullets; recompute 5 top-50 bullets from their referenced snapshots; unit tests for scoring, games-missed, VBD baselines/keeper holes, WHY rendering (real fixtures).

### Phase 7 — Board UI, MVP (day 6)
- **Board**: rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags; tier bands; drafted dimmed; positional / sleeper / bust presets as filters. **Player drawer**: WHY bullets with source/as_of, 3-season PPG line, key metrics, tags. **Draft-day controls**: mark drafted, my pick, undo, "my next pick in N" from `pick_schedule`, VONA top-3 per position, bye-stack warning (≥3 projected starters sharing a bye; 2026 week 11 has six teams). **Keeper entry** form (team_slot, player, cost_round). CSV export. Keyboard j/k, d = drafted, m = my pick.
- Deferred: Team view, settings/curated editors, printable sheet, sparklines.
- **Gate**: 400 players render < 2 s; drafted/undo/keeper edits recompute best-available and P(avail) without reload.

### Phase 8 — Availability & live sync
- **8a (day 5, in the ranking package)**: closed-form `P(available at my next pick) = 1 − Φ((my_next_pick − room_adp) / sd_adp)`; VONA = value_now − Σ P(avail) × value of best same-position candidates at my next pick, weighted by my open slots (open starter → full VBD, bench only → 0.5×); K/DST excluded before round 12.
- **8b (day 8, only if Yahoo access approved AND a harness exists)**: `yahoo_oauth` + httpx; single token owner under `backend/.tokens/`, proactive refresh < 55 min; raw `league/{key}/settings` diff vs league.yaml (report only); poll raw `league/{key}/draftresults?format=json` from draft_time − 60 min: 60 s in `predraft` (captures draft order + pre-filled keeper rows), 10–15 s in `draft`, stop at `postdraft`; persist **every** row (player_key nullable, is_keeper); on-the-clock = lowest unfilled pick; exponential backoff from 30 s on 4xx/5xx/999; after 3 consecutive failures switch to manual mode with a banner; no roster/player calls during the draft; player resolution = dict lookup on the pre-resolved Yahoo pool; SSE to the board. Harness: mock-draft visibility spike; if mocks are invisible, a throwaway private Yahoo league with autopick and a scheduled live draft on day 8–9. If neither exists by day 8, live sync is dropped for this draft.
- **8c (post-MVP)**: vectorized Monte Carlo (N=2000; 25% autopick by Yahoo pre-rank, else Normal(room_adp, sd) urgency; positional-need multipliers; run bump).
- **Gate (8b)**: fixture test with unfilled + keeper rows; OAuth round-trip survives an hour; new pick detected within 15 s in the harness; SSE delivers; manual mode identical.

### Phase 9 — Keeper helper, review, freeze, readiness (days 7–10)
- Day 7: Derek's ~2 h top-200 sanity pass by position → fixes; **keeper-value helper**: for each candidate on Derek's roster (manual list; `team/{key}/roster` if OAuth works) `keeper_surplus = VORP(player) − expected VORP of the best player available at the cost-round pick under room ADP`, ranked with WHY bullets, delivered before the Yahoo keeper deadline (≥1 h before draft, commissioner approval); draft-week runbook; fixtures + PROVENANCE; docs updated.
- Day 8: Track A = 8b if gated conditions hold; Track B = ESPN injuries, programmatic skill_movement (2025 targets+carries departed/added per team from `stats_player_reg` × 2026 roster team change), display-only 2025 positional points-allowed columns (REG, league scoring, full season / wk 1–4 / wk 15–17, "proxy" label), sparklines. Either way: full refresh and **hard freeze** of `draft_snapshot` the evening before the draft (no later than Sep 9 23:00). After Sep 10 every ingest requires `--post-kickoff` (upstream semantics change to ROS); parsers assert expected shape (FP week == 0, Sleeper week null, `page_type == 'redraft-overall'`) and refuse to overwrite the frozen run.
- Day 9: Derek's 1–2 h curated-table re-check (ATL/LV/KC QB rooms, OL injuries, late signings: Decker, Conklin, Mixon, Chubb, Hopkins) with source URLs; re-freeze only if required (explicit, logged); dry run of draft-day mode with a scripted pick feed in real Yahoo-ADP order (plus the poller if 8b shipped): undo, keeper holes in pick counts, P(avail)/VONA updates, CSV.
- Day 10: buffer — dry-run bug fixes only; verify the frozen snapshot serves with the recorded config hash; final README/CLAUDE/decisions update.

## Data model (detailed in docs/spec/data-model.md before Phase 1 code)

`raw_snapshots` · `ranking_runs` · `players` (id hub: gsis, esb, sleeper, espn, yahoo, fantasypros, pfr, otc) · `player_week_stats` / `player_season_stats` (raw counting stats, season_type kept) · `player_expected_stats` · `roster_weeks` · `injury_weeks` · `rosters_2026` · `depth_chart_snapshots` · `games` 2023–2026 + `team_bye` · `draft_picks_nfl` · `projections` (source, stat line, upstream_as_of) · `rank_snapshots` (source, format, rank/adp/std/min/max) · curated: `coaching_changes`, `qb_situations`, `ol_changes`, `known_missed_weeks`, `id_overrides` · derived: `player_features`, `team_context`, `rankings` (run_id), `why_bullets` (run_id, rule_id, inputs, snapshot_ids), `draft_snapshot` (pinned run_id + config hash) · draft: `leagues` (draft_time, draft_status, num_teams, rounds, draft_order), `keepers`, `pick_schedule`, `draft_picks` (pick, round, team_slot, player nullable, is_keeper, source manual|yahoo).

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Yahoo access not approved in time / unapproved app blocked | Submit day 1 with Client ID; day-1 smoke test; manual mode is first-class; Yahoo ADP via the public endpoint regardless |
| `draftresults` not live mid-draft (unverified) / no mock harness | Visibility spike; throwaway private league with scheduled draft; otherwise drop live sync for this draft |
| Draft lands early (≤ day 6) | Draft-day minimum by day 5; board-lite pulled into day 5, WHY polish dropped |
| Unofficial endpoints change (Sleeper projections, Yahoo pub, FFC) | Hash-deduped immutable snapshots; app runs on the last good snapshot; multiple ADP sources |
| Season flip on Sep 10 changes upstream semantics | Explicit seasons; `--post-kickoff` guard; shape assertions; frozen run pinned to config hash |
| Curated context wrong/stale | source_url + confidence + last_checked per row; day-9 re-check; tags only, no multipliers |
| Double counting context/age/injury on vendor projections | Adjustments only on the in-house component; ONE E[games] at per-game → season |
| Scoring mis-copied | Phase 2 gate against real Yahoo 2025 totals; 8b settings diff |

## Verification

- Unit tests on real fixture extracts (with PROVENANCE): scoring (fractional/negative), games-missed, VBD baselines with keeper holes, pick_schedule, room ADP, P(avail), WHY rendering, draftresults parsing (unfilled + keeper rows).
- Ingest acceptance checks as CLI commands (`ingest check-ids`, REG-weeks check, snapshot registry), results recorded in phase docs.
- Model guard: Spearman ≥ 0.8 vs ECR on top-150; ≥3 bullets per top-100 player; 5 bullets recomputed from snapshots.
- Manual: Derek's top-200 sanity pass (day 7) and curated-table review (day 9).
- End-to-end: `uv run fastapi dev` + `pnpm dev`; dry run of draft-day mode with a scripted real-ADP pick feed; 8b tested against the Yahoo harness if shipped.

## Calendar (CONFIRMED: draft Sun **Sep 6, 8:45pm CDT**; keeper deadline Mon **Aug 31**)

Re-planned 2026-08-30 — the draft is 3 days earlier than the plan assumed, and the keeper deadline lands on day 2,
so the keeper-value helper moves from day 7 to day 2 and every gate shifts earlier. All dates are before the
Sep 10 kickoff, so the post-kickoff guard never fires this cycle.

| Day | Date | Deliverable / gate |
|---|---|---|
| 1 | Sun Aug 30 | ✅ commit/push; league_key + draft time in `league.yaml`; **Phase 4-lite market composite (gate passed)**; Phase 3 feature modules |
| 2 | Mon Aug 31 | Phase 3 assembly (`player_features`); minimal projection + VBD → **keeper-value helper before the keeper deadline**; Derek enters keepers |
| 3 | Tue Sep 1 | Phase 6 core: blend, adjustments, keeper-aware VBD, tiers, room ADP — Spearman ≥ 0.8 gate |
| 4 | Wed Sep 2 | Flags + WHY bullets + 8a availability/VONA + CSV export + `recompute` → **draft-day minimum** |
| 5 | Thu Sep 3 | Board UI (Phase 7) → **MVP checkpoint**; candidate freeze v1 |
| 6 | Fri Sep 4 | Derek's top-200 review + fixes; Phase 5 curated loader → `team_context` API + tags; Yahoo 8b if approved |
| 7 | Sat Sep 5 | Curated re-check (QB rooms, OL, late signings); dry run of draft-day mode; **hard freeze** |
| 8 | Sun Sep 6 | Buffer + final refresh in the morning; **draft 8:45pm CDT** |


## Deliverables on approval

1. Repo scaffold, README.md, CLAUDE.md, `docs/PLAN.md`, `docs/phases/00–09` checklists, `docs/spec/*` skeletons, `docs/runbook-draft-week.md`, `docs/decisions.md`.
2. Immediately proceed with Phase 0 → Phase 1a, ticking checklists as items complete, pausing only for the day-1 inputs (scoring, roster, keeper rules, league_key, draft date/slot) and the Yahoo steps only Derek can do.
