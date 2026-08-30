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
