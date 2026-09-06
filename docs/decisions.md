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


## 2026-09-03 — Draft-week refresh caught a silent upstream break (ARI → AZ)

The Aug 31 roster cutdown happened after the data was pulled, so a full refresh was run four days before the draft.
It surfaced a genuine data-quality failure that no gate would have caught on its own.

**nflverse changed Arizona's team code from `ARI` to `AZ`** in the 2026 roster file, while depth charts and weekly
stats stayed on `ARI`. The players hub takes `team` from the roster, so all 32 Arizona players ended up on a code
that matched nothing: no team volume from `team_tendencies`, no row in `team_context`. They silently fell back to a
**vendor-only projection with no team context at all** — Trey McBride (rank 40), Marvin Harrison Jr (75) and
Jeremiyah Love (32) among them. Only 31 of 32 teams were being projected.

Fixed at the canonical layer: `TEAM_FIX` in `players_hub.py` now normalises `AZ`, `ARZ`, `SFO`, `KCC`, `LVR`, `NOS`
and the other common variants to the nflverse stats dialect, with `FA` recognised as a real value (unsigned free
agents) rather than a club. `ingest check-ids` gained a **team-code guard** that fails loudly on any unrecognised
code and on any count other than 32 canonical teams, so the next dialect drift is caught at ingest rather than by a
test that happens to count teams. `app/context/build.py` now validates the curated seeds against `CANONICAL_TEAMS`
instead of whatever dialect the current roster file uses — the seeds were right and the reference was wrong.

Restoring Arizona moved McBride from 40 to **30**.

### Other real changes the refresh brought in

- **Josh Jacobs (GB, ADP 45) fell from RB1 to RB4** behind MarShawn Lloyd, carrying a groin injury. The pipeline
  reacted on its own: rank 45 → 222 and a `bust` flag. Lloyd rose from 312 to 93 with a `sleeper` flag.
- **Zach Charbonnet is PUP with a post-surgical ACL and has fallen to RB4** behind Jadarian Price; he correctly lost
  the sleeper flag he had on 2026-08-31.
- **Four players moved to IR after the seed was written** — Isiah Pacheco (back), James Conner (foot), Tank Dell
  (knee) and Jordyn Tyson (hamstring). The curated `known_missed_weeks` had them at 1–2 weeks as Questionable.
  Updated to a **four-game floor**, which is the NFL rule for IR once the 53-man roster is set, not a guess. Their
  expected games dropped to 13 and they fell 100+ places apart.

This is the case for the day-before refresh in `docs/runbook-draft-week.md`: three of these would have left a
materially wrong board.


## 2026-09-06 — Yahoo draft-room automation investigated in a live mock: NO-GO

Joined a live 10-team Yahoo mock draft on draft day and inspected the draft client from inside the page
(`/draftclient/f1/{league_id}/{slot}`). Findings, in order of how much they mattered:

**What works.** The room renders picks as plain text that is trivially parseable:
`Last: J. TAYLOR (RB · IND) Robert`, alongside `Craig's Pick • You're up in 7 Picks • Round 1, Pick 2` and a page
title that counts down (`7 picks until your turn`). A MutationObserver watching for that text pattern would catch
picks as they happen, and matching on text rather than class names would survive a restyle.

**Why it is still a no-go for this draft.** Only the **most recent** pick exists in the DOM. Clicking the "Picks"
tab did not surface a full history (virtualised or fetched on demand), so there is no list to reconcile against.
That forces the fragile design rather than the robust one: the extension must catch **every** pick as a discrete
event, with no way to detect that it missed one. Compounding factors: class names are obfuscated
(`_ys_1o5vjbq`), the page carries 21 iframes, and pick text is abbreviated (`C. LAMB`, `J. TAYLOR`) so every pick
needs fuzzy resolution against name + position + team — exactly the kind of thing that resolves 46 picks correctly
and then silently attributes the 47th to the wrong player.

**Decision:** not built. Manual entry via QuickPick is measured at ~2 s and four keystrokes per pick, the dry run
put 30 picks through in 0.8 s, and the Teams view drift check catches mis-attribution. An untested event-catching
extension shipped into the real draft a few hours before it starts is a worse risk than the typing it saves.

Worth revisiting for 2027, when there is time to test it across several mocks — and by then Yahoo's API access
(applied for 2026-08-30, quoted at 1–2 weeks) should have landed, which is a structured feed and strictly better
than scraping a rendered page.

## 2026-09-06 — VONA weights every position by what the roster can actually start

**Problem.** Asked whether the board understood that a rostered position is worth less than an empty one, the
honest answer was "only partly", and testing it exposed two flaws.

1. **FLEX was invisible.** `_state()` built `open_slots` from the named starting slots and skipped `FLEX`
   entirely, so once RB1/RB2 were filled a third running back looked like a bench body — when he can actually
   start every week. Any surplus at a flex-eligible position now consumes a FLEX slot, and a player who fills the
   remaining FLEX gets full weight.
2. **The weight was binary.** `1.0 if open_slots > 0 else 0.5` gave a backup quarterback — who can never start in
   a 1-QB lineup — the same 0.5 as a third running back who can. In the late rounds the highest projected player
   left on the board is very often a quarterback, so the board kept recommending one.

**Fix.** `_slot_weight()` returns a weight *and* the sentence explaining it, which the VONA panel renders:

| Case | Weight | Shown as |
|---|---|---|
| Fills a starting slot | 1.00 | fills a starting slot |
| Flex-eligible, FLEX open | 1.00 | fills the FLEX |
| Backup QB (1-QB lineup) | 0.15 | backup QB — cannot start in a 1-QB lineup |
| K/DST already rostered | 0.03 | already rostered — streamed weekly |
| Bench depth *n* | 0.35 × 0.55^(n−1), floor 0.10 | bench depth n — can cover injuries and byes |

The bench curve is decay, not a cliff: the first backup at a position has real value (injuries and byes), the
fourth has very little. `BENCH_FLOOR` keeps it above zero so a genuinely elite player still surfaces.

**Verified** by simulating 95 picks with Josh Allen on my roster. Raw value vs. VONA:

```
Jakobi Meyers   WR  raw 19.7  VONA 2.6   (×0.35  bench WR)
Kyle Monangai   RB  raw 22.7  VONA 1.5   (×0.106 bench depth 3)
Travis Kelce    TE  raw 16.9  VONA 1.3   (×0.193 bench depth 2)
Patrick Mahomes QB  raw 18.5  VONA 0.5   (×0.15  backup QB)
```

Monangai has the highest raw value of the four and correctly ranks below Meyers; Mahomes projects for more points
than Kelce or Meyers and correctly ranks last. This is display-and-recommendation logic only — it scales VONA in
`/api/availability`, which is computed live. The frozen run's rankings, VORP and WHY bullets are untouched.

## 2026-09-06 — A keeper edit now carries the freeze forward

**Bug, found by a test that had been failing for the wrong reason.** `current_run()` prefers the frozen run.
`_recompute()` (on every keeper add/remove) built a *new, unfrozen* run — so after the hard freeze, keeper
corrections produced a run that nothing ever served. The board would have gone on showing the previous keeper
set's baselines, room ADP and pick schedule, silently. Six such orphaned runs were sitting in `ranking_runs`.

The freeze exists to pin the **inputs** (snapshots + config hash) so the board is reproducible, not to reject a
keeper correction: `_recompute` reads only stored data, so its inputs are identical to the frozen run's and only
keeper state moved. It now unfreezes the superseded run and freezes the new one, noting which run it came from.
Exactly one run is frozen at any time, and the audit trail records the chain.

## 2026-09-06 — Test FFC resolution against the snapshot, not a hardcoded count

`assert per_source["ffc"] >= 232` was meant to check that every FFC row resolves to a player, but it asserted the
size of a pool we do not control. FFC's half-ppr board shrank from 232 to 227 rows during draft season and the
test failed while resolution was in fact perfect (227/227). It now compares against `raw_snapshots.row_count` for
the latest registered FFC snapshot, which is what the assertion always meant.

## 2026-09-06 — Code review before the draft: the board's two decision columns were frozen at pick 10

A full review the afternoon of draft day, driven by simulating drafts against the live API rather than reading
code. Five defects, four of them in the path Derek uses on every pick.

### 1. P(avail) and VONA described the draft's opening position, forever (critical)

`pipeline.py` computes `p_avail_next` and `vona` once, at `next_live_pick(sched, my_slot, 0)` — my FIRST pick,
against a room ADP that excludes keepers but knows nothing about who has since come off the board. Nothing
recomputed them: only a keeper edit triggers `_recompute`, never a pick. Simulating 40 picks in ADP order:

```
                       BOARD (frozen)      TRUTH (live)
Bucky Irving  P(avail)          1.00              0.06
              VONA            -44.97            +21.02
```

The board told me a running back was **certain** to last until my next pick when he had a 6% chance, and scored
the most valuable pick available at −45.0. `P(avail)` is a sortable column and VONA is rendered in DraftPanel for
both the selected player and best-available, so both were in front of me on every pick.

Fixed by recomputing both live in `/api/rankings`:
- `_live_room_adp()` re-ranks *what is left* by ADP and offsets by the picks already made, so the room is modelled
  as continuing to take the best available from here. The stored `room_adp`/`gap`/`gap_z` are left alone — they are
  pre-draft market judgements and the sleeper/bust flags are built on them.
- `_decision_horizon()` returns the pick being reasoned about. While I am ON THE CLOCK my next pick is this one,
  every available player survives to it trivially, and the real question is what I can get at the pick *after* —
  so the horizon steps forward when `picks_until_mine` is 0.
- `expected_best_excluding()` gives every player's leave-one-out expectation in O(n) instead of O(n²), using the
  recursion `E_from[i] = v_i·p_i + (1−p_i)·E_from[i+1]` rather than dividing the excluded factor back out, which
  is unstable exactly when a candidate is certain to be available.

### 2. K and DST were ordered arbitrarily (spec §12 violation)

They are deliberately given VBD 0, so all 40 of them tie and the sort among them fell back to input order:
Cairo Santos (ADP 329) ranked above Ka'imi Fairbairn (ADP 132), and Chad Ryland (ADP 654, undrafted in most
leagues) sat at rank 130. That is the ordering the last two rounds would have been drafted from. The board now
breaks ties on consensus ADP. Diffing the rebuilt run against the old one: 90 players moved, **every one of them
had an exactly equal VORP** to its neighbour, and no player with a distinct value moved at all. It also improved a
real tie — Ashton Jeanty (ADP 19) now sits above Javonte Williams (ADP 32) instead of below him on input order.

### 3. "Best available" recommended a kicker from round 9

VBD 0 parks K/DST around rank 125, ahead of ~430 real players, and `bestAvailable()` is pure rank — so the green
star, and the default keyboard highlight that follows it, became a kicker well before kickers are worth a pick.
It now skips K/DST until round 12, matching the VONA panel, and falls back to naming one if a filter leaves
nothing else. The panel gained the K/DST blocks it was always supposed to show from round 12 (`showKdst` was dead
code because the endpoint filtered them out unconditionally), ranked by ADP since VBD cannot rank them.

### 4. The VONA panel disagreed with the board on below-replacement players

The panel used a signed `value_now` while its own candidate pool clamps at `max(0, vorp)`, so it subtracted a
clamped expectation from an unclamped value: Sam Darnold showed −3.0 in the panel and 0.0 on the board. A negative
VORP means "worse than a freely available replacement" and the gain from drafting him is 0, not negative. Now
clamped in both. Worst board/panel disagreement across a simulated 140-pick draft: 0.09, i.e. rounding.

### 5. QuickPick could record the wrong player on a click

`onMouseDown` called `setI(n)` and then `submit()`, which read `i` from the render closure — so a click that beat
its own mouse-enter re-render recorded whichever player was previously highlighted. Mouse-enter almost always
lands first, which is why it never showed up, but "records the wrong player under time pressure" is the one
failure this box exists to avoid. `submit()` now takes the index explicitly.

### Also fixed

`ff rank run --freeze` marked the new run frozen without unfreezing the old one, leaving a second silently
shadowed "draft-day board" in the table (`current_run()` takes the newest). Exactly one run is frozen now, matching
the keeper-edit path.

### Checked and found correct

Yahoo's non-fractional-yardage rounding (moot: the league uses fractional points, so scoring a season total and
summing weekly scores agree); the `E[games]=0` on Brandon Aiyuk (Reserve/DNR, sourced, confidence high — he
correctly falls to replacement value); `keeper_value` divisions (a round only becomes a key when it has a live
pick, so the denominators cannot be 0); the polars UInt32 rank-underflow class (every surviving `rank()` is cast
before subtraction, or only ever compared); the drift check's claim that the n-th surviving `draft_picks` row is
the n-th live slot (holds across undo, since ids stay monotonic and undo only removes the last pick).

## 2026-09-06 — `ingest all` + `rank run` rebuilt the board on the PREVIOUS pull's ADP

Asked on draft day whether the rankings needed refreshing, I ran `ff ingest all` (which wrote new Yahoo and
Sleeper snapshots at 12:17) and then `ff rank run`, and the board did not move by a single rank. That looked like
"nothing changed upstream", but it was not: `rank_snapshots` — the normalised market table the ranking reads —
still pointed at the **10:40** pull for every source. Only `ff market build` refreshes it from the raw tables,
and it was never wired into either command.

So the documented daily job (`ingest all` → `check-ids` → recompute) had a silent hole: `recompute` was described
in the runbook and listed in the README's command table, but **no such command existed**. Running the two
commands that do exist rebuilds the board on stale ADP and reports success.

Fixes:
- `ff recompute [--freeze]` now exists and runs the chain the docs always claimed: features → market → ranking →
  WHY. It takes ~5 s (runbook budget: 5 min). The runbook and README now say to use it and say why `ff rank run`
  alone is not enough.
- `ff rank check` gained a third gate: the market layer must not be behind the raw snapshots. It compares per
  (source, endpoint), because a re-pull whose content matched is registered `skipped_dupe` rather than `ok` —
  comparing per source alone made a fresh `nflverse/schedules` pull mark `fantasypros_mirror` stale. Verified it
  fires by pointing the check at the older FFC snapshot.
- The draft-day checklist gained an explicit "final refresh at draft_time − 60 min" line.

**After running the real chain, the board still did not move**: 634 players, 0 rank changes, 0 PPG changes, 0
composite-ADP changes against the 10:40 board. Yahoo and Sleeper produced new content hashes from volatile
metadata (Sleeper stamps `last_modified` on every response) while the ADP and projection values were identical;
FFC and the FantasyPros mirror deduped outright, which matches their once-a-day cadence. The frozen run is now
`0875dcdc`, built on the 12:17 Sleeper/Yahoo snapshots and the 10:40 FFC/ECR snapshots, gates passing
(Spearman 0.923, every top-100 player ≥ 3 WHY bullets, market layer current).

## 2026-09-06 12:29 CDT — Pre-draft re-freeze (runbook §"Freeze procedure")

Full chain run and verified end to end ~8 h before the 20:45 CDT draft, to prove the refresh path works before
the moment it matters rather than at draft − 60 min:

```
uv run ff ingest all         58 s   ID gate PASSED
uv run ff ingest check-ids   < 1 s  PASSED
uv run ff recompute --freeze  5 s   features -> market -> ranking -> WHY
```

| | |
|---|---|
| run_id | `1116e5dd` |
| frozen_at | 2026-09-06 12:29:32 CDT |
| league_config_sha256 | `35a02bc48073` |
| git_sha | `74f1dfd` |
| model_version | 2026.1 |
| players / WHY bullets | 634 / 3615 |

Input snapshots: `fantasypros_mirror` 0ffb88b7 (09-06 10:40) · `ffc` 9cc13335 (09-06 10:40) ·
`sleeper` 902d5c23 (09-06 12:26) · `yahoo_pub` 26e35922 (09-06 12:26). FFC and the FantasyPros mirror are on the
10:40 pull because their 12:26 re-pull deduped — they publish once a day, and the new market-currency gate
correctly distinguishes that from being behind.

Guards: Spearman(top-150 vs ECR) 0.9233 ≥ 0.80 · every top-100 player ≥ 3 WHY bullets · market layer current ·
exactly one frozen run · id gate 300/300 ECR, 381/381 Yahoo, 300/300 Sleeper, 43/43 2026 R1–R4 skill, 32/32 teams.

**The board did not move**: 634 players, 0 changes to overall_rank, ppg_blend, composite_adp or e_games against
the 10:40 board. Three refreshes today have produced an identical board, so the market has settled.

Draft state at freeze: 0 picks, one keeper (Colston Loveland, TE, Derek/slot 10).

Note for draft day: running `pytest` re-freezes. The keeper tests add and remove a keeper, and each edit triggers
`_recompute`, which now carries the freeze forward — so the frozen run_id churns even though the resulting board
is identical (verified). Harmless, but re-run `ff recompute --freeze` afterwards if you want the serving run to
be the one the documented chain produced, and don't run the suite mid-draft.

## 2026-09-06 — A racing pick submission returned a bare 500

Chasing a one-off test failure (`test_my_next_pick_matches_the_snake_for_my_slot`, which passed in isolation and
in four consecutive full runs) turned up a real defect next to it.

`make_pick` reads `picks_made`, resolves the on-the-clock slot, then inserts. Two submissions in flight both read
the same count and aim at the same slot. The data was never at risk — `uq_draft_picks_active UNIQUE (league_id,
overall_pick) WHERE undone_at IS NULL` means exactly one wins — but the loser's `IntegrityError` escaped as a
bare **500 Internal Server Error**. Verified by firing concurrent submissions at the live API.

On draft night that is the worst possible message: a double-tapped Enter in QuickPick shows "Internal Server
Error" and leaves you unable to tell whether the pick landed, at the one moment there is no time to check. It now
returns 409 with `pick N was just recorded by another submission — the board has moved on; check the last pick
before re-entering`, which the client already renders (the fetch layer preserves the FastAPI `detail` string).

The flaky test was separately made order-independent: it asserted `live_pick == my_draft_slot`, which silently
assumed an untouched board and made it a tripwire for any earlier test leaving a pick behind rather than a check
of the snake. It now derives from the actual `picks_made` and only asserts the slot when the board is untouched.

## 2026-09-06 12:54 CDT — Pre-draft refresh #2 (7h51m before the 20:45 draft)

```
uv run ff ingest all         57 s   id gate PASSED
uv run ff ingest check-ids   < 1 s  PASSED
uv run ff recompute --freeze  6 s   features -> market -> ranking -> WHY
```

| | |
|---|---|
| run_id | `3ddd5393` |
| frozen_at | 2026-09-06 12:54:38 CDT |
| league_config_sha256 | `35a02bc48073` |
| git_sha | `5f0c94a` |
| players / WHY bullets | 634 / 3615 |

Input snapshots: `fantasypros_mirror` 0ffb88b7 (10:40) · `ffc` 9cc13335 (10:40) · `sleeper` d82d9671 (12:53) ·
`yahoo_pub` 44eabcf6 (12:54). Only Sleeper projections and the Yahoo pool returned new payloads; FFC, the
FantasyPros mirror, depth charts, rosters and every historical table deduped (`skipped_dupe`).

**The board did not move**: 634 players, 0 changes to overall_rank, ppg_blend, composite_adp or e_games. That is
the fourth identical board today (10:40, 12:26, 12:29, 12:54), so the market has settled and Sleeper's changing
content hash is its `last_modified` stamp rather than moving projections.

Guards: Spearman 0.9233 · every top-100 ≥ 3 WHY bullets · market layer current · exactly one frozen run ·
id gate 300/300 ECR, 381/381 Yahoo, 300/300 Sleeper, 43/43 2026 R1–R4 skill, 32/32 teams.
State: 0 picks, 8 keepers, my slot 10, first pick R1 P10, keeper Colston Loveland.

Injury-driven E[games] carried into the frozen board (the values a later pull could still move): Egbuka 14.2 Q ·
Love 13.7 Q · Monangai 13.2 Q · Kittle 13.8 Q · Tyson 11.0 IR · Charbonnet 9.0 PUP · Aiyuk 0.0 DNR.

## 2026-09-06 — `ff rank turns` offered keepers as certainties

Walking through the board with Derek, `ff rank turns` listed Drake London and Javonte Williams as the two best
players available at picks 30 and 31, both at 100%. Both are keepers — the board itself correctly strikes them
through and dims them.

Cause: `turns` selected the pool with only `vorp is not null and not is_kdst`, with no keeper/drafted filter.
Kept players are excluded from room ADP by design, so their `room_adp` is null, and `p_available()` treats a null
room ADP as "undrafted/unknown → assume available" and returns exactly 1.0. Being both high-VORP and scored 1.0,
they sorted to the top of every turn. Anyone planning a turn around that output would be planning around two
players who cannot be drafted.

`turns` now applies the same availability rule as `/api/rankings` and `/api/availability` (not kept, not already
drafted). Picks 30/31 now correctly lead with Bucky Irving (0.98) and Emeka Egbuka (0.97). Two tests added: one
asserting the offered pool never intersects the keeper list, one pinning `p_available(None, …) == 1.0` so the
guard cannot quietly stop testing the mechanism that caused it.

## 2026-09-06 — `ff rank turns` and `ff rank export` answered about the wrong run, and `turns` ignored the draft

Asked whether `turns` is meant to be run during the draft, and the honest answer was no — for three reasons, two
of which were defects rather than design.

1. **It planned from pick 1 forever.** `mine[:8]` took my first eight schedule slots with no reference to picks
   already made, so mid-draft it re-planned picks that had already happened. It now takes only slots with
   `live_pick_no > picks_made`; after 35 picks it correctly opens at round 5, pick 50.
2. **It used the pre-draft room ADP** against an advancing pick number — the same staleness that made the board's
   P(avail) column read 100% for a player with a 4% chance. It now re-ranks whoever is left and offsets by the
   picks made, and measures survival against the pick *before* mine rather than my own.
3. **`turns` and `export` read `LATEST_RUN`, while the board serves the frozen run.** They agree today only
   because `recompute --freeze` makes the newest run the frozen one. Any bare `ff rank run` would have split
   them — and `export` produces the offline fallback CSV, so the sheet Derek drafts from on paper could have
   described a board nobody was looking at. Both now use `SERVING_RUN`, which resolves exactly as
   `app.api.board.current_run()` does (frozen first, else newest), with a test asserting the two agree.

`turns` is a **pre-draft planning** tool: it answers "which of my picks should I be targeting whom at". During the
draft the board is the tool — VONA top-3 per position and the P(avail) column are recomputed live on every pick,
which `turns` is not. The fixes mean running it mid-draft is now correct rather than misleading, but it is still
answering a planning question, not a which-player-now question.
