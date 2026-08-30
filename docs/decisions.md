# Decisions log

ADR-style, newest last. Each entry: date, decision, why, consequences.

## 2026-08-29 — Plan v2 adopted after adversarial review
- Hard MVP cut line with two gates: draft-day minimum (end of day 5) and MVP checkpoint (end of day 6); day 10 buffer. See `docs/PLAN.md`.
- Why: four-lens review found the original phase layout ~2× over-committed for a draft that lands before Sep 10.

## 2026-08-29 — Data stack: nflreadpy + free endpoints only
- nflreadpy 0.1.5 (nflverse, CC-BY-4.0) is the only historical-stats source; `nfl_data_py` is archived and pins pandas<2 — never used.
- Explicit `seasons=[...]` on every nflreadpy call; `get_current_season()` flips to 2026 on 2026-09-10 and would 404.
- Unofficial endpoints accepted as risks (each pull is snapshotted; the app runs on the last good snapshot):
  - Sleeper `api.sleeper.com/projections/nfl/2026?season_type=regular` and `/v1/players/nfl` (once/day).
  - Yahoo `pub-api-ro.fantasysports.yahoo.com/.../game/nfl/players;sort=AR;...;out=draft_analysis` (site-wide ADP; once/day; never during the draft). Sanctioned equivalent: OAuth `game/nfl/players;out=draft_analysis`.
  - FFC `api/v1/adp` is an official free API (attribution in README).
  - FantasyPros ECR via `nflreadpy.load_ff_rankings('draft')` (DynastyProcess mirror). Direct scraping only post-MVP, ≤1 page/day, personal use only, never exported.
- ESPN kona projections excluded from the MVP blend until the stat-id map is validated (reproduce `appliedTotal` for ≥20 players).

## 2026-08-29 — Modeling decisions (fixed for this draft)
- Per-game blend: Sleeper/Rotowire 0.70 / in-house 0.30; rookies and players without a ≥8-game same-team-role season 0.90 / 0.10 (in-house = draft-capital prior × depth slot). Renormalize over available components.
- Context (coaching, QB room, OL) and age adjustments touch ONLY the in-house component; vendor lines already embed 2026 context. Context tables produce tags/WHY bullets, no multipliers, in MVP.
- ONE expected-games factor applied at the per-game → season conversion; season value uses the man-games form `E[g]×PPG + (17−E[g])×replacement_PPG`.
- Keepers are per-team round holes in `pick_schedule`; "room ADP" re-ranks each ADP source after removing kept players.
- ADP variance from FFC stdev (verified ≈ half of ADP/4), fallback line refit nightly.
- Tiers: 1-D GMM on ECR average with fixed k per position (Boris Chen method); value tiers from projection drop-offs.
- SoS display-only (positional points-allowed YoY r ≈ 0.16–0.26). Contract flags informational only (effect neutral-to-negative once age is controlled).
- WHY text is rule-based over stored signals; each bullet row references rule_id, inputs and snapshot ids.

## 2026-08-29 — Yahoo integration
- Library: `yahoo_oauth` for the token dance + `httpx` raw JSON (archived). Wrappers (`yfpy`, `yahoo_fantasy_api`) drop unfilled draft-result rows and settings fields, so they are optional readers only.
- Yahoo API access application: **not yet submitted** (Derek's day-1 action). Record the submission date here when done.
- Live sync (Phase 8b) is gated on approval AND a verified harness (mock-draft visibility spike or throwaway private league). Manual pick entry is first-class and identical in the UI.

## 2026-08-29 — Testing policy
- Real data only: test fixtures are extracts of real snapshots under `backend/tests/fixtures/{source}/` with a `PROVENANCE.md` (URL, fetched_at, sha256). Expected values are hand-computed from those rows. No invented players or stat lines.

## 2026-08-30 — Confirmed league inputs, re-planned calendar
- `league_key = 470.l.335180` (Yahoo 2026 NFL game key `470` + league id `335180`, "shirtlesschugsonly"); derived from the
  `470.p.*` player keys in our own ingested Yahoo pool.
- Draft: **Sun Sep 6, 2026, 8:45pm CDT** (`2026-09-06T20:45:00-05:00`). Keeper declaration deadline: **Mon Aug 31**.
- Consequence: the calendar in `docs/PLAN.md` is compressed by 3 days and the **keeper-value helper moves from day 7 to day 2**
  — Derek has to choose keepers before the model is finished, so it runs off a minimal projection + VBD and is re-run after the
  full Phase 6 pipeline lands. Everything still completes before the Sep 10 kickoff, so the `--post-kickoff` guard never fires.
- Yahoo developer app created and the API access application submitted 2026-08-30 (awaiting review; Yahoo publishes no SLA).
  Phase 8b stays gated on approval **and** a verified harness; manual pick entry remains first-class.
- Still pending: the real scoring table (a screenshot was mentioned but no image arrived), roster slots/bench, max keepers,
  draft slot. `config/league.yaml` remains the labeled Yahoo-default placeholder and the Phase 2 gate cannot pass until it lands.

## 2026-08-30 — Phase 4-lite gate depth amended with evidence
- Written gate: "every top-200 ECR player has ≥2 ADP sources". Measured on real data: free ADP markets are ~230 players deep
  (Yahoo 227, FFC 232) and do not overlap perfectly, so 6 players at ECR 173–198 have only Sleeper ADP.
- Enforced gate is now: top-300 composite; **top-150** ECR ≥2 ADP sources + non-null disagreement; **top-200** ECR ≥1 ADP source.
  A 10-team × 16-round draft is 160 picks, so 150-deep two-source coverage spans the whole board. Rationale is duplicated in
  `app/market/build.py` (`GATE_TWO_SOURCE_DEPTH`) and `docs/phases/04-market.md`.
- `sd_adp` OLS on FFC gives `1.04 + 0.105·ADP`, confirming the plan's placeholder and ~halving the rejected `ADP/4` heuristic.

## 2026-08-30 — Phase 7 board UI
- **Table**: hand-rolled typed table + `@tanstack/react-virtual` instead of TanStack Table. The installed
  `@tanstack/react-table` is **v9.2.4**, a store/plugin API unrelated to the v8 the plan assumed; sorting and filtering
  631 rows client-side is a `useMemo` and a comparator, so the dependency bought nothing and risked a lot on draft eve.
  Query stays on TanStack Query. `pnpm add @tanstack/react-virtual` is the only dependency added.
- **Tier bands fire on first appearance of a tier, not on every change of `tier`.** `tier` is a GMM over ECR while
  `rank` is ordered by value, so the two disagree locally and the literal §3 rule ("a rule whenever `tier` changes")
  drew a band every two or three rows. First-appearance gives one rule per tier in rank order; stragglers still show
  their tier in the Tier column. Value-tier breaks are monotonic with rank and keep the literal dashed rule.
- **Best available is the lowest-ranked undrafted row under the filter, not the first row in the current sort.** Sorting
  by ECR descending would otherwise star the worst player on the board — the opposite of useful thirty seconds before a
  pick. When sorted by rank (the default) the two are identical.
- **The board asks `/api/rankings?limit=1000`, not 600.** The pinned run holds 631 players; 600 silently cut the tail,
  including Derek's own keeper (Colston Loveland, rank 631), so his keeper was invisible on the board.
- **Keeper state is joined onto board rows in the client.** `/api/rankings` reflects `draft_picks` but not the `keepers`
  table, so a declared keeper comes back `drafted: false`. The board overlays `/api/keepers` (both endpoints are
  authoritative) so a kept player is dimmed, carries the `K` badge and is attributed to the team that kept him.
- **The player name column is inserted after rank**, keeping the 14 columns of `docs/spec/ui.md` §3 in their exact
  relative order. §3 omits `name` but the CSV contract in §7 includes it, so the omission is an oversight.
- **Losing the API mid-draft never blanks the board.** The no-run/offline state only replaces the page when a run has
  never loaded; after that a banner appears over the last good data with a Retry that refetches every query.
- Known backend gaps found while wiring the UI, not worked around in the client:
  - `POST/DELETE /api/keepers` re-cuts `pick_schedule` (`total_picks` 159 ↔ 158 immediately) but does **not** recompute
    baselines, room ADP or P(avail); the endpoint says so in its own `note`, which the Keepers tab shows verbatim.
    Measured: Nico Collins stayed at `room_adp 21 / p_avail 0.9997` across a keeper add and remove. The Phase 7 gate
    clause "keeper edits recompute … P(avail) without reload" therefore needs `ff rank run` server-side.
  - `rookie_draft_capital` WHY text renders the drafting team as Python `None`: "2026 rookie: round 1, pick #3 overall (None)".
  - `POST /api/draft/picks {my_pick: true}` fills the lowest unfilled schedule slot and attributes it to my team, so
    pressing `m` out of turn still advances the clock past someone else's pick. Correct when used on my own turn.
  - There is no `PUT /api/keepers/{id}`; the Keepers tab says so and edits are remove-then-add.
- Measured Phase 7 gate on Derek's machine (Vite **dev** build, React StrictMode, Chrome, 631 rows): the render pass
  that commits the rows takes **41–306 ms** typical (worst observed 618 ms on a cold dev server), and **233–970 ms**
  from navigation start to rows in the DOM including all six API calls. Gate is < 2 s, so it passes with a wide
  margin; a production build removes the StrictMode double render and the dev module evaluation that account for
  most of the spread. Marks are left in the Performance timeline as `board:render-start`, `board:committed`,
  `board:render` and `board:from-navigation-start`, so the number can be re-measured any time.
