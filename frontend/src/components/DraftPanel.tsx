/**
 * Draft tab. Everything needed to make one pick without a second click: the highlighted player
 * with its two actions, the best available echo, the bye-stack warning, my roster and VONA.
 * Manual entry is first-class — the controls behave identically whatever `mode` says.
 */
import type { AvailabilityResponse, BoardPlayer, DraftState, RunInfo } from '../api/types'
import { int, one, pct } from '../lib/format'
import { FlagChips, PosChip } from './Chips'
import { RosterGrid } from './RosterGrid'
import { VonaPanel } from './VonaPanel'

interface Props {
  run: RunInfo | undefined
  state: DraftState | undefined
  availability: AvailabilityResponse | undefined
  selected: BoardPlayer | null
  best: BoardPlayer | null
  byeWarnWeeks: Set<number>
  busy: boolean
  teamOverride: number | null
  onTeamOverride: (slot: number | null) => void
  onDraft: (playerId: number, mine: boolean) => void
  onUndo: () => void
  onSelect: (playerId: number) => void
  onOpenDrawer: (playerId: number) => void
}

function Section({ title, right, children }: { title: string; right?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="px-3 py-2.5" style={{ borderTop: '1px solid var(--border)' }}>
      <div className="flex items-center justify-between mb-1.5">
        <h3 className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>{title}</h3>
        {right}
      </div>
      {children}
    </section>
  )
}

export function DraftPanel({
  run, state, availability, selected, best, byeWarnWeeks, busy, teamOverride, onTeamOverride,
  onDraft, onUndo, onSelect, onOpenDrawer,
}: Props) {
  const teams = run?.league.teams ?? 10
  const canUndo = (state?.picks_made ?? 0) > 0
  const round = state?.on_the_clock?.round ?? null

  return (
    <div className="flex flex-col overflow-y-auto min-h-0 flex-1">
      {/* selected player + the two actions */}
      <div className="px-3 pt-3 pb-2.5">
        {selected ? (
          <>
            <div className="flex items-start gap-2">
              <div className="min-w-0 flex-1">
                <button
                  type="button"
                  onClick={() => onOpenDrawer(selected.player_id)}
                  className="text-left text-[15px] font-semibold leading-tight truncate w-full"
                  title="Open the player drawer (Enter)"
                  style={{ textDecoration: selected.drafted ? 'line-through' : 'none' }}
                >
                  {selected.name}
                </button>
                <div className="flex items-center gap-1.5 mt-1 flex-wrap">
                  <PosChip pos={selected.pos} />
                  <span className="mono text-[11px]" style={{ color: 'var(--muted)' }}>
                    {selected.team ?? '—'} · bye {selected.bye ?? '—'}
                  </span>
                  <span className="mono text-[11px]" style={{ color: 'var(--muted)' }}>
                    #{selected.rank} · T{selected.tier ?? '—'}/VT{selected.value_tier ?? '—'}
                  </span>
                </div>
                <div className="mt-1"><FlagChips flags={selected.flags} tags={selected.tags} /></div>
              </div>
            </div>

            <div className="grid grid-cols-3 gap-1.5 mt-2 text-center">
              <Stat label="Proj PPG" value={one(selected.proj_ppg)} sub={`${int(selected.proj_season)} szn`} />
              <Stat label="Value" value={selected.is_kdst ? '—' : int(selected.value)} sub={`ECR ${one(selected.ecr)}`} />
              <Stat
                label="P(avail)"
                value={pct(selected.p_avail)}
                sub={selected.vona != null ? `VONA ${one(selected.vona)}` : '—'}
                tone={selected.p_avail != null && selected.p_avail >= 0.66 ? 'var(--good)' : selected.p_avail != null && selected.p_avail <= 0.2 ? 'var(--bad)' : 'var(--warn)'}
              />
            </div>

            {selected.drafted ? (
              <div
                className="mt-2 rounded px-2 py-2 text-[12px] text-center"
                style={{ background: 'var(--panel-3)', border: '1px solid var(--border)', color: 'var(--muted)' }}
              >
                Already drafted{selected.drafted_by != null ? ` — team ${selected.drafted_by}` : ''}
                {selected.is_keeper ? ' (keeper)' : ''}. Undo is the way back.
              </div>
            ) : (
              <div className="grid grid-cols-2 gap-1.5 mt-2">
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDraft(selected.player_id, false)}
                  className="rounded py-2 text-[13px] font-semibold"
                  style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}
                  title="POST /api/draft/picks — fills the pick on the clock"
                >
                  Drafted <kbd className="mono text-[10px]" style={{ color: 'var(--muted)' }}>d</kbd>
                </button>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onDraft(selected.player_id, true)}
                  className="rounded py-2 text-[13px] font-bold"
                  style={{ background: 'var(--accent)', color: '#06121f', border: '1px solid var(--accent)' }}
                  title="POST /api/draft/picks with my_pick: true"
                >
                  My pick <kbd className="mono text-[10px]" style={{ opacity: 0.65 }}>m</kbd>
                </button>
              </div>
            )}
          </>
        ) : (
          <div className="text-[12px] py-3" style={{ color: 'var(--muted)' }}>
            No row highlighted. Click a row or press <kbd className="mono">j</kbd> / <kbd className="mono">k</kbd>.
          </div>
        )}

        <div className="flex items-center gap-1.5 mt-2">
          <button
            type="button"
            disabled={busy || !canUndo}
            onClick={onUndo}
            className="rounded px-2 py-1 text-[11.5px]"
            style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--muted)' }}
            title="POST /api/draft/undo — removes the most recent manual pick"
          >
            ↶ Undo <kbd className="mono text-[10px]">u</kbd>
          </button>
          <label className="ml-auto flex items-center gap-1 text-[10.5px]" style={{ color: 'var(--muted)' }}>
            for team
            <select
              value={teamOverride ?? ''}
              onChange={(e) => onTeamOverride(e.target.value === '' ? null : Number(e.target.value))}
              className="rounded px-1 py-0.5 text-[11px]"
              style={{ background: 'var(--bg)', border: '1px solid var(--border)' }}
              title="Override the drafting team; default is whoever is on the clock"
            >
              <option value="">on the clock</option>
              {Array.from({ length: teams }, (_, i) => i + 1).map((s) => (
                <option key={s} value={s}>Team {s}{s === state?.my_slot ? ' (me)' : ''}</option>
              ))}
            </select>
          </label>
        </div>
      </div>

      {/* bye-stack warning */}
      {state && state.bye_stack_warnings.length > 0 && (
        <div className="mx-3 mb-2 rounded px-2 py-1.5 text-[11.5px]" style={{ background: 'var(--warn-dim)', border: '1px solid rgba(210,153,34,0.45)' }}>
          {state.bye_stack_warnings.map((w) => (
            <div key={w.bye_week}>
              <span style={{ color: 'var(--warn)', fontWeight: 700 }}>⚠ {w.players.length} projected starters share bye {w.bye_week}</span>
              <div style={{ color: 'var(--muted)' }}>{w.players.join(', ')}</div>
            </div>
          ))}
        </div>
      )}

      {/* best available */}
      <Section title="Best available">
        {best ? (
          <button
            type="button"
            onClick={() => onSelect(best.player_id)}
            className="w-full rounded px-2 py-1.5 text-left"
            style={{ background: 'rgba(63,185,80,0.09)', border: '1px solid rgba(63,185,80,0.4)' }}
          >
            <div className="flex items-center gap-1.5">
              <span style={{ color: 'var(--good)' }}>★</span>
              <span className="font-semibold text-[13px] truncate">{best.name}</span>
              <PosChip pos={best.pos} />
              <span className="mono text-[10.5px] ml-auto" style={{ color: 'var(--muted)' }}>#{best.rank}</span>
            </div>
            <div className="mono text-[10.5px] mt-0.5" style={{ color: 'var(--muted)' }}>
              P(avail) {pct(best.p_avail)} · VONA {one(best.vona)} · value {best.is_kdst ? '—' : int(best.value)}
            </div>
          </button>
        ) : (
          <div className="text-[11.5px]" style={{ color: 'var(--muted)' }}>Nothing undrafted under this filter.</div>
        )}
      </Section>

      {/* VONA */}
      <Section
        title="VONA top 3 by position"
        right={availability?.my_next_pick
          ? <span className="mono text-[10px]" style={{ color: 'var(--muted)' }}>at R{availability.my_next_pick.round} P{availability.my_next_pick.live_pick}</span>
          : null}
      >
        <VonaPanel availability={availability} currentRound={round} onPick={onSelect} />
      </Section>

      {/* roster */}
      <Section
        title="My roster"
        right={
          <span className="text-[10px]" style={{ color: 'var(--muted)' }}>
            {Object.entries(state?.open_slots ?? {}).filter(([, n]) => n > 0).map(([p, n]) => `${p}×${n}`).join(' ') || 'starters full'}
          </span>
        }
      >
        <RosterGrid league={run?.league} roster={state?.my_roster ?? []} byeWarnWeeks={byeWarnWeeks} />
      </Section>

      {/* recent picks */}
      <Section title="Recent picks">
        {state && state.recent_picks.length > 0 ? (
          <div className="flex flex-col gap-0.5">
            {[...state.recent_picks].reverse().map((p) => (
              <div key={p.id} className="flex items-center gap-1.5 text-[11.5px]">
                <span className="mono text-[10px] shrink-0" style={{ color: 'var(--muted)', width: 46 }}>
                  R{p.round} P{p.overall_pick}
                </span>
                <span className="mono text-[10px] shrink-0" style={{ color: p.team_slot === state.my_slot ? 'var(--accent)' : 'var(--muted)', width: 24 }}>
                  T{p.team_slot}
                </span>
                <span className="truncate">{p.name ?? '(unresolved)'}</span>
                {p.position && <PosChip pos={p.position} />}
              </div>
            ))}
          </div>
        ) : (
          <div className="text-[11.5px]" style={{ color: 'var(--muted)' }}>No picks yet.</div>
        )}
      </Section>
    </div>
  )
}

function Stat({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="rounded px-1 py-1" style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}>
      <div className="text-[9px] uppercase tracking-wider" style={{ color: 'var(--muted)' }}>{label}</div>
      <div className="mono text-[14px] font-semibold" style={{ color: tone ?? 'var(--text)' }}>{value}</div>
      {sub && <div className="mono text-[9.5px]" style={{ color: 'var(--muted)' }}>{sub}</div>}
    </div>
  )
}
