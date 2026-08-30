/**
 * Number formatting rules from docs/spec/ui.md §9: one decimal for PPG / ECR / ADP,
 * integers for season points and gap, percent for P(avail). Nulls always render as an em dash
 * so an empty cell is never mistaken for a zero.
 */
export const DASH = '—'

export function one(n: number | null | undefined): string {
  return n == null || Number.isNaN(n) ? DASH : n.toFixed(1)
}

export function int(n: number | null | undefined): string {
  return n == null || Number.isNaN(n) ? DASH : Math.round(n).toLocaleString('en-US')
}

/** Signed integer, used for `gap` where the sign is the whole point. */
export function signedInt(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH
  const r = Math.round(n)
  return r > 0 ? `+${r}` : String(r)
}

export function pct(n: number | null | undefined, digits = 0): string {
  return n == null || Number.isNaN(n) ? DASH : `${(n * 100).toFixed(digits)}%`
}

export function signedOne(n: number | null | undefined): string {
  if (n == null || Number.isNaN(n)) return DASH
  return n > 0 ? `+${n.toFixed(1)}` : n.toFixed(1)
}

export function shortHash(h: string | null | undefined, n = 8): string {
  return h ? h.slice(0, n) : DASH
}

export function shortId(id: string | null | undefined): string {
  return id ? id.slice(0, 8) : DASH
}

/** `2026-08-30T16:06:43+00:00` -> `Aug 30, 16:06` in the viewer's zone. */
export function stamp(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit', hour12: false })
}

export function dateOnly(iso: string | null | undefined): string {
  if (!iso) return DASH
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString('en-US', { weekday: 'short', month: 'short', day: 'numeric' })
}

/** Human host for a provenance URL, e.g. `github.com/nflverse`. */
export function sourceLabel(url: string | null | undefined): string {
  if (!url) return 'curated'
  try {
    const u = new URL(url)
    const seg = u.pathname.split('/').filter(Boolean)[0]
    return seg ? `${u.hostname.replace(/^www\./, '')}/${seg}` : u.hostname.replace(/^www\./, '')
  } catch {
    return url
  }
}

export function num(v: unknown): number | null {
  return typeof v === 'number' && !Number.isNaN(v) ? v : null
}

export function str(v: unknown): string | null {
  return typeof v === 'string' && v.length > 0 ? v : null
}

export function bool(v: unknown): boolean {
  return v === true
}
