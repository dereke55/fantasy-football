# UI spec — Draft board

Purpose: what the Vite/React/TS dark-theme board shows and does on draft day (Board, Player drawer, draft-day controls, keeper entry, CSV export, keyboard), with the MVP / deferred / cut line drawn exactly as in the plan.

Status: Not started

Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` (Phase 7, Phase 8a, MVP cut line, Decisions). Data contract: `docs/spec/api.md`. Stack (plan): "Vite + React + TS, Tailwind + shadcn/ui (dark), TanStack Query/Table"; `frontend/` is already scaffolded (`pnpm dev`).

## 1. Scope and cut line

**MVP (day 6, Sat Sep 5 — "Board UI → MVP checkpoint")**: Board, Player drawer, draft-day controls, keeper entry form, CSV export, keyboard shortcuts, dark theme. If the draft lands early (≤ day 6) the plan pulls a **board-lite** (Board + mark drafted / my pick / undo / keeper entry, no drawer polish) into day 5 and drops WHY polish.

**Deferred (plan, Phase 7)**: "Team view, settings/curated editors, printable sheet, sparklines." Post-MVP tracks that touch the UI: display-only 2025 SoS columns ("proxy" label), sparklines/polish, Monte Carlo availability (8c) replacing the closed-form number, keeper-value helper output (day 7, delivered as a ranked list with WHY bullets — API/CLI first; a board panel only if time allows).

**Cut for this draft (plan)**: settings/curated editors (edit YAML + reload instead), printable sheet, any SoS multiplier or offense-environment score, news table, Sleeper trending. None of these get a placeholder in the UI.

**Team view: pulled back in (§5b).** It was cut as a nice-to-have, but Yahoo did not approve API access before the draft, so all ~159 picks are typed by hand while the clock runs. That makes silent desynchronisation — a missed pick, a double entry, a pick credited to the wrong team — the failure mode with no error attached to it, and every availability number downstream goes stale without complaint. The Teams tab exists to make that disagreement findable against Yahoo's own board in seconds.

## 2. Layout

Single page, dark, full-width. Three regions:

1. **Top bar** — draft status strip: `mode` (manual / Yahoo + fallback banner), on-the-clock (`R3 P23 · Team 3`), **"My next pick in N"** (from `pick_schedule`), picks made / total, run id + config hash (short) with a red badge if `/api/rankings` returned 409 `config_hash_mismatch`, and the CSV export button.
2. **Board** — the ranked table (§3). Left of it, a narrow filter rail: position chips (ALL / QB / RB / WR / TE / K / DST), preset chips (Sleepers / Busts), "hide drafted" toggle (default off: drafted rows are dimmed, not removed), search box.
3. **Right panel** — tabs: **Draft** (draft-day controls, §5), **Teams** (all ten rosters + drift check, §5b), **Keepers** (entry form, §6). The **Player drawer** (§4) slides over the right panel when a row is selected.

Board fills the viewport height and virtualizes rows (TanStack Table + a row virtualizer) so the Phase 7 gate "400 players render < 2 s" holds with the drawer open.

## 3. Board

Columns, in this order (plan, Phase 7, verbatim list: "rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags"):

| # | Column | Source field (`/api/rankings`) | Notes |
|---|---|---|---|
| 1 | Rank | `rank` | overall; `pos_rank` shown as small suffix (`RB3`) |
| 2 | Tier | `tier` | GMM ECR tier; drives tier bands |
| 3 | Value tier | `value_tier` | projection drop-off tier; cliffs use this |
| 4 | Pos | `pos` | color chip per position |
| 5 | Team | `team` | |
| 6 | Bye | `bye` | highlighted when it matches a bye already stacked on my roster |
| 7 | Proj PPG / season | `proj_ppg`, `proj_season` | two numbers in one cell: `21.4 · 318` ; tooltip shows `E[games]` |
| 8 | Value | `value` | keeper-aware VOLS; K/DST show `—` (VBD 0) |
| 9 | ECR | `ecr` (± `ecr_sd` in tooltip) | |
| 10 | Yahoo ADP | `adp_yahoo_site` | header reads "Yahoo ADP (site-wide)" — labeled as such per plan |
| 11 | Room ADP | `room_adp` | keeper-adjusted; raw and room shown side by side (10 vs 11) |
| 12 | Gap | `gap` (± `gap_z` tooltip) | signed picks; green ≥ +6, red ≤ −6 |
| 13 | P(avail) | `p_avail` | percent at my next pick; `—` until a draft slot is set |
| 14 | Flags | `flags` + `tags` | icon chips: sleeper, bust, injury_prone, structural_injury_return, rookie, new_play_caller, qb_uncertain_team |

Behavior:
- **Tier bands**: a horizontal rule + tier label whenever `tier` changes while sorted by rank (or by position rank when a position filter is on). Value-tier boundaries are a subtle dashed rule.
- **Drafted dimmed**: rows with `drafted: true` render at reduced opacity with strike-through name and the drafting slot (`→ T3`); keepers show a `K` badge; my picks show a filled marker.
- **Presets as filters**: Sleepers = `flags` contains `sleeper`; Busts = `flags` contains `bust`; positional = `pos`. Presets combine with position filter; they are the only saved views in MVP.
- Sorting: any column; default rank ascending. Sorting is client-side on the full 400-row payload — no round trip.
- Selection: click or **j/k** moves the highlight; Enter/click opens the drawer.
- Best available: the top undrafted row under the current filter is outlined; its `p_avail` and `vona` (from `/api/availability`) are echoed in the Draft tab.
- Every number rendered is from the pinned run; the board never computes points itself and never shows vendor points.

## 4. Player drawer

Opens for the highlighted row. Contents (plan: "WHY bullets with source/as_of, 3-season PPG line, key metrics, tags"):

1. Header: name, pos/team/bye, rank / tier / value tier, flags + tags as chips, drafted/keeper state, buttons **Drafted (d)** and **My pick (m)**.
2. **WHY** — the ordered `why[]` bullets (≤ ~6). Each bullet shows the template text, and beneath it in muted small type the source label + `as_of` (e.g. `nflverse stats_player_week · 2026-08-26`), with the `source_url` as a link and the `rule_id` in a tooltip. Bullets are the deterministic rule output — no free text, no LLM.
3. **3-season PPG line** — `ppg_by_season` (2023–2025) as a simple 3-point line with games as labels; seasons where `same_team_role` is false are drawn hollow. Rookies show "No NFL history — rookie" instead of the line.
4. **Key metrics** grid: opportunity (targets/g, target share, air-yards share, WOPR, carries/g, trend), luck (TD diff, PPG diff under league scoring), durability (missed / eligible, causes, `E[games]`, known missed weeks), consistency for 2025 (mean / SD / floor p25 / ceiling p90 / starter weeks), projection blend (Sleeper PPG under league scoring, in-house PPG, weights, age step).
5. **Market** table: one row per `rank_snapshots.source` (`fantasypros_mirror`, `yahoo_pub` — displayed as "Yahoo (site-wide)", `ffc`, `sleeper`) with rank/ADP, sd, best/worst or high/low, `as_of`.
6. **Team context**: the three curated rows for the player's team with `confidence` and `last_checked`, each with its `source_url`.

Sparklines (weekly points) are **deferred** — the 3-point season line is the MVP chart.

## 5. Draft-day controls (right panel, Draft tab)

Plan: "mark drafted, my pick, undo, 'my next pick in N' from `pick_schedule`, VONA top-3 per position, bye-stack warning (≥3 projected starters sharing a bye; 2026 week 11 has six teams)".

- **Mark drafted** — `POST /api/draft/picks {player_id}` for the highlighted player; fills `on_the_clock`. Confirmation is implicit; the Undo button is the safety net.
- **My pick** — `POST /api/draft/picks {player_id, my_pick: true}`.
- **Undo** — `POST /api/draft/undo`; disabled when the response would be 409 (nothing to undo / last pick came from Yahoo).
- **My next pick in N** — `picks_until_mine` and `my_next_pick` from `DraftState`; large type; updates after every mutation and every SSE event (8b).
- **On the clock** — slot + round/pick, from `DraftState.on_the_clock`.
- **VONA top-3 per position** — from `/api/availability.vona`: for each of QB/RB/WR/TE (and K/DST from round 12) the top 3 candidates with `value_now`, `expected_value_at_next`, `vona`, and `p_avail`; clicking a row highlights it on the board. Weighted by my open slots (open starter → full VBD, bench only → 0.5×) — the weight is shown so the number is explainable.
- **My roster** — slot grid (QB/RB/RB/WR/WR/TE/FLEX/K/DST/BN… from league.yaml) pre-populated with my keepers; open slots highlighted.
- **Bye-stack warning** — from `DraftState.bye_stack_warnings`: a yellow banner "3 projected starters share bye 11" listing the players; also colors the Bye column for that week.
- **Manual mode is first-class**: every control works identically whether `mode` is `manual` or `yahoo`; in `yahoo` mode the controls are still enabled (a manual pick is a correction that the next poll reconciles).
- After every mutation the panel and the board re-render from the returned `state` and a refetch of `/api/rankings` + `/api/availability` — no page reload (Phase 7 gate).

## 5b. Teams (right panel, Teams tab)

The defence against silent drift in a hand-entered draft. Everything is derived from endpoints that already exist; no
new backend route.

- **Drift check header** — picks recorded / `total_picks`, what the snake says is next (`R2 P13 · T8`), the keeper
  count, and then either "All 10 teams match the snake" in green or, in red, one line per offending team: `T4 has 3,
  expected 4 — 1 missing (a pick of theirs recorded on another team?)`. A **Yahoo picks made** input is the one
  external fact the app cannot derive; entering it reports "we are 2 picks behind — a pick was missed". Drift also
  shows as a `⚠` on the Teams tab itself, so it is visible from the Draft tab.
- **Per team**, all ten slots, mine highlighted: the players taken in pick order with round/pick, position chip, name,
  NFL team, and a `K{cost_round}` badge for keepers; a compact tally of starters filled against `league.slots`
  (`QB 0/1 RB 2/2 WR 1/3 …` plus `BN n/6`), open slots called out — and on my own row, an unmissable `OPEN QB · WR×2 ·
  FLEX · K · DST` chip. A pick whose recorded team differs from the team the snake gave that pick to carries a `≠T7`
  badge on the row itself.
- **Derivation** (`frontend/src/lib/teamsModel.ts`): `POST /api/draft/picks` always stamps a pick with
  `on_the_clock(schedule, picks_made)` and only ever appends, so the n-th surviving `draft_picks` row is the n-th live
  slot of the schedule. Sorting the drafted `/api/rankings` rows by `pick_id` and walking them against
  `live_pick_no = 1, 2, 3 …` recovers round and overall pick for every team. The owner is `drafted_by` (the *stored*
  slot, which the "for team" override can make differ from the scheduled slot — exactly the mis-attribution being
  hunted). Keepers are not `draft_picks` rows: they come from `/api/keepers` and are placed at the `is_keeper_slot`
  hole the schedule cut for that (team, cost round), so they appear before the draft starts.
- Clicking any player highlights him on the board (the same selection mechanism as VONA and Best available).

## 6. Keeper entry (right panel, Keepers tab)

Plan: "**Keeper entry** form (team_slot, player, cost_round)".

- Form: `team_slot` select (1–10, labeled with team names from league.yaml or the Yahoo draft order once known), player search (typeahead over `/api/rankings` names, shows pos/team), `cost_round` select (1..rounds), `status` (`declared` / `approved` — the `keepers.status` values in `docs/spec/data-model.md`; `removed` is what DELETE sets). Submit → `POST /api/keepers`.
- List below the form grouped by team slot, each row editable inline (`PUT`) or removable (`DELETE`), with `source` badge (manual / yahoo).
- Every change recomputes baselines, `pick_schedule`, room ADP and P(avail) server-side; the board re-renders from the returned `state` (Phase 7 gate: "keeper edits recompute best-available and P(avail) without reload").
- Validation surfaces the API's 409 reasons verbatim (duplicate round for a team, player already kept, max keepers exceeded).
- Shows `max_keepers` and the keeper deadline (day-1 input 4) at the top of the tab.

## 7. CSV export

Top-bar button → opens `GET /api/export/board.csv` (current position/preset filter passed through). The file has the §3 columns plus `name`, `player_id`, `yahoo_id`, `run_id`. This is the draft-day-minimum fallback if the board is unusable: the CSV plus `curl` against the picks API is a complete draft-day workflow.

## 8. Keyboard shortcuts

Plan: "Keyboard j/k, d = drafted, m = my pick."

| Key | Action |
|---|---|
| `j` / `k` | move highlight down / up one row (skips nothing; drafted rows are still navigable) |
| `d` | mark highlighted player drafted (`POST /api/draft/picks`) |
| `m` | mark highlighted player as my pick (`POST /api/draft/picks … my_pick: true`) |
| `Enter` | open / close the Player drawer for the highlighted row |
| `Esc` | close the drawer |
| `u` | undo last manual pick *(impl detail; same as the Undo button)* |
| `/` | focus the search box *(impl detail)* |

Shortcuts are disabled while focus is in a text input. `d` and `m` never prompt; Undo is the recovery path.

## 9. Dark theme and visual rules

- Tailwind + shadcn/ui with the `dark` class on `<html>`; there is no light theme in MVP.
- Position colors (chips only, never row backgrounds): QB, RB, WR, TE, K, DST each get one hue; flags use icons + a short label, never color alone.
- Numeric columns are right-aligned, tabular figures; one decimal for PPG/ECR/ADP, integers for season points and gap, percent for P(avail).
- Density: compact rows (≈ 32 px) so ~30 rows are visible at 1080p with the panel open.
- Data provenance is always one hover away: run id/config hash in the top bar, `as_of` under every WHY bullet, `source` on every market row.
- Attribution footer (README licensing table): nflverse CC-BY-4.0, FFC, "Fantasy data provided by Yahoo Fantasy", FantasyPros personal use.

## 10. Data fetching

- TanStack Query keys: `['run']`, `['rankings', filters]`, `['player', id]`, `['schedule']`, `['state']`, `['availability']`, `['keepers']`, `['team_context']`.
- Rankings are fetched once per run (staleTime: infinity) and invalidated only by a mutation or a new pinned run; `state` and `availability` are invalidated after every mutation; in 8b the SSE `state`/`pick` events invalidate them too.
- 409 `config_hash_mismatch` → the board shows a blocking banner "League config changed since the frozen run — re-freeze from the CLI" and keeps the last good table on screen.
- 503 (no pinned run) → empty state with the CLI command to run.

## 11. Checklist

- [ ] `pnpm dev` renders the dark shell with top bar, board, right panel, no console errors
- [ ] Board renders all 14 columns in the §3 order from a real `/api/rankings` payload of ≥400 rows
- [ ] Measured with the React profiler / `performance.now()`: initial render of 400 rows completes in < 2 s on Derek's machine (Phase 7 gate)
- [ ] Tier bands appear at every `tier` change when sorted by rank; value-tier rules appear at every `value_tier` change
- [ ] Position chips, Sleepers and Busts presets filter the table client-side without a request
- [ ] Drafted rows are dimmed with the drafting slot shown; keepers show `K`; "hide drafted" toggle removes them
- [ ] Pressing `d` on a highlighted player posts the pick, dims the row, advances "on the clock" and "my next pick in N" without a reload
- [ ] Pressing `m` records the pick to my slot and the player appears in the My roster grid
- [ ] Undo restores the row, the roster and the previous `p_avail` values without a reload
- [ ] Adding a keeper via the form marks the `(round, team_slot)` slot in the pick grid and changes `picks_until_mine` and `p_avail` without a reload (Phase 7 gate)
- [ ] Bye-stack warning appears when 3 projected starters share a bye (test with three week-11 players)
- [ ] VONA panel shows top 3 per position for QB/RB/WR/TE and hides K/DST before round 12
- [ ] Player drawer shows ≥3 WHY bullets, each with source label and `as_of`, for a top-100 veteran and for a rookie
- [ ] 3-season PPG line renders for a veteran; rookie shows the "No NFL history" state
- [ ] CSV export button downloads a file whose header matches §3 columns plus `name`, `player_id`, `yahoo_id`, `run_id`
- [ ] Teams tab lists all 10 rosters in pick order with keepers present before pick 1, and my open starter slots called out
- [ ] Recording a pick for the wrong team (Draft tab "for team" override) turns the drift check red for both the team that gained the pick and the team that lost it, and badges the row `≠T{slot}`
- [ ] `j`/`k`/`Enter`/`Esc` work and are ignored while typing in the search or keeper form
- [ ] Config-hash mismatch (409) shows the blocking banner and does not blank the table
- [ ] No vendor fantasy-points field is referenced anywhere in `frontend/src` (grep `pts_ppr|pts_half_ppr|pts_std`)
- [ ] Day 9 dry run: scripted pick feed in real Yahoo-ADP order drives the board end to end (undo, keeper holes in pick counts, P(avail)/VONA updates, CSV)

## Gate

Phase 7: "400 players render < 2 s; drafted/undo/keeper edits recompute best-available and P(avail) without reload."

## Derek's actions

- Provide the draft slot (day-1 input 3) — until then P(avail), "my next pick in N" and VONA show as unavailable.
- Provide roster slots + bench count (day-1 input 2) so the My roster grid and open-slot weighting match the league.
- Enter the keeper list through the Keepers tab (or the API) when it is known; confirm it before the Yahoo keeper deadline.
- Day 7 (Sun Sep 6): ~2 h top-200 sanity pass by position using the board and drawer; report wrong-looking rows.
