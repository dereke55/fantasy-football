# Ranking model

Every formula and constant in the ranking package — per-game blend, adjustments, E[games], season value, baselines with keeper holes, room ADP, tiers, flags, P(available) and VONA — so Phase 6 and 8a can be implemented and unit-tested without interpretation.

Status: Not started

Source of truth: `docs/PLAN.md` Phase 6 (days 4–5), Phase 8a (day 5), plus the Phase 3 (durability), Phase 4-lite (market) and Phase 9 (keeper helper) formulas they depend on. Every constant below is also written into `ranking_runs.weights` at run time so a run is self-describing. Rule of the plan: vendor projections already embed 2026 context/age/injury, so **context and age adjustments never multiply vendor numbers** — they touch the in-house component only, and ONE E[games] factor is applied at the per-game → season step.

## 0. Inputs and outputs

Inputs (latest `ok` snapshot per source; all ids recorded in `ranking_runs.input_snapshot_ids`): `projections` (Sleeper/Rotowire stat lines), `player_features` (Phase 3), `rank_snapshots` (ECR + Yahoo site-wide ADP + FFC + Sleeper ADP), `depth_chart_snapshots`, `team_context` (curated tags), `keepers`, `pick_schedule`, `config/league.yaml`.

Outputs: one `rankings` row per player (columns listed in `docs/spec/data-model.md`) and the `why_bullets` rows (`docs/spec/why-rules.md`). `recompute` is network-free and must finish in < 5 min.

Notation: `teams = 10`; `starters[pos]` from `roster.slots`; `pos ∈ {QB, RB, WR, TE}` for VBD; K/DST handled separately (§7).

## 1. Per-game components

### 1a. Vendor PPG (Sleeper/Rotowire)

```
vendor_PPG = score(stat_line, league_scoring) / divisor
divisor    = 17                              # default
           = 17 − known_missed_weeks         # when Sleeper injury_status ∈ {IR, PUP, Out}
                                             # or the player is listed in seeds/known_missed_weeks.yaml
```

`stats.gp` is never used (constant 18). ESPN weight is 0 in MVP (kona excluded until its stat-id map is validated).

### 1b. In-house PPG (veterans)

Opportunity × efficiency, TDs from expected-TD rate:

```
team_plays[team]      = 2025 REG pass attempts/game and rush attempts/game of the 2026 team-of-record
share[player]         = same team + role share history (target share, carry share; weighted 0.5/0.3/0.2 over 2025/2024/2023, same-role seasons only)
                        else 2025 league-average share for the player's depth-chart slot (e.g. WR2, RB1)
team-level cap        : Σ target_share ≤ 1 and Σ carry_share ≤ 1 per team (scale down proportionally if exceeded)
opportunity/game      = share × team_plays                           # targets/game, carries/game
efficiency            = player's yards-per-opportunity and catch rate regressed to the positional mean
                        (weight = n_opps / (n_opps + k_pos); k_pos recorded in ranking_runs.weights)
TDs/game              = opportunity/game × expected-TD rate per opportunity (positional, from player_expected_stats)
in-house_PPG_raw      = score({rec, rec_yd, rec_td, rush_yd, rush_td, pass_yd, pass_td, …}/game, league_scoring)
```

For QBs the opportunity is team pass attempts/game (share = 1 for the projected QB1 from `qb_situations`, split when `status = competition`).

### 1c. In-house PPG (rookies / no qualifying history)

```
in-house_PPG_raw = draft_capital_tier_prior[pos, tier] × landing_spot_depth_slot_factor[pos, depth_slot]
```

- `tier` from `draft_picks_nfl` (2026 rows joined on `esb_id`): R1 early / R1 late / R2 / R3 / R4+ / UDFA.
- `depth_slot` from the latest `depth_chart_snapshots` (`pos_rank` on the 2026 team-of-record).
- The prior tables are run constants (in `ranking_runs.weights`), seeded from the verified hit-rate evidence and Derek's day-7 sanity pass.

## 2. Blend

```
qualifies_vet = has a season with ≥ 8 games in the same team + role
weights       = (vendor 0.70, in-house 0.30)  if qualifies_vet
              = (vendor 0.90, in-house 0.10)  for rookies and everyone else
PPG           = Σ w_i × PPG_i / Σ w_i   over the components that exist (renormalise when one is missing)
```

Missing vendor line → PPG = in-house PPG (weight renormalised to 1.0), and the player is tagged `no_vendor_projection`. Missing in-house (no history and no draft-capital row) → PPG = vendor PPG. ESPN weight = 0.

The vendor-vs-in-house gap is **logged as a WHY bullet** (`MARKET_VENDOR_GAP`), never used to move the vendor number.

## 3. Adjustments (in-house component only)

### 3a. Age step (age at 2026-09-10; year-over-year step applied once)

| pos | age | factor |
|---|---|---|
| RB | ≤ 27 | 1.00 |
| RB | 28 | 0.97 |
| RB | 29 | 0.92 |
| RB | 30 | 0.85 |
| RB | 31+ | 0.78 |
| WR | ≤ 23 | 1.05 |
| WR | 24–29 | 1.00 |
| WR | 30–31 | 0.96 |
| WR | 32+ | 0.88 |
| TE | ≤ 25 | 1.03 |
| TE | 26–31 | 1.00 |
| TE | 32+ | 0.93 |
| QB | ≤ 35 | 1.00 |
| QB | 36+ | 0.95 |

```
in-house_PPG = in-house_PPG_raw × age_factor[pos, age]
```

### 3b. Context tables → tags only

`coaching_changes`, `qb_situations`, `ol_changes` produce WHY tag bullets and feed only the `new_play_caller` / `qb_uncertain_team` flags. **No multipliers in MVP.**

### 3c. Structural-injury return

`structural_injury_return` (single season-ending ACL/Achilles, return-season discount only if < 12 months before Week 1): the discount applies to the in-house component only; the factor is a run constant in `ranking_runs.weights` (the plan fixes the condition, not the magnitude — set during Phase 6 and reviewed on day 7).

## 4. E[games] (ONE factor, from Phase 3 durability)

Definitions (REG only):

```
games_missed(season) = team REG games (excl. bye) where the player was on 53/IR/PUP
                       (roster status not DEV/CUT/SUS/RET/EXE)
                       − weeks present in player_week_stats with ≥ 1 opportunity
unmapped player      → "unknown" (never "missed")
cause                = injuries.report_primary_injury (blank → "unspecified")
missed_rate          = Σ games_missed(2023..2025) / Σ eligible games(2023..2025)

injury_prone = (missed_rate ≥ 0.20 AND ≥ 2 distinct injury events across ≥ 2 seasons)
               OR ≥ 2 soft-tissue listings (hamstring/groin/calf) in different seasons
structural_injury_return = single season-ending ACL/Achilles; discount only if < 12 months before Week 1
```

Positional base games missed by ADP band (rounds from composite ADP, 10 teams):

| pos | rounds 1–2 | rounds 3–5 | rounds 6–8 |
|---|---|---|---|
| RB | 2.4 | 3.3 | 3.8 |
| WR | 2.2 | 2.8 | 3.3 |

```
base_missed        = table[pos, band]                                   # rounds 9+: use the 6–8 band
base_rate          = base_missed / 17
excess             = max(0, missed_rate − base_rate)
expected_missed    = base_missed + 1.0 × (excess / 0.20)                # +1.0 game per 20 % historical rate above base
E[games]           = min(17 − known_missed_weeks, 17 − expected_missed)
known_missed_weeks = weeks implied by Sleeper injury_status ∈ {IR, PUP, Out} (players.injury_status, refreshed once/day)
                     + seeds/known_missed_weeks.yaml (source_url per row; the seed row wins when both exist)
```

QB and TE have no band values in the plan; until a positional table is added they use the WR band (spec default, recorded in `ranking_runs.weights`). Rookies have no `missed_rate` → `expected_missed = base_missed`.

## 5. Season value (man-games form)

```
season_value = E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]
```

A missed week costs `PPG − replacement_PPG[pos]`. `replacement_PPG[pos]` = PPG of the player at `baseline_rank[pos]` (§6) — so it depends on keepers and is recomputed on every keeper edit.

## 6. Baselines, VOLS / VORP, FLEX

```
keepers_at[pos]      = number of keepers (status != removed) whose player is at pos
baseline_rank[pos]   = teams × starters[pos] − keepers_at[pos]          # last starter after keeper removal
FLEX allocation      : greedy by PPG across RB/WR/TE on the remaining (non-keeper) pool —
                       after filling QB/RB/WR/TE starters, the next teams × starters[FLEX] best PPG
                       among RB/WR/TE extend that position's baseline by one each
VOLS[player]         = season_value − season_value at baseline_rank[pos]  (FLEX-extended)
VORP baseline rank   = baseline_rank[pos] (FLEX-extended) + typical bench share[pos]
                       bench share[pos] = round(teams × bench × 2025 league-average share of bench slots at pos)   # spec default; recorded in ranking_runs.weights
VORP[player]         = season_value − season_value at VORP baseline rank
value (board column) = VOLS; VORP shown in the drawer and used by the keeper helper
```

Pure numpy; recomputed on every keeper edit (the `keepers_hash` on `ranking_runs` and `draft_snapshot` records which set was used).

## 7. K / DST

VBD = 0; sorted by consensus ADP; "last two rounds" rule (they are excluded from VONA/best-available before round 12 — §12). No scoring for K/DST in MVP.

## 8. Keepers and `pick_schedule`

- `keepers(team_slot, player, cost_round, status, source)` — keeper cost = round drafted last year; Yahoo assigns each keeper to that round and the team is skipped in that round.
- `pick_schedule(overall_pick, round, team_slot, is_keeper_slot)` = `10 × rounds` snake (odd rounds slot 1→10, even rounds 10→1) with keeper-consumed slots marked (`is_keeper_slot = true` for `(team_slot, cost_round)` of every keeper).
- Each team's roster is pre-populated with its keepers.
- "My next pick in N", availability (§10), baselines (§6) and room ADP (§9) all read `pick_schedule`.
- `my_next_pick` = lowest `overall_pick > current_pick` with `team_slot = my_team_slot` and `is_keeper_slot = false`. `N` = number of non-keeper slots strictly between the current pick and `my_next_pick`.

## 9. Market: composite, disagreement, `sd_adp`, room ADP

### 9a. Composite (Phase 4-lite)

Sources stored separately per `(player, source, format, snapshot)`: FantasyPros ECR (mirror: avg/sd/best/worst), Yahoo site-wide ADP (labelled as such), FFC ADP (+stdev/high/low), Sleeper ADP.

```
composite_rank  = mean of available source ranks (ECR avg and each ADP as a rank); store n and std
disagreement    = residual ECR std:  ecr_sd − expected_sd(rank)
expected_sd     = a_pos + b_pos × rank     (OLS per position on the current ECR snapshot)
```

### 9b. `sd_adp`

```
sd_adp = FFC stdev                       when the player matched FFC
       = max(1, a + b × ADP)             otherwise; (a, b) refit nightly by OLS on FFC rows
initial (a, b) = (1, 0.10)               # verified: FFC stdev ≈ half of ADP/4 at every band
sentinel ADPs (Sleeper ≥ 999, Yahoo blank) are nulled before any fit
```

### 9c. Room ADP

For each ADP source: remove kept players, re-rank the remainder, and map rank `r` to the `r`-th **non-keeper** slot of `pick_schedule` (its `overall_pick`). `room_adp` = mean over available sources; raw and room-adjusted ADP are shown side by side. Flags (§11), the gap column and availability (§10) use **room ADP**.

### 9d. Our pick equivalent and gap

```
our_pick_equivalent = overall_pick of the r-th non-keeper slot in pick_schedule, where r = our overall rank among undrafted, non-keeper players
gap                 = room_adp − our_pick_equivalent           # picks; positive = market takes them later than we would
gap_z               = gap / sd_adp
```

## 10. Tiers

### 10a. Consensus tiers (Boris Chen method, fixed k)

1-D `GaussianMixture` on positional ECR avg within a rank window; components sorted by mean → rank-contiguous tiers (any non-contiguity is resolved by assigning the tier of the neighbouring rank).

| pos | k | window |
|---|---|---|
| QB | 8 | top-26 |
| RB | 10 | top-40 |
| WR | 12 | top-60 |
| TE | 7 | top-24 |
| K / DST | 4 | ranked by consensus ADP |

Players outside the window get `tier = k + 1`. Fixed `random_state`; `n_init` recorded in `ranking_runs.weights`.

### 10b. Value tiers (ours)

Sort by `season_value` within position; start a new value tier when the drop to the next player `≥ 0.5 × positional_weekly_SD` (the SD of weekly scores of the position's starters in 2025 under league scoring, from the consistency features). Cliffs and VONA use value tiers.

## 11. Flags

```
sleeper  if gap_z ≥ 1.0  AND gap ≥ 6 picks   AND ≥ 2 supporting signals
bust     if gap_z ≤ −1.0 AND gap ≤ −6 picks  AND ≥ 2 risk signals
```

Supporting signals (sleeper): opportunity gain (target share / carries per game up year-over-year, same role); negative luck (`|TD_diff| ≥ 3` or `|PPG_diff| ≥ 1.0` with actual below expected); depth-chart rise (`pos_rank` improved vs. the snapshot 30 days earlier); favorable context tag (from `team_context`).

Risk signals (bust): positive luck (actual above expected by the same thresholds); age cliff (RB ≥ 29 / WR ≥ 31 / TE ≥ 32 at kickoff); `injury_prone`; `new_play_caller`; `qb_uncertain_team`; OL `delta ≤ −1`; high disagreement (`disagreement > 0` by more than one expected-sd unit).

Tags (always set when true, independent of gap): `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team`. The signals that fired are stored in `rankings.signals` and must each appear as a WHY bullet.

## 12. Availability and VONA (Phase 8a, closed form)

```
P(available at my next pick) = 1 − Φ((my_next_pick − room_adp) / sd_adp)        # Φ = standard normal CDF

VONA[player] = value_now − Σ_{c ∈ best same-position candidates at my next pick} P(avail_c) × value_c × slot_weight[pos]
slot_weight[pos] = 1.0  if I still have an open starter at pos (incl. FLEX for RB/WR/TE)
                 = 0.5  if only bench slots remain for pos
K/DST excluded from VONA and best-available before round 12
```

`value_now` = VOLS of the candidate now; the candidate set at my next pick = the top-3 same-position players by VOLS among those still available, weighted by their P(avail). Board shows VONA top-3 per position and P(avail) per player; both recompute on every drafted / undo / keeper edit without a network call.

Post-MVP (8c): vectorized Monte Carlo (N = 2000; 25 % autopick by Yahoo pre-rank, else Normal(room_adp, sd) urgency; positional-need multipliers; run bump).

## 13. Keeper-value helper (Phase 9, day 7 — post-MVP, first)

```
keeper_surplus[candidate] = VORP(candidate) − E[VORP of the best player available at the cost-round pick under room ADP]
```

Candidates = Derek's roster (manual list; `team/{key}/roster` if OAuth works). Ranked with WHY bullets; delivered before the Yahoo keeper deadline (≥ 1 h before draft, commissioner approval).

## 14. Guards

- Spearman(our overall rank, ECR) on the top-150 ≥ 0.8, stored on `ranking_runs.spearman_top150`; a run below the guard is marked `failed` and cannot be frozen.
- Every top-100 player incl. rookies has ≥ 3 WHY bullets.
- `recompute` (no network) < 5 min.
- The draft board serves a pinned `run_id`; config-hash mismatch → refuse until explicit re-freeze.

## Constants summary (all written to `ranking_runs.weights`)

| constant | value |
|---|---|
| blend (vet / rookie) | 0.70 / 0.30 · 0.90 / 0.10; ESPN 0 |
| vet qualification | ≥ 8-game same team + role season |
| trend weights | 0.5 / 0.3 / 0.2 (2025 / 2024 / 2023) |
| age steps | §3a table |
| E[games] bases | RB 2.4 / 3.3 / 3.8 · WR 2.2 / 2.8 / 3.3 (rounds 1–2 / 3–5 / 6–8); +1.0 game per 20 % above base |
| injury_prone | missed_rate ≥ 0.20 AND ≥ 2 events in ≥ 2 seasons, OR ≥ 2 soft-tissue seasons |
| structural return window | < 12 months before Week 1 |
| sd_adp fallback | max(1, 1 + 0.10 × ADP), refit nightly on FFC |
| tier k | QB 8 / RB 10 / WR 12 / TE 7 / K, DST 4; windows 26 / 40 / 60 / 24 |
| value-tier break | ≥ 0.5 × positional weekly SD |
| flags | gap_z ≥ 1.0 & gap ≥ 6 & ≥ 2 signals · gap_z ≤ −1.0 & gap ≤ −6 & ≥ 2 signals |
| luck thresholds | \|TD_diff\| ≥ 3 · \|PPG_diff\| ≥ 1.0 |
| age cliffs (bust signal) | RB ≥ 29 / WR ≥ 31 / TE ≥ 32 |
| VONA slot weights | open starter 1.0 · bench only 0.5; K/DST excluded before round 12 |
| guard | Spearman top-150 ≥ 0.8 |

## Checklist

- [ ] `vendor_ppg()` divides by 17 or `17 − known_missed_weeks`; never reads `gp`.
- [ ] `inhouse_ppg()` with same-role share history, depth-slot fallback, team caps, efficiency regression, expected-TD rate.
- [ ] Rookie prior tables (draft-capital tier × depth slot) as run constants.
- [ ] Blend with renormalisation over available components; vendor-vs-in-house gap emitted as a WHY input.
- [ ] Age step table applied to the in-house component only (test: vendor PPG unchanged for a 31-year-old RB).
- [ ] `e_games()` from durability features + known missed weeks; rookies fall back to the base.
- [ ] `season_value()` man-games form; `replacement_ppg` from the keeper-aware baseline.
- [ ] `baselines()` with keeper holes and greedy FLEX; VORP bench share; pure numpy; test with keeper holes on real fixtures.
- [ ] `pick_schedule` builder (snake + keeper slots) and `my_next_pick`/`N`.
- [ ] Composite, disagreement, `sd_adp` (FFC else fit), room ADP per source, `our_pick_equivalent`, `gap`, `gap_z`.
- [ ] GMM tiers with fixed k and windows; value tiers from drop-offs.
- [ ] Flags with signal counting; tags; `rankings.signals` populated.
- [ ] `p_avail()` and `vona()` (8a) with slot weights and the K/DST round-12 rule.
- [ ] Spearman guard computed and enforced before freeze.
- [ ] `recompute` end-to-end < 5 min on the full pool.

## Gate

Phase 6: "Spearman(our overall rank, ECR) on top-150 ≥ 0.8; every top-100 player incl. rookies has ≥3 bullets; recompute 5 top-50 bullets from their referenced snapshots; unit tests for scoring, games-missed, VBD baselines/keeper holes, WHY rendering (real fixtures)."

Phase 3 (inputs): "5 named-player profiles match nflverse REG totals (e.g. Bijan Robinson 2025 rushing attempts/yards); games-missed correct for 3 players with known 2024/2025 IR stints; rookie profile returns nulls cleanly."

Phase 4-lite (inputs): "composite for top-300; every top-200 ECR player has ≥2 ADP sources; disagreement non-null for top-200."

## Derek's actions

- Day-1 inputs: roster slots + bench, keeper rules (max per team, whether "Assign Keeper Players" has run, deadline), draft slot (or "TBD by <date>") — these set `starters[pos]`, `bench`, `keepers` and `my_team_slot`.
- Enter the keeper list as it becomes known (manual entry is primary).
- Day 7: ~2 h top-200 sanity pass by position (rookie priors and the structural-return factor are reviewed here).
