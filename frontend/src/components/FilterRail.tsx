/**
 * Narrow left rail: position chips, the two saved presets, the hide-drafted toggle and search.
 * Everything here filters client-side over the pinned payload — no request is made (§3).
 */
import { forwardRef } from 'react'
import type { BoardFilters } from '../lib/boardModel'
import { PRESETS } from '../lib/flags'
import { POS_FILTERS } from '../lib/positions'
import { posColor } from '../lib/positions'

interface Props {
  filters: BoardFilters
  counts: Record<string, number>
  shown: number
  total: number
  undrafted: number
  onChange: (f: BoardFilters) => void
}

export const FilterRail = forwardRef<HTMLInputElement, Props>(function FilterRail(
  { filters, counts, shown, total, undrafted, onChange }, searchRef,
) {
  const set = (patch: Partial<BoardFilters>) => onChange({ ...filters, ...patch })
  const togglePreset = (k: string) =>
    set({ presets: filters.presets.includes(k) ? filters.presets.filter((p) => p !== k) : [...filters.presets, k] })

  const chip = (active: boolean, accent?: string) => ({
    background: active ? (accent ? `${accent}22` : 'var(--accent-dim)') : 'transparent',
    borderColor: active ? (accent ?? 'var(--accent)') : 'var(--border)',
    color: active ? (accent ?? 'var(--accent)') : 'var(--muted)',
  })

  const dirty = filters.pos != null || filters.presets.length > 0 || filters.search !== '' || filters.hideDrafted

  return (
    <aside
      className="flex flex-col gap-3 p-2.5 shrink-0 overflow-y-auto"
      style={{ width: 146, background: 'var(--panel)', borderRight: '1px solid var(--border)' }}
    >
      <div>
        <label className="block text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--muted)' }}>
          Search <span className="mono" style={{ opacity: 0.7 }}>/</span>
        </label>
        <input
          ref={searchRef}
          value={filters.search}
          onChange={(e) => set({ search: e.target.value })}
          placeholder="name / team"
          spellCheck={false}
          className="w-full rounded px-2 py-1 text-[12px] outline-none"
          style={{ background: 'var(--bg)', border: '1px solid var(--border)' }}
        />
      </div>

      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--muted)' }}>Position</div>
        <div className="flex flex-wrap gap-1">
          <button
            type="button"
            onClick={() => set({ pos: null })}
            className="rounded border px-1.5 py-0.5 text-[11px] font-semibold"
            style={chip(filters.pos == null)}
          >
            ALL <span style={{ opacity: 0.65 }}>{total}</span>
          </button>
          {POS_FILTERS.map((p) => {
            const c = posColor(p.key)
            return (
              <button
                key={p.key}
                type="button"
                onClick={() => set({ pos: filters.pos === p.key ? null : p.key })}
                className="rounded border px-1.5 py-0.5 text-[11px] font-semibold"
                style={chip(filters.pos === p.key, c.fg)}
              >
                {p.label} <span style={{ opacity: 0.65 }}>{counts[p.key] ?? 0}</span>
              </button>
            )
          })}
        </div>
        {(filters.pos === 'K' || filters.pos === 'DEF') && (
          <div className="mt-1.5 text-[10px] leading-snug" style={{ color: 'var(--warn)' }}>
            K and DST carry VBD 0 — take them in the last two rounds.
          </div>
        )}
      </div>

      <div>
        <div className="text-[10px] font-semibold uppercase tracking-wider mb-1" style={{ color: 'var(--muted)' }}>Presets</div>
        <div className="flex flex-col gap-1">
          {PRESETS.map((p) => (
            <button
              key={p.key}
              type="button"
              onClick={() => togglePreset(p.key)}
              className="flex items-center justify-between rounded border px-1.5 py-0.5 text-[11px] font-semibold"
              style={chip(filters.presets.includes(p.key), p.key === 'bust' ? 'var(--bad)' : 'var(--good)')}
            >
              <span>{p.icon} {p.label}</span>
              <span style={{ opacity: 0.65 }}>{counts[p.key] ?? 0}</span>
            </button>
          ))}
        </div>
      </div>

      <div>
        <label className="flex items-center gap-1.5 text-[11px] cursor-pointer" style={{ color: 'var(--muted)' }}>
          <input
            type="checkbox"
            checked={filters.hideDrafted}
            onChange={(e) => set({ hideDrafted: e.target.checked })}
            style={{ accentColor: 'var(--accent)' }}
          />
          Hide drafted
        </label>
        <div className="mt-1 text-[10px] leading-snug" style={{ color: 'var(--muted)', opacity: 0.8 }}>
          Off by default — drafted rows stay in place, dimmed.
        </div>
      </div>

      <div className="mt-auto pt-2 text-[10.5px] leading-relaxed" style={{ color: 'var(--muted)', borderTop: '1px solid var(--border)' }}>
        <div><span className="mono" style={{ color: 'var(--text)' }}>{shown}</span> shown</div>
        <div><span className="mono" style={{ color: 'var(--good)' }}>{undrafted}</span> undrafted</div>
        {dirty && (
          <button
            type="button"
            onClick={() => onChange({ pos: null, presets: [], search: '', hideDrafted: false })}
            className="mt-1.5 w-full rounded border px-1.5 py-0.5 text-[10.5px]"
            style={{ borderColor: 'var(--border)', color: 'var(--muted)' }}
          >
            Clear filters
          </button>
        )}
      </div>
    </aside>
  )
})
