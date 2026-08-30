/**
 * Flag registry. Every flag renders as icon + short label — never colour alone (docs/spec/ui.md §9),
 * so the board stays readable for a colour-blind reader and in a screenshot.
 */
export type FlagTone = 'good' | 'bad' | 'warn' | 'info'

export interface FlagDef {
  icon: string
  label: string
  tone: FlagTone
  title: string
}

export const FLAGS: Record<string, FlagDef> = {
  sleeper: { icon: '▲', label: 'SLP', tone: 'good', title: 'Sleeper — unheralded, and our projection is well ahead of the market' },
  value: { icon: '◆', label: 'VAL', tone: 'good', title: 'Value — an established player the market is discounting (early ADP or a starter-level 2025)' },
  bust: { icon: '▼', label: 'BUST', tone: 'bad', title: 'Bust — the market is well ahead of our projection' },
  injury_prone: { icon: '⚕', label: 'INJ', tone: 'warn', title: 'Injury prone — elevated missed-game rate over 2023-25' },
  structural_injury_return: { icon: '⛑', label: 'RTN', tone: 'warn', title: 'Returning from a structural injury (ACL/Achilles class)' },
  rookie: { icon: '✦', label: 'RK', tone: 'info', title: 'Rookie — no NFL history, projection leans on draft capital' },
  new_play_caller: { icon: '↻', label: 'PC', tone: 'info', title: 'New offensive play-caller in 2026 — tag only, no projection change' },
  qb_uncertain_team: { icon: '?', label: 'QB?', tone: 'warn', title: 'Unsettled QB room — tag only, no projection change' },
  positional_reach: { icon: '↗', label: 'RCH', tone: 'warn', title: 'Positional reach — drafted well before positional value supports it' },
}

export function flagDef(name: string): FlagDef {
  return FLAGS[name] ?? { icon: '•', label: name.slice(0, 4).toUpperCase(), tone: 'info', title: name }
}

export const TONE_STYLE: Record<FlagTone, { color: string; bg: string; border: string }> = {
  good: { color: 'var(--good)', bg: 'rgba(63,185,80,0.13)', border: 'rgba(63,185,80,0.38)' },
  bad: { color: 'var(--bad)', bg: 'rgba(248,81,73,0.13)', border: 'rgba(248,81,73,0.38)' },
  warn: { color: 'var(--warn)', bg: 'rgba(210,153,34,0.13)', border: 'rgba(210,153,34,0.38)' },
  info: { color: 'var(--muted)', bg: 'rgba(139,152,165,0.11)', border: 'rgba(139,152,165,0.30)' },
}

/** The two saved views in MVP. */
export const PRESETS = [
  { key: 'sleeper', label: 'Sleepers', icon: FLAGS.sleeper.icon },
  { key: 'value', label: 'Value', icon: FLAGS.value.icon },
  { key: 'bust', label: 'Busts', icon: FLAGS.bust.icon },
] as const
export type PresetKey = (typeof PRESETS)[number]['key']
