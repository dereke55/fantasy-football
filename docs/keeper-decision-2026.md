# Keeper decision — 2026 (deadline Mon Aug 31)

**Recommendation: keep Colston Loveland (TE, CHI) at his round 13 cost.**

Generated 2026-08-30 from `ff keeper value` plus `player_features` / `team_context`, under the league's real scoring
(`config/league.yaml`, validated to the penny against Yahoo's own 2025 totals — see `tests/test_scoring_vs_yahoo.py`).

## The board

Your round 1–4 picks (McCaffrey, Chase Brown, Kenneth Walker III, George Pickens) are marked **Not Eligible** by
Yahoo, so the decision is among the 13 players drafted in rounds 6–16.

The question for each is: **is this player worth more than the pick that keeping him costs?**

Two bars answer that, and they bracket the truth:

- **Bar A (model-optimal)** — the expected VORP of the *highest-VORP* player still available at that pick. This is
  what you get if our projections are right and you always take the best available.
- **Bar B (market-consistent)** — the average VORP of players actually going around that pick. This is what a normal
  drafter gets.

| Round | Pick cost | Bar A | Bar B |
|---|---|---|---|
| 6 | 51–60 | 84.3 | 51.2 |
| 7 | 61–70 | 73.1 | 37.4 |
| 9 | 81–90 | 69.2 | 35.5 |
| 11 | 101–110 | 60.5 | 23.5 |
| 13 | 121–130 | 48.9 | 14.3 |
| 15 | 141–150 | 37.4 | −1.9 |
| 16 | 151–160 | 31.2 | −15.9 |

## Every eligible player

Sorted by surplus under the market-consistent bar. "Picks saved" = the pick the keeper costs minus the player's
consensus ADP — the simplest sanity check, and it agrees with the ranking.

| Player | Pos | Cost | ADP | Pick it costs | VORP | Surplus (Bar A) | Surplus (Bar B) | Picks saved |
|---|---|---|---|---|---|---|---|---|
| **Colston Loveland** | TE | R13 | 48 | ~125 | 42.1 | −6.8 | **+27.8** | **+77** |
| Wan'Dale Robinson | WR | R16 | 114 | ~156 | 16.8 | −14.4 | +32.7 | +42 |
| Chris Olave | WR | R7 | 29 | ~66 | 68.0 | −5.1 | +30.6 | +37 |
| Jared Goff | QB | R15 | 118 | ~146 | 7.1 | −30.3 | +9.0 | +28 |
| Josh Downs | WR | R11 | 104 | ~106 | 16.8 | −43.7 | −6.7 | +1 |
| Detroit Lions | DEF | R14 | 146 | ~136 | — | — | — | −11 |
| Brock Purdy | QB | R9 | 103 | ~86 | 19.7 | −49.5 | −15.8 | −18 |
| Jakobi Meyers | WR | R8 | 114 | ~76 | 17.2 | −53.9 | −15.4 | −39 |
| **Travis Hunter** | WR | R6 | 155 | ~56 | −28.6 | −112.9 | −79.8 | **−100** |

Kickers and defenses (McPherson R16, Reichard R16, Browns R16, Dolphins R16) are not modeled — they carry VBD 0 by
design because they are streamable and replacement-level. Keeping one is never right when a comparable option is
available in the same round, which for K/DEF it always is.

## Why Loveland

1. **The largest surplus on the board, by a wide margin.** ADP 48 (a top-5 TE) at a 13th-round cost is 77 picks of
   value — nothing else is close.
2. **Positive under both bars.** He is the only player that is strongly positive market-consistently (+27.8) while
   being essentially tied with Olave for the least-negative under the strict model bar (−6.8 vs −5.1).
3. **Cleanest risk profile of the finalists.** One game missed in his career (hip), no `injury_prone` flag, age 22.4
   — the youngest player under consideration, and the one with the most room to grow.
4. **Best offensive environment.** Chicago's play-caller is Ben Johnson (head coach, calls plays), the QB room is
   settled (Caleb Williams, quality tier 2), and the offensive line ranks 5th.
5. **Positional scarcity compounds it.** In a 1-TE league TE replacement level is 7.34 PPG; he projects 10.26. That
   +2.9 PPG edge over a streamed TE is structural and persists every week of the season.
6. **The pick you give up is cheap.** A 13th-round pick returns ~14 VORP market-consistently.

## Why not the alternatives

- **Chris Olave** has the highest raw value (VORP 68) and is a defensible keep. Two things cost him the nod: he costs
  a **7th-round pick**, a real asset in a 16-round draft, and he carries the worst injury profile of the three —
  11 games missed in 51 (21.6%), driven by **concussions**, which flags him `injury_prone` and drags his expected
  games down. His offense is also the weakest: New Orleans' QB room is quality tier 3 (Tyler Shough). Six rounds
  cheaper and materially safer, Loveland gets you nearly the same surplus.
- **Wan'Dale Robinson** is nearly free at R16 and has grown three years running (6.9 → 8.0 → 11.1 PPG, 27.8% target
  share). But he changed teams, and Tennessee is the worst situation among the candidates: new head coach
  (Robert Saleh), **new play-caller** (Brian Daboll), quality-tier-3 QB (Cam Ward), the **29th-ranked offensive
  line**, and he is currently listed Questionable and sits WR2 on the depth chart. His 2025 production was earned in
  a different offense. R16 value is genuinely available in the draft.
- **Travis Hunter is the clearest drop on the sheet.** Keeping him costs a **6th-round** pick for a player the market
  drafts around **pick 155** — 100 picks of negative value, the worst on your roster.

## Caveats

- **Assumes one keeper.** Your Yahoo sheet shows a single "Keeper" column, so this recommends one. If the league
  allows more, the order is **Loveland → Olave → Wan'Dale Robinson**, and all three clear the market-consistent bar.
- **Draft slot is unknown**, so every round's pick value is averaged over all 10 slots. An early slot raises the bar
  slightly in odd rounds and lowers it in even ones; it does not change the ranking.
- **The projection is vendor-only** (Sleeper/Rotowire stat lines re-scored under your settings). The in-house
  opportunity component is not blended in yet, and it is the piece most likely to temper the late-round running-back
  projections that inflate Bar A. That is exactly why both bars are shown rather than one.
- Rank correlation between our value and the market is 0.74 (top 50) / 0.81 (top 100) / 0.86 (top 150). The
  disagreement is concentrated in running backs, which is a known weakness of vendor projections and the reason the
  market-consistent bar carries weight here.
