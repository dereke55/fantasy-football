# Phase 5 — Curated team context

Seed and serve the three hand-curated 2026 team-context tables (coaching/play-caller changes, QB situations, OL changes) that produce WHY tag bullets and the `new_play_caller` / `qb_uncertain_team` flags — tags only, no multipliers.

Status: Seeds written and verified 2026-08-29 (backend/seeds/*.yaml); loader, team_context API, flags and day-9 re-check still to do

Calendar: day 5 (Fri Sep 4) — part of the **draft-day minimum**; Derek's re-check on day 9 (Tue Sep 8). Source of truth: `/Users/derek/.claude/plans/we-are-going-to-ethereal-newt.md` → "Phase 5 — Curated team context". Specs: `docs/spec/data-model.md` (curated tables + `team_context`), `docs/spec/api.md` §3.5, `docs/spec/why-rules.md` rules #20–#23, `docs/spec/ranking-model.md` §3b/§11.

## Scope (from the plan)

- Three YAML tables, 32 rows each, every row with `source_url`, `confidence`, `last_checked`, seeded from the verified research: `coaching_changes` (hc, hc_new, oc, oc_new, play_caller, play_caller_new), `qb_situations` (projected_qb1, status: settled/competition/injury_return, changed_from_2025), `ol_changes` (delta −2..+2, notes).
- They produce WHY tag bullets and feed only the `new_play_caller` / `qb_uncertain_team` flags — **no multipliers in MVP**. Edited as YAML + reload.
- Team context has no structured source (play-caller is not in any dataset). `games.csv` 2026 coach columns are stale for 3 teams (ARI still lists Jonathan Gannon, ATL Raheem Morris, BUF Sean McDermott; LV is misspelled "Klint Kubliak") — **never derive HC changes from it**.
- Vendor projections already embed 2026 context/age/injury → context adjustments must not multiply vendor numbers (this phase never touches the Sleeper component).
- CUT for this draft: offense-environment score, win totals, implied totals, context multipliers, curated-table editors in the UI (edit YAML + reload only).

## Files and schema

| File | Columns (all rows also carry `team`, `source_url`, `confidence` (0–1), `last_checked` (YYYY-MM-DD)) | Feeds |
|---|---|---|
| `backend/seeds/coaching_changes.yaml` | `hc`, `hc_new` (bool), `oc`, `oc_new` (bool), `play_caller`, `play_caller_new` (bool) | flag `new_play_caller`; WHY bullet "New play-caller (<name>) — tag only" |
| `backend/seeds/qb_situations.yaml` | `projected_qb1`, `status` ∈ {settled, competition, injury_return}, `changed_from_2025` (bool) | flag `qb_uncertain_team` (status ≠ settled); WHY bullet with projected QB1 + status |
| `backend/seeds/ol_changes.yaml` | `delta` ∈ {−2, −1, 0, +1, +2}, `notes` | bust risk signal "OL delta ≤ −1" (Phase 6); WHY bullet with delta + notes |

Loaded into the curated tables `coaching_changes`, `qb_situations`, `ol_changes`; the derived `team_context` table joins all three per team and is what `GET /api/team_context` serves. Seed-file hashes are recorded on every `ranking_runs` row.

## Verified 2026 seed facts (as of 2026-08-29)

Every row below becomes a seed row (or part of one) with its `source_url`. `confidence` starts at the value in the table; fansports "Authority" percentages are stored as-is for play-caller rows. Verifier notes are from the adversarial check of the research on 2026-08-29.

### New head coaches (10) — `coaching_changes.hc_new = true`

| Team | 2026 HC | Replaced | Play-caller 2026 | confidence | source_url |
|---|---|---|---|---|---|
| ARI | Mike LaFleur | Jonathan Gannon (fired Jan 5) | LaFleur (HC) calls plays; OC Nathaniel Hackett assists design | 0.95 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.nfl.com/news/cardinals-oc-nathaniel-hackett-aims-to-help-first-year-hc-mike-lafleur-be-the-best-version-of-himself |
| ATL | Kevin Stefanski | Raheem Morris (fired Jan 4) | OC Tommy Rees calls plays (called CLE plays from Wk 10 2025) | 0.90 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.nbcsports.com/nfl/profootballtalk/rumor-mill/news/kevin-stefanski-says-tommy-rees-will-call-offensive-plays-for-falcons |
| BAL | Jesse Minter | John Harbaugh (fired Jan 6) | OC Declan Doyle (ex-CHI OC) | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.fansports.com/nfl/play-callers |
| BUF | Joe Brady | Sean McDermott (fired Jan 19; Brady promoted from OC) | Brady (HC) calls plays; OC Pete Carmichael Jr. (his game-plan/backup role is unverified) | 0.90 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.si.com/nfl/bills/onsi/breaking-news-buffalo-bills-plan-for-offensive-play-caller-under-joe-brady-revealed |
| CLE | Todd Monken | Kevin Stefanski (fired Jan 5) | Monken (HC) calls plays; OC Travis Switzer has no play-calling experience | 0.90 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.si.com/nfl/browns/onsi/news/browns-head-coach-todd-monken-reveals-who-will-be-calling-plays-on-offense-01kgj9t3ezar |
| LV | Klint Kubiak | Pete Carroll (fired Jan 5) | Kubiak (HC); OC Andrew Janocko | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.fansports.com/nfl/play-callers |
| MIA | Jeff Hafley | Mike McDaniel (fired Jan 8) | OC Bobby Slowik | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.fansports.com/nfl/play-callers |
| NYG | John Harbaugh | Brian Daboll (fired Nov 10 2025; Mike Kafka interim) | OC Matt Nagy | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.fansports.com/nfl/play-callers |
| PIT | Mike McCarthy | Mike Tomlin (resigned Jan 13) | McCarthy (HC) calls plays; OC Brian Angelichio handles scheme/game-plan | 0.90 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://steelersdepot.com/2026/04/new-steelers-oc-brian-angelichio-explains-how-dynamic-will-work-with-mike-mccarthy-as-play-caller/ |
| TEN | Robert Saleh | Brian Callahan (fired Oct 13 2025) | OC Brian Daboll | 0.90 | https://en.wikipedia.org/wiki/2026_NFL_season ; https://www.espn.com/nfl/story/_/id/49619516/why-titans-believe-brian-daboll-maximize-cam-ward-potential |

Returning HCs (22) and the full 32-row OC/DC lists come from https://en.wikipedia.org/wiki/List_of_current_National_Football_League_head_coaches , https://en.wikipedia.org/wiki/List_of_current_NFL_offensive_coordinators (21 OCs with since = 2026) and https://en.wikipedia.org/wiki/List_of_current_NFL_defensive_coordinators . The Pro Football Rumors tracker (https://www.profootballrumors.com/2026/02/2026-nfl-offensive-defensive-coordinator-search-tracker) is a Feb-23 candidate tracker — seed only, not final. Note the plan says "18–21 new OCs": Wikipedia counts 21, the FOX tracker 18.

### New play-caller despite the same HC (9, "re-check") — `coaching_changes.play_caller_new = true`, `hc_new = false`

| Team | 2026 play-caller | 2025 play-caller | confidence | source_url |
|---|---|---|---|---|
| DEN | OC Davis Webb (primary; Payton "still involved, will call some plays") | HC Sean Payton | 0.75 (fansports Authority) | https://www.nfl.com/news/broncos-coach-sean-payton-handing-play-calling-duties-to-new-oc-davis-webb |
| CAR | OC Brad Idzik (first play-calling job) | HC Dave Canales | 0.74 (fansports Authority) | https://www.panthers.com/news/dave-canales-offensive-coordinator-brad-idzik-to-call-plays-in-2026 |
| PHI | OC Sean Mannion (first-time play-caller; Sirianni retains oversight) | OC Kevin Patullo | 0.78 (fansports Authority) | https://www.nbcsportsphiladelphia.com/nfl/philadelphia-eagles/nick-sirianni-not-concerned-sean-mannion-inexperienced-offensive-coordinator/742483/ |
| DET | OC Drew Petzing (ex-ARI OC) | OC John Morton | 0.72 (fansports Authority) | https://www.fansports.com/nfl/play-callers |
| SEA | OC Brian Fleury | OC Klint Kubiak | 0.85 | https://www.fansports.com/nfl/play-callers |
| WAS | OC David Blough | OC Kliff Kingsbury | 0.85 | https://www.fansports.com/nfl/play-callers |
| TB | OC Zac Robinson (ex-ATL OC) | OC Josh Grizzard | 0.85 | https://www.fansports.com/nfl/play-callers |
| LAC | OC Mike McDaniel | OC Greg Roman | 0.85 | https://www.fansports.com/nfl/play-callers |
| NYJ | OC Frank Reich | OC Tanner Engstrand | 0.85 | https://www.fansports.com/nfl/play-callers |

Not new play-callers: KC (Andy Reid still calls; OC Matt Nagy → Eric Bieniemy) and CHI (Ben Johnson still calls; OC Declan Doyle → Press Taylor) → `oc_new = true`, `play_caller_new = false`. The fansports page was last updated July 9 2026 and carries an "Authority" column (DET 72%, CAR 74%, ATL/DEN 75%, PHI 78% least certain) — re-check those five on day 9. 4for4 counts 18 teams with a new play-caller (https://www.4for4.com/2026/preseason/how-play-calling-tendencies-affect-fantasy-football); the 10 new-HC teams + these 9 = 19 — reconcile on day 9.

### QB rooms (as of 8/29) — `qb_situations`

| Team | projected_qb1 | status | changed_from_2025 | Note (verifier-corrected) | confidence | source_url |
|---|---|---|---|---|---|---|
| ATL | Tua Tagovailoa / Michael Penix Jr. — undecided | competition | true (Penix → TBD) | Stefanski names a starter only when the depth chart must be published; Penix (partial ACL, season-ending surgery announced Nov 19 2025) back to 11-on-11 but sat the finale; reports lean Penix | 0.60 | https://www.nfl.com/news/michael-penix-jr-out-falcons-preseason-finale-falcons-qb1-decision |
| LV | Kirk Cousins — expected, not announced | competition | true (Geno Smith → Cousins; Fernando Mendoza #1 pick) | Kubiak declined to name a starter after the Aug 27 finale; RotoWire 8/29 2:30 PM PDT "Expected to be named starter" (Matt Zenitz, CBS); Mendoza reported as likely QB3 | 0.70 | https://www.rotowire.com/rss/news.php?sport=NFL ; https://www.upi.com/Sports_News/NFL/2026/08/28/Klint-Kubiak-name-starter-Raiders-Mendoza-Cousins/9881787916966 |
| KC | Patrick Mahomes | injury_return | false | Torn ACL + LCL Dec 14 2025; received full clearance by the start of camp (late July); still listed Questionable on ESPN's feed 2026-08-29 with Rapoport "on track to start Week 1" (Sept 14 vs DEN); Justin Fields is the fallback | 0.80 | https://www.profootballrumors.com/2026/08/chiefs-qb-patrick-mahomes-remains-on-track-for-week-1 |
| MIN | Kyler Murray | settled | true (J.J. McCarthy → Murray) | Named Week 1 starter Aug 11; 1-yr vet-min deal after ARI release Mar 11 | 0.95 | https://www.nfl.com/news/vikings-name-kyler-murray-starting-week-1-quarterback-for-2026-season |
| CLE | Deshaun Watson | settled | true (Sanders/Flacco → Watson) | Named Aug 24 over Shedeur Sanders (backup); missed all of 2025 (Achilles re-rupture) | 0.90 | https://www.nfl.com/news/browns-deshaun-watson-starting-qb-week-1-2026-season |
| ARI | Jacoby Brissett | settled | true (Murray → Brissett) | Contract reworked Jul 26 ($10M raise to $15.5M 2026 salary, incentives to $21M — not "$15M guaranteed"); Gardner Minshew backup; rookie Carson Beck (R3 #65) | 0.90 | https://www.azcardinals.com/news/jacoby-brissett-cardinals-work-out-new-contract |
| NYJ | Geno Smith | settled | true (Fields/Taylor → Geno, via LV trade Mar 11) | Glenn: "No doubt about it. He's our guy."; Jets open AT Tennessee Sept 13 | 0.95 | https://www.nfl.com/news/jets-hc-aaron-glenn-has-no-doubt-geno-smith-will-be-new-york-s-starter-he-s-our-guy |
| MIA | Malik Willis | settled | true (Tua → Willis, 3-yr/$67.5M from GB) | Tua released Mar 11, signed ATL Mar 13 | 0.90 | https://www.nfl.com/news/ten-best-moves-of-2026-nfl-offseason-so-far-trades-free-agent-signings-boost-rams-dolphins-steelers |
| PIT | Aaron Rodgers | settled | false | 1-yr ($22M gtd, up to $25M), reunited with McCarthy; announced May 20 that 2026 is his final season (cite the Steelers season page for that clause, not the CBS article) | 0.90 | https://www.cbssports.com/nfl/news/aaron-rodgers-steelers-return-2026-season/ |
| NO | Tyler Shough | settled | true (Rattler → Shough) | 2025 R2 pick, 5-4 as starter; Zach Wilson / Spencer Rattler compete for backup | 0.90 | https://www.espn.com/nfl/story/_/id/47541318/saints-committed-tyler-shough-starting-qb-2026 |
| IND | Daniel Jones | injury_return | false (Jones back from Achilles) | 2-yr/$88M; "absolutely" expects Week 1 — cited article is from spring OTAs; re-verify camp status day 9 | 0.70 | https://www.nfl.com/news/colts-qb-daniel-jones-achilles-absolutely-expects-to-be-ready-week-1 |
| DEN | Bo Nix | injury_return | false | Two right-ankle surgeries (Jan fracture, April bone spurs); on track for Week 1, sat the preseason opener | 0.85 | https://www.espn.com/nfl/story/_/id/49593421/bo-nix-track-sit-broncos-preseason-opener |

Remaining 20 teams: `status = settled`, `changed_from_2025 = false`, seeded from SI's running starter list (Last Updated Aug 25; KC/LV/ATL marked TBD there): https://www.si.com/nfl/every-starting-nfl-quarterback-2026-season-updated-weekly . TEN Cam Ward (settled, Trubisky backup): https://www.espn.com/nfl/story/_/id/49619516/why-titans-believe-brian-daboll-maximize-cam-ward-potential .

### OL items — `ol_changes`

| Team | Item | Suggested delta | confidence | source_url |
|---|---|---|---|---|
| CLE | R1 #9 OT Spencer Fano (Utah); + G Zion Johnson (FA from LAC), OT Tytus Howard (trade from HOU) | +1 | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_draft |
| NYG | R1 #10 G Francis Mauigoa (Miami) | +1 | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_draft |
| MIA | R1 #12 OT Kadyn Proctor (Alabama) | +1 | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_draft |
| BAL | R1 #14 G Vega Ioane (Penn St); lost C Tyler Linderbaum to LV; C Danny Pinter carted off joint practice (Pocic/Gwyn at C) | −1 | 0.80 | https://en.wikipedia.org/wiki/2026_NFL_draft ; https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| DET | R1 #17 OT Blake Miller (Clemson); C Cade Mays wrist fracture 8–10 weeks (Juice Scruggs fills in) | 0 | 0.80 | https://en.wikipedia.org/wiki/2026_NFL_draft ; https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| CAR | R1 #19 OT Monroe Freeling (Georgia) starting; LT Ikem Ekwonu on PUP (patellar tendon rupture, Week 1 unlikely); RT Taylor Moton out indefinitely (lung blood clots) | −2 | 0.85 | https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| PIT | R1 #21 OT Max Iheanachor (Arizona St) out (neck/shoulder); OT Broderick Jones traded to DAL Aug 29 | −1 | 0.80 | https://en.wikipedia.org/wiki/2026_NFL_draft ; https://www.profootballrumors.com/2026/08/cowboys-to-acquire-t-broderick-jones-from-steelers |
| HOU | R1 #26 G Keylan Rutledge (Georgia Tech); + OT Braden Smith (IND), G Wyatt Teller (CLE) | +2 | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_draft ; https://www.cbssports.com/nfl/news/familiar-faces-new-places-biggest-nfl-offseason-moves-2026/ |
| NE | R1 #28 OT Caleb Lomu (Utah); + G Alijah Vera-Tucker (3-yr/$42M) | +1 | 0.85 | https://en.wikipedia.org/wiki/2026_NFL_draft |
| LV | C Tyler Linderbaum from BAL (3-yr/$81M, record for a center) | +1 | 0.90 | https://www.cbssports.com/nfl/news/familiar-faces-new-places-biggest-nfl-offseason-moves-2026/ |
| WAS | LT Laremy Tunsil torn triceps (announced Aug 8, surgery, out indefinitely; Brandon Coleman to LT); C Nick Allegretti calf (Questionable) | −2 | 0.90 | https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| LAC | C Tyler Biadasz torn ACL (IR Aug 23; rookie Jake Slaughter to C, Kayode Awosika LG); + G Cole Strange, OT Trevor Penning | −1 | 0.85 | https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| CHI | C Drew Dalman retired (Mar); C Garrett Bradbury via trade from NE; LT Ozzy Trapilo out most of 2026 (knee); Braxton Jones projected LT; Taylor Decker (unsigned) linked | −1 | 0.75 | https://www.chicagobears.com/news/braxton-jones-excited-to-vie-for-bears-starting-left-tackle-position |
| ARI | + G Isaac Seumalo (PIT); R2 G Chase Bisontis torn MCL → IR | 0 | 0.75 | https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| JAX | Cole Van Lanen PUP, Patrick Mekari back surgery, Anton Harrison moved to LT | −1 | 0.75 | https://fantasyindex.com/2026/08/21/offensive-lines/updated-offensive-line-rankings |
| DAL | + OT Broderick Jones (trade from PIT Aug 29; spinal fusion after Nov 2025, cleared PUP, "not yet 100%") | 0 | 0.70 | https://www.profootballrumors.com/2026/08/cowboys-to-acquire-t-broderick-jones-from-steelers |
| KC | + OT Diego Pounds (trade from BAL Aug 29); Jawaan Taylor released; RT open competition | −1 | 0.70 | https://www.profootballrumors.com/2026/08/chiefs-trade-for-ravens-t-diego-pounds |

Nine OL went in Round 1 (CLE, NYG, MIA, BAL, DET, CAR, PIT, HOU, NE) per https://en.wikipedia.org/wiki/2026_NFL_draft . Other teams default to `delta = 0` with a note "no material change found (2026-08-29)" and the Wikipedia 2026 FA list as `source_url` (https://en.wikipedia.org/wiki/2026_NFL_season ; adds DJ Humphries LAR→WAS, Elgton Jenkins GB→CLE, David Edwards BUF→NO). Deltas above are suggestions for the seed; Derek confirms them in the review table.

## Checklist

### Seed files
- [ ] Write `backend/seeds/coaching_changes.yaml`: 32 rows; `hc`, `hc_new`, `oc`, `oc_new`, `play_caller`, `play_caller_new`, `source_url`, `confidence`, `last_checked = 2026-08-29`; HC/OC names from the Wikipedia lists, play-caller from fansports + the per-team articles above.
- [ ] Write `backend/seeds/qb_situations.yaml`: 32 rows; `projected_qb1`, `status` ∈ {settled, competition, injury_return}, `changed_from_2025`, `source_url`, `confidence`, `last_checked`; ATL/LV = competition, KC/IND/DEN = injury_return per the table above.
- [ ] Write `backend/seeds/ol_changes.yaml`: 32 rows; `delta` ∈ −2..+2, `notes`, `source_url`, `confidence`, `last_checked`; nine R1 OL picks, Linderbaum → LV, WAS Tunsil, CAR Ekwonu, LAC Biadasz encoded.
- [ ] Add a header comment to each YAML: "games.csv coach columns are stale (ARI/ATL/BUF) — never derive HC changes from it"; source URLs are mandatory per row.

### Loader and validation
- [ ] `ingest seeds` (no network): parse the three YAML files into `coaching_changes`, `qb_situations`, `ol_changes` (truncate + insert), compute each file's sha256 and store it as a seed hash on the next `ranking_runs` row.
- [ ] Validation on load (fail loudly): exactly 32 distinct teams per file matching nflverse team abbrs; every row has non-empty `source_url` (http/https), `confidence` in [0, 1], `last_checked` a date; `status` in the enum; `delta` in −2..+2; booleans are booleans.
- [ ] Build the derived `team_context` table (one row per team joining all three) inside `recompute`; `recompute` stays network-free.

### API
- [ ] `GET /api/team_context` returns all three tables for 32 teams (per `docs/spec/api.md` §3.5), including `source_url`, `confidence`, `last_checked` on every row and the seed hashes of the pinned run.
- [ ] `GET /api/team_context/{team}` for the player drawer.

### Flags and WHY bullets (consumed by Phase 6)
- [ ] `new_play_caller` flag = `coaching_changes.play_caller_new` for the player's 2026 team-of-record (`rosters_2026`).
- [ ] `qb_uncertain_team` flag = `qb_situations.status != 'settled'` for the player's team.
- [ ] WHY templates exactly as in `docs/spec/why-rules.md`: `CTX_PLAY_CALLER` "New play-caller ({play_caller}) — tag only"; `CTX_HC` "New head coach ({hc}) — tag only"; `CTX_QB` "QB room unsettled ({qb_names}, {status} as of {as_of}) — qb_uncertain_team" / "New QB1 ({projected_qb1}, {status}) — tag only"; `CTX_OL` "OL delta {delta:+d} ({notes}) — tag only"; each bullet stores `source_url` and `last_checked` (as `as_of`) from the seed row.
- [ ] Assert in a test that no ranking value changes when a context table is edited (tags only — no multipliers).

### Reload and review
- [ ] Editing a YAML + `ingest seeds` + `recompute` refreshes tags without code changes; document the command in `docs/runbook-draft-week.md`.
- [ ] `team-context review` CLI renders all three tables into ONE markdown table (team | HC (new?) | play-caller (new?) | QB1 (status) | OL delta | notes | confidence | last_checked | source_url) at `docs/team-context-review.md` for Derek's day-9 re-check.
- [ ] Day-9 re-check list pre-filled in that file: ATL/LV/KC QB rooms; OL injuries (WAS Tunsil, CAR Ekwonu/Moton, LAC Biadasz, DET Mays, PIT Iheanachor); late signings Decker, Conklin, Mixon, Chubb, Hopkins; the five low-Authority play-caller rows (DET, CAR, ATL, DEN, PHI); IND Daniel Jones camp status.

### Tests (real seed files)
- [ ] Loader tests run against the committed YAML files (real data): 32 rows each, enum/range validation, missing `source_url` rejected.
- [ ] Flag tests: DEN/CAR/PHI players get `new_play_caller`; ATL/LV players get `qb_uncertain_team`; KC players get `qb_uncertain_team` only while `status = injury_return`.

## Results

_(fill in: date of `ingest seeds`, seed hashes, `/api/team_context` row counts, link to the review table)_

## Gate

`team_context` API returns all three for 32 teams; every row has a source_url; Derek reviews them in one markdown table (day 9 re-check).

## Derek's actions

- Day 9 (Tue Sep 8): review `docs/team-context-review.md` (1–2 h) — confirm ATL/LV/KC QB rooms, the OL deltas, and the five low-confidence play-caller rows; report late signings (Decker, Conklin, Mixon, Chubb, Hopkins) with source URLs so the rows can be updated and, only if required, the snapshot explicitly re-frozen.
