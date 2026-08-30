/**
 * Board filtering, sorting and row-item assembly.
 *
 * Sorting and filtering are client-side over the whole pinned payload — no round trip (§3).
 * The virtualizer consumes a flat item list in which tier bands are their own items, so a band
 * scrolls with its rows instead of floating.
 */
import type { BoardPlayer } from '../api/types'

export type SortKey =
  | 'rank' | 'name' | 'tier' | 'value_tier' | 'pos' | 'team' | 'bye'
  | 'proj_ppg' | 'value' | 'ecr' | 'adp_yahoo_site' | 'room_adp' | 'gap' | 'p_avail'
export type SortDir = 'asc' | 'desc'

export interface BoardFilters {
  pos: string | null
  presets: string[]
  search: string
  hideDrafted: boolean
}

export const EMPTY_FILTERS: BoardFilters = { pos: null, presets: [], search: '', hideDrafted: false }

function fieldOf(p: BoardPlayer, k: SortKey): number | string | null {
  switch (k) {
    case 'name': return p.name.toLowerCase()
    case 'pos': return p.pos
    case 'team': return p.team ?? ''
    default: return (p as unknown as Record<string, number | null>)[k] ?? null
  }
}

/** Nulls always sort last, whichever direction — an unpriced player must never top the board. */
function compare(a: BoardPlayer, b: BoardPlayer, key: SortKey, dir: SortDir): number {
  const av = fieldOf(a, key)
  const bv = fieldOf(b, key)
  if (av == null && bv == null) return a.rank - b.rank
  if (av == null) return 1
  if (bv == null) return -1
  let c = 0
  if (typeof av === 'string' || typeof bv === 'string') c = String(av).localeCompare(String(bv))
  else c = (av as number) - (bv as number)
  if (c === 0) return a.rank - b.rank
  return dir === 'asc' ? c : -c
}

export function filterPlayers(players: BoardPlayer[], f: BoardFilters): BoardPlayer[] {
  const q = f.search.trim().toLowerCase()
  return players.filter((p) => {
    if (f.pos && p.pos !== f.pos) return false
    if (f.presets.length && !f.presets.every((k) => p.flags.includes(k))) return false
    if (f.hideDrafted && p.drafted) return false
    if (q) {
      const hay = `${p.name} ${p.team ?? ''} ${p.pos}`.toLowerCase()
      if (!hay.includes(q)) return false
    }
    return true
  })
}

export function sortPlayers(players: BoardPlayer[], key: SortKey, dir: SortDir): BoardPlayer[] {
  return [...players].sort((a, b) => compare(a, b, key, dir))
}

/**
 * The best available player is the undrafted row with the lowest overall rank under the current
 * filter — deliberately independent of the column the board happens to be sorted by. Sorting by,
 * say, ECR descending would otherwise star the *worst* player on the board, which is exactly the
 * wrong thing to make unmissable thirty seconds before a pick.
 */
export function bestAvailable(players: BoardPlayer[]): BoardPlayer | undefined {
  let best: BoardPlayer | undefined
  for (const p of players) {
    if (p.drafted) continue
    if (!best || p.rank < best.rank) best = p
  }
  return best
}

export type RowItem =
  | { kind: 'band'; id: string; tier: number; label: string; count: number }
  | { kind: 'player'; id: string; player: BoardPlayer; valueTierBreak: boolean; isBest: boolean }

export const ROW_H = 32
export const BAND_H = 26

/**
 * Tier bands only make sense while the board is in ranked order (§3): sorted by `rank`, or by
 * `pos_rank` implicitly when a position filter narrows the pool. Any other sort drops them.
 *
 * WHICH tier the band follows depends on the sort, because the two tiers are built on different
 * orderings. `tier` is a GMM over expert consensus (ECR); `value_tier` is the drop-off in OUR
 * projection. Sorted by our rank, only `value_tier` is monotonic — banding by the ECR tier there
 * produced the visibly wrong sequence "Tier 1, Tier 2, Tier 4, Tier 3", because the 11th-most
 * valuable player happens to sit in ECR tier 4. So: band by value tier in our rank order, and by
 * ECR tier when the board is sorted by ECR. Both tiers stay visible in their own columns either way.
 */
export function buildRows(
  players: BoardPlayer[],
  opts: { bands: boolean; posFilter: string | null; bandBy?: 'value_tier' | 'tier' },
): RowItem[] {
  const best = bestAvailable(players)
  const items: RowItem[] = []
  const seenTiers = new Set<number>()
  let lastValueTier: number | null = null
  const bandKey: 'value_tier' | 'tier' = opts.bandBy ?? 'value_tier'
  const label = bandKey === 'value_tier' ? 'Value tier' : 'Tier'

  const tierCounts = new Map<number, number>()
  for (const q of players) {
    const t = q[bandKey]
    if (t != null) tierCounts.set(t, (tierCounts.get(t) ?? 0) + 1)
  }

  for (let i = 0; i < players.length; i++) {
    const p = players[i]
    const t = p[bandKey]
    if (opts.bands && t != null && !seenTiers.has(t)) {
      seenTiers.add(t)
      items.push({
        kind: 'band',
        id: `band-${t}-${i}`,
        tier: t,
        label: opts.posFilter ? `${opts.posFilter} ${label.toLowerCase()} ${t}` : `${label} ${t}`,
        count: tierCounts.get(t) ?? 0,
      })
      lastValueTier = p.value_tier ?? null
    }
    // the secondary dashed rule marks the OTHER tier's breaks, so both groupings stay legible
    const vtBreak =
      opts.bands && bandKey === 'value_tier'
        ? false
        : p.value_tier != null && lastValueTier != null && p.value_tier !== lastValueTier
    if (p.value_tier != null) lastValueTier = p.value_tier
    items.push({
      kind: 'player',
      id: `p-${p.player_id}`,
      player: p,
      valueTierBreak: Boolean(vtBreak),
      isBest: best != null && best.player_id === p.player_id,
    })
  }
  return items
}

export function itemHeight(item: RowItem): number {
  return item.kind === 'band' ? BAND_H : ROW_H
}
