/**
 * The MVP chart: PPG under league scoring for 2023-2025 as a three-point line, games as labels.
 * A season played in a different team/role than the reference season is drawn hollow, because its
 * PPG is not comparable — that is the whole reason the role_key is carried through.
 * Weekly sparklines are deferred (docs/spec/ui.md §4).
 */
import type { SeasonRow } from '../api/types'
import { one } from '../lib/format'

export function PpgLine({ seasons, refRole }: { seasons: SeasonRow[]; refRole: string | null }) {
  const pts = seasons
    .filter((s) => s.ppg != null)
    .sort((a, b) => a.season - b.season)

  if (pts.length === 0) {
    return (
      <div
        className="rounded px-2 py-3 text-[12px] text-center"
        style={{ background: 'var(--panel-3)', border: '1px dashed var(--border)', color: 'var(--muted)' }}
      >
        No NFL history — rookie
      </div>
    )
  }

  const W = 300, H = 84, padX = 30, padY = 14
  const vals = pts.map((p) => p.ppg as number)
  const lo = Math.min(...vals, 0)
  const hi = Math.max(...vals) * 1.12 || 1
  const x = (i: number) => padX + (pts.length === 1 ? (W - padX * 2) / 2 : (i * (W - padX * 2)) / (pts.length - 1))
  const y = (v: number) => H - padY - ((v - lo) / (hi - lo || 1)) * (H - padY * 2)
  const path = pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(i)},${y(p.ppg as number)}`).join(' ')

  return (
    <div className="rounded p-1" style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} role="img" aria-label="PPG by season">
        <line x1={padX - 12} y1={y(0)} x2={W - padX + 12} y2={y(0)} stroke="var(--border)" strokeWidth={1} />
        <path d={path} fill="none" stroke="var(--accent)" strokeWidth={1.8} />
        {pts.map((p, i) => {
          const sameRole = refRole == null || p.role_key === refRole
          return (
            <g key={p.season}>
              <circle
                cx={x(i)} cy={y(p.ppg as number)} r={4}
                fill={sameRole ? 'var(--accent)' : 'var(--bg)'}
                stroke="var(--accent)" strokeWidth={1.8}
              >
                <title>{`${p.season}: ${one(p.ppg)} PPG over ${p.games ?? '—'} games${sameRole ? '' : ` — different role (${p.role_key})`}`}</title>
              </circle>
              <text x={x(i)} y={y(p.ppg as number) - 9} textAnchor="middle" fontSize={10} fill="var(--text)" fontFamily="var(--mono)">
                {one(p.ppg)}
              </text>
              <text x={x(i)} y={H - 2} textAnchor="middle" fontSize={9} fill="var(--muted)" fontFamily="var(--mono)">
                {p.season} · {p.games ?? '—'}g
              </text>
            </g>
          )
        })}
      </svg>
      {pts.some((p) => refRole != null && p.role_key !== refRole) && (
        <div className="px-1.5 pb-0.5 text-[9.5px]" style={{ color: 'var(--muted)' }}>
          Hollow point = different team/role than {refRole}.
        </div>
      )}
    </div>
  )
}
