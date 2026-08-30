/**
 * One board row. Memoised because 600 of these exist and only a handful are mounted at a time —
 * re-rendering on every selection change would cost more than the virtualizer saves.
 */
import { memo } from 'react'
import type { BoardPlayer } from '../api/types'
import { DASH, int, one, pct, signedInt } from '../lib/format'
import { GRID_TEMPLATE } from './columns'
import { FlagChips, PosChip } from './Chips'

export interface BoardRowProps {
  player: BoardPlayer
  selected: boolean
  isBest: boolean
  valueTierBreak: boolean
  byeWarn: boolean
  striped: boolean
  onSelect: (id: number) => void
  onOpen: (id: number) => void
}

function gapTone(gap: number | null): string {
  if (gap == null) return 'var(--text)'
  if (gap >= 6) return 'var(--good)'
  if (gap <= -6) return 'var(--bad)'
  return 'var(--text)'
}

function pAvailTone(p: number | null): string {
  if (p == null) return 'var(--muted)'
  if (p >= 0.66) return 'var(--good)'
  if (p <= 0.2) return 'var(--bad)'
  return 'var(--warn)'
}

function BoardRowInner({
  player: p, selected, isBest, valueTierBreak, byeWarn, striped, onSelect, onOpen,
}: BoardRowProps) {
  const drafted = p.drafted
  const bg = selected ? 'var(--row-selected)' : isBest && !drafted ? 'rgba(88,166,255,0.06)' : striped ? 'var(--row-alt)' : 'transparent'

  return (
    <div
      role="row"
      aria-selected={selected}
      onMouseDown={() => onSelect(p.player_id)}
      onDoubleClick={() => onOpen(p.player_id)}
      className="grid items-center px-2 text-[12.5px] cursor-default select-none"
      style={{
        gridTemplateColumns: GRID_TEMPLATE,
        height: 32,
        background: bg,
        opacity: drafted ? 0.42 : 1,
        borderTop: valueTierBreak ? '1px dashed rgba(139,152,165,0.28)' : '1px solid transparent',
        boxShadow: selected
          ? 'inset 3px 0 0 var(--accent)'
          : isBest && !drafted
            ? 'inset 3px 0 0 var(--good)'
            : 'none',
      }}
    >
      {/* 1 — rank (+ positional rank) */}
      <div className="num pr-2 leading-none">
        <span className="mono" style={{ fontWeight: 600 }}>{p.rank}</span>
        <div className="mono text-[9.5px] mt-0.5" style={{ color: 'var(--muted)' }}>
          {p.pos_rank != null ? `${p.pos === 'DEF' ? 'DST' : p.pos}${p.pos_rank}` : ''}
        </div>
      </div>

      {/* 2 — name */}
      <div className="flex items-center gap-1.5 pr-2 min-w-0">
        {isBest && !drafted && (
          <span title="Best available under the current filter" style={{ color: 'var(--good)', fontSize: 10 }}>★</span>
        )}
        <span
          className="truncate"
          style={{ textDecoration: drafted ? 'line-through' : 'none', fontWeight: isBest && !drafted ? 600 : 400 }}
          title={p.name}
        >
          {p.name}
        </span>
        {p.is_mine && <span title="My pick" style={{ color: 'var(--accent)', fontSize: 10 }}>●</span>}
        {p.is_keeper && (
          <span
            title="Keeper"
            className="rounded px-1 text-[9px] font-bold"
            style={{ color: 'var(--warn)', border: '1px solid rgba(210,153,34,0.45)', lineHeight: '13px' }}
          >K</span>
        )}
        {drafted && p.drafted_by != null && !p.is_mine && (
          <span className="mono text-[10px] shrink-0" style={{ color: 'var(--muted)' }}>→ T{p.drafted_by}</span>
        )}
        {p.current_injury_status && (
          <span
            title={`Injury status: ${p.current_injury_status}`}
            className="text-[9px] font-bold shrink-0"
            style={{ color: 'var(--warn)' }}
          >{p.current_injury_status.slice(0, 1)}</span>
        )}
      </div>

      {/* 3 — tier */}
      <div className="num pr-2 mono" style={{ color: 'var(--muted)' }}>{p.tier ?? DASH}</div>
      {/* 4 — value tier */}
      <div className="num pr-2 mono" style={{ color: 'var(--muted)' }}>{p.value_tier ?? DASH}</div>
      {/* 5 — pos */}
      <div><PosChip pos={p.pos} dim={drafted} /></div>
      {/* 6 — team */}
      <div className="mono text-[11px]" style={{ color: 'var(--muted)' }}>{p.team ?? DASH}</div>
      {/* 7 — bye */}
      <div
        className="num pr-2 mono"
        title={byeWarn ? 'This bye week is already stacked on my roster' : undefined}
        style={byeWarn
          ? { color: 'var(--warn)', fontWeight: 700 }
          : { color: 'var(--muted)' }}
      >
        {p.bye ?? DASH}
      </div>
      {/* 8 — proj ppg · season */}
      <div className="num pr-2 mono" title={p.e_games != null ? `E[games] ${one(p.e_games)}` : undefined}>
        {one(p.proj_ppg)}
        <span style={{ color: 'var(--muted)' }}> · {int(p.proj_season)}</span>
      </div>
      {/* 9 — value (K/DST carry VBD 0 -> em dash) */}
      <div className="num pr-2 mono" style={{ fontWeight: 600 }}>
        {p.is_kdst ? <span style={{ color: 'var(--muted)' }} title="K and DST carry VBD 0">{DASH}</span> : int(p.value)}
      </div>
      {/* 10 — ECR */}
      <div className="num pr-2 mono" title={p.ecr_sd != null ? `ECR sd ±${one(p.ecr_sd)}` : undefined}>{one(p.ecr)}</div>
      {/* 11 — Yahoo site-wide ADP */}
      <div className="num pr-2 mono">{one(p.adp_yahoo_site)}</div>
      {/* 12 — room ADP */}
      <div className="num pr-2 mono">{one(p.room_adp)}</div>
      {/* 13 — gap */}
      <div
        className="num pr-2 mono"
        title={p.gap_z != null ? `gap z ${one(p.gap_z)}` : undefined}
        style={{ color: gapTone(p.gap), fontWeight: p.gap != null && Math.abs(p.gap) >= 6 ? 600 : 400 }}
      >
        {signedInt(p.gap)}
      </div>
      {/* 14 — P(avail) at my next pick */}
      <div className="num pr-2 mono" style={{ color: pAvailTone(p.p_avail) }}>{pct(p.p_avail)}</div>
      {/* 15 — flags */}
      <div className="overflow-hidden"><FlagChips flags={p.flags} tags={p.tags} max={3} /></div>
    </div>
  )
}

export const BoardRow = memo(BoardRowInner)
