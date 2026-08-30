/**
 * Keepers tab. A keeper is a hole in the pick schedule, so every add/remove moves `total_picks`,
 * `picks_until_mine`, the room ADP and P(avail) — the panel and the board both refetch from the
 * returned state (Phase 7 gate: no reload).
 *
 * The API exposes POST and DELETE only (no PUT), so "edit" is remove-then-add; the UI says so
 * rather than pretending an inline edit exists.
 */
import { useMemo, useRef, useState } from 'react'
import type { BoardPlayer, Keeper, RunInfo } from '../api/types'
import { PosChip, Pill } from './Chips'

interface Props {
  run: RunInfo | undefined
  keepers: Keeper[]
  players: BoardPlayer[]
  busy: boolean
  error: string | null
  note: string | null
  onAdd: (body: { player_id: number; team_slot: number; cost_round: number; status: string }) => void
  onDelete: (id: number) => void
  onDismiss: () => void
}

export function KeeperPanel({ run, keepers, players, busy, error, note, onAdd, onDelete, onDismiss }: Props) {
  const teams = run?.league.teams ?? 10
  const rounds = run?.league.rounds ?? 16
  const [slot, setSlot] = useState<number>(run?.league.my_slot ?? 1)
  const [round, setRound] = useState<number>(1)
  const [status, setStatus] = useState('declared')
  const [query, setQuery] = useState('')
  const [picked, setPicked] = useState<BoardPlayer | null>(null)
  const [open, setOpen] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)

  const matches = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (q.length < 2) return []
    return players.filter((p) => p.name.toLowerCase().includes(q)).slice(0, 8)
  }, [players, query])

  const grouped = useMemo(() => {
    const by = new Map<number, Keeper[]>()
    for (const k of keepers) by.set(k.team_slot, [...(by.get(k.team_slot) ?? []), k])
    return by
  }, [keepers])

  const submit = () => {
    if (!picked) return
    onAdd({ player_id: picked.player_id, team_slot: slot, cost_round: round, status })
  }

  return (
    <div className="flex flex-col overflow-y-auto min-h-0 flex-1">
      <div className="px-3 py-2.5 flex items-center gap-2 flex-wrap" style={{ borderBottom: '1px solid var(--border)' }}>
        <Pill tone="info">MAX {run?.league.max_keepers ?? '—'} PER TEAM</Pill>
        <Pill tone={run?.league.keeper_deadline ? 'warn' : 'info'} title="Yahoo keeper deadline">
          DEADLINE {run?.league.keeper_deadline ?? '—'}
        </Pill>
        <span className="text-[10.5px] ml-auto" style={{ color: 'var(--muted)' }}>{keepers.length} declared</span>
      </div>

      <div className="px-3 py-2.5 flex flex-col gap-2" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="relative">
          <label className="block text-[9px] font-bold uppercase tracking-widest mb-0.5" style={{ color: 'var(--muted)' }}>Player</label>
          <input
            ref={inputRef}
            value={picked ? `${picked.name} · ${picked.pos} ${picked.team ?? ''}` : query}
            onChange={(e) => { setPicked(null); setQuery(e.target.value); setOpen(true) }}
            onFocus={() => setOpen(true)}
            placeholder="type at least 2 letters"
            spellCheck={false}
            className="w-full rounded px-2 py-1 text-[12px] outline-none"
            style={{ background: 'var(--bg)', border: `1px solid ${picked ? 'var(--good)' : 'var(--border)'}` }}
          />
          {open && matches.length > 0 && !picked && (
            <div
              className="absolute z-20 left-0 right-0 mt-0.5 rounded overflow-hidden"
              style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', boxShadow: '0 8px 24px rgba(0,0,0,0.55)' }}
            >
              {matches.map((m) => (
                <button
                  key={m.player_id}
                  type="button"
                  onClick={() => { setPicked(m); setOpen(false); setQuery('') }}
                  className="flex w-full items-center gap-1.5 px-2 py-1 text-left text-[12px]"
                  style={{ background: 'transparent' }}
                >
                  <span className="truncate flex-1">{m.name}</span>
                  <PosChip pos={m.pos} />
                  <span className="mono text-[10px]" style={{ color: 'var(--muted)' }}>{m.team} #{m.rank}</span>
                </button>
              ))}
            </div>
          )}
        </div>

        <div className="grid grid-cols-3 gap-1.5">
          <Field label="Team slot">
            <select value={slot} onChange={(e) => setSlot(Number(e.target.value))} className="w-full rounded px-1 py-1 text-[12px]" style={selStyle}>
              {Array.from({ length: teams }, (_, i) => i + 1).map((s) => (
                <option key={s} value={s}>Team {s}{s === run?.league.my_slot ? ' (me)' : ''}</option>
              ))}
            </select>
          </Field>
          <Field label="Cost round">
            <select value={round} onChange={(e) => setRound(Number(e.target.value))} className="w-full rounded px-1 py-1 text-[12px]" style={selStyle}>
              {Array.from({ length: rounds }, (_, i) => i + 1).map((r) => <option key={r} value={r}>R{r}</option>)}
            </select>
          </Field>
          <Field label="Status">
            <select value={status} onChange={(e) => setStatus(e.target.value)} className="w-full rounded px-1 py-1 text-[12px]" style={selStyle}>
              <option value="declared">declared</option>
              <option value="approved">approved</option>
            </select>
          </Field>
        </div>

        <button
          type="button"
          disabled={busy || !picked}
          onClick={submit}
          className="rounded py-1.5 text-[12.5px] font-semibold"
          style={{ background: 'var(--accent)', color: '#06121f', border: '1px solid var(--accent)' }}
        >
          Add keeper
        </button>

        {error && (
          <div
            className="rounded px-2 py-1.5 text-[11.5px] flex items-start gap-1.5"
            style={{ background: 'var(--bad-dim)', border: '1px solid rgba(248,81,73,0.45)', color: 'var(--bad)' }}
          >
            <span>✕</span>
            <span className="flex-1">{error}</span>
            <button type="button" onClick={onDismiss} style={{ color: 'var(--muted)' }}>×</button>
          </div>
        )}
        {note && (
          <div
            className="rounded px-2 py-1.5 text-[11px] flex items-start gap-1.5"
            style={{ background: 'var(--warn-dim)', border: '1px solid rgba(210,153,34,0.4)', color: 'var(--warn)' }}
          >
            <span>⚠</span><span className="flex-1">{note}</span>
            <button type="button" onClick={onDismiss} style={{ color: 'var(--muted)' }}>×</button>
          </div>
        )}
      </div>

      <div className="px-3 py-2.5 flex flex-col gap-2">
        <div className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>
          Declared keepers · rounds consumed
        </div>
        {Array.from({ length: teams }, (_, i) => i + 1).map((s) => {
          const ks = grouped.get(s) ?? []
          const mine = s === run?.league.my_slot
          return (
            <div key={s} className="rounded" style={{ border: '1px solid var(--border)', background: ks.length ? 'var(--panel-3)' : 'transparent' }}>
              <div className="flex items-center gap-1.5 px-2 py-1 text-[11px]">
                <span className="mono font-bold" style={{ color: mine ? 'var(--accent)' : 'var(--muted)' }}>Team {s}{mine ? ' · me' : ''}</span>
                <span className="ml-auto" style={{ color: 'var(--muted)' }}>
                  {ks.length ? ks.map((k) => `R${k.cost_round}`).join(', ') : 'none'}
                </span>
              </div>
              {ks.map((k) => (
                <div key={k.id} className="flex items-center gap-1.5 px-2 py-1 text-[12px]" style={{ borderTop: '1px solid var(--border)' }}>
                  <span className="truncate flex-1">{k.name}</span>
                  <PosChip pos={k.position} />
                  <span className="mono text-[10px]" style={{ color: 'var(--muted)' }}>{k.team}</span>
                  <span className="mono text-[10px] font-bold" style={{ color: 'var(--warn)' }}>R{k.cost_round}</span>
                  <Pill tone="info" title={`source: ${k.source} · status: ${k.status}`}>{k.source}</Pill>
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => onDelete(k.id)}
                    title="DELETE /api/keepers/{id} — removes the keeper and restores the pick"
                    className="rounded px-1 text-[11px]"
                    style={{ color: 'var(--bad)', border: '1px solid rgba(248,81,73,0.35)' }}
                  >×</button>
                </div>
              ))}
            </div>
          )
        })}
        <div className="text-[10px] leading-snug" style={{ color: 'var(--muted)' }}>
          No PUT endpoint exists — to change a keeper, remove it and add it again. Adding or removing a keeper
          re-cuts the pick schedule immediately; room ADP and P(avail) follow the next `ff rank run`.
        </div>
      </div>
    </div>
  )
}

const selStyle = { background: 'var(--bg)', border: '1px solid var(--border)' } as const

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <label className="block text-[9px] font-bold uppercase tracking-widest mb-0.5" style={{ color: 'var(--muted)' }}>{label}</label>
      {children}
    </div>
  )
}
