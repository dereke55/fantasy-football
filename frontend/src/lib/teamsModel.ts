/**
 * Per-team rosters, positional needs and the drift check (Teams tab).
 *
 * Yahoo's API was never approved, so every pick is typed into the QuickPick bar while the clock
 * runs. The failure that matters is not an error — it is *silence*: a missed pick, a double entry
 * or a pick attributed to the wrong team leaves the board internally consistent while quietly
 * disagreeing with the real draft, and every P(avail) downstream goes stale without complaint.
 * This module reconstructs what each team has taken and compares it with what the snake says they
 * should have by now, so the disagreement has somewhere to show up.
 *
 * How a team's roster is derived — nothing here is guessed:
 *
 * 1. `POST /api/draft/picks` always stamps the pick with `on_the_clock(schedule, picks_made)`, i.e.
 *    the next unfilled live slot, and only ever appends. So the n-th surviving `draft_picks` row is
 *    the n-th live slot of the schedule, and `draft_picks.id` (surfaced as `pick_id` on every board
 *    row) orders those rows exactly as they were made. Sorting the drafted board rows by `pick_id`
 *    and walking them against `live_pick_no = 1, 2, 3 …` therefore recovers the round and overall
 *    pick of every pick in the draft, for every team — no extra endpoint needed.
 * 2. The team credited is `drafted_by`, which is the *stored* `team_slot`. The Draft tab's "for team"
 *    override writes a slot that can differ from the slot the schedule expected at that pick — which
 *    is precisely the mis-attribution this view exists to catch, so the two are kept apart:
 *    `scheduledSlot` is what the snake ordered, the grouping key is what was recorded.
 * 3. Keepers are not `draft_picks` rows at all. They come from `/api/keepers` and are placed at the
 *    `is_keeper_slot` hole the schedule cut for that (team, cost round), so they occupy a roster slot
 *    before pick 1 is ever made.
 */
import type { BoardPlayer, Keeper, LeagueInfo, SchedulePick } from '../api/types'

/** Starter slots in the order the roster grid shows them; FLEX must settle after the fixed slots. */
export const SLOT_ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DEF'] as const

export interface TeamEntry {
  playerId: number
  name: string
  pos: string
  team: string | null
  bye: number | null
  round: number
  /** Schedule position; a keeper sits in the hole its cost round cut. */
  overallPick: number | null
  /** Dense live-pick number, `null` for a keeper (a keeper is never a live pick). */
  livePick: number | null
  isKeeper: boolean
  costRound: number | null
  /** The slot the snake said owned this pick — differs from the owner when a pick was mis-attributed. */
  scheduledSlot: number | null
  /** False when the player is not in the pinned run, so clicking cannot highlight him. */
  onBoard: boolean
}

export interface SlotTally {
  label: string
  pos: string
  required: number
  filled: number
}

export interface TeamSummary {
  slot: number
  isMine: boolean
  entries: TeamEntry[]
  tally: SlotTally[]
  benchRequired: number
  benchFilled: number
  /** e.g. `['QB', 'WR×3']` — starter slots still empty. */
  openStarters: string[]
  /** Live picks recorded against this team (keepers excluded — a keeper is not a pick). */
  actual: number
  /** Live picks the snake says this team has had by `picksMade`. */
  expected: number
  delta: number
  keepers: number
}

export interface TeamsModel {
  teams: TeamSummary[]
  /** Authoritative count from `/api/state`. */
  picksMade: number
  totalPicks: number
  /** Picks reconstructed from the board payload; short of `picksMade` if an unranked player was taken. */
  boardPicks: number
  missingFromBoard: number
  /** Teams whose recorded count disagrees with the snake. */
  offenders: TeamSummary[]
  keeperCount: number
}

export const EMPTY_TEAMS_MODEL: TeamsModel = {
  teams: [], picksMade: 0, totalPicks: 0, boardPicks: 0, missingFromBoard: 0, offenders: [], keeperCount: 0,
}

/**
 * Fill the league's starter slots greedily — own position first, then FLEX, then bench — so an
 * empty QB slot reads as an empty QB slot instead of being hidden behind a fourth wide receiver.
 * Mirrors the fill order of `RosterGrid` so the two never disagree about who is a starter.
 */
function tallyOf(league: LeagueInfo, entries: TeamEntry[]): Pick<TeamSummary, 'tally' | 'benchFilled' | 'openStarters'> {
  const left: Record<string, number> = {}
  for (const e of entries) left[e.pos] = (left[e.pos] ?? 0) + 1

  const tally: SlotTally[] = []
  for (const pos of SLOT_ORDER) {
    const required = league.slots[pos] ?? 0
    if (required === 0) continue
    let filled = 0
    if (pos === 'FLEX') {
      for (const fp of league.flex_eligible) {
        while (filled < required && (left[fp] ?? 0) > 0) { left[fp] -= 1; filled += 1 }
      }
    } else {
      filled = Math.min(required, left[pos] ?? 0)
      left[pos] = (left[pos] ?? 0) - filled
    }
    tally.push({ label: pos === 'DEF' ? 'DST' : pos, pos, required, filled })
  }

  const benchFilled = Object.values(left).reduce((a, b) => a + Math.max(0, b), 0)
  const openStarters = tally
    .filter((t) => t.filled < t.required)
    .map((t) => (t.required - t.filled > 1 ? `${t.label}×${t.required - t.filled}` : t.label))
  return { tally, benchFilled, openStarters }
}

export function buildTeams(args: {
  players: BoardPlayer[]
  schedule: SchedulePick[] | undefined
  keepers: Keeper[]
  league: LeagueInfo | undefined
  picksMade: number
  totalPicks: number
}): TeamsModel {
  const { players, schedule, keepers, league, picksMade, totalPicks } = args
  if (!league || !schedule || schedule.length === 0) return EMPTY_TEAMS_MODEL

  const liveByNo = new Map<number, SchedulePick>()
  const expected = new Map<number, number>()
  for (const s of schedule) {
    if (s.live_pick_no == null) continue
    liveByNo.set(s.live_pick_no, s)
    if (s.live_pick_no <= picksMade) expected.set(s.team_slot, (expected.get(s.team_slot) ?? 0) + 1)
  }

  const byPlayerId = new Map(players.map((p) => [p.player_id, p]))
  const entriesBySlot = new Map<number, TeamEntry[]>()
  const push = (slot: number, e: TeamEntry) => {
    entriesBySlot.set(slot, [...(entriesBySlot.get(slot) ?? []), e])
  }

  /* --- keepers: they own a roster slot before pick 1, so they are placed first --- */
  for (const k of keepers) {
    const hole = schedule.find(
      (s) => s.is_keeper_slot && s.team_slot === k.team_slot && s.round === k.cost_round,
    )
    const p = byPlayerId.get(k.player_id)
    push(k.team_slot, {
      playerId: k.player_id,
      name: k.name,
      pos: k.position,
      team: k.team,
      bye: p?.bye ?? null,
      round: k.cost_round,
      overallPick: hole?.overall_pick ?? null,
      livePick: null,
      isKeeper: true,
      costRound: k.cost_round,
      scheduledSlot: null,
      onBoard: p != null,
    })
  }

  /* --- live picks: pick_id order is the order they were made, which is live_pick_no order --- */
  const drafted = players
    .filter((p) => p.pick_id != null && p.drafted_by != null)
    .sort((a, b) => (a.pick_id as number) - (b.pick_id as number))

  drafted.forEach((p, i) => {
    const no = i + 1
    const sched = liveByNo.get(no)
    push(p.drafted_by as number, {
      playerId: p.player_id,
      name: p.name,
      pos: p.pos,
      team: p.team,
      bye: p.bye,
      round: sched?.round ?? 0,
      overallPick: sched?.overall_pick ?? null,
      livePick: no,
      isKeeper: false,
      costRound: null,
      scheduledSlot: sched?.team_slot ?? null,
      onBoard: true,
    })
  })

  const teams: TeamSummary[] = []
  for (let slot = 1; slot <= league.teams; slot++) {
    const entries = (entriesBySlot.get(slot) ?? []).sort(
      (a, b) => (a.overallPick ?? Number.MAX_SAFE_INTEGER) - (b.overallPick ?? Number.MAX_SAFE_INTEGER),
    )
    const actual = entries.filter((e) => !e.isKeeper).length
    const exp = expected.get(slot) ?? 0
    teams.push({
      slot,
      isMine: slot === league.my_slot,
      entries,
      ...tallyOf(league, entries),
      benchRequired: league.bench,
      actual,
      expected: exp,
      delta: actual - exp,
      keepers: entries.filter((e) => e.isKeeper).length,
    })
  }

  return {
    teams,
    picksMade,
    totalPicks,
    boardPicks: drafted.length,
    missingFromBoard: picksMade - drafted.length,
    offenders: teams.filter((t) => t.delta !== 0),
    keeperCount: keepers.length,
  }
}
