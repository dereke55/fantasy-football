/**
 * Board columns in the exact order of docs/spec/ui.md §3 — rank, tier, value tier, pos, team, bye,
 * proj PPG/season, value, ECR, Yahoo site-wide ADP, room ADP, gap, P(avail), flags — with the player
 * name inserted after rank (the spec's own CSV contract carries `name`; the 14 keep their relative order).
 */
import type { SortKey } from '../lib/boardModel'

export interface ColumnDef {
  id: string
  header: string
  title?: string
  width: string
  align: 'left' | 'right' | 'center'
  sortKey: SortKey | null
  /** Descending is the useful first click for "bigger is better" columns. */
  defaultDir: 'asc' | 'desc'
}

export const COLUMNS: ColumnDef[] = [
  { id: 'rank', header: '#', title: 'Overall rank from the pinned run; positional rank shown beneath', width: '50px', align: 'right', sortKey: 'rank', defaultDir: 'asc' },
  { id: 'name', header: 'Player', width: 'minmax(146px, 1fr)', align: 'left', sortKey: 'name', defaultDir: 'asc' },
  { id: 'tier', header: 'Tier', title: 'GMM tier over ECR — drives the tier bands', width: '34px', align: 'right', sortKey: 'tier', defaultDir: 'asc' },
  { id: 'value_tier', header: 'VT', title: 'Value tier — projection drop-off tier; cliffs use this', width: '32px', align: 'right', sortKey: 'value_tier', defaultDir: 'asc' },
  { id: 'pos', header: 'Pos', width: '42px', align: 'left', sortKey: 'pos', defaultDir: 'asc' },
  { id: 'team', header: 'Tm', width: '36px', align: 'left', sortKey: 'team', defaultDir: 'asc' },
  { id: 'bye', header: 'Bye', width: '32px', align: 'right', sortKey: 'bye', defaultDir: 'asc' },
  { id: 'proj', header: 'Proj PPG · Szn', title: 'Projected points per game and season total under league scoring; hover for E[games]', width: '92px', align: 'right', sortKey: 'proj_ppg', defaultDir: 'desc' },
  { id: 'value', header: 'Value', title: 'Keeper-aware VOLS/VORP; K and DST carry VBD 0', width: '50px', align: 'right', sortKey: 'value', defaultDir: 'desc' },
  { id: 'ecr', header: 'ECR', title: 'FantasyPros expert consensus rank; hover for the standard deviation', width: '46px', align: 'right', sortKey: 'ecr', defaultDir: 'asc' },
  { id: 'adp_yahoo_site', header: 'Yahoo', title: 'Yahoo ADP (site-wide) — not this room', width: '58px', align: 'right', sortKey: 'adp_yahoo_site', defaultDir: 'asc' },
  { id: 'room_adp', header: 'Room', title: 'Keeper-adjusted ADP for this 10-team room', width: '58px', align: 'right', sortKey: 'room_adp', defaultDir: 'asc' },
  { id: 'gap', header: 'Gap', title: 'Signed picks between our rank and room ADP; hover for the z-score', width: '42px', align: 'right', sortKey: 'gap', defaultDir: 'desc' },
  { id: 'p_avail', header: 'P(avail)', title: 'Probability the player is still there at my next pick', width: '60px', align: 'right', sortKey: 'p_avail', defaultDir: 'desc' },
  { id: 'flags', header: 'Flags', width: 'minmax(100px, 124px)', align: 'left', sortKey: null, defaultDir: 'asc' },
]

export const GRID_TEMPLATE = COLUMNS.map((c) => c.width).join(' ')
export const BOARD_MIN_WIDTH = 898
