# Draft-week runbook

Purpose: the operational procedure for the week before, the evening before, and the day of the draft — daily jobs, what to do when a source fails (serve the last good snapshot), the freeze, the post-kickoff guard, the draft-day checklist and the keeper deadline.

Status: Not started

## Key dates and times

| When | What |
|---|---|
| Every day through the freeze | Daily jobs (below), then `ingest check-ids`, then `recompute` |
| Day 6 (Sat Sep 5) | Candidate freeze v1 (MVP checkpoint) |
| Keeper deadline | ≥1 h before draft, commissioner approval — keeper-value helper must be delivered before it |
| Evening before the draft, **no later than Sep 9 23:00** | Full refresh + **hard freeze** of `draft_snapshot` |
| draft_time − 60 min | Start the draft-day checklist; if 8b shipped, the `draftresults` poller starts here |
| Exact draft date/time | Day-1 input from Derek (`config/league.yaml`); before Sep 10 |
| Sep 10 (NFL kickoff) | `nflreadpy.get_current_season()` flips to 2026; upstream semantics change to ROS; every ingest requires `--post-kickoff` |

If the draft lands early (≤ day 6), the board-lite is pulled into day 5 and WHY polish is dropped; the freeze moves to the evening before the actual draft.

## Daily jobs (through the freeze)

Run in this order, once per day, never during the draft. Every pull is registered in `raw_snapshots` and written as an immutable, hash-deduped file under `data/raw/{source}/{endpoint}/{YYYYMMDDTHHMMSSZ}_{sha8}.{ext}`. Per-source isolation: one failing source never fails the job.

- [ ] `ingest all` (explicit seasons `[2023, 2024, 2025]` for history, 2026 for rosters/depth charts/schedule/draft picks — never rely on `get_current_season()`):
  - nflverse freshness: one `releases/tags/{tag}` call per tag (optional `GITHUB_TOKEN`), compare per-asset `updated_at`, store as `upstream_as_of`; re-pull only changed assets.
  - `depth_charts` 2026 (all `dt` snapshots), `rosters` 2026, `schedules` 2023–2026 (derive `team_bye`), `draft_picks` (ESB join).
  - `ff_rankings('draft')` (DynastyProcess mirror of FantasyPros ECR, daily; filter `page_type == 'redraft-overall'`).
  - Sleeper projections `api.sleeper.com/projections/nfl/2026?season_type=regular` (Rotowire lines; cached 1 h upstream; store `company` + `last_modified`; `gp` is a constant 18 — never use; 999 = undrafted sentinel → null ADP ≥ 999).
  - Sleeper players `/v1/players/nfl` once/day, conditional fetch on ETag (injury_status IR/PUP/Out → `known_missed_weeks`).
  - FFC ADP × 3 formats `api/v1/adp/{half-ppr|ppr|standard}?teams=10&year=2026` (updates once/day; the window is not a fixed 7 days — store `meta.start_date/end_date/total_drafts` per snapshot).
  - Yahoo pub ADP `pub-api-ro.fantasysports.yahoo.com/fantasy/v2/game/nfl/players;sort=AR;start=N;count=100;out=draft_analysis?format=json` (~6 pages of 100 + DEF + K passes, 2 s spacing, once/day, **never during the draft**).
- [ ] `ingest check-ids` (re-run after every ingest): top-300 ECR, top-300 Sleeper projection rows, top-400 Yahoo pool, every 2026 R1–R4 QB/RB/WR/TE pick resolve; `unmatched.csv` < 3% and reviewed.
- [ ] Review the snapshot registry: every source has a new `raw_snapshots` row with a row count today, or is explicitly marked "reused last good snapshot" in the job log.
- [ ] `recompute` (no network, must finish in < 5 min): scoring → features → market composite (nightly OLS refit of `sd_adp` on FFC) → ranking → WHY → new `ranking_runs` row (git sha, league-config hash, seed hashes, input snapshot ids).
- [ ] Model guard: Spearman(our overall rank, ECR) on top-150 ≥ 0.8; every top-100 player incl. rookies has ≥3 bullets. A failing guard does not replace the pinned run.
- [ ] Curated tables: if any seed YAML changed (`coaching_changes`, `qb_situations`, `ol_changes`, `known_missed_weeks`, `id_overrides`), every changed row has `source_url`, `confidence`, `last_checked`; reload and note in `docs/decisions.md`.

## Failure handling — serve the last good snapshot

Principle (from the plan): hash-deduped immutable snapshots; the app runs on the last good snapshot; multiple ADP sources.

- A source that fails (HTTP error, shape assertion, empty payload, `unmatched.csv` ≥ 3%) is logged with the error and skipped; the job continues with the other sources and `recompute` reads that source's **last good** `raw_snapshots` row.
- The board never reads live source data; it serves the **pinned run_id** from `draft_snapshot`. A failed daily job therefore changes nothing the board shows.
- The composite market is a mean of the available ranks with `n` and std stored; losing one ADP source lowers `n` but does not null the composite.

Checklist when a source fails:

- [ ] Read the job log: which source, which endpoint, HTTP status or assertion message.
- [ ] Confirm `recompute` used the last good snapshot for that source (snapshot id and `fetched_at` are in the new `ranking_runs` row) and note the age of that snapshot.
- [ ] If an ADP/ECR source is stale on the freeze evening, decide explicitly (log the snapshot age and the decision in `docs/decisions.md`) whether to freeze anyway; the composite still works with the remaining sources.
- [ ] Do not hot-fix a parser during the draft; manual mode and the frozen run are the fallback.
- [ ] Unofficial endpoints (Sleeper projections, Yahoo pub, FFC) may change or block without notice; if one changes shape, the shape assertion fails and the last good snapshot is used — file the fix for after the draft.

## Freeze procedure (evening before the draft, no later than Sep 9 23:00)

- [ ] Run the full daily-jobs sequence above (`ingest all` → `ingest check-ids` → `recompute` → guards).
- [ ] Confirm `config/league.yaml` is final (real scoring from Yahoo League → Settings, roster slots, bench, teams, keeper rules, draft date/slot) and all known keepers are entered in `keepers` (manual, or captured from Yahoo pre-draft `draftresults` if 8b shipped).
- [ ] Pin the run: write `draft_snapshot` (pinned run_id + league-config hash).
- [ ] Record in `docs/decisions.md`: freeze timestamp, run_id, config hash, git sha, seed hashes, input snapshot ids per source, guard results.
- [ ] Verify: restart the backend and confirm the board serves that run_id and the recorded config hash.
- [ ] Verify the refusal path: change any value in `config/league.yaml`, confirm the board refuses to serve (config hash mismatch), revert, confirm it serves again. The draft board serves a pinned run_id and refuses to serve if the config hash changed without an explicit re-freeze.
- [ ] Export the full-pool CSV from the frozen run and keep it as the offline fallback for draft day.
- [ ] Re-freeze only if required (explicit, logged): a re-freeze repeats this list and appends a new entry in `docs/decisions.md` with the reason (e.g. day-9 curated edits, a late keeper change).

## Post-kickoff guard (on and after Sep 10)

After Sep 10 every ingest requires `--post-kickoff` (upstream semantics change to ROS); parsers assert expected shape (FP week == 0, Sleeper week null, `page_type == 'redraft-overall'`) and refuse to overwrite the frozen run.

- [ ] Without `--post-kickoff`, `ingest` exits non-zero on or after 2026-09-10 with a message naming this runbook section.
- [ ] Shape assertions run on every parse regardless of date: FantasyPros/ECR mirror week == 0 and `page_type == 'redraft-overall'`; Sleeper projections week null (season totals, not weekly); FFC `meta.type` matches the requested format.
- [ ] Any ingest, with or without `--post-kickoff`, refuses to overwrite the frozen `draft_snapshot` run; a new run is only pinned by the explicit re-freeze step above.
- [ ] Every nflreadpy call passes explicit seasons; `ingest all` runs green with the clock mocked to 2026-09-11 (Phase 1a gate test) — re-run this test before the freeze.
- [ ] If the draft itself is on or after Sep 10, do not run any ingest on draft day; serve the frozen run.

## Draft-day checklist

Preparation (draft_time − 60 min):

- [ ] Start Postgres (docker, :5432), then `uv run fastapi dev` in `backend/` and `pnpm dev` in `frontend/`; open the board.
- [ ] Board top bar (`docs/spec/ui.md` §2) shows the frozen run_id and config hash matching `docs/decisions.md`.
- [ ] Draft slot in `config/league.yaml` matches the Yahoo draft order (late-bound: set it now if it was "TBD"); `pick_schedule` shows my picks and "my next pick in N".
- [ ] All keepers for all 10 teams entered; each keeper-consumed slot shows as `is_keeper_slot` and the owning team is skipped in that round.
- [ ] Offline fallback CSV (frozen run) open in a second window.
- [ ] If 8b shipped: token refreshed (< 55 min old), poller started at draft_time − 60 min, cadence 60 s in `predraft`; confirm it captured the draft order and the pre-filled keeper rows, and that SSE is connected on the board.
- [ ] Confirm no daily job is scheduled during the draft window (no Yahoo pub pool pull, no Sleeper players pull, no roster/player calls).

During the draft:

- [ ] Poller (if live) runs at 10–15 s in `draft`; on-the-clock = lowest unfilled pick.
- [ ] Manual mode is always available: d = drafted, m = my pick, undo for manual rows; j/k to move.
- [ ] If the banner "switched to manual mode" appears (3 consecutive poll failures, backoff from 30 s on 4xx/5xx/999), keep entering picks by hand; do not restart the poller mid-round unless the failure cause is known.
- [ ] Use VONA top-3 per position and P(avail) at each of my picks; K/DST are excluded from VONA before round 12 and follow the "last two rounds" rule.
- [ ] Watch the bye-stack warning (≥3 projected starters sharing a bye; 2026 week 11 has six teams).
- [ ] Any Yahoo pick whose `player_key` did not resolve appears in the banner — fix it by manual entry, never by editing the pool during the draft.

After the draft:

- [ ] Poller stops at `postdraft` (if live); confirm every `pick_schedule` slot has a `draft_picks` row.
- [ ] Export the final `draft_picks` CSV and keep it with the frozen run id.
- [ ] Note in `docs/decisions.md`: whether live sync was used, failures seen, and anything to fix post-draft.

## Keeper deadline

- Rules: keeper league; keepers cost the round they were drafted in last year; Yahoo assigns each keeper to a round and that team is skipped in that round. Max keepers per team, whether the commissioner has already run "Assign Keeper Players", and the keeper deadline are day-1 inputs from Derek.
- Deadline: ≥1 h before draft, commissioner approval.
- Helper: `keeper_surplus = VORP(player) − expected VORP of the best player available at the cost-round pick under room ADP`, ranked with WHY bullets (Phase 9, day 7).

- [ ] Run the keeper-value helper on Derek's candidate list (manual list; `team/{key}/roster` if OAuth works) and deliver the ranked table before the deadline.
- [ ] After Derek submits keepers in Yahoo, enter them in `keepers` (team_slot, player, cost_round) and confirm `pick_schedule` marks the consumed slots.
- [ ] Enter every other team's announced keepers as they become known (manual primary; Yahoo pre-draft `draftresults` rows if 8b shipped); baselines, room ADP, P(avail) and VONA recompute on every keeper edit.
- [ ] If keepers change after the freeze, re-run `recompute` and re-freeze explicitly (logged) — keeper edits change the baselines that the frozen run depends on.

## Derek's actions

- Provide the exact draft date/time, draft slot, keeper deadline, max keepers per team and whether the commissioner has run "Assign Keeper Players" (day-1 inputs).
- Submit keepers in Yahoo before the keeper deadline (≥1 h before draft, commissioner approval) and report them so they can be entered.
- Report other teams' keepers as they are announced.
- On the freeze evening, confirm `config/league.yaml` is final and approve the freeze; approve any re-freeze explicitly.
- On draft day, sit at the board with the offline CSV open and enter picks by hand if the live poller switches to manual mode.
