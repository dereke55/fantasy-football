/**
 * VONA top-3 per position from /api/availability. The slot weight is shown next to each position
 * so the number stays explainable: an open starter counts full VBD, a bench-only need half.
 * K and DST are hidden before round 12 (docs/spec/ranking-model.md §12).
 */
import type { AvailabilityResponse } from '../api/types'
import { one, pct } from '../lib/format'
import { posColor } from '../lib/positions'

const ORDER = ['RB', 'WR', 'TE', 'QB', 'K', 'DEF']

export function VonaPanel({
  availability, currentRound, onPick,
}: { availability: AvailabilityResponse | undefined; currentRound: number | null; onPick: (id: number) => void }) {
  if (!availability) return <div className="text-[11.5px]" style={{ color: 'var(--muted)' }}>Availability unavailable.</div>
  const showKdst = currentRound != null && currentRound >= 12
  const entries = ORDER
    .filter((p) => availability.positions[p] != null)
    .filter((p) => showKdst || (p !== 'K' && p !== 'DEF'))

  if (!entries.length) {
    return <div className="text-[11.5px]" style={{ color: 'var(--muted)' }}>No draft slot set — VONA is unavailable.</div>
  }

  return (
    <div className="flex flex-col gap-2">
      {entries.map((pos) => {
        const v = availability.positions[pos]
        const c = posColor(pos)
        return (
          <div key={pos}>
            <div className="flex items-center gap-1.5 mb-0.5">
              <span
                className="rounded px-1 text-[10px] font-bold"
                style={{ color: c.fg, background: c.bg, border: `1px solid ${c.border}` }}
              >{pos === 'DEF' ? 'DST' : pos}</span>
              <span className="text-[10px]" style={{ color: 'var(--muted)' }}>
                {v.open_slots} open · weight ×{v.slot_weight}
              </span>
            </div>
            <div className="flex flex-col gap-0.5">
              {v.candidates.map((cd) => (
                <button
                  key={cd.player_id}
                  type="button"
                  onClick={() => onPick(cd.player_id)}
                  title={`value now ${one(cd.value_now)} → expected at my next pick ${one(cd.expected_value_at_next)}`}
                  className="grid items-center gap-1 rounded px-1.5 text-[11.5px] text-left"
                  style={{
                    gridTemplateColumns: '1fr 46px 44px', height: 22,
                    background: 'var(--panel-3)', border: '1px solid var(--border)',
                  }}
                >
                  <span className="truncate">
                    {cd.name} <span className="mono text-[9.5px]" style={{ color: 'var(--muted)' }}>{cd.team}</span>
                  </span>
                  <span
                    className="num mono text-[11px] font-semibold"
                    style={{ color: cd.vona > 0 ? 'var(--good)' : cd.vona < 0 ? 'var(--muted)' : 'var(--text)' }}
                  >{cd.vona > 0 ? `+${one(cd.vona)}` : one(cd.vona)}</span>
                  <span
                    className="num mono text-[10.5px]"
                    style={{ color: cd.p_avail >= 0.66 ? 'var(--good)' : cd.p_avail <= 0.2 ? 'var(--bad)' : 'var(--warn)' }}
                  >{pct(cd.p_avail)}</span>
                </button>
              ))}
            </div>
          </div>
        )
      })}
      <div className="text-[9.5px] leading-snug" style={{ color: 'var(--muted)' }}>
        Columns: VONA (value lost by waiting) and P(avail) at my next pick.
        {!showKdst && ' K and DST appear from round 12.'}
      </div>
    </div>
  )
}
