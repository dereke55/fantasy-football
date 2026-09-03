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


## 2026-08-30 — Vacated opportunity and capped team-context effects

Derek asked which of his listed factors actually reach the number. Audit result: roster changes partly, coaching
tags-only, workhorse-vs-committee yes (via carry share), injury yes, **strength of schedule not built**, **contract
not built** (the WHY rule exists but nflverse contracts were never ingested — Phase 1b). He asked for the first two
gaps closed and SoS explicitly dropped.

**1. Vacated opportunity** (`_redistribute_vacated` in `app/ranking/inhouse.py`). Every player's share is estimated
from his own history or a depth-slot baseline, so a club that lost a large share of its 2025 usage projected to a
total well below what a real offence spends, and everyone remaining was under-projected. The team cap already
handled the opposite case; this is its mirror image. The shortfall is distributed in proportion to each remaining
player's own share, capped so no player gains more than 50% of his own share. Miami (Hill released, Waddle traded)
is the largest beneficiary, then Baltimore and Pittsburgh (Pickens to Dallas). Every club now lands exactly at the
measured budget.

**2. Team context now moves the projection**, but only the in-house half and only within a hard cap of
[0.94, 1.06]: QB quality tier ±4%/−3% for players who catch his passes, −2% more for an unsettled QB room, O-line
delta ±1.5%/point for QBs and ±1.0% for RBs, −1% for a new play-caller (uncertainty, not a talent claim).

Applied to the in-house component rather than the blend for the same reason context was tags-only before: the
vendor half already prices 2026 context in, so adjusting the blend would double-count. Living in the 30% component
also means the effective swing on a player's final projection is roughly a third of the cap. Observed spread across
845 players: 0.96–1.05, mean 1.005.

Rank correlation with expert consensus moved 0.925 → 0.920 — within noise, and a small independent divergence is
the expected consequence of the model holding an opinion the market does not.

**Not done, deliberately**: strength of schedule (dropped by Derek; positional points-allowed has YoY correlation
0.16–0.26, essentially zero for WRs) and contracts (evidence for the contract-year effect is neutral-to-negative
once age is controlled).

### Sleeper-flag review (diagnosis only — no change made)

Derek flagged that Dak Prescott and Patrick Mahomes are labelled "sleepers" and that 5 seems too few. Both are
real, and they are separate problems:

- **The label, not the maths.** Dak (our 56 vs ADP 74) and Mahomes (86 vs 105) qualify on `negative_td_luck` +
  `ppg_trend_up`. Dak was the most touchdown-unlucky player in the NFL in 2025 (−11.4 vs expected), Mahomes −6.2.
  The regression argument is sound; calling a former MVP a "sleeper" is not. A `value` or `regression_candidate`
  label, or excluding established players by ADP or prior finish, would fix the semantics without touching the
  model.
- **The count is limited by the support catalogue, not the gap threshold.** 38 players clear
  gap ≥ 6 / gap_z ≥ 1.0 / draftable; 33 are blocked by needing ≥ 2 support signals. Breece Hall (+9 picks),
  D'Andre Swift (+10) and Mike Evans (+13) have zero support signals despite large gaps, because the catalogue is
  thin (six signals, several of which need two seasons of same-role history).


## 2026-08-30 — Sleeper split into sleeper / value, and a wider support catalogue

Both problems from the review above, fixed as Derek asked.

**Sleeper vs value.** Same evidence, different word. A player is *established* if the market already spends a
top-5-round pick on him (`ESTABLISHED_ROUNDS = 5`) **or** he finished 2025 as a startable starter at his position
in a league this size (top 10 QB / 20 RB / 30 WR / 10 TE, with >= 8 games). Established players clearing the value
gap are flagged `value`; everyone else stays `sleeper`. Both carry the identical evidentiary burden
(gap_z >= 1.0, gap >= 6 picks, >= 2 support signals, draftable ADP).

Result: 15 sleepers, 10 value. Dak Prescott (2025 QB7), Patrick Mahomes (QB5), Brock Purdy (QB4) and Nico Collins
(WR11) moved to `value` where they belong; the sleeper list is now genuinely unheralded — Zach Charbonnet (ADP 134,
inheriting Kenneth Walker's vacated carries), Dalton Schultz (+81 picks), Brenton Strange (+64), Chris Rodriguez.

**Wider support catalogue.** Five signals added, three of which only became possible with the vacated-opportunity
and team-context work earlier today:
`inherits_vacated_opportunity` (>= 2% of a club's per-game share inherited from departed team-mates),
`our_model_sees_more_than_the_vendor` (in-house projection >= 1.0 PPG above the vendor line),
`underperformed_expected_points` (ppg_diff <= -1.0), `team_context_tailwind` (context factor >= 1.02),
`high_draft_capital_with_a_role` (R1-R2 rookie at depth rank 1-2).

Flag coverage of players clearing the value gap went from 5/38 to 25/38. A test now guards the ratio at >= 40% and
asserts each new signal actually fires, so the catalogue cannot silently rot back to unusable.

Also: years of experience now appears in the player drawer as "NFL season" (2nd, 3rd, ... or Rookie). It was
computed in `player_features` and typed in the frontend, but the board API never selected it.


## 2026-08-31 — Yahoo live sync dropped for this draft

Yahoo's reply quotes a 1–2 week review for API access; the draft is Sep 6. Phase 8b was always gated on approval
**and** a verified harness, so it is out of scope. Manual pick entry is now the draft-day path rather than a
fallback, which changes what is worth building in the remaining days: entry speed and drift resistance, not
integration.

`QuickPick` (frontend) is the response — type-and-Enter recording against the team on the clock, ~4 keystrokes and
about two seconds per pick, with the box re-focusing for the next one.

One bug worth recording because it would have cost a real pick: the first matcher ranked strictly by match tier,
so "chas" returned Chase McLaughlin (K, rank 140) and Chase Roberts (rank 564) above Ja'Marr Chase (rank 4) — their
first names matched, his surname did. A fast Enter would have recorded a kicker. Scoring is now
`tier × 60 + board_rank` with surname prefixes weighted like full-name prefixes.


## 2026-08-31 — Teams view, and the limits of a drift check

With Yahoo's API out of scope, every pick is typed by hand and the real failure mode is **silent drift** — a missed
or mis-attributed pick desynchronises the board from the draft with no error anywhere. The TEAMS tab is the defence:
all ten rosters in pick order, positional tallies against the league's starting requirements, and a drift header
comparing each team's recorded picks against what the snake says it should have.

Per-team pick order is derived exactly rather than inferred: `POST /api/draft/picks` stamps every pick with the
schedule slot that was on the clock and only ever appends, so the n-th surviving `draft_picks` row is the n-th live
slot. Where the stored team differs from the scheduled team (the "for team" override) the row is badged `≠T7` —
that divergence is precisely the mis-attribution being hunted, so the two are never conflated.

**Known limit, worth stating plainly:** the per-team count catches *mis-attribution*, but not a plain missed pick
or a double-entry — those consume consecutive snake slots and leave every team's count self-consistent, so only the
*names* would be wrong. Two mitigations: rosters list names in pick order for a name-by-name scan against Yahoo,
and the header carries a manual "Yahoo picks made" input, which is the one fact the app cannot derive and turns
"picks recorded" from a tautology into a real comparison. Kept deliberately.


## 2026-09-03 — All eight league keepers recorded

The commissioner's sheet arrived. Eight of ten managers kept a player; Jason and Tony kept none.

| Manager | Keeper | Cost round | Board rank | ADP |
|---|---|---|---|---|
| John | Drake London (WR ATL) | 8 | 19 | 17 |
| Marc | Javonte Williams (RB DAL) | 10 | 23 | 34 |
| Mike | Travis Etienne (RB NO) | 10 | 44 | 40 |
| Devin | Cam Skattebo (RB NYG) | 12 | 43 | 39 |
| Junior | Tyler Warren (TE IND) | 12 | 62 | 57 |
| Derek | Colston Loveland (TE CHI) | 13 | 58 | 48 |
| Al | Caleb Williams (QB CHI) | 13 | 91 | 78 |
| Danny | Luther Burden III (WR CHI) | 14 | 65 | 59 |

Effects, all now live: eight players out of the pool (three RB, two WR, two TE, one QB — every one inside the top
100 by ADP), the draft shortened from 159 to **152 live picks**, VBD baselines shifted, room ADP re-ranked and
P(avail) recomputed.

**Assumption that needs confirming: the manager → draft slot mapping.** The keeper sheet is not in draft order —
Derek is listed third but drafts from slot 10 — so the other nine slots were assigned in sheet order and recorded
in `config/league.yaml` under `league.managers` with `draft_order_confirmed: false`.

What this does and does not affect:
- **Exact regardless of slot**: which players are gone, the 152-pick length, VBD baselines, room ADP, and every
  availability number in rounds 1–7 (the earliest keeper hole is round 8).
- **Depends on the slot**: where each keeper's hole falls, which shifts live pick numbering from round 8 on. Derek's
  round-12 pick is currently live pick 108 rather than 111, and his last is 143 rather than 150. Correcting the
  mapping once Yahoo publishes the draft order is a one-line edit per manager plus `ff rank run`.
