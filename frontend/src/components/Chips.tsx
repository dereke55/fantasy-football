/** Small shared chips: position hue, flag icon+label, and a generic pill. */
import { flagDef, TONE_STYLE } from '../lib/flags'
import { posColor } from '../lib/positions'

export function PosChip({ pos, dim = false }: { pos: string; dim?: boolean }) {
  const c = posColor(pos)
  return (
    <span
      className="inline-flex items-center justify-center rounded px-1.5 text-[10px] font-bold tracking-wide"
      style={{
        color: c.fg, background: c.bg, border: `1px solid ${c.border}`,
        lineHeight: '15px', minWidth: 30, opacity: dim ? 0.6 : 1,
      }}
    >
      {pos === 'DEF' ? 'DST' : pos}
    </span>
  )
}

export function FlagChip({ name }: { name: string }) {
  const d = flagDef(name)
  const t = TONE_STYLE[d.tone]
  return (
    <span
      title={d.title}
      className="inline-flex items-center gap-0.5 rounded px-1 text-[10px] font-semibold whitespace-nowrap"
      style={{ color: t.color, background: t.bg, border: `1px solid ${t.border}`, lineHeight: '14px' }}
    >
      <span aria-hidden style={{ fontSize: 9 }}>{d.icon}</span>
      {d.label}
    </span>
  )
}

/** Flags plus tags, de-duplicated — the two lists overlap (injury_prone appears in both). */
export function FlagChips({ flags, tags = [], max }: { flags: string[]; tags?: string[]; max?: number }) {
  const all = Array.from(new Set([...flags, ...tags]))
  const shown = max ? all.slice(0, max) : all
  const rest = all.length - shown.length
  return (
    <span className="inline-flex items-center gap-1">
      {shown.map((f) => <FlagChip key={f} name={f} />)}
      {rest > 0 && (
        <span title={all.slice(shown.length).join(', ')} className="text-[10px]" style={{ color: 'var(--muted)' }}>
          +{rest}
        </span>
      )}
    </span>
  )
}

export function Pill({
  children, tone = 'info', title,
}: { children: React.ReactNode; tone?: 'good' | 'bad' | 'warn' | 'info' | 'accent'; title?: string }) {
  const map = {
    good: { color: 'var(--good)', bg: 'var(--good-dim)', border: 'rgba(63,185,80,0.35)' },
    bad: { color: 'var(--bad)', bg: 'var(--bad-dim)', border: 'rgba(248,81,73,0.4)' },
    warn: { color: 'var(--warn)', bg: 'var(--warn-dim)', border: 'rgba(210,153,34,0.35)' },
    info: { color: 'var(--muted)', bg: 'rgba(139,152,165,0.1)', border: 'var(--border)' },
    accent: { color: 'var(--accent)', bg: 'var(--accent-dim)', border: 'rgba(88,166,255,0.4)' },
  }[tone]
  return (
    <span
      title={title}
      className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold tracking-wide"
      style={{ color: map.color, background: map.bg, border: `1px solid ${map.border}` }}
    >
      {children}
    </span>
  )
}
