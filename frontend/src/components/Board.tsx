/**
 * The ranked board. 600 rows are virtualised with @tanstack/react-virtual over a flat item list
 * that interleaves tier bands with player rows, so a band scrolls with the rows it heads.
 */
import { useEffect, useLayoutEffect, useRef } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import type { RowItem, SortDir, SortKey } from '../lib/boardModel'
import { BAND_H, ROW_H } from '../lib/boardModel'
import { BOARD_MIN_WIDTH, COLUMNS, GRID_TEMPLATE } from './columns'
import { BoardRow } from './BoardRow'

export interface BoardProps {
  items: RowItem[]
  selectedId: number | null
  byeWarnWeeks: Set<number>
  sort: { key: SortKey; dir: SortDir }
  onSort: (key: SortKey) => void
  onSelect: (id: number) => void
  onOpen: (id: number) => void
  /** Index the parent wants scrolled into view (keyboard navigation). */
  scrollToIndex: number | null
  onRendered?: (ms: number) => void
  loading: boolean
}

export function Board({
  items, selectedId, byeWarnWeeks, sort, onSort, onSelect, onOpen, scrollToIndex, onRendered, loading,
}: BoardProps) {
  const parentRef = useRef<HTMLDivElement>(null)
  const measured = useRef(false)
  const startedAt = useRef<number>(0)

  // Phase 7 gate instrumentation. Timed from the start of the render pass that actually commits,
  // not from the first pass that had rows: React may start rendering, be interrupted by another
  // query resolving, and re-render — timing across that would measure the other queries' latency
  // rather than the cost of putting 600+ rows on screen.
  if (!measured.current && items.length > 0) {
    startedAt.current = performance.now()
    performance.mark('board:render-start')
  }

  const virt = useVirtualizer({
    count: items.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (i) => (items[i]?.kind === 'band' ? BAND_H : ROW_H),
    overscan: 12,
    getItemKey: (i) => items[i]?.id ?? i,
  })

  useLayoutEffect(() => {
    if (measured.current || items.length === 0) return
    measured.current = true
    const started = startedAt.current
    // Measured at commit, not inside requestAnimationFrame: rAF is throttled to ~1 fps in a
    // background window, which would report seconds for a render that took milliseconds.
    performance.mark('board:committed')
    performance.measure('board:render', 'board:render-start', 'board:committed')
    // End-to-end for the record: navigation start -> rows in the DOM, network included.
    performance.measure('board:from-navigation-start', undefined, 'board:committed')
    onRendered?.(performance.now() - started)
  }, [items.length, onRendered])

  useEffect(() => {
    if (scrollToIndex == null) return
    virt.scrollToIndex(scrollToIndex, { align: 'auto' })
  }, [scrollToIndex, virt])

  const rows = virt.getVirtualItems()

  return (
    <div
      className="flex flex-col min-h-0 flex-1"
      style={{ background: 'var(--panel-2)', minWidth: 0 }}
    >
      {/* Header and rows share one horizontal scroller, so they can never drift apart; the rows
          then get their own vertical scroller, which keeps the virtualizer's coordinates exact. */}
      <div className="flex-1 min-h-0 overflow-x-auto overflow-y-hidden">
        <div className="flex flex-col h-full" style={{ minWidth: BOARD_MIN_WIDTH }}>
          <div
            role="row"
            className="grid items-center px-2 text-[10.5px] font-semibold uppercase tracking-wider shrink-0"
            style={{
              gridTemplateColumns: GRID_TEMPLATE, height: 30,
              background: 'var(--panel)', color: 'var(--muted)',
              borderBottom: '1px solid var(--border)',
            }}
          >
            {COLUMNS.map((c) => {
              const active = c.sortKey != null && sort.key === c.sortKey
              return (
                <button
                  key={c.id}
                  type="button"
                  title={c.title ?? (c.sortKey ? `Sort by ${c.header}` : undefined)}
                  disabled={c.sortKey == null}
                  onClick={(e) => {
                    if (!c.sortKey) return
                    onSort(c.sortKey)
                    // Hand focus straight back to the board: a focused header would swallow Space
                    // and re-sort, and j/k/d/m must keep working after a sort click.
                    e.currentTarget.blur()
                  }}
                  className="flex items-center gap-0.5 h-full overflow-hidden whitespace-nowrap"
                  style={{
                    justifyContent: c.align === 'right' ? 'flex-end' : 'flex-start',
                    paddingRight: c.align === 'right' ? 8 : 0,
                    color: active ? 'var(--accent)' : 'inherit',
                    background: 'transparent', border: 0,
                    opacity: c.sortKey == null ? 0.75 : 1,
                    cursor: c.sortKey == null ? 'default' : 'pointer',
                  }}
                >
                  <span className="truncate">{c.header}</span>
                  {active && <span aria-hidden>{sort.dir === 'asc' ? '\u25b2' : '\u25bc'}</span>}
                </button>
              )
            })}
          </div>

          {loading && (
            <div className="p-6 text-sm" style={{ color: 'var(--muted)' }}>Loading the pinned run\u2026</div>
          )}
          {!loading && items.length === 0 && (
            <div className="p-6 text-sm" style={{ color: 'var(--muted)' }}>
              No players match the current filter. Clear the search or the presets.
            </div>
          )}

          <div ref={parentRef} className="flex-1 min-h-0 overflow-y-auto" tabIndex={-1}>
          <div style={{ height: virt.getTotalSize(), position: 'relative' }}>
            {rows.map((v) => {
              const item = items[v.index]
              if (!item) return null
              return (
                <div
                  key={v.key}
                  style={{ position: 'absolute', top: 0, left: 0, width: '100%', height: v.size, transform: `translateY(${v.start}px)` }}
                >
                  {item.kind === 'band' ? (
                    <div
                      className="flex items-center gap-2 px-2.5 text-[10px] font-bold uppercase tracking-widest h-full"
                      style={{
                        background: 'var(--band)', color: 'var(--muted)',
                        borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)',
                      }}
                    >
                      <span style={{ color: 'var(--text)' }}>{item.label}</span>
                      <span style={{ opacity: 0.7 }}>{item.count} {item.count === 1 ? 'player' : 'players'}</span>
                      <span className="flex-1" style={{ borderTop: '1px solid var(--border)' }} />
                    </div>
                  ) : (
                    <BoardRow
                      player={item.player}
                      selected={selectedId === item.player.player_id}
                      isBest={item.isBest}
                      valueTierBreak={item.valueTierBreak}
                      byeWarn={item.player.bye != null && byeWarnWeeks.has(item.player.bye)}
                      striped={v.index % 2 === 1}
                      onSelect={onSelect}
                      onOpen={onOpen}
                    />
                  )}
                </div>
              )
            })}
          </div>
          </div>
        </div>
      </div>
    </div>
  )
}
