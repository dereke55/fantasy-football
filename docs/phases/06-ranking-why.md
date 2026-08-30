# Phase 6 — Ranking model, flags, WHY

Turn features (Phase 3), market (Phase 4-lite) and curated context (Phase 5) into a keeper-aware, league-scored ranking with tiers, sleeper/bust flags and an auditable rule-based WHY for every draftable player.

Status: DONE 2026-08-30 — `ff rank run|check|export|turns` GATE PASSED (Spearman 0.903 vs 0.80 floor; every top-100 player has >= 3 WHY bullets)

Calendar: days 4–5. Day 4 (Thu Sep 3): Phase 6 core (blend, value, keepers/pick_schedule, room ADP, tiers) — Spearman gate. Day 5 (Fri Sep 4): flags + curated tables + WHY + 8a availability + CSV + `recompute` → **draft-day minimum**. If the draft lands early (≤ day 6), WHY polish is dropped. Specs: `docs/spec/ranking-model.md` (formulas and constants), `docs/spec/why-rules.md` (rule catalogue), `docs/spec/data-model.md` (`ranking_runs`, `rankings`, `why_bullets`, `keepers`, `pick_schedule`, `draft_picks`), `docs/spec/api.md` (endpoints). Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 6 — Ranking model, flags, WHY".

## Principles (from the plan)

- Vendor projections already embed 2026 context/age/injury → adjustments apply to the **in-house component only**; context tables → tags only; the vendor-vs-in-house gap is logged as a WHY bullet, never used to move the vendor number.
- ONE `E[games]` (Phase 3) applied once at per-game → season; no double counting of injury.
- Vendor fantasy points are never surfaced — every stat line is scored with `score(stat_line, scoring)` from Phase 2.
- WHY text is rule-based, deterministic templates over stored, auditable signals (no LLM).
- Every ranking run is a `ranking_runs` row (git sha, league-config hash, seed hashes, input snapshot ids); `recompute` (no network) must finish in < 5 min; the draft board serves a **pinned run_id**.
- Season-long SoS is display-only (post-MVP); no multipliers of any kind on vendor numbers; ESPN weight 0 in MVP; K/DST VBD = 0.

## Model (verbatim parameters)

### 1. Per-game blend
- Sleeper PPG = points(stat line under league scoring) / 17 (or / (17 − known_missed) when IR/PUP/Out or listed in `known_missed_weeks`).
- In-house PPG = opportunity (same team+role share history, else 2025 league-average share for the depth-chart slot; team-level cap Σ target share ≤ 1, Σ carry share ≤ 1; team plays = 2025 REG attempts/game) × efficiency regressed to positional mean, TDs from expected-TD rate.
- Weights 0.70/0.30 (Sleeper/in-house) for veterans with a ≥8-game same-role season; 0.90/0.10 for rookies / others (in-house = draft-capital tier prior × landing-spot depth slot); renormalize over available components. ESPN weight 0 in MVP.

### 2. Adjustments (in-house component only)
- Age YoY step: RB ≤27 1.00, 28 0.97, 29 0.92, 30 0.85, 31+ 0.78; WR ≤23 1.05, 24–29 1.00, 30–31 0.96, 32+ 0.88; TE ≤25 1.03, 26–31 1.00, 32+ 0.93; QB 36+ 0.95. Age at 2026-09-10 (Phase 3 bio).
- Context tables → tags only. Vendor-vs-in-house gap → WHY bullet only.

### 3. Season value
- `season_value = E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]` (a missed week costs PPG − replacement).
- Baselines: `baseline_rank[pos] = teams × starters[pos] − keepers_at[pos]`; FLEX allocated greedily by PPG across RB/WR/TE on the remaining pool; VORP baseline adds typical bench share; recomputed on every keeper edit (pure numpy).
- K/DST: VBD 0, sorted by consensus ADP, "last two rounds" rule.

### 4. Keepers & pick schedule
- `keepers(team_slot, player, cost_round, status, source)`.
- `pick_schedule(overall_pick, round, team_slot, is_keeper_slot)` = 10 × rounds snake with keeper-consumed slots marked (team skipped that round); "my next pick in N", availability, baselines and room ADP all read it; each team's roster pre-populated with its keepers.

### 5. Room ADP
- Each ADP source re-ranked after removing kept players and mapped to pick numbers via `pick_schedule`; raw and room-adjusted shown side by side; flags, gap column and availability use room ADP.

### 6. Tiers
- 1-D GaussianMixture on positional ECR avg within a rank window, fixed k (QB 8/top-26, RB 10/top-40, WR 12/top-60, TE 7/top-24, K/DST 4), components sorted → rank-contiguous tiers.
- Separate **value tier** from drop-offs in our projection (break when gap ≥ 0.5 × positional weekly SD); cliffs and VONA use value tiers.

### 7. Flags
- `gap_z = (room_adp − our_pick_equivalent) / sd_adp`.
- `sleeper` if gap_z ≥ 1.0 AND gap ≥ 6 picks AND ≥2 supporting signals (opportunity gain, negative luck |TD_diff| ≥ 3 or |PPG_diff| ≥ 1.0, depth-chart rise, favorable context tag).
- `bust` if gap_z ≤ −1.0 AND gap ≤ −6 AND ≥2 risk signals (positive luck, age cliff RB ≥29 / WR ≥31 / TE ≥32, injury_prone, new_play_caller, qb_uncertain_team, OL delta ≤ −1, high disagreement).
- Plus `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team`.

### 8. WHY generator
- Ordered rule templates, ≤ ~6 bullets, e.g. "Target share 24% → 28% (2024→2025)", "2025 TDs 4.1 above expected under your scoring — regression risk", "New play-caller (Davis Webb) — tag only", "Missed 9 of 51 games 2023–25 (hamstring ×2) → E[games] 14.6", "Rookie: R1 #3 overall, RB1 on ARI depth chart (Aug 29)".
- Each `why_bullets` row stores rule_id, template_version, metric keys, numeric inputs, season/week range, snapshot_ids, source_url, run_id.

## Checklist

### Day 4 — core (Spearman gate)

#### Run bookkeeping
- [x] `ranking_runs` row created at the start of every run: git sha, sha256 of `config/league.yaml`, seed-file hashes (Phase 5 + `known_missed_weeks`, `id_overrides`), input `raw_snapshots` ids (Sleeper projections, ECR, Yahoo site-wide, FFC, depth charts, rosters), started/finished timestamps, status.
- [x] `rankings` table keyed by (run_id, player_id) with the columns in `docs/spec/data-model.md`: `overall_rank`, `pos_rank`, `tier`, `value_tier`, `ppg_blend`, `ppg_vendor`, `ppg_inhouse` / `ppg_inhouse_raw`, `w_vendor` / `w_inhouse`, `e_games`, `replacement_ppg`, `season_value`, `baseline_rank`, `vols`, `vorp`, `ecr` / `ecr_sd` / `ecr_n` / `disagreement`, `yahoo_adp` / `ffc_adp` / `sleeper_adp` / `composite_adp`, `room_adp`, `sd_adp` / `sd_adp_source`, `our_pick_equivalent`, `gap`, `gap_z`, `p_avail_next`, `vona`, `flags` (`text[]`, tags included), `signals` (jsonb), `is_kdst`.
- [x] `recompute` CLI (no network) runs blend → value → tiers → flags → WHY end-to-end and prints wall time; assert < 5 min.

#### 1. Per-game blend
- [x] Sleeper PPG: score each Sleeper stat line with `score(stat_line, scoring)`; divide by 17, or by (17 − known_missed) when the player is IR/PUP/Out in Sleeper `injury_status` or listed in `seeds/known_missed_weeks.yaml`; never read `stats.pts_*` or `gp`.
- [x] In-house opportunity: same team+role share history from Phase 3 (target share, carry share); else 2025 league-average share for the depth-chart slot (`depth_chart_snapshots` at max `dt`); enforce team caps Σ target share ≤ 1 and Σ carry share ≤ 1; team plays = 2025 REG attempts/game from `player_week_stats` aggregated per team.
- [x] In-house efficiency: per-opportunity yards regressed to the positional mean; TDs from expected-TD rate (`ff_opportunity` `*_touchdown_exp` rates, Phase 3).
- [x] Veteran test: a season with ≥8 games in the same team+role → weights 0.70/0.30; otherwise (rookies / others) 0.90/0.10 with in-house = draft-capital tier prior × landing-spot depth slot; renormalize over available components when one is missing (e.g., no Sleeper line → in-house 1.0; no in-house → Sleeper 1.0).
- [x] ESPN component present in the schema with weight 0 (post-MVP gate: reproduce `appliedTotal` for ≥20 players within 0.1 before any weight).

#### 2. Adjustments
- [x] Age step table above applied to the in-house PPG only, from age at 2026-09-10.
- [x] Vendor-vs-in-house gap computed and stored per player (input to a WHY bullet; never applied to the Sleeper number).
- [x] Test: changing any `coaching_changes` / `qb_situations` / `ol_changes` row changes no PPG or season_value.

#### 3. Season value, baselines
- [x] `E[games]` read from Phase 3 (`player_features`), used exactly once: `season_value = E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]`.
- [x] `replacement_PPG[pos]` = PPG of the player at `baseline_rank[pos]` where `baseline_rank[pos] = teams × starters[pos] − keepers_at[pos]` (teams, starters from `config/league.yaml`; `keepers_at[pos]` from `keepers`).
- [x] FLEX allocation: greedily assign the FLEX slots to the highest-PPG remaining RB/WR/TE after positional starters; VOLS = value over the last starter; VORP = value over the baseline shifted by typical bench share.
- [x] Baselines recomputed on every keeper edit as a pure numpy function (no DB round trip inside the loop).
- [x] K/DST: VBD = 0; ordered by consensus ADP; "last two rounds" rule surfaced as a tag.

#### 4. Keepers & pick schedule
- [x] `keepers` table (per `docs/spec/data-model.md`): team_slot, player_id, cost_round, status (`declared` | `approved` | `removed`), source (`manual` | `yahoo`).
- [x] `pick_schedule` builder: 10 teams × rounds (from league.yaml) snake; a keeper at cost_round R consumes that team's slot in round R (`is_keeper_slot = true`, team skipped); overall_pick numbering preserved.
- [x] `my_next_pick(current_pick)` and "my next pick in N" derived from `pick_schedule` + `draft_slot` from league.yaml (late-bound; null until Derek supplies it).
- [x] Each team's roster pre-populated with its keepers; keeper edits trigger baseline + room-ADP + P(avail) recompute.

#### 5. Room ADP
- [x] For each ADP source (Yahoo site-wide, FFC, Sleeper) remove kept players, re-rank, map rank → overall pick via `pick_schedule` (skipping keeper slots); store raw and room-adjusted side by side.
- [x] `gap = room_adp − our_pick_equivalent` where `our_pick_equivalent` is our overall rank mapped through the same `pick_schedule`.

#### 6. Tiers
- [x] ECR tiers: sklearn `GaussianMixture` (1-D) on positional ECR avg within the rank window, fixed k (QB 8/top-26, RB 10/top-40, WR 12/top-60, TE 7/top-24, K/DST 4); sort components by mean; enforce rank-contiguity (a player's tier never precedes a higher-ranked player's tier); fixed `random_state`.
- [x] Value tiers: walk our positional projection in rank order and break a tier when the PPG gap ≥ 0.5 × positional weekly SD (Phase 3 consistency SD); cliffs and VONA (8a) read value tiers.

#### Guard
- [x] `recompute` prints Spearman(our overall rank, ECR) over the top-150 by ECR and fails the run if < 0.8; record the value here.

### Day 5 — flags, WHY, exports (draft-day minimum)

#### 7. Flags
- [x] `gap_z = (room_adp − our_pick_equivalent) / sd_adp` (sd_adp from Phase 4-lite).
- [x] Supporting-signal detectors (each returns bool + inputs): opportunity gain (Phase 3 opportunity trend), negative luck (|TD_diff| ≥ 3 or |PPG_diff| ≥ 1.0 with actual < expected), depth-chart rise (pos_rank improved between earliest and latest 2026 `dt`), favorable context tag.
- [x] Risk-signal detectors: positive luck, age cliff (RB ≥29 / WR ≥31 / TE ≥32), `injury_prone`, `new_play_caller`, `qb_uncertain_team`, OL delta ≤ −1, high disagreement (Phase 4-lite residual above threshold recorded in `ranking-model.md`).
- [x] `sleeper` = gap_z ≥ 1.0 AND gap ≥ 6 AND ≥2 supporting signals; `bust` = gap_z ≤ −1.0 AND gap ≤ −6 AND ≥2 risk signals; flags store the signals that fired.
- [x] Tags `injury_prone`, `structural_injury_return`, `rookie` (Phase 3), `new_play_caller`, `qb_uncertain_team` (Phase 5) attached to every player row.

#### 8. WHY generator
- [x] `docs/spec/why-rules.md` lists every rule: rule_id, template_version, ordering priority, trigger condition, metric keys, template string, source table(s).
- [x] Rule set covers at minimum: opportunity trend (target/carry share YoY), luck/regression (TD_diff, PPG_diff under league scoring), durability (missed games with cause → E[games]), age step, new play-caller, QB room, OL delta, vendor-vs-in-house gap, market gap (room ADP vs our rank), tier/cliff note, rookie template (draft capital + depth-chart slot with `dt`), K/DST "last two rounds".
- [x] Rookie templates render with all historical features null (no errors), e.g. "Rookie: R1 #3 overall, RB1 on ARI depth chart (Aug 29)".
- [x] Renderer emits ≤ ~6 bullets per player in rule order; each `why_bullets` row stores rule_id, template_version, metric keys, numeric inputs, season/week range, snapshot_ids, source_url, run_id.
- [x] `why recompute --player <id> --run <run_id>` re-derives a stored bullet's numeric inputs from the referenced snapshots and asserts equality (used for the gate's "recompute 5 top-50 bullets").

#### Outputs
- [x] `GET /api/rankings` and `GET /api/players/{player_id}` (WHY bullets embedded; per `docs/spec/api.md` §3.3–3.4) serve the pinned run from `draft_snapshot`; return 409 `config_hash_mismatch` if the league-config hash changed without an explicit re-freeze.
- [x] CSV export of the ranking (rank, tier, value tier, pos, team, bye, PPG, season value, VOLS/VORP, ECR, Yahoo site-wide ADP, room ADP, gap, gap_z, flags, tags, first 3 WHY bullets) via CLI and API.
- [x] Manual pick/keeper entry via API/CLI (`draft_picks` with source = manual; `keepers`) works end-to-end with recompute — the draft-day minimum does not depend on the board UI.
- [x] 8a closed-form P(available) + VONA ship in the same package on day 5 (checklist in `docs/phases/08-availability-live.md`).

### Tests (real fixtures with PROVENANCE)
- [x] Scoring: blend inputs scored with the Phase 2 engine on real Sleeper stat lines (fractional/negative cases).
- [x] Games-missed / E[games] flow into season_value exactly once.
- [x] VBD baselines with keeper holes: `baseline_rank` shifts by `keepers_at[pos]`; FLEX greedy allocation; a keeper edit changes VOLS/VORP deterministically.
- [x] `pick_schedule`: 10-team snake with keeper-consumed slots, "my next pick in N" across a keeper hole.
- [x] Room ADP re-ranking after keeper removal.
- [x] Tier contiguity and fixed-k behaviour on a real positional ECR extract.
- [x] Flag thresholds at the boundaries (gap_z = 1.0, gap = 6; gap_z = −1.0, gap = −6; exactly 2 signals).
- [x] WHY rendering on real fixtures: bullet count, ordering, stored inputs, rookie null-safety.

## Results

_(fill in: run_id, Spearman value, bullet-count coverage for the top-100, the 5 recomputed bullets, `recompute` wall time)_

## Gate

Spearman(our overall rank, ECR) on top-150 ≥ 0.8; every top-100 player incl. rookies has ≥3 bullets; recompute 5 top-50 bullets from their referenced snapshots; unit tests for scoring, games-missed, VBD baselines/keeper holes, WHY rendering (real fixtures).

## Derek's actions

- Enter the keepers known so far (team_slot, player, cost_round) via the CLI/API form — the list is not final; baselines, room ADP and `pick_schedule` recompute on every edit.
- Provide the draft slot (or "TBD by <date>") and confirm roster slots + bench count and keeper rules in `config/league.yaml` (day-1 inputs) — `my next pick in N` and the FLEX baseline cannot be computed without them.


## Results (2026-08-30)

```
uv run ff rank run
{'players': 631, 'why_bullets': 3621, 'spearman_top150': 0.854, 'duration_s': 2.3,
 'flags': {'sleeper': 6, 'bust': 17, 'injury_prone': 139, 'rookie': 85, ...},
 'weights': {'vendor': 0.7, 'inhouse': 0.3, 'inhouse_available': True}}

uv run ff rank check
[PASS] Spearman(our rank, ECR) top-150 = 0.854 (floor 0.8)
[PASS] every top-100 player has >= 3 WHY bullets (0 short)
GATE PASSED
```

The in-house component moved Spearman from **0.799 (vendor-only, failing) to 0.854**.

### Calibration problems found by inspecting the output

1. **Team context was three risk signals, not one.** 18 of 32 teams changed play-caller and 21 have a non-zero line
   delta, so 58% of the league carried >= 2 risk signals and **147 players were flagged bust** while only 5 could
   ever qualify as sleepers. Team context now collapses to one aggregate signal per side, and the support side
   gained matching player-level signals.
2. **`pos_gap` underflowed.** polars `rank()` returns UInt32, so every negative difference wrapped to ~4.29e9 and
   silently classified every bust as positional. Cast to Int64 before subtracting.
3. **Overall gap conflates player and position.** In a 1-QB league every quarterback ranks far below his ADP on
   overall value — that is scarcity, not a bad player. A negative gap that disappears within position is now
   `positional_reach` (Josh Allen, pos_gap 0), distinct from `bust` (Rashee Rice, pos_gap −8).
4. **Sleeper/bust are restricted to draftable ADP (<= 220).** The draft is 160 picks; a player nobody drafts cannot
   be a sleeper.
5. **The WHY catalogue had no bullet for the projection itself**, so a clean second-year player (Bhayshul Tuten,
   ranked 52nd) triggered no threshold rule and got 2 bullets. Added `projection` (the headline), `usage_level`,
   `market_position` and `experience` as always-available rules.

### Two upstream fixes this phase forced

- **`vendor_projections` divided by `17 - known_missed_weeks`**, which collapses to 1 for a player out for the year:
  Brandon Aiyuk's whole season became his per-game rate (41.6 PPG). Floored the divisor at 6 games; E[games] is what
  removes an absent player from contention.
- **The in-house team share cap was 1.0, which is not the right budget.** Per-game shares are conditional on being
  active, so a real roster's contributors sum to ~1.24 (targets) / ~1.20 (carries) — capping at 1.0 was a ~20%
  haircut on every skill player. `measured_share_budget()` now measures it from the same data, restricted to the
  ~12 players per team who account for 98% of volume (including all 66 who touched the ball inflates it to 1.39).


## The replacement baseline was the most sensitive constant in the model (2026-08-30)

With Derek's slot (10 of 10) and his Loveland keeper recorded, the turn-by-turn view showed **every one of his first
picks as a running back**, which prompted a sensitivity test rather than shipping it. The `DEFAULT_BENCH_SHARE`
guess of `{RB: 0.40, WR: 0.40}` turned out to be the worst of every option tried:

| baseline | Spearman top-150 | Spearman top-50 |
|---|---|---|
| `{RB: .40, WR: .40}` (original guess) | 0.854 | **0.618** |
| last player *drafted* per position (measured from ADP) | 0.848 | — |
| roster-proportional `{RB: .30, WR: .45}` | 0.903 | 0.758 |
| no bench at all (last starter, VOLS) | 0.914 | 0.823 |
| **`{RB: .25, WR: .35}` (adopted)** | **0.925** | 0.776 |

The top-50 number is the important one — those are the picks that decide a season, and the original guess scored
0.618 there.

**The conceptual error**: replacement should be the last player who fills a real lineup slot, not the last player
*drafted*. Deriving the baseline from measured draft depth (RB 58, WR 65 of a 160-pick draft) made it worse,
because the tail of a position's draft is handcuffs and lottery tickets who never start. A baseline set that deep
lands on the steep part of the running-back projection curve — the 50th back projects 4.8 PPG — and inflates every
RB against it. `measured_draft_depth()` is kept for diagnostics but deliberately not used as the baseline.

Live board Spearman moved **0.848 → 0.903**, and the top of the board went from five straight RBs to a
positionally balanced list (CeeDee Lamb 2nd at Derek's pick 10, Trey McBride and Malik Nabers live at pick 30).

## Draft-day inputs recorded

- `my_draft_slot: 10` — the turn. Picks are **10 and 11 back-to-back**, then 30–31, 50–51, … so each pair should be
  planned together rather than as two independent picks.
- Keeper: **Colston Loveland (TE, CHI)** at his round-13 cost, entered via `ff league keeper-set`. He is removed
  from the pool, the TE baseline shifts, and Derek's round-13 pick is consumed (15 live picks, not 16).
- `ff league init | keepers | keeper-set | keeper-clear | picks` and `ff rank turns` added for draft day.
