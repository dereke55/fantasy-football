# Phase 8 — Availability & live sync (8a / 8b / 8c)

Purpose: give the board a probability that each player survives to my next pick (8a, closed-form, MVP), sync picks live from Yahoo when — and only when — access is approved and a test harness exists (8b, gated), and later replace the closed form with a Monte Carlo (8c, post-MVP).

Status: Not started

Specs: `docs/spec/ranking-model.md` §8–§9, §12 (`pick_schedule`, room ADP, `sd_adp`, P(avail), VONA), `docs/spec/live-draft.md` (OAuth, `draftresults` poller, keeper rows, harness), `docs/spec/api.md` §3.10–3.11 (`/api/availability`, `/api/draft/stream`), `docs/spec/data-model.md` (`keepers`, `pick_schedule`, `draft_picks`).

## Sub-phase summary

| Sub-phase | When | Gate condition | In MVP? |
|---|---|---|---|
| 8a closed-form P(avail) + VONA | day 5 (Fri Sep 4), in the ranking package | none beyond Phase 6 gate + fixture unit tests | Yes (draft-day minimum) |
| 8b Yahoo live sync | day 8 (Mon Sep 7), **only if Yahoo access approved AND a harness exists** | 8b gate below | No (Track A post-MVP) |
| 8c Monte Carlo availability | post-MVP | none | No |

Manual mode is first-class and identical; every live feature must behave the same when picks are entered by hand.

---

## 8a — Closed-form availability (day 5, in the ranking package)

Formulas (verbatim from the plan):

- `P(available at my next pick) = 1 − Φ((my_next_pick − room_adp) / sd_adp)`
- VONA = value_now − Σ P(avail) × value of best same-position candidates at my next pick, weighted by my open slots (open starter → full VBD, bench only → 0.5×); K/DST excluded before round 12.

Inputs and where they come from:

- `my_next_pick` — from `pick_schedule` (10 × rounds snake with keeper-consumed slots marked; team skipped that round).
- `room_adp` — Phase 6 item 5: each ADP source re-ranked after removing kept players and mapped to pick numbers via `pick_schedule`.
- `sd_adp` — Phase 4-lite: FFC stdev when matched, else `max(1, a + b·ADP)` refit nightly by OLS on FFC (initial 1 + 0.10·ADP); sentinel ADPs nulled.
- Candidate values — Phase 6 season value (`E[games] × PPG + (17 − E[games]) × replacement_PPG[pos]`) and VBD over keeper-aware baselines; value tiers drive the "best same-position candidates" set.
- My open slots — roster slots from `config/league.yaml` minus my keepers and my `draft_picks`.

### Checklist

- [ ] Implement `p_available(my_next_pick, room_adp, sd_adp)` as a vectorized numpy function using the normal CDF; players with null room ADP return null (never 0 or 1).
- [ ] `sd_adp` fallback path uses the nightly OLS coefficients stored with the ranking run; unit test that a player without an FFC match gets `max(1, a + b·ADP)`.
- [ ] Implement VONA per position: value_now minus the P(avail)-weighted value of the best same-position candidates at my next pick.
- [ ] Open-slot weighting: open starter slot → full VBD; bench-only need → 0.5×; FLEX counts as an open starter for RB/WR/TE.
- [ ] Exclude K/DST from VONA before round 12.
- [ ] P(avail) and VONA recompute on every pick, undo and keeper edit (pure numpy, no network), reading the current `pick_schedule` and `draft_picks`.
- [ ] Expose P(avail) per row in `GET /api/rankings` and VONA top-3 per position in `GET /api/availability` (`docs/spec/api.md` §3.3, §3.10) for the board (Phase 7).
- [ ] Unit tests on real fixture extracts (with PROVENANCE): P(avail) for a player at `room_adp == my_next_pick` is 0.5; P(avail) decreases monotonically as `my_next_pick` grows; keeper holes shift `my_next_pick` correctly.
- [ ] CSV export includes the P(avail) column (draft-day minimum).

### 8a acceptance

No separate gate line exists for 8a in the plan. It ships inside the day-5 **draft-day minimum** and is verified by the plan's Verification list: "Unit tests on real fixture extracts (with PROVENANCE): … pick_schedule, room ADP, P(avail)" and by the Phase 7 gate ("drafted/undo/keeper edits recompute best-available and P(avail) without reload").

---

## 8b — Yahoo live sync (day 8, only if Yahoo access approved AND a harness exists)

Gating conditions (both must hold on day 8; otherwise Track B runs instead and live sync is dropped for this draft):

1. Yahoo access approved (application submitted day 1 at sports.yahoo.com/developer/access with the Client ID; date recorded in `docs/decisions.md`) and the day-1 smoke test shows API calls work.
2. A verified harness exists: the **mock-draft visibility spike** shows a Yahoo mock in `leagues`/`draftresults`, or a throwaway private Yahoo league with autopick and a scheduled live draft on day 8–9.

Facts from research that shape 8b:

- `GET /fantasy/v2/users;use_login=1/games;game_keys=nfl/leagues?format=json` returns `league_key` (`{game_key}.l.{league_id}`, e.g. `470.l.12345` — 2026 game_key 470), `draft_status` (`predraft|draft|postdraft`), `num_teams`, `scoring_type`.
- `GET /fantasy/v2/league/{league_key}/draftresults?format=json` returns every pick slot including **unfilled** rows (draft order, keeper holes, who is on the clock). Wrappers (`yahoo_fantasy_api`, `yfpy`) drop unfilled rows, so poll raw JSON with httpx. Official docs only show postdraft samples; live mid-draft behaviour is "plausible, unverified" — hence the harness requirement.
- Keepers are not in settings; they appear as pre-filled draftresults rows and as `is_keeper` on league-scoped player objects.
- `league/{key}/settings` carries roster_positions, stat_categories, stat_modifiers, uses_fractional_points, uses_negative_points, draft_time.
- Yahoo temporarily blocks apps that make "too many requests" and publishes no numbers; attribution "Fantasy data provided by Yahoo Fantasy" is required.

### Checklist — auth and settings

- [ ] `yahoo_oauth` for tokens + httpx raw JSON; wrappers optional readers only (library decision from Phase 0).
- [ ] Single token owner process; tokens stored under `backend/.tokens/` (git-ignored); proactive refresh < 55 min.
- [ ] Fetch raw `league/{key}/settings` and diff against `config/league.yaml` (stat_id map 4 PassYd, 5 PassTD, 6 INT, 9 RushYd, 10 RushTD, 11 Rec, 12 RecYd, 13 RecTD, 18 FumLost, …, `uses_fractional_points`, `uses_negative_points`, roster_positions, `draft_time`); **report only — never overwrites league.yaml**.
- [ ] Record `draft_time` from settings and compare with the day-1 draft date/time input; discrepancy goes to `docs/decisions.md`.

### Checklist — draftresults poller

- [ ] Poll raw `league/{key}/draftresults?format=json` starting at draft_time − 60 min.
- [ ] Cadence: 60 s in `predraft` (captures draft order + pre-filled keeper rows), 10–15 s in `draft`, stop at `postdraft`.
- [ ] Persist **every** row into `draft_picks` (pick, round, team_slot, player nullable via `player_key`, `is_keeper`, source `yahoo`); unfilled rows keep `player_key` null.
- [ ] Pre-filled keeper rows in `predraft` populate `keepers` and `pick_schedule.is_keeper_slot` (source `yahoo`, status `approved`) where no manual row exists; where a manual row disagrees, the manual row is kept, the diff is logged and a `conflict` banner asks Derek to resolve it (`docs/spec/live-draft.md` §5) — never a silent overwrite.
- [ ] On-the-clock = lowest unfilled pick; expose it to the board.
- [ ] Exponential backoff from 30 s on 4xx/5xx/999 responses.
- [ ] After 3 consecutive failures switch to manual mode and show a banner on the board; polling resumes only by explicit operator action.
- [ ] No roster/player calls during the draft; player resolution = dict lookup on the pre-resolved Yahoo pool (`players.yahoo_id`, built by the once/day pub-pool ingest, never during the draft).
- [ ] Unresolved `player_key` rows are persisted with the raw key and surfaced in the banner for manual fix — never dropped.
- [ ] SSE endpoint pushes new picks / on-the-clock changes to the board; the board's manual controls keep working while SSE is connected.
- [ ] Manual mode and live mode write the same `draft_picks` rows; undo of a `yahoo`-sourced row is refused (re-fetch is the source of truth).

### Checklist — harness and tests

- [ ] Fixture test on a real `draftresults` payload containing unfilled + keeper rows (fixture with PROVENANCE: url, fetched_at, sha256): parser yields every slot, keeper rows flagged, on-the-clock correct.
- [ ] OAuth round-trip test: token refreshed proactively; a poll loop survives an hour without a manual re-auth.
- [ ] Harness: mock-draft visibility spike result logged in `docs/decisions.md`; if mocks are invisible, throwaway private Yahoo league with autopick and a scheduled live draft on day 8–9.
- [ ] In the harness draft: new pick detected within 15 s; SSE delivers to the board; manual mode produces identical `draft_picks` rows for the same picks.
- [ ] If neither harness exists by day 8: log "live sync dropped for this draft" in `docs/decisions.md` and proceed with Track B.

---

## 8c — Monte Carlo availability (post-MVP)

Only after day 6 and after the keeper-value helper; last item in the post-MVP priority list.

- [ ] Vectorized Monte Carlo, N=2000 simulated drafts from the current pick to my next pick.
- [ ] Each opposing pick: 25% autopick by Yahoo pre-rank, else Normal(room_adp, sd) urgency draw.
- [ ] Positional-need multipliers per team from its current roster (keepers + `draft_picks`).
- [ ] Run bump: after consecutive picks at one position, raise that position's urgency.
- [ ] Output replaces the closed-form P(avail) column only behind a switch; closed-form stays the default until the two agree within tolerance on the day-9 dry run.

---

## Gate

Gate (8b): fixture test with unfilled + keeper rows; OAuth round-trip survives an hour; new pick detected within 15 s in the harness; SSE delivers; manual mode identical.

(8a has no separate gate line in the plan — see "8a acceptance" above. 8c is post-MVP with no gate.)

## Derek's actions

- Report the Yahoo access application status (approval email / developer console) on day 8 so the 8b gate decision can be made.
- Run the `yahoo_oauth` browser consent flow with the Yahoo account that owns the league (day 1 smoke test; again if tokens are lost).
- Join a Yahoo mock draft for the mock-draft visibility spike and say when it is scheduled.
- If mocks are invisible: create a throwaway private Yahoo league with autopick and schedule its live draft on day 8–9; share its `league_key`.
- Decide (day 8) whether to drop live sync for this draft if neither harness exists.
