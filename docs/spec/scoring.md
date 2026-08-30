# Scoring

`config/league.yaml` schema, the canonical stat keys, the Yahoo `stat_id` map, the fractional/negative flags, and how one `score()` function is applied to historical, expected and projection stat lines.

Status: Not started

Source of truth: `docs/PLAN.md` Phase 2 (day 2) plus the "Day-1 inputs" section. Vendor fantasy-point columns are **never surfaced**; every point shown anywhere in the app comes from `score()` under this league's config.

## Where the config comes from

- Day-1 input #1: the **scoring table copied from Yahoo League → Settings** (incl. fractional points on/off, negative points on/off, yardage bonuses). Until it lands, `config/league.yaml` carries Yahoo default public-league scoring with its `source_url` and is labelled as such (`source: yahoo_default_public_league_scoring`).
- When the real table lands: `source: yahoo_settings_page`, `as_of: <date>`. Every derived number recomputes on change (the `league_config_hash` in `ranking_runs` changes; the frozen `draft_snapshot` refuses to serve until an explicit re-freeze).
- Phase 8b (only if Yahoo access is approved): the raw `league/{key}/settings` payload is diffed against `league.yaml` — **diff-only report; never overwrites `league.yaml`**.
- No K/DST scoring in MVP (K and DST are ranked by consensus ADP only; VBD 0).

## `config/league.yaml` schema

Matches the file already scaffolded in the repo.

```yaml
source: yahoo_default_public_league_scoring   # → yahoo_settings_page once Derek's table lands
source_url: https://help.yahoo.com/kb/SLN6448.html   # record the page the values were copied from
as_of: 2026-08-29
league:
  platform: yahoo
  league_key: null            # {game_key}.l.{league_id}, e.g. 470.l.12345 (2026 game_key 470; from the league URL) — DAY-1 INPUT
  num_teams: 10
  draft_type: snake
  draft_datetime: null        # ISO 8601 local, before 2026-09-10 — DAY-1 INPUT
  my_draft_slot: null         # 1..10, or null if not yet assigned (late-bound)
  keepers:
    max_per_team: null        # DAY-1 INPUT
    cost_rule: round_drafted  # keeper occupies the round drafted last year; team skips that round
    deadline: null            # Yahoo: managers declare >= 1 hour before draft; commissioner approves
    assigned_in_yahoo: null   # true once the commissioner has run "Assign Keeper Players"
roster:
  slots: { QB: 1, RB: 2, WR: 3, TE: 1, FLEX: 1, K: 1, DEF: 1 }   # standard 1-QB; DAY-1 INPUT #2
  flex_eligible: [RB, WR, TE]
  bench: 6                    # DAY-1 INPUT #2
  ir: 0
scoring:
  uses_fractional_points: true
  uses_negative_points: true
  # points per unit; yardage keys are per yard (25 yds/pt = 0.04)
  pass_yd: 0.04
  pass_td: 4
  pass_int: -1
  pass_2pt: 2
  rush_yd: 0.1
  rush_td: 6
  rush_2pt: 2
  rec: 0.5
  rec_yd: 0.1
  rec_td: 6
  rec_2pt: 2
  fum_lost: -2
  ret_td: 6
  bonuses: []               # e.g. {stat: pass_yd, threshold: 300, points: 2}
  position_overrides: {}    # e.g. {TE: {rec: 1.0}} — not used (no TE premium)
```

Field rules:

| key | type | rule |
|---|---|---|
| `source`, `source_url`, `as_of` | str, url, date | required; `source` is copied into `ranking_runs.league_config_source` |
| `league.num_teams` | int | 10 |
| `league.draft_type` | enum | `snake` only in MVP |
| `league.my_draft_slot` | int/null | late-bound; null allowed until assigned |
| `roster.slots` | map pos→int | starters per position; `FLEX` uses `flex_eligible` |
| `roster.bench` | int | bench count (feeds the VORP "typical bench share") |
| `scoring.<stat_key>` | number | points per unit of the canonical stat key; missing key = 0 |
| `scoring.bonuses[]` | list | `{stat, threshold, points}`: `points` awarded once per player-game when `stat ≥ threshold` (Yahoo yardage bonuses) |
| `scoring.position_overrides` | map | per-position override of any stat key (empty; no TE premium) |
| `scoring.uses_fractional_points` | bool | see "Flags" |
| `scoring.uses_negative_points` | bool | see "Flags" |

The config hash is `sha256` of the YAML canonicalised (sorted keys, no comments) so a comment edit does not invalidate a freeze.

## Canonical stat keys

`score()` only understands these keys. Every input line is translated to them first.

| key | meaning | historical (`player_week_stats`, nflverse `stats_player_week`) | expected (`player_expected_stats`, ffopportunity `ep_weekly`) | projection (`projections.stat_line`, Sleeper) |
|---|---|---|---|---|
| `pass_yd` | passing yards | `passing_yards` | `pass_yards_gained_exp` | `pass_yd` |
| `pass_td` | passing TDs | `passing_tds` | `pass_touchdown_exp` | `pass_td` |
| `pass_int` | interceptions thrown | `passing_interceptions` | — (no expected; see rule E1) | `pass_int` |
| `pass_2pt` | passing 2-pt conversions | `passing_2pt_conversions` | — | `pass_2pt` (when present) |
| `rush_yd` | rushing yards | `rushing_yards` | `rush_yards_gained_exp` | `rush_yd` |
| `rush_td` | rushing TDs | `rushing_tds` | `rush_touchdown_exp` | `rush_td` |
| `rush_2pt` | rushing 2-pt | `rushing_2pt_conversions` | — | `rush_2pt` (when present) |
| `rec` | receptions | `receptions` | `receptions_exp` | `rec` |
| `rec_yd` | receiving yards | `receiving_yards` | `rec_yards_gained_exp` | `rec_yd` |
| `rec_td` | receiving TDs | `receiving_tds` | `rec_touchdown_exp` | `rec_td` |
| `rec_2pt` | receiving 2-pt | `receiving_2pt_conversions` | — | `rec_2pt` (when present) |
| `fum_lost` | fumbles lost | `rushing_fumbles_lost + receiving_fumbles_lost + sack_fumbles_lost` (= `fumbles_lost_total`) | — | `fum_lost` |
| `ret_td` | kick/punt return TDs | `special_teams_tds` | — | not provided → 0 |

Translation rules:

- **E1 (expected lines)**: keys with no `_exp` counterpart (`pass_int`, `*_2pt`, `fum_lost`, `ret_td`) take the **actual** value on the expected line, so they cancel in `score(actual) − score(expected)`. Luck therefore measures yardage/TD/reception luck only.
- **P1 (projections)**: `stats.gp` is **never used** (constant 18). Any key absent from the vendor line is 0. K/DEF keys (`fgm_*`, `xpm`, `sack`, `int`, `pts_allow_*`) are stored and not scored in MVP.
- **H1 (historical)**: only `season_type = 'REG'` rows feed features; POST rows are stored and never scored into totals.
- Counting stats are stored raw; `score()` is the only place points are produced.

## Yahoo `stat_id` map

Used only to (a) label the day-1 paste and (b) run the 8b settings diff. The ids the plan lists are the verified core; the rest are expected and must be confirmed from the raw `league/{key}/settings` payload (`stat_categories[].stat_id`, `stat_modifiers[].value`) before the diff trusts them.

| stat_id | Yahoo name | canonical key | status |
|---|---|---|---|
| 4 | Passing Yards | `pass_yd` (Yahoo gives "per N yards" → points/yard = `1/N`) | verified (plan) |
| 5 | Passing Touchdowns | `pass_td` | verified (plan) |
| 6 | Interceptions | `pass_int` | verified (plan) |
| 9 | Rushing Yards | `rush_yd` | verified (plan) |
| 10 | Rushing Touchdowns | `rush_td` | verified (plan) |
| 11 | Receptions | `rec` | verified (plan) |
| 12 | Receiving Yards | `rec_yd` | verified (plan) |
| 13 | Receiving Touchdowns | `rec_td` | verified (plan) |
| 18 | Fumbles Lost | `fum_lost` | verified (plan) |
| 15 | Return Touchdowns | `ret_td` | expected — confirm from payload |
| 16 | 2-Point Conversions | `pass_2pt` / `rush_2pt` / `rec_2pt` (Yahoo uses one category; all three keys get the same value) | expected — confirm from payload |
| 17 | Fumbles (total) | not scored in MVP unless the league uses it | expected — confirm from payload |
| 57 | Offensive Fumble Return TD | not scored in MVP unless the league uses it | expected — confirm from payload |
| K / DEF ids (19–23, 29–30, 31–36, 45–56 …) | kicking / team defense | none (K/DST unscored in MVP) | out of scope |

Settings payload fields used by the diff: `stat_categories[{stat_id, name, display_name, position_type}]`, `stat_modifiers[{stat_id, value}]`, `uses_fractional_points`, `uses_negative_points`, `roster_positions[{position, count}]`, `draft_time`. Any `stat_id` in the payload that is not in this map is reported as `unmapped` in the diff output.

## Flags

- `uses_fractional_points: true` → points are exact decimals (e.g. 0.04/yd → 237 yds = 9.48).
- `uses_fractional_points: false` → Yahoo awards whole points per category: each yardage category contributes `floor(yards / N)` points (e.g. 237 yds at 25 yds/pt = 9). Implementation default: truncate toward zero **per stat category per player-game**; the exact Yahoo behaviour is confirmed by the Phase 2 gate (recompute 2025 totals against the league's pages) and the fixture tests.
- `uses_negative_points: true` → a player-game total may be negative (e.g. 2 INT, 0 yards = −2).
- `uses_negative_points: false` → a player-game total is floored at 0 after all categories are summed. Per-category negatives (INT, fumbles lost) still subtract before the floor.
- Both flags are applied inside `score()` so every caller (historical, expected, projection) behaves identically. Both paths are unit-tested on **real fixture rows** (Phase 2 gate).

## `score(stat_line, scoring) -> points`

```
score(line, cfg, position=None):
    pts = 0
    for key, per_unit in cfg.effective(position).items():   # position_overrides merged
        v = line.get(key, 0)
        if key is yardage and not cfg.uses_fractional_points:
            pts += trunc(v / (1 / per_unit)) * 1          # whole points per N yards
        else:
            pts += v * per_unit
    for b in cfg.bonuses:
        if line.get(b.stat, 0) >= b.threshold: pts += b.points
    if not cfg.uses_negative_points: pts = max(pts, 0)
    return pts
```

Properties (tested): pure, deterministic, key-order independent; unknown keys ignored; `score({}) == 0`; `score(a + b) == score(a) + score(b)` when both flags are true (linear), and the non-linear cases (truncation, floor, bonuses) are only ever applied at the **player-game** grain.

### Applied uniformly to three line types

| line type | grain | used for |
|---|---|---|
| historical weekly (`player_week_stats`, REG only) | player-game | PPG, positional PPG rank, YoY deltas, trend, consistency (mean/SD/floor/ceiling), starter threshold |
| expected weekly (`player_expected_stats`) | player-game | luck = `score(actual) − score(expected)`; `td_diff`, `ppg_diff` |
| projection season line (`projections.stat_line`) | season total | vendor PPG = `score(line) / 17` (or `/ (17 − known_missed_weeks)` when IR/PUP/Out or in `known_missed_weeks`) — see `docs/spec/ranking-model.md` |

Season totals for the gate = `Σ_weeks score(week_line)` over REG weeks 1–18 (never `score(Σ weeks)` when a non-linear flag is on).

## Validation

- Phase 2 gate (below): 5 named players' 2025 totals recomputed from `player_week_stats` under the real scoring must match the totals on the Yahoo league's 2025 pages.
- Fixture tests: real 2025 rows (with `PROVENANCE.md`) covering a multi-INT game, a fumble-lost game, a 2-pt conversion, a return TD, a yardage-bonus threshold, and a negative-total game — each asserted under both flag settings.
- 8b diff: `stat_modifiers` → points/unit compared to `league.yaml`; mismatches and unmapped ids printed; exit non-zero on mismatch; file untouched.

## Checklist

- [ ] `config/league.yaml` validated by a Pydantic model on load (unknown keys rejected, required keys present).
- [ ] `scoring.score()` implemented with the canonical keys, `bonuses`, `position_overrides`, both flags.
- [ ] Translators: `from_week_stats(row)`, `from_expected(row)` (rule E1), `from_sleeper(stat_line)` (rule P1).
- [ ] Yahoo `stat_id` map module with `verified`/`expected` status per id; diff tool reports `unmapped`.
- [ ] Fixture tests on real 2025 rows for fractional on/off and negative on/off.
- [ ] 2025 season totals for 5 named players recomputed and compared to the Yahoo league's 2025 pages; result recorded in `docs/phases/02-scoring.md`.
- [ ] `league_config_hash` computed from canonicalised YAML and stored on every `ranking_runs` row.

## Gate

"recompute 2025 season totals for 5 named players under the real scoring and match the totals on the Yahoo league's 2025 pages; fractional/negative tests on real fixture rows."

## Derek's actions

- Paste the scoring table from Yahoo League → Settings (incl. fractional points on/off, negative points on/off, yardage bonuses) — day-1 input #1; blocks Phase 2.
- Provide roster slots + bench count (day-1 input #2).
- Name the 5 players (or let the tool pick 5 top-50 players) and read their 2025 totals off the Yahoo league's 2025 pages for the gate.
