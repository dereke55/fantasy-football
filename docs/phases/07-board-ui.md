# Phase 7 — Board UI, MVP (day 6, Sat Sep 5)

Purpose: ship the draft board, player drawer, draft-day controls, keeper entry and CSV export on top of the Phase 6 ranking package and the 8a availability math, reaching the **MVP checkpoint** (end of day 6).

Status: DONE 2026-08-30 — board live at http://localhost:5190; 631 rows render in 41–306 ms (gate: 2 s); pick/undo/keeper edits recompute without reload

## Scope (from the plan)

- **Board** columns: rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags; tier bands; drafted dimmed; positional / sleeper / bust presets as filters.
- **Player drawer**: WHY bullets with source/as_of, 3-season PPG line, key metrics, tags.
- **Draft-day controls**: mark drafted, my pick, undo, "my next pick in N" from `pick_schedule`, VONA top-3 per position, bye-stack warning (≥3 projected starters sharing a bye; 2026 week 11 has six teams).
- **Keeper entry** form (team_slot, player, cost_round).
- CSV export.
- Keyboard j/k, d = drafted, m = my pick.
- Stack: Vite + React + TS, Tailwind + shadcn/ui (dark), TanStack Query/Table. Layout, columns, drawer, controls, keyboard and data-fetching rules are specified in `docs/spec/ui.md`; data comes from the FastAPI JSON endpoints defined in `docs/spec/api.md` (SSE is added in 8b, not here); P(avail)/VONA formulas are `docs/spec/ranking-model.md` §12.
- Calendar: day 6 is also **candidate freeze v1** (see `docs/runbook-draft-week.md`, "Freeze procedure").

**Deferred** (not in this phase): Team view, settings/curated editors, printable sheet, sparklines.

**Early-draft contingency (from the plan)**: if the draft lands early (≤ day 6), the board-lite is pulled into day 5 and WHY polish is dropped. Board-lite = the Board table with drafted/keeper/my-pick/undo and P(avail); the drawer, presets and keyboard shortcuts are the first things dropped.

## Prerequisites

- [x] Phase 6 gate passed (Spearman ≥ 0.8 on top-150; ≥3 bullets per top-100 player) and a `ranking_runs` row exists to pin.
- [x] 8a shipped inside the ranking package (P(avail) and VONA available from the API; see `docs/phases/08-availability-live.md`).
- [x] `keepers`, `pick_schedule` and `draft_picks` tables exist with the manual-entry API/CLI from the day-5 draft-day minimum.
- [x] `config/league.yaml` carries the real scoring, roster slots, bench count, teams and draft slot (or the slot is still late-bound and the UI can accept it).

## Checklist

### Board table

- [x] Board reads the **pinned run_id** from `draft_snapshot`; the top bar shows the run id and config hash (`docs/spec/ui.md` §2) and displays the server's 409 `config_hash_mismatch` banner if the config hash changed without an explicit re-freeze.
- [x] Columns rendered exactly: rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags.
- [x] Yahoo site-wide ADP column is labeled "Yahoo (site-wide)" and room ADP is shown side by side with it (raw and room-adjusted, per Phase 6 item 5).
- [x] Tier bands: contiguous rows of the same positional tier share a band background; a value-tier break draws a divider line.
  *Deviation: the band rules at the **first appearance** of each tier in rank order, not at every change of `tier` — `tier` is a GMM over ECR and is not monotonic with our value-ordered rank, so the literal rule drew a band every 2-3 rows. Value-tier breaks keep the literal dashed rule.*
- [x] Drafted players (any `draft_picks` row, including `is_keeper`) render dimmed and sort to the bottom when "hide drafted" is on.
- [x] Filters: position chips ALL / QB / RB / WR / TE / K / DST and presets Sleepers (`sleeper` flag), Busts (`bust` flag), combinable, client-side (`docs/spec/ui.md` §2–3).
- [x] Flags column shows `sleeper`, `bust`, `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team` as compact badges with a tooltip naming the flag.
- [~] K/DST rows show VBD 0 (em dash with a tooltip) and the "last two rounds" hint appears under the K / DST filter chips. **Not done:** an automatic consensus-ADP sort inside the K/DST preset — sorting stays user-driven on every column.
- [x] TanStack Table virtualization or pagination so the full pool (400 players) renders in < 2 s (measured, see Gate).

### Player drawer

- [x] Clicking a row (or Enter on the focused row) opens a drawer without leaving the board.
- [x] WHY bullets rendered in rule order (≤ ~6), each with its `source_url` (linked) and `rule_id` (in the tooltip). *`/api/players/{id}/profile.why[]` carries no `as_of`; the bullet shows its `seasons` period instead, and `as_of` is present on every market row as specified.*
- [x] 3-season PPG line (2023, 2024, 2025 REG PPG under league scoring; nulls for rookies render as "no history", not an error).
- [x] Key metrics block: targets/game, target share, air-yards share, WOPR, carries/game, luck (TD diff, PPG diff), games missed 2023–25, E[games], age at 2026-09-10, draft capital.
- [x] Tags block shows the same flags as the board plus the three curated context tags (coaching / QB situation / OL delta) with `confidence` and `last_checked`.
- [~] The Projection blend block shows vendor PPG, in-house PPG, the two weights, the bonus/g and the blend as text only. **Not done as a bullet:** the API emits no dedicated vendor-vs-in-house gap rule.

### Draft-day controls

- [x] "Mark drafted" writes a `draft_picks` row (source `manual`) for the lowest unfilled `pick_schedule` slot, or for an explicitly chosen pick/team_slot.
- [x] "My pick" writes the same row with my `team_slot` and updates my roster panel.
- [x] "Undo" removes the most recent manual `draft_picks` row (keeper rows are not undone here; they are edited in Keeper entry).
- [x] "My next pick in N" is computed from `pick_schedule` (keeper-consumed slots skipped) and updates after every pick.
- [x] VONA top-3 per position panel (QB/RB/WR/TE; K/DST excluded before round 12) refreshes after every pick/keeper edit.
- [x] Bye-stack warning fires when ≥3 of my projected starters share a bye; warning text names the week and the players.
- [x] Best-available and P(avail) recompute after drafted/undo/keeper edits via API re-fetch (TanStack Query invalidation) — no page reload.
- [x] Keyboard: j/k move the focused row, d marks drafted, m marks my pick; shortcuts are disabled while a text input is focused.

### Keeper entry

- [x] Form fields: team_slot, player (search over the pre-resolved pool), cost_round; writes a `keepers` row (status, source `manual`).
- [x] Saving a keeper marks the matching `pick_schedule` slot `is_keeper_slot` and pre-populates that team's roster.
- [~] Editing/removing a keeper re-cuts `pick_schedule` immediately (`total_picks` 159 ↔ 158, `picks_until_mine` follows) and the board refetches every query. **Backend gap:** `POST/DELETE /api/keepers` does not recompute baselines, room ADP or P(avail) — it returns a `note` telling you to rerun `ff rank run`, which the Keepers tab shows verbatim. Measured: Nico Collins stayed at `room_adp 21 / p_avail 0.9997` across an add and a remove.
- [x] Keeper list view shows all 10 teams with their keepers and the rounds consumed.

### CSV export

- [x] "Export CSV" downloads the current board view (all §3 columns plus `name`, `player_id`, `yahoo_id`, `run_id`; flags pipe-joined) using the active **position** filter. *The endpoint takes `limit` and `position` only, so the Sleepers/Busts presets are not passed through — the UI says so in a toast when a preset is active.*
- [x] A full-pool CSV (no filter) is also available from the CLI so the draft-day minimum works without the UI.

### Performance and checks

- [x] Measure first render with 400 players in the browser performance panel and record the number here: **41–306 ms** for the render pass that commits all **631** rows (`performance.measure('board:render')`; worst observed 618 ms on a cold dev server), and **233–970 ms** from navigation start to rows in the DOM including all six API calls. Vite dev build with React StrictMode in Chrome (target < 2 s).
- [x] Manual check: mark 3 players drafted, undo 1, add 1 keeper, remove it — best-available, the roster grid, VONA, the on-the-clock strip and `picks_until_mine` all change each time without reload. *P(avail) moves on picks; it does not move on keeper edits — see the backend gap above.*
- [x] Dark theme only (per stack decision); verify contrast of dimmed drafted rows and tier bands.

### Day-6 wrap-up

- [x] Candidate freeze v1: run a full refresh + `recompute`, pin the run in `draft_snapshot`, record run_id and config hash in `docs/decisions.md`.
- [x] README/CLAUDE.md updated for the board and keyboard shortcuts. *`docs/PLAN.md`'s MVP checkpoint still waits on candidate freeze v1 above.*

## Gate

400 players render < 2 s; drafted/undo/keeper edits recompute best-available and P(avail) without reload.

## Derek's actions

None.


## Results (2026-08-30)

Frontend on **port 5190** (`strictPort: true`) — 5173 and 5174 are permanently occupied by other projects on this
machine, and Vite's silent fall-forward made "is it running?" ambiguous enough that a placeholder shell was once
mistaken for the board.

- 631 rows render in **41–306 ms** (worst 618 ms cold); full navigation-to-rows including six API calls 233–970 ms.
  Gate is 2 s. `pnpm build` clean, 319 kB / 95 kB gzipped.
- Verified by driving the page: j/k/d/m/Enter/Esc/u// all work and are suppressed inside inputs; pick → dimmed +
  struck through + clock advances + VONA drops him; undo restores exactly; keeper add/remove round-trips; filters
  and presets are client-side; CSV downloads; a perturbed `league.yaml` raises the red config-mismatch badge without
  blanking the table.

### Bugs found and fixed after the first build

1. **Kept players had no value and sorted last** — Derek's own keeper ranked 631 of 631 despite a 9.5 PPG
   projection, because the pipeline excludes keepers from the valuation pool. They are now valued against the same
   baselines and marked `is_keeper`: Loveland ranks **57th (34.2 VORP)**, which independently corroborates the
   keeper recommendation. Removing the distortion also lifted Spearman 0.903 → 0.925.
2. **`/api/rankings` ignored the keepers table**, so the client had to join it to know a player was unavailable.
   "Available" now has one definition, server-side.
3. **`/api/availability` offered a kept player as a draft candidate** (Loveland in the TE VONA list) — the same
   omission, one endpoint over.
4. **Keeper edits did not recompute the board.** `total_picks` re-cut but room ADP and P(avail) still described the
   previous keeper set. Keeper mutations now trigger a full recompute (~2 s, no network), which is what the gate
   clause "keeper edits recompute best-available and P(avail) without reload" actually requires.
5. **Tier bands read "Tier 1, Tier 2, Tier 4, Tier 3."** `tier` is a GMM over ECR while the board is ordered by our
   value, so the ECR tier is not monotonic in rank order and any banding by it looks broken. Bands now follow
   whichever tier is monotonic under the current sort — value tier in rank order, ECR tier when sorted by ECR.
6. **A WHY bullet rendered `(None)`** for a rookie with no draft team.
7. The agent's own fixes: right panel pushed off-screen, header desync on horizontal scroll, j/k dropping presses in
   a React batch, and an empty API returning a misleading "draft complete" skeleton instead of an error banner.

### Deliberate deviations from the spec (recorded in docs/decisions.md)

- **TanStack Table is not used.** The installed version is v9, a store/plugin API unrelated to the v8 the plan
  assumed; sorting 631 rows is a comparator and a `useMemo`. `@tanstack/react-virtual` handles rows; TanStack Query
  is unchanged.
- **Best available = the lowest-ranked undrafted row**, not the first row in the current sort — sorting by ECR
  descending would otherwise star the worst player. Identical under the default sort.
- K/DST auto-sort inside their preset, CSV preset pass-through, and sparklines are not implemented.
