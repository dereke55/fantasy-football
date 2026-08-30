/** One hue per position; used on chips only, never as a row background (docs/spec/ui.md §9). */
export const POSITIONS = ['QB', 'RB', 'WR', 'TE', 'K', 'DEF'] as const
export type PosKey = (typeof POSITIONS)[number]

const COLORS: Record<string, { fg: string; bg: string; border: string }> = {
  QB: { fg: '#f0a3c4', bg: 'rgba(214, 62, 120, 0.16)', border: 'rgba(214, 62, 120, 0.45)' },
  RB: { fg: '#7ee3a8', bg: 'rgba(45, 164, 96, 0.16)', border: 'rgba(45, 164, 96, 0.45)' },
  WR: { fg: '#8fc4ff', bg: 'rgba(56, 122, 214, 0.18)', border: 'rgba(56, 122, 214, 0.5)' },
  TE: { fg: '#f2c17a', bg: 'rgba(199, 130, 40, 0.16)', border: 'rgba(199, 130, 40, 0.45)' },
  K: { fg: '#b8a9e8', bg: 'rgba(122, 96, 200, 0.18)', border: 'rgba(122, 96, 200, 0.45)' },
  DEF: { fg: '#9fb2c4', bg: 'rgba(110, 135, 160, 0.16)', border: 'rgba(110, 135, 160, 0.42)' },
}

const FALLBACK = { fg: 'var(--muted)', bg: 'rgba(139,152,165,0.14)', border: 'rgba(139,152,165,0.4)' }

export function posColor(pos: string | null | undefined) {
  if (!pos) return FALLBACK
  return COLORS[pos.toUpperCase()] ?? FALLBACK
}

/** The board filter offers DST as a label; the data (and league.yaml) call it DEF. */
export const POS_FILTERS: { key: PosKey; label: string }[] = [
  { key: 'QB', label: 'QB' },
  { key: 'RB', label: 'RB' },
  { key: 'WR', label: 'WR' },
  { key: 'TE', label: 'TE' },
  { key: 'K', label: 'K' },
  { key: 'DEF', label: 'DST' },
]
