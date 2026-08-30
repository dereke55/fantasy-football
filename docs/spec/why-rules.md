# WHY rules

Catalogue of the deterministic, rule-based templates that produce every WHY bullet — `rule_id`, trigger, template, inputs, source — plus ordering, the rookie templates, and the storage contract that makes each bullet recomputable from its snapshots.

Status: Not started

Source of truth: `docs/PLAN.md` Phase 6.8 ("WHY generator: ordered rule templates, ≤ ~6 bullets … Each `why_bullets` row stores rule_id, template_version, metric keys, numeric inputs, season/week range, snapshot_ids, source_url, run_id"). No LLM: text is rendered from stored, auditable signals only. Thresholds marked **(plan)** are copied from the plan; thresholds marked **(spec default)** are not fixed by the plan and are run constants recorded in `ranking_runs.weights` — tune them during Phase 6 / Derek's day-7 pass, never silently.

## Contract

- Input: one `rankings` row + its `player_features`, `team_context`, `projections`, `rank_snapshots`, `depth_chart_snapshots` and curated rows, all from the same `run_id`.
- Output: ordered `why_bullets` rows (see `docs/spec/data-model.md`): `run_id`, `player_id`, `ordinal`, `rule_id`, `template_version`, `polarity`, `text`, `metric_keys`, `inputs`, `season_from/to`, `week_from/to`, `snapshot_ids`, `source_url`, `as_of`.
- Each rule is a pure function `(signals) -> bullet | None`. Rendering = `template.format(**inputs)`; re-rendering a stored row from its `inputs` must reproduce `text` byte-for-byte (test).
- ≤ ~6 bullets per player (hard cap 6 — `WHY_MAX_BULLETS`), every top-100 player incl. rookies ≥ 3 (gate).
- Every signal that contributed to a `sleeper` / `bust` flag (`rankings.signals`) **must** appear as a bullet, so a flag is never unexplained.
- Rookies: all historical rules return `None` (features null) without error; rookie templates fire instead.
- Every bullet carries the `raw_snapshots.id`s its inputs came from; curated bullets carry the row's `source_url` and `last_checked` as `as_of`.

## Rendering conventions

| thing | format | example |
|---|---|---|
| PPG / points | 1 decimal | `14.6` |
| shares | whole percent | `24%` |
| picks / ranks / games | integer | `pick 58`, `9 of 51` |
| change | `a → b (yearA→yearB)` | `24% → 28% (2024→2025)` |
| season ranges | en dash, short year | `2023–25` |
| dates | `Mon D` from the snapshot `as_of` | `(Aug 29)` |
| scoring reference | the literal phrase `under your scoring` | |
| context bullets | end with `— tag only` | |
| player names | `players.display_name` | |
| position slot | `{pos}{rank}` from the depth chart | `RB1` |

## Rule catalogue

Priority = display order (lower first). `polarity`: `+` positive, `−` negative, `0` neutral, `T` tag.

| # | rule_id | trigger | template | inputs (`metric_keys`) | source tables / snapshot |
|---|---|---|---|---|---|
| 1 | `VALUE_SUMMARY` | always (every ranked player) | `Projected {ppg:.1f} PPG × E[games] {e_games:.1f} → {season_value:.0f} season value; VOLS {vols:+.0f} ({pos} baseline #{baseline_rank}{keeper_note})` where `keeper_note` = `, {k} keeper(s) removed` when `keepers_at[pos] > 0` | `ppg_blend`, `e_games`, `season_value`, `vols`, `baseline_rank`, `keepers_at_pos` | `rankings`, `keepers`; projection + ECR snapshots |
| 2 | `MARKET_GAP_SLEEPER` | `flags ∋ sleeper` **(plan: gap_z ≥ 1.0 AND gap ≥ 6 AND ≥ 2 supporting signals)** | `Room ADP {room_adp:.0f} vs our pick {our_pick:.0f} (gap {gap:+.0f}, z {gap_z:.1f}) — sleeper: {signal_list}` | `room_adp`, `our_pick_equivalent`, `gap`, `gap_z`, `sd_adp`, `signals` | `rankings`; ADP snapshots (FFC, Yahoo pub, Sleeper), `pick_schedule` |
| 3 | `MARKET_GAP_BUST` | `flags ∋ bust` **(plan: gap_z ≤ −1.0 AND gap ≤ −6 AND ≥ 2 risk signals)** | `Room ADP {room_adp:.0f} vs our pick {our_pick:.0f} (gap {gap:+.0f}, z {gap_z:.1f}) — bust risk: {signal_list}` | as above | as above |
| 4 | `ROOKIE_CAPITAL` | `is_rookie` | `Rookie: R{round} #{pick} overall, {pos}{depth_rank} on {team} depth chart ({as_of})`; UDFA: `Rookie: undrafted, {pos}{depth_rank} on {team} depth chart ({as_of})` | `draft_round`, `draft_pick`, `depth_rank`, `team` | `draft_picks_nfl` (ESB join), `depth_chart_snapshots` max `dt` |
| 5 | `ROOKIE_PRIOR` | `is_rookie` | `Rookie prior: {tier} {pos} × depth slot {depth_rank} → in-house {inhouse_ppg:.1f} PPG (weight {w_inhouse:.2f}; Rotowire {vendor_ppg:.1f} at {w_vendor:.2f})` | `capital_tier`, `depth_rank`, `ppg_inhouse`, `ppg_vendor`, `w_inhouse`, `w_vendor` | `rankings`, `projections` |
| 6 | `ROOKIE_LANDING` | `is_rookie AND depth_rank > 1` | `Behind {ahead_name} ({pos}1) on {team} chart ({as_of}); {ahead_name} {ahead_status}` where `ahead_status` ∈ {`healthy`, `IR/PUP/Out`, `Questionable`} from Sleeper `injury_status` | `ahead_player_id`, `ahead_injury_status`, `depth_rank` | `depth_chart_snapshots`, Sleeper players snapshot |
| 7 | `PROD_TREND` | veteran; `\|ppg_2025 − ppg_2024\| / ppg_2024 ≥ 0.15` **(spec default)**, same team + role | `PPG {ppg_prev:.1f} → {ppg_last:.1f} ({y_prev}→{y_last}, same role); 3-season trend {trend:+.1f}` | `ppg_2024`, `ppg_2025`, `ppg_trend3`, `pos_ppg_rank_2025` | `player_week_stats` (REG), league scoring |
| 8 | `OPP_TARGET_SHARE` | WR/TE/RB; `\|Δ target_share\| ≥ 0.03` **(spec default)** between last two same-role seasons | `Target share {ts_prev:.0%} → {ts_last:.0%} ({y_prev}→{y_last})` — e.g. **`Target share 24% → 28% (2024→2025)`** | `target_share_2024`, `target_share_2025` | `player_week_stats` (`target_share`) |
| 9 | `OPP_AIR_YARDS` | WR/TE; `\|Δ wopr\| ≥ 0.05` **(spec default)** | `WOPR {w_prev:.2f} → {w_last:.2f} ({y_prev}→{y_last}); air-yards share {ays:.0%}` | `wopr_2024`, `wopr_2025`, `air_yards_share_2025` | `player_week_stats` (`wopr`, `air_yards_share`) |
| 10 | `OPP_CARRIES` | RB/QB; `\|Δ carries/game\| ≥ 2.0` **(spec default)** | `Carries {c_prev:.1f} → {c_last:.1f} per game ({y_prev}→{y_last})` | `carries_pg_2024`, `carries_pg_2025` | `player_week_stats` (`carries`) |
| 11 | `OPP_INHOUSE` | veteran with in-house line | `In-house: {opp_pg:.1f} {opp_kind}/game ({share:.0%} of {team} {plays:.0f}) × efficiency → {inhouse_ppg:.1f} PPG` | `share`, `team_plays`, `efficiency`, `ppg_inhouse` | in-house component (`player_week_stats`, `rosters_2026`) |
| 12 | `LUCK_TD` | `\|td_diff_2025\| ≥ 3` **(plan)** | above: `2025 TDs {td_diff:.1f} above expected under your scoring — regression risk`; below: `2025 TDs {abs_td_diff:.1f} below expected under your scoring — positive regression` — e.g. **`2025 TDs 4.1 above expected under your scoring — regression risk`** | `td_diff_2025`, `td_actual_2025`, `td_expected_2025` | `player_expected_stats` (`*_touchdown_exp`) vs `player_week_stats`, scored |
| 13 | `LUCK_PPG` | `\|ppg_diff_2025\| ≥ 1.0` **(plan)** | `2025 PPG {ppg_diff:+.1f} vs expected under your scoring ({direction})` where `direction` = `production outran opportunity` / `opportunity outran production` | `ppg_diff_2025`, `ppg_actual_2025`, `ppg_expected_2025` | as above |
| 14 | `DUR_MISSED` | veteran; `games_missed_2023_25 ≥ 2 OR is_injury_prone` **(spec default)** | `Missed {missed} of {eligible} games 2023–25 ({causes}) → E[games] {e_games:.1f}` where `causes` = top causes with counts, e.g. `hamstring ×2` — e.g. **`Missed 9 of 51 games 2023–25 (hamstring ×2) → E[games] 14.6`** | `games_missed_2023..2025`, `games_eligible_2023..2025`, `injury_events`, `e_games` | `roster_weeks`, `player_week_stats`, `injury_weeks` (`report_primary_injury`) |
| 15 | `DUR_CLEAN` | veteran; `games_missed_2023_25 ≤ 1 AND eligible seasons ≥ 2` **(spec default)** | `Missed {missed} of {eligible} games 2023–25 → E[games] {e_games:.1f} (positional base {base:.1f} missed)` | as above + `base_missed` | as above |
| 16 | `DUR_INJURY_PRONE` | `is_injury_prone` **(plan rule)** | `injury_prone: {rate:.0%} of games missed 2023–25, {n_events} injury events in {n_seasons} seasons` or `… ≥2 soft-tissue listings ({seasons})` | `missed_rate_2023_25`, `injury_events`, `soft_tissue_seasons` | `injury_weeks`, `roster_weeks` |
| 17 | `DUR_STRUCTURAL` | `is_structural_injury_return` **(plan)** | `Returning from {injury} ({event_date:%b %Y}, {months:.0f} months before Week 1) — structural_injury_return{discount_note}` | `structural_event`, `months_before_week1` | `injury_weeks`, `known_missed_weeks` |
| 18 | `DUR_KNOWN_MISSED` | `known_missed_weeks > 0` | `Listed {status} ({src}, {as_of}) → {weeks} known missed weeks; projection divisor {divisor}` | `known_missed_weeks`, `known_missed_source`, `injury_status` | Sleeper players snapshot / `seeds/known_missed_weeks.yaml` (`source_url`) |
| 19 | `AGE_STEP` | `age_factor ≠ 1.00` | `Age {age} at kickoff → {pos} step {factor:.2f} on the in-house component only` | `age_at_kickoff`, `age_factor` | `players`, age table (§3a of ranking-model) |
| 20 | `CTX_PLAY_CALLER` | `team_context.play_caller_new` | `New play-caller ({play_caller}) — tag only` — e.g. **`New play-caller (Davis Webb) — tag only`** | `play_caller`, `play_caller_new` | `coaching_changes` (`source_url`, `last_checked`) |
| 21 | `CTX_HC` | `team_context.hc_new` (and not already covered by #20 for the same person) | `New head coach ({hc}) — tag only` | `hc`, `hc_new` | `coaching_changes` |
| 22 | `CTX_QB` | `qb_situations.status ∈ {competition, injury_return}` → tag `qb_uncertain_team`; or `changed_from_2025` | competition: `QB room unsettled ({qb_names}, {status} as of {as_of}) — qb_uncertain_team`; changed: `New QB1 ({projected_qb1}, {status}) — tag only` | `projected_qb1`, `qb_status`, `changed_from_2025` | `qb_situations` |
| 23 | `CTX_OL` | `ol_changes.delta ≠ 0` | `OL delta {delta:+d} ({notes}) — tag only` | `ol_delta`, `ol_notes` | `ol_changes` |
| 24 | `MARKET_VENDOR_GAP` | `\|ppg_vendor − ppg_inhouse\| ≥ 1.0` **(spec default)** | `Rotowire {vendor:.1f} PPG vs in-house {inhouse:.1f} (blend {blend:.1f}, weights {w_v:.2f}/{w_i:.2f}) — logged, vendor number unchanged` | `ppg_vendor`, `ppg_inhouse`, `ppg_blend`, `w_vendor`, `w_inhouse` | `projections`, `rankings` |
| 25 | `MARKET_DISAGREE` | `disagreement` high (risk signal) | `Experts disagree: ECR sd {sd:.1f} vs {expected_sd:.1f} typical at rank {rank:.0f} (best {best}, worst {worst})` | `ecr_sd`, `expected_sd`, `ecr`, `ecr_best`, `ecr_worst` | FantasyPros mirror snapshot |
| 26 | `DEPTH_RISE` | `pos_rank` improved vs. the snapshot 30 days earlier (supporting signal) | `Depth chart: {pos}{old} → {pos}{new} since {dt_old:%b %-d}` | `depth_rank_30d_ago`, `depth_slot` | `depth_chart_snapshots` (two `dt`) |
| 27 | `TIER_CLIFF` | player is last in a value tier and the next-tier drop ≥ 0.5 × positional weekly SD **(plan)** | `Last of value tier {vt} at {pos}; next tier drops {drop:.1f} PPG` | `value_tier`, `next_tier_drop`, `pos_weekly_sd` | `rankings` |
| 28 | `CONSISTENCY` | veteran with ≥ 8 REG weeks in 2025 (display only) | `2025 floor {floor:.1f} / ceiling {ceil:.1f} PPG; {pct:.0%} of weeks above the {pos} starter line` | `floor25_2025`, `ceiling90_2025`, `pct_weeks_above_starter_2025` | `player_week_stats` (weeks with ≥ 3 opportunities) |
| 29 | `KDST_ADP_ONLY` | `position ∈ {K, DEF}` | `{pos} ranked by consensus ADP only (VBD 0) — last two rounds` | `composite_adp` | ADP snapshots |
| 30 | `NO_VENDOR_LINE` | no Sleeper projection row | `No Rotowire projection — in-house only (weight 1.00)` | `w_inhouse` | `projections` |

Notes on specific rules:

- `signal_list` (#2, #3) is the comma-joined short names of `rankings.signals`, e.g. `target share up, TDs below expected` / `TDs above expected, age 30, new play-caller`. The full bullets for each signal follow lower in the list.
- `capital_tier` (#5): `R1 early` / `R1 late` / `R2` / `R3` / `R4+` / `UDFA`.
- `discount_note` (#17): ` (return-season discount on in-house)` when `< 12 months before Week 1`, else empty.
- #20/#21: if the new HC is also the play-caller, only #20 fires (dedupe by person).
- #22 is the only source of the `qb_uncertain_team` flag text; #20 the only source of `new_play_caller`.

## Rookie templates

For `is_rookie` players the historical rules (#7–#16, #28) return `None`; the minimum set is:

1. `VALUE_SUMMARY` (#1)
2. `ROOKIE_CAPITAL` (#4) — **`Rookie: R1 #3 overall, RB1 on ARI depth chart (Aug 29)`**
3. `ROOKIE_PRIOR` (#5)
4. `ROOKIE_LANDING` (#6) when not the top of the chart
5. `DUR_KNOWN_MISSED` (#18) when listed (e.g. a preseason IR/PUP)
6. context tags (#20–#23) for the landing team
7. `MARKET_GAP_*` / `MARKET_VENDOR_GAP` / `MARKET_DISAGREE` as applicable

This guarantees ≥ 3 bullets for every rookie (1 + 2 + 3) without any historical feature.

## Ordering and selection

1. Evaluate every rule; collect candidates with their priority (#).
2. Force-include: `VALUE_SUMMARY`; the `MARKET_GAP_*` bullet when a flag is set; every bullet backing a fired signal (`rankings.signals`); every `T` tag bullet for a set flag/tag.
3. Fill remaining slots by priority up to `WHY_MAX_BULLETS = 6`. When forced bullets alone exceed 6, drop from the bottom of the priority list (never drop the forced set below the flag's own signal bullets; `VALUE_SUMMARY` is never dropped).
4. One bullet per `rule_id` per player; `ordinal` = final position 1..N.
5. Deterministic: same run inputs → identical rows (test on real fixtures).

## Examples (from the plan)

| text | rule_id | inputs |
|---|---|---|
| `Target share 24% → 28% (2024→2025)` | `OPP_TARGET_SHARE` | `{"target_share_2024": 0.24, "target_share_2025": 0.28}` |
| `2025 TDs 4.1 above expected under your scoring — regression risk` | `LUCK_TD` | `{"td_diff_2025": 4.1, "td_actual_2025": …, "td_expected_2025": …}` |
| `New play-caller (Davis Webb) — tag only` | `CTX_PLAY_CALLER` | `{"play_caller": "Davis Webb", "play_caller_new": true}` + `source_url` |
| `Missed 9 of 51 games 2023–25 (hamstring ×2) → E[games] 14.6` | `DUR_MISSED` | `{"games_missed": 9, "games_eligible": 51, "injury_events": [...], "e_games": 14.6}` |
| `Rookie: R1 #3 overall, RB1 on ARI depth chart (Aug 29)` | `ROOKIE_CAPITAL` | `{"draft_round": 1, "draft_pick": 3, "depth_rank": 1, "team": "ARI"}` + `as_of` = depth-chart `dt` |

## Storage row (per bullet)

```
run_id, player_id, ordinal, rule_id, template_version ("v1"), polarity,
text, metric_keys[], inputs{}, season_from, season_to, week_from, week_to,
snapshot_ids[], source_url, as_of
```

`template_version` is bumped whenever a template string or its input set changes; old rows keep rendering from their own version (the renderer keeps every version it has ever shipped).

## Tests (real fixtures with `PROVENANCE.md`)

- Render each rule from a hand-computed `inputs` dict and compare to the expected string (one fixture player per rule, extracted from real 2025 rows / real curated rows).
- Re-render 5 stored top-50 bullets from their referenced `snapshot_ids` and assert equality (gate).
- Rookie fixture (e.g. a 2026 R1 pick): historical rules return `None`, ≥ 3 bullets produced, no exception.
- Flag consistency: for every flagged player, every entry of `rankings.signals` has a matching bullet.
- Cap: no player has > 6 bullets; every top-100 player has ≥ 3.

## Checklist

- [ ] `why/rules.py`: one function per `rule_id` above, registered with priority and polarity.
- [ ] `why/render.py`: versioned templates; `render(rule_id, template_version, inputs) -> text`.
- [ ] `why/select.py`: forced set + priority fill + cap 6; deterministic ordering.
- [ ] Spec-default thresholds (#7, #8, #9, #10, #14, #15, #24) stored in `ranking_runs.weights`.
- [ ] Curated bullets carry `source_url` and `last_checked` → `as_of`.
- [ ] Fixture tests listed above pass; results recorded in `docs/phases/06-ranking-why.md`.
- [ ] Player drawer shows each bullet with its source / `as_of` (Phase 7).

## Gate

Phase 6: "Spearman(our overall rank, ECR) on top-150 ≥ 0.8; every top-100 player incl. rookies has ≥3 bullets; recompute 5 top-50 bullets from their referenced snapshots; unit tests for scoring, games-missed, VBD baselines/keeper holes, WHY rendering (real fixtures)."

## Derek's actions

- Day 7 top-200 sanity pass: flag bullets that read wrong or fire too often (the spec-default thresholds are tuned from this feedback).
- Day 9 curated-table re-check (ATL/LV/KC QB rooms, OL injuries, late signings) with source URLs — the context bullets (#20–#23) render straight from those rows.
