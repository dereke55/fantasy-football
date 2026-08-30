# Phase 7 — Board UI, MVP (day 6, Sat Sep 5)

Purpose: ship the draft board, player drawer, draft-day controls, keeper entry and CSV export on top of the Phase 6 ranking package and the 8a availability math, reaching the **MVP checkpoint** (end of day 6).

Status: Not started

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

- [ ] Phase 6 gate passed (Spearman ≥ 0.8 on top-150; ≥3 bullets per top-100 player) and a `ranking_runs` row exists to pin.
- [ ] 8a shipped inside the ranking package (P(avail) and VONA available from the API; see `docs/phases/08-availability-live.md`).
- [ ] `keepers`, `pick_schedule` and `draft_picks` tables exist with the manual-entry API/CLI from the day-5 draft-day minimum.
- [ ] `config/league.yaml` carries the real scoring, roster slots, bench count, teams and draft slot (or the slot is still late-bound and the UI can accept it).

## Checklist

### Board table

- [ ] Board reads the **pinned run_id** from `draft_snapshot`; the top bar shows the run id and config hash (`docs/spec/ui.md` §2) and displays the server's 409 `config_hash_mismatch` banner if the config hash changed without an explicit re-freeze.
- [ ] Columns rendered exactly: rank, tier, value tier, pos, team, bye, proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags.
- [ ] Yahoo site-wide ADP column is labeled "Yahoo (site-wide)" and room ADP is shown side by side with it (raw and room-adjusted, per Phase 6 item 5).
- [ ] Tier bands: contiguous rows of the same positional tier share a band background; a value-tier break draws a divider line.
- [ ] Drafted players (any `draft_picks` row, including `is_keeper`) render dimmed and sort to the bottom when "hide drafted" is on.
- [ ] Filters: position chips ALL / QB / RB / WR / TE / K / DST and presets Sleepers (`sleeper` flag), Busts (`bust` flag), combinable, client-side (`docs/spec/ui.md` §2–3).
- [ ] Flags column shows `sleeper`, `bust`, `injury_prone`, `structural_injury_return`, `rookie`, `new_play_caller`, `qb_uncertain_team` as compact badges with a tooltip naming the flag.
- [ ] K/DST rows show VBD 0 and sort by consensus ADP within their preset ("last two rounds" rule shown as a hint in the K/DST preset header).
- [ ] TanStack Table virtualization or pagination so the full pool (400 players) renders in < 2 s (measured, see Gate).

### Player drawer

- [ ] Clicking a row (or Enter on the focused row) opens a drawer without leaving the board.
- [ ] WHY bullets rendered in rule order (≤ ~6), each with its `source_url` and `as_of` (snapshot fetched_at) visible on hover/expand.
- [ ] 3-season PPG line (2023, 2024, 2025 REG PPG under league scoring; nulls for rookies render as "no history", not an error).
- [ ] Key metrics block: targets/game, target share, air-yards share, WOPR, carries/game, luck (TD diff, PPG diff), games missed 2023–25, E[games], age at 2026-09-10, draft capital.
- [ ] Tags block shows the same flags as the board plus the three curated context tags (coaching / QB situation / OL delta) with `confidence` and `last_checked`.
- [ ] Drawer shows the vendor-vs-in-house gap bullet as text only (never used to move the vendor number).

### Draft-day controls

- [ ] "Mark drafted" writes a `draft_picks` row (source `manual`) for the lowest unfilled `pick_schedule` slot, or for an explicitly chosen pick/team_slot.
- [ ] "My pick" writes the same row with my `team_slot` and updates my roster panel.
- [ ] "Undo" removes the most recent manual `draft_picks` row (keeper rows are not undone here; they are edited in Keeper entry).
- [ ] "My next pick in N" is computed from `pick_schedule` (keeper-consumed slots skipped) and updates after every pick.
- [ ] VONA top-3 per position panel (QB/RB/WR/TE; K/DST excluded before round 12) refreshes after every pick/keeper edit.
- [ ] Bye-stack warning fires when ≥3 of my projected starters share a bye; warning text names the week and the players.
- [ ] Best-available and P(avail) recompute after drafted/undo/keeper edits via API re-fetch (TanStack Query invalidation) — no page reload.
- [ ] Keyboard: j/k move the focused row, d marks drafted, m marks my pick; shortcuts are disabled while a text input is focused.

### Keeper entry

- [ ] Form fields: team_slot, player (search over the pre-resolved pool), cost_round; writes a `keepers` row (status, source `manual`).
- [ ] Saving a keeper marks the matching `pick_schedule` slot `is_keeper_slot` and pre-populates that team's roster.
- [ ] Editing/removing a keeper triggers baseline recompute (VOLS/VORP with keeper holes) and refreshes room ADP, P(avail) and VONA.
- [ ] Keeper list view shows all 10 teams with their keepers and the rounds consumed.

### CSV export

- [ ] "Export CSV" downloads the current board view (all columns above plus flags as a comma-joined field and the run_id) using the active filter.
- [ ] A full-pool CSV (no filter) is also available from the CLI so the draft-day minimum works without the UI.

### Performance and checks

- [ ] Measure first render with 400 players in the browser performance panel and record the number here: ______ ms (target < 2 s).
- [ ] Manual check: mark 3 players drafted, undo 1, add 1 keeper, remove it — best-available list and P(avail) change each time without reload.
- [ ] Dark theme only (per stack decision); verify contrast of dimmed drafted rows and tier bands.

### Day-6 wrap-up

- [ ] Candidate freeze v1: run a full refresh + `recompute`, pin the run in `draft_snapshot`, record run_id and config hash in `docs/decisions.md`.
- [ ] Tick MVP checkpoint in `docs/PLAN.md`; update README/CLAUDE.md for the board and keyboard shortcuts.

## Gate

400 players render < 2 s; drafted/undo/keeper edits recompute best-available and P(avail) without reload.

## Derek's actions

None.
