# Phase 9 — Keeper helper, review, freeze, readiness (days 7–10)

Purpose: turn the MVP into a draft-ready tool — Derek's review pass and fixes, the keeper-value helper before the keeper deadline, the Track A/B day, the hard freeze, the curated re-check, the dry run, and the buffer day.

Status: Not started

Specs: `docs/spec/ranking-model.md` §13 (keeper-value helper) and §14 (guards), `docs/spec/live-draft.md` (Track A / harness / dry-run feed), `docs/spec/data-model.md` (`draft_snapshot`, `raw_snapshots.post_kickoff` / `shape_ok`), `docs/runbook-draft-week.md` (freeze and post-kickoff procedures).

## Calendar (draft before Sep 10; adjust if the date is earlier)

| Day | Date | Deliverable |
|---|---|---|
| 7 | Sun Sep 6 | Derek review + fixes; keeper-value helper; runbook |
| 8 | Mon Sep 7 | Track A (Yahoo live) or Track B (injuries/skill movement/SoS display/polish); hard freeze the evening before the draft |
| 9 | Tue Sep 8 | Curated re-check; dry run |
| 10 | Wed Sep 9 | Buffer |

The hard freeze happens the evening before the draft, **no later than Sep 9 23:00**. If the draft is earlier than Sep 9, the freeze moves with it and days 8–10 compress (dry-run bug fixes only after the freeze).

---

## Day 7 (Sun Sep 6) — review, keeper-value helper, runbook

### Derek's top-200 sanity pass

- [ ] Export the top-200 by position (QB/RB/WR/TE plus K/DST by ADP) as a markdown table with rank, tier, value, ECR, room ADP, flags and the first WHY bullet.
- [ ] Derek's ~2 h top-200 sanity pass by position → list of concrete issues (wrong team, missing injury, absurd rank, bad bullet).
- [ ] Triage each issue: data fix (`seeds/id_overrides.yaml`, `seeds/known_missed_weeks.yaml`, curated tables) vs model fix (Phase 6 rule) vs accepted; record decisions in `docs/decisions.md`.
- [ ] Re-run `recompute` (< 5 min, no network) and re-check the Spearman ≥ 0.8 guard after fixes.

### Keeper-value helper (post-MVP priority #1)

- [ ] Candidate list = Derek's roster (manual list; `team/{key}/roster` if OAuth works), each with last year's draft round = cost_round.
- [ ] For each candidate: `keeper_surplus = VORP(player) − expected VORP of the best player available at the cost-round pick under room ADP`.
- [ ] Rank candidates by `keeper_surplus`, show the WHY bullets for each, and show the pick number the cost round maps to in `pick_schedule` for Derek's draft slot.
- [ ] Helper is a CLI command and an API endpoint so it can be re-run after any keeper announcement from other teams.
- [ ] Deliver the ranked keeper list to Derek before the Yahoo keeper deadline (≥1 h before draft, commissioner approval).

### Runbook, fixtures, docs

- [ ] `docs/runbook-draft-week.md` finalized: daily jobs, failure handling, freeze, post-kickoff guard, draft-day checklist, keeper deadline.
- [ ] `backend/tests/fixtures/{source}/…` + `PROVENANCE.md` (url, fetched_at, sha256) complete for every source used by a unit test — real extracts only.
- [ ] README.md, CLAUDE.md, `docs/PLAN.md` phase index and this checklist updated.

---

## Day 8 (Mon Sep 7) — Track A or Track B, then hard freeze

Decision gate at start of day (record in `docs/decisions.md`): Track A runs only if Yahoo access is approved **and** a harness exists (see `docs/phases/08-availability-live.md`); otherwise Track B.

### Track A — 8b Yahoo live sync (if gated conditions hold)

- [ ] Complete the 8b checklist in `docs/phases/08-availability-live.md` and pass its gate.

### Track B — post-MVP data and polish (otherwise)

- [ ] ESPN injuries feed: parse athlete id from `links[].href`; core per-team fallback; feeds `known_missed_weeks` only via review.
- [ ] Programmatic `skill_movement`: 2025 targets+carries departed/added per team from `stats_player_reg` × 2026 roster team change; WHY tag bullets only.
- [ ] Display-only 2025 positional points-allowed columns (REG, league scoring; full season / wk 1–4 / wk 15–17) labeled "proxy" in the UI; no ranking effect.
- [ ] Sparklines in the player drawer.

### Hard freeze (either track; evening before the draft, no later than Sep 9 23:00)

- [ ] Full refresh: `ingest all` (every source writes a snapshot + row count; one source failing does not fail the job) → `ingest check-ids` → `recompute`.
- [ ] Spearman ≥ 0.8 guard and ≥3-bullets-per-top-100 check pass on the new run.
- [ ] Pin the run in `draft_snapshot` (run_id + league-config hash); record run_id, config hash, git sha, seed hashes and input snapshot ids in `docs/decisions.md`.
- [ ] Verify the board refuses to serve if `config/league.yaml` is edited after the freeze (config hash mismatch) and serves again only after an explicit re-freeze.
- [ ] After Sep 10 every ingest requires `--post-kickoff` (upstream semantics change to ROS); parsers assert expected shape (FP week == 0, Sleeper week null, `page_type == 'redraft-overall'`) and refuse to overwrite the frozen run — test this with the clock mocked to 2026-09-11 before the freeze.

---

## Day 9 (Tue Sep 8) — curated re-check and dry run

### Curated-table re-check (Derek, 1–2 h)

- [ ] Produce one markdown table of `coaching_changes`, `qb_situations`, `ol_changes` (32 rows each) with `source_url`, `confidence`, `last_checked` for Derek's review.
- [ ] Derek re-checks with source URLs: ATL/LV/KC QB rooms, OL injuries, late signings: Decker, Conklin, Mixon, Chubb, Hopkins.
- [ ] Apply YAML edits + reload; every changed row gets a new `source_url` and `last_checked = 2026-09-08`.
- [ ] Re-freeze **only if required** (explicit, logged in `docs/decisions.md` with the reason and the new run_id/config hash).

### Dry run of draft-day mode

- [ ] Scripted pick feed in real Yahoo-ADP order (from the frozen Yahoo site-wide ADP snapshot), fed through the manual-entry API at draft speed.
- [ ] If 8b shipped: run the poller against the harness draft in parallel and confirm the board shows the same picks.
- [ ] Verify: undo works; keeper holes appear in pick counts ("my next pick in N" skips keeper-consumed slots); P(avail)/VONA update after each pick; CSV export downloads with the run_id.
- [ ] Verify the bye-stack warning triggers when the scripted feed gives me ≥3 starters on one bye.
- [ ] Log every bug found in `docs/decisions.md` or the issue list; only dry-run bugs are fixed on day 10.

---

## Day 10 (Wed Sep 9) — buffer

- [ ] Dry-run bug fixes only; no new features, no model changes.
- [ ] Verify the frozen snapshot serves with the recorded config hash (`GET` the board payload, compare run_id and config hash with `docs/decisions.md`).
- [ ] Confirm the `--post-kickoff` guard is in place for any ingest run on or after Sep 10.
- [ ] Final README/CLAUDE/decisions update (Yahoo application date and outcome, live-sync decision, freeze run_id, known issues).
- [ ] Walk through the draft-day checklist in `docs/runbook-draft-week.md` once end-to-end.

## Gate

The plan defines no single gate line for Phase 9; the acceptance criteria are its per-day deliverables and the Verification items, verbatim:

- Day 7: Derek's ~2 h top-200 sanity pass by position → fixes; **keeper-value helper**: for each candidate on Derek's roster (manual list; `team/{key}/roster` if OAuth works) `keeper_surplus = VORP(player) − expected VORP of the best player available at the cost-round pick under room ADP`, ranked with WHY bullets, delivered before the Yahoo keeper deadline (≥1 h before draft, commissioner approval); draft-week runbook; fixtures + PROVENANCE; docs updated.
- Day 8: Track A = 8b if gated conditions hold; Track B = ESPN injuries, programmatic skill_movement, display-only 2025 positional points-allowed columns, sparklines. Either way: full refresh and **hard freeze** of `draft_snapshot` the evening before the draft (no later than Sep 9 23:00). After Sep 10 every ingest requires `--post-kickoff`; parsers assert expected shape (FP week == 0, Sleeper week null, `page_type == 'redraft-overall'`) and refuse to overwrite the frozen run.
- Day 9: Derek's 1–2 h curated-table re-check (ATL/LV/KC QB rooms, OL injuries, late signings: Decker, Conklin, Mixon, Chubb, Hopkins) with source URLs; re-freeze only if required (explicit, logged); dry run of draft-day mode with a scripted pick feed in real Yahoo-ADP order (plus the poller if 8b shipped): undo, keeper holes in pick counts, P(avail)/VONA updates, CSV.
- Day 10: buffer — dry-run bug fixes only; verify the frozen snapshot serves with the recorded config hash; final README/CLAUDE/decisions update.
- Verification: Manual: Derek's top-200 sanity pass (day 7) and curated-table review (day 9). End-to-end: `uv run fastapi dev` + `pnpm dev`; dry run of draft-day mode with a scripted real-ADP pick feed; 8b tested against the Yahoo harness if shipped.

## Derek's actions

- Day 7: ~2 h top-200 sanity pass by position and report issues.
- Day 7: provide the list of players on his roster eligible to be kept, with the round each was drafted in last year (or confirm OAuth so `team/{key}/roster` can be read).
- Before the keeper deadline (≥1 h before draft, commissioner approval): submit keeper choices in Yahoo and confirm whether the commissioner has run "Assign Keeper Players".
- Day 8: report Yahoo access approval status for the Track A/B decision.
- Day 9: 1–2 h curated-table re-check (ATL/LV/KC QB rooms, OL injuries, late signings: Decker, Conklin, Mixon, Chubb, Hopkins) with source URLs.
- Day 9: approve any re-freeze explicitly.
- Confirm the exact draft date/time (day-1 input) so the freeze evening and the poller start (draft_time − 60 min) are correct.
