# Live draft spec — Yahoo sync (Phase 8b) and manual mode

Purpose: how the tool learns about picks during the draft — Yahoo OAuth setup, the raw `draftresults` poller (cadence, backoff, manual fallback), keeper rows, the test harness options, and which parts are still unverified.

Status: Not started

Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` (Phase 0 Yahoo steps, Research → Yahoo API, Phase 8b, Phase 9, Risks). Board contract: `docs/spec/api.md` §3.8–3.11.

## 1. Gating (from the plan)

Live sync is **post-MVP** and double-gated. Plan: "**8b (day 8, only if Yahoo access approved AND a harness exists)**" and "If neither exists by day 8, live sync is dropped for this draft." Day 8 is Mon Sep 7 (Track A = 8b; otherwise Track B = ESPN injuries / skill movement / SoS display / polish).

**Manual mode is first-class and identical** (Decisions: "Live auto-sync from Yahoo **gated** on approval + a verified test harness; manual mode is first-class and identical"). Everything in `docs/spec/ui.md` §5 works with zero Yahoo calls; the poller only adds `source: "yahoo"` rows to the same `draft_picks` table through the same service function the API uses.

Independent of 8b: Yahoo **site-wide ADP** comes from the unauthenticated `pub-api-ro` endpoint (Phase 1a/4-lite) and needs no OAuth — "Yahoo ADP via the public endpoint regardless" (Risks).

## 2. Yahoo OAuth — setup steps (Phase 0, day 1)

In order (plan, Phase 0, verbatim sequence):

1. **Create the app** at developer.yahoo.com — Installed Application, permission **Fantasy Sports Read**, redirect URI `https://localhost:8080`. Store Client ID / Client Secret in `backend/.env` (`YAHOO_CLIENT_ID`, `YAHOO_CLIENT_SECRET`; `.env.example` lists the names, values never committed).
   - *Unverified*: the "Installed Application / `https://localhost:8080` / Fantasy Sports Read" specifics are library-convention guidance (research: developer.yahoo.com/apps/create redirects to login; not stated on any fetched Yahoo page). Use whatever the create-app form actually offers and record the choice in `docs/decisions.md`.
2. **Submit the access application** at sports.yahoo.com/developer/access **with the Client ID**, use case "personal, single league, read-only draft monitor". Record the submission date in `docs/decisions.md`. Verified facts: Yahoo reviews every application, "including where access is limited to personal or single league use"; the API is read-only; "incomplete or insufficiently detailed submissions … will be closed without further correspondence"; **no review SLA is published**.
3. **Same day, smoke test**: run the `yahoo_oauth` consent flow (browser login, paste the code) and call `GET https://fantasysports.yahooapis.com/fantasy/v2/users;use_login=1/games;game_keys=nfl/leagues?format=json`. Outcome A: 200 with Derek's league(s) → an unapproved app is *not* blocked; continue to the mock-draft visibility spike (§7). Outcome B: 401/403 → log it; live sync waits on approval.
4. **Library decision** (plan): `yahoo_oauth` for tokens + `httpx` raw JSON (`yahoo_oauth` is archived; acceptable for token exchange/refresh only). `yahoo_fantasy_api` (2.12.3) / `yfpy` (17.0.0) are optional readers only — they **drop unfilled `draftresults` rows**, which is exactly what the pick schedule needs, so they are never on the polling path.

### Token handling (Phase 8b)

- Single token owner: the FastAPI process. Token JSON lives under `backend/.tokens/` (git-ignored); the CLI and tests read it, never refresh it concurrently.
- Access tokens expire in 1 h (research). **Proactive refresh at < 55 min** of token age, by the poller loop, before the request that would fail. Refresh tokens are long-lived.
- Gate item: "OAuth round-trip survives an hour" — a test that starts the poller, waits > 60 min in `predraft` cadence, and asserts every request was 200 and exactly one refresh happened.
- Attribution "Fantasy data provided by Yahoo Fantasy" is shown in the board footer (Yahoo API Access and Use Agreement).

## 3. Endpoints used

All under `https://fantasysports.yahooapis.com/fantasy/v2/`, `?format=json`, Bearer token. `league_key` (day-1 input 5) has the form `{game_key}.l.{league_id}`; the 2026 NFL `game_key` is **470** (verified via pub-api-ro); e.g. `470.l.12345`.

| Call | When | Purpose |
|---|---|---|
| `users;use_login=1/games;game_keys=nfl/leagues` | day-1 smoke test | proves the app works; yields `league_key`, `draft_status` (predraft \| draft \| postdraft), `num_teams`, `scoring_type` |
| `league/{league_key}/settings` | once, on connect; again at draft_time − 60 min | `roster_positions[{position,count}]`, `stat_categories[{stat_id,name,display_name,position_type}]`, `stat_modifiers[{stat_id,value}]`, `uses_fractional_points`, `uses_negative_points`, `draft_type` (live \| self \| offline), `is_auction_draft`, `draft_time`. **Diff-only vs `config/league.yaml` — report, never overwrite** (plan: "raw `league/{key}/settings` diff vs league.yaml (report only)"; Phase 2: "validated against the raw settings payload in 8b (diff-only; never overwrites league.yaml)"). Stat-id map checked: 4 PassYd, 5 PassTD, 6 INT, 9 RushYd, 10 RushTD, 11 Rec, 12 RecYd, 13 RecTD, 18 FumLost, … |
| `league/{league_key}/draftresults` | polled (§4) | the pick feed: every pick slot, including unfilled rows and pre-filled keeper rows |
| `team/{team_key}/roster` | day 7 only, if OAuth works | Derek's roster for the keeper-value helper (Phase 9); the manual list is the fallback. `team_key` = `{league_key}.t.{n}` |

**Never during the draft**: no roster, players, teams or settings calls once `draft_status == draft` (plan: "no roster/player calls during the draft"). Player resolution is a **dict lookup on the pre-resolved Yahoo pool** (Phase 1a: Yahoo pub pool ~6 pages × 100 + DEF + K, fetched once/day, never during the draft; `players.yahoo_id = coalesce(ff_playerids.yahoo_id, stats_id)` plus `seeds/yahoo_team_defense_ids.yaml` for the 32 DEF ids and `seeds/id_overrides.yaml`). A `player_key` like `470.p.40059` resolves by its numeric tail `40059` → `players.yahoo_id`. An unresolved key is persisted with `player_id NULL` and surfaced as a board banner "unresolved Yahoo pick 470.p.NNNNN — enter manually"; it is never guessed by name mid-draft.

### `draftresults` payload shape

Documented/wrapper-visible fields per row: `pick`, `round`, `team_key`, `player_key`, `cost` (auction only). Plan (research row): the raw endpoint "returns every pick slot incl. **unfilled** rows (the live pick schedule: draft order, keeper holes, who is on the clock)". Persist **every** row (`player_key` nullable, `is_keeper`); the exact JSON nesting (`fantasy_content.league[1].draft_results.{i}.draft_result`) is captured from the first real payload into `backend/tests/fixtures/yahoo/draftresults_*.json` with PROVENANCE, and the parser is written against that fixture, not against documentation.

Mapping into local tables:

| Yahoo row | Local |
|---|---|
| `pick` | `draft_picks.overall_pick` / `pick_schedule.overall_pick` (the plan's `draft_picks(pick, …)`) |
| `round` | `round` |
| `team_key` → order of first appearance in round 1 | `team_slot` (1–10) and `leagues.draft_order` |
| `player_key` present + row present before `draft_status == draft` | keeper row → `keepers(team_slot, player, cost_round = round, status = approved, source = yahoo)` and `draft_picks.is_keeper = true`, `pick_schedule.is_keeper_slot = true` |
| `player_key` present, appeared during `draft` | `draft_picks` row, `source = yahoo` |
| `player_key` absent | unfilled slot → `pick_schedule` row only; lowest such `pick` = on the clock |

## 4. Polling cadence, backoff, manual fallback (Phase 8b, verbatim numbers)

- **Start** at `draft_time − 60 min` (`draft_time` from settings, cross-checked with day-1 input 6).
- **`predraft`: every 60 s.** Captures the draft order and the pre-filled keeper rows; writes `leagues.draft_order`, `keepers`, `pick_schedule`; emits SSE `schedule`/`keeper` events.
- **`draft`: every 10–15 s** (default 12 s *(impl detail within the plan's range)*). Each poll diffs rows against `draft_picks`; a newly filled `pick` becomes a `source: "yahoo"` row and an SSE `pick` event. **On-the-clock = lowest unfilled pick.** A row that changed player (Yahoo-side correction) updates the local row and emits `pick` again; a row that became unfilled again emits `undo`.
- **Stop** when `draft_status == postdraft` (one final full persist, then the poller exits and `mode` stays `yahoo` with a "draft complete" banner).
- **Backoff**: exponential from **30 s** on any 4xx/5xx or Yahoo's **999** throttle response (`999` = "Unable to process request at this time" — Yahoo's rate-limit/blocked reply; Yahoo publishes no limits, only that apps making "too many requests" are temporarily blocked). Sequence 30 s → 60 s → 120 s *(the 120 s cap is an impl detail; the plan fixes only the 30 s start)*.
- **After 3 consecutive failures → switch to manual mode with a banner** (`DraftState.mode = manual`, `banner = "Yahoo sync lost at HH:MM — enter picks manually"`). The poller stops; polling resumes only by explicit operator action (`draft poll --resume`, same rule as `docs/phases/08-availability-live.md` and the runbook's "do not restart the poller mid-round unless the failure cause is known"). On resume it reconciles: Yahoo rows fill slots with no manual row; a manual row on a slot Yahoo shows differently raises a logged `conflict` banner and is never silently overwritten (data-model rule: "a Yahoo row never overwrites a newer manual row for the same pick without a logged conflict"); `mode` flips back to `yahoo` after the first successful poll.
- Every poll is one request; request timing is logged (`live_polls` log lines with status, latency, rows, new picks) so the 15 s detection gate can be measured from logs.
- Every raw payload is also written as an immutable snapshot under `data/raw/yahoo/draftresults/{YYYYMMDDTHHMMSSZ}_{sha8}.json` (hash-deduped — unchanged payloads are not re-stored) and registered in `raw_snapshots`.

State machine:

```
idle ──(draft_time − 60 min)──▶ predraft (60 s) ──(draft_status=draft)──▶ draft (10–15 s) ──(postdraft)──▶ done
   ▲                                │                                        │
   └────────── manual ◀── 3 consecutive failures (backoff 30 s → 60 s → 120 s) ┘   (retry continues; success → back)
```

### Manual mode (always available)

- `POST /api/draft/picks`, `/api/draft/undo`, `/api/keepers` per `docs/spec/api.md`; the board's `d` / `m` keys.
- Dry run (Phase 9, day 9 Tue Sep 8): "scripted pick feed in real Yahoo-ADP order (plus the poller if 8b shipped): undo, keeper holes in pick counts, P(avail)/VONA updates, CSV". The feed is a CLI (`draft replay --feed <csv> --interval 3s`) that posts picks through the public API so the same code path is exercised.
- Gate item "manual mode identical": the same fixture draft replayed once through the poller (fixture payloads) and once through the manual API must produce byte-identical `draft_picks` / `pick_schedule` tables except `source` and `picked_at`.

## 5. Keeper rows

- League rules (Decisions): keeper league, "keepers cost the round they were drafted in"; "Yahoo assigns each keeper to a round; that team is skipped in that round". Keeper list is **not final** and is entered manually (primary) or captured from Yahoo pre-draft `draftresults` if OAuth works.
- Yahoo exposes keepers two ways (plan): pre-filled `draftresults` rows before the draft, and `is_keeper` on **league-scoped** player objects (`league/{key}/players…`). The game-scoped pub-api-ro pool also carries an `is_keeper` key, but it is not league-specific — never read keepers from it.
- Precedence (same rule as `docs/phases/08-availability-live.md`): a `source: yahoo` keeper row observed in `predraft` fills a team/round that has no manual row; where a manual row exists (`declared` or `approved`, per `keepers.status` in `docs/spec/data-model.md`) and disagrees with Yahoo, the manual row is kept, the diff is logged, and a `conflict` banner asks Derek to resolve it in the Keepers tab — never a silent overwrite.
- Whether the commissioner has run "Assign Keeper Players" (day-1 input 4) decides whether keeper rows can exist in `draftresults` before draft day at all; until then the manual list is the only source and the keeper deadline (≥ 1 h before the draft, commissioner approval) is the hard stop for edits.

## 6. SSE to the board

`GET /api/draft/stream` (`docs/spec/api.md` §3.11): events `pick`, `undo`, `keeper`, `schedule`, `state`, `heartbeat`. The poller and the manual mutation path publish to the same in-process broker so a second tab (or the CLI `draft tail` command) sees both. Gate item: "SSE delivers".

## 7. Test harness (required before 8b is enabled)

Plan: "Yahoo mock drafts are not verified API-visible → test harness must be proven"; options, in order:

1. **Mock-draft visibility spike** (day 1, same day as the smoke test if calls work): Derek joins a Yahoo mock draft; the CLI calls `users;use_login=1/games;game_keys=nfl/leagues` and, if the mock appears as a league, `league/{mock_key}/draftresults` during the mock. Log the result in `docs/decisions.md` either way. *Unverified*: whether mock drafts are visible via the API at all.
2. **Throwaway private Yahoo league** with autopick and a **scheduled live draft on day 8–9** (Mon Sep 7 / Tue Sep 8) if mocks are invisible: Derek creates a 10-team private league, fills it with autopick, schedules the draft, and the poller runs against it end to end (predraft → draft → postdraft) while the fixture recorder saves every payload.
3. **Neither by day 8 → live sync is dropped for this draft** (Track B instead); manual mode + the day-9 scripted dry run is the draft-day path.

Fixture policy (plan): real extracts only, under `backend/tests/fixtures/yahoo/` with `PROVENANCE.md` (url, fetched_at, sha256). Fixtures needed for the gate: one `predraft` payload with unfilled rows and ≥1 keeper row; one mid-`draft` payload; one `postdraft` payload; one 999/throttle response body.

## 8. Unverified items (explicitly labeled)

| Item | Status | Where it gets verified |
|---|---|---|
| `draftresults` returns picks-so-far **mid-draft** | *Plausible, unverified* — wrapper docstring says so; official docs only show postdraft samples; research did not exercise the API (needs OAuth) | harness (§7) — gate "new pick detected within 15 s" |
| Raw `draftresults` includes **unfilled** rows and keeper rows before the draft | Stated in the plan's research summary; JSON nesting not captured yet; wrappers are known to drop unfilled rows | first real `predraft` payload → fixture test "unfilled + keeper rows" |
| Yahoo **mock drafts** visible through the API | *Unverified* | day-1 spike (§7.1) |
| Unapproved app can call the API at all | *Unknown* (no SLA; review is mandatory) | day-1 smoke test (§2.3) |
| App-create form specifics (Installed Application, `https://localhost:8080`, Fantasy Sports Read) | *Unverified* (login-gated page) | Derek's day-1 app creation; record actual choices |
| Rate limits / 999 thresholds | *Unpublished* by Yahoo | defensive cadence (≥ 10 s) + backoff; log every non-200 |
| `draft_time` timezone/format in settings | *Unverified* | settings fixture; cross-check with day-1 input 6 |
| Exact Yahoo stat_id ↔ league.yaml map | *Partially verified* (ids listed in research "verify from the settings payload") | settings diff, report only |

## 9. Checklist

- [ ] Yahoo app created; `YAHOO_CLIENT_ID` / `YAHOO_CLIENT_SECRET` in `backend/.env`; actual app-type/redirect choices logged in `docs/decisions.md`
- [ ] Access application submitted with the Client ID and use case "personal, single league, read-only draft monitor"; submission date logged in `docs/decisions.md`
- [ ] `yahoo_oauth` consent flow completed; token JSON under `backend/.tokens/` (git-ignored)
- [ ] Smoke test: `users;use_login=1/games;game_keys=nfl/leagues` result (200 vs 401/403) logged in `docs/decisions.md`
- [ ] Mock-draft visibility spike run and its result logged
- [ ] Decision recorded on day 8 (Mon Sep 7): Track A (8b) or Track B, with the two gating conditions checked explicitly
- [ ] `league/{key}/settings` fetched once; diff vs `config/league.yaml` printed by `league settings-diff`; `league.yaml` byte-identical afterwards
- [ ] `draftresults` parser written against a real fixture with unfilled rows and ≥1 keeper row; test asserts row count = teams × rounds, keeper rows → `keepers` + `is_keeper_slot`, on-the-clock = lowest unfilled pick
- [ ] Poller starts at `draft_time − 60 min`, uses 60 s in `predraft`, 10–15 s in `draft`, stops at `postdraft` (unit test with a fake clock and fixture sequence)
- [ ] Backoff test: 4xx/5xx/999 responses produce 30 s → 60 s → 120 s waits; third consecutive failure sets `mode = manual` and a banner; the next success clears it
- [ ] No roster/players/teams/settings request is issued while `draft_status == draft` (assert on the httpx transport mock)
- [ ] Player resolution is a dict lookup on the pre-resolved Yahoo pool; an unknown `player_key` is persisted with null `player_id` and raises a banner
- [ ] Every poll payload is snapshot to `data/raw/yahoo/draftresults/` (hash-deduped) and registered in `raw_snapshots`
- [ ] Token refresh happens proactively before 55 min; a > 60 min poller run against the harness shows all 200s and exactly one refresh
- [ ] SSE: a connected board tab receives a `pick` event within one poll interval of a new row
- [ ] Harness run (mock or throwaway league): at least one new pick detected and shown on the board within 15 s of being made in Yahoo; timing taken from poll logs
- [ ] Manual-mode identity test: fixture draft replayed via poller and via the manual API yields identical `draft_picks` / `pick_schedule` except `source` / `picked_at`
- [ ] Day 9 dry run executed with the scripted real-Yahoo-ADP pick feed (plus the poller if 8b shipped); undo, keeper holes, P(avail)/VONA updates and CSV verified
- [ ] "Fantasy data provided by Yahoo Fantasy" attribution present in the board footer and README

## Gate

Phase 8b: "fixture test with unfilled + keeper rows; OAuth round-trip survives an hour; new pick detected within 15 s in the harness; SSE delivers; manual mode identical."

## Derek's actions

- Day 1: create the Yahoo app at developer.yahoo.com (Installed Application, Fantasy Sports Read, redirect `https://localhost:8080` — or whatever the form actually offers) and paste Client ID / Secret into `backend/.env`.
- Day 1: submit the access application at sports.yahoo.com/developer/access with the Client ID and the use case "personal, single league, read-only draft monitor"; tell me the submission date for `docs/decisions.md`.
- Day 1: complete the `yahoo_oauth` browser consent when the CLI prompts (paste the code back).
- Day 1: join a Yahoo mock draft while the visibility spike runs.
- Provide `league_key` (day-1 input 5, from the league URL), the exact draft date/time (input 6), and the keeper rules incl. whether "Assign Keeper Players" has been run and the keeper deadline (input 4).
- Day 8–9 if mocks are invisible and access is approved: create a throwaway private 10-team Yahoo league with autopick and schedule its live draft so the poller can be tested end to end.
- Draft day: keep the Yahoo draft room open on the same account; if the banner switches to manual mode, enter picks with `d` / `m` on the board.
