/**
 * My roster as the league's actual slot grid (from league.yaml via /api/run), pre-populated with
 * keepers. Players fill their own position first, then FLEX, then bench — so an open starter slot
 * is always visible as an open slot rather than hidden behind a deep bench.
 */
import type { LeagueInfo, RosterPlayer } from '../api/types'
import { PosChip } from './Chips'

const ORDER = ['QB', 'RB', 'WR', 'TE', 'FLEX', 'K', 'DEF']

interface Slot { label: string; pos: string; player: RosterPlayer | null }

function buildSlots(league: LeagueInfo | undefined, roster: RosterPlayer[]): Slot[] {
  if (!league) return []
  const slots: Slot[] = []
  for (const pos of ORDER) {
    const n = league.slots[pos] ?? 0
    for (let i = 0; i < n; i++) slots.push({ label: n > 1 ? `${pos}${i + 1}` : pos, pos, player: null })
  }
  for (let i = 0; i < league.bench; i++) slots.push({ label: `BN${i + 1}`, pos: 'BN', player: null })

  const pool = [...roster]
  const take = (pred: (p: RosterPlayer) => boolean): RosterPlayer | null => {
    const i = pool.findIndex(pred)
    return i >= 0 ? pool.splice(i, 1)[0] : null
  }
  for (const s of slots) {
    if (s.pos === 'FLEX') s.player = take((p) => league.flex_eligible.includes(p.position))
    else if (s.pos === 'BN') s.player = take(() => true)
    else s.player = take((p) => p.position === s.pos)
  }
  return slots
}

export function RosterGrid({
  league, roster, byeWarnWeeks,
}: { league: LeagueInfo | undefined; roster: RosterPlayer[]; byeWarnWeeks: Set<number> }) {
  const slots = buildSlots(league, roster)
  const starters = slots.filter((s) => s.pos !== 'BN')
  const bench = slots.filter((s) => s.pos === 'BN')

  const row = (s: Slot, i: number) => {
    const open = s.player == null
    return (
      <div
        key={`${s.label}-${i}`}
        className="flex items-center gap-1.5 px-1.5 rounded text-[11.5px]"
        style={{
          height: 24,
          background: open ? 'rgba(88,166,255,0.07)' : 'var(--panel-3)',
          border: open ? '1px dashed rgba(88,166,255,0.4)' : '1px solid var(--border)',
        }}
      >
        <span
          className="mono text-[9.5px] font-bold shrink-0"
          style={{ color: open ? 'var(--accent)' : 'var(--muted)', width: 26 }}
        >{s.label}</span>
        {s.player ? (
          <>
            <span className="truncate flex-1" title={s.player.name}>{s.player.name}</span>
            {s.player.bye != null && (
              <span
                className="mono text-[9.5px] shrink-0"
                title={`Bye week ${s.player.bye}`}
                style={{ color: byeWarnWeeks.has(s.player.bye) ? 'var(--warn)' : 'var(--muted)', fontWeight: byeWarnWeeks.has(s.player.bye) ? 700 : 400 }}
              >b{s.player.bye}</span>
            )}
            {s.player.is_keeper && (
              <span className="text-[9px] font-bold shrink-0" title={`Keeper — cost round ${s.player.cost_round}`} style={{ color: 'var(--warn)' }}>
                K{s.player.cost_round}
              </span>
            )}
            <PosChip pos={s.player.position} />
          </>
        ) : (
          <span className="flex-1" style={{ color: 'var(--accent)', opacity: 0.75 }}>open</span>
        )}
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-1">
      <div className="grid grid-cols-2 gap-1">{starters.map(row)}</div>
      <div className="text-[9px] font-semibold uppercase tracking-widest mt-1" style={{ color: 'var(--muted)' }}>Bench</div>
      <div className="grid grid-cols-2 gap-1">{bench.map(row)}</div>
    </div>
  )
}
