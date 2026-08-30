/**
 * Draft-status strip. The one thing Derek must be able to read from across the room is
 * "how many picks until mine" — and, because he drafts from slot 10 of 10, that his picks come
 * in back-to-back pairs (10 & 11, 30 & 31, …). Both get the largest type on the page.
 */
import type { DraftState, NextPick, RunInfo } from '../api/types'
import { dateOnly, shortId, shortHash, stamp } from '../lib/format'
import { Pill } from './Chips'

interface Props {
  run: RunInfo | undefined
  state: DraftState | undefined
  myUpcoming: NextPick[]
  onExport: () => void
  renderMs: number | null
}

function Box({ label, children, tone }: { label: string; children: React.ReactNode; tone?: string }) {
  return (
    <div
      className="flex flex-col justify-center px-3 h-full"
      style={{ borderLeft: '1px solid var(--border)', background: tone }}
    >
      <div className="text-[9px] font-semibold uppercase tracking-widest mb-0.5" style={{ color: 'var(--muted)' }}>{label}</div>
      {children}
    </div>
  )
}

export function TopBar({ run, state, myUpcoming, onExport, renderMs }: Props) {
  const otc = state?.on_the_clock
  const until = state?.picks_until_mine
  const onClockNow = until === 0 || otc?.is_mine === true
  const next = myUpcoming[0]
  const after = myUpcoming[1]
  const backToBack = next != null && after != null && next.live_pick != null && after.live_pick != null
    && after.live_pick - next.live_pick === 1
  const pctDone = state && state.total_picks > 0 ? (state.picks_made / state.total_picks) * 100 : 0
  const mismatch = run != null && !run.config_hash_matches

  return (
    <header className="shrink-0" style={{ background: 'var(--panel)', borderBottom: '1px solid var(--border)' }}>
      <div className="flex items-stretch" style={{ height: 62 }}>
        {/* identity + provenance */}
        <div className="flex flex-col justify-center px-3.5 shrink-0" style={{ minWidth: 208 }}>
          <div className="flex items-center gap-2">
            <span className="font-semibold tracking-tight text-[14px]">Draft Board</span>
            <Pill tone={state?.mode === 'manual' ? 'info' : 'accent'} title="Pick entry mode">
              {(state?.mode ?? '…').toUpperCase()}
            </Pill>
            {run?.is_frozen
              ? <Pill tone="good" title="This run is frozen — the numbers cannot change under you">FROZEN</Pill>
              : <Pill tone="warn" title="Run is not frozen yet — re-freeze before the draft">DRAFT RUN</Pill>}
          </div>
          <div className="mono text-[10px] mt-0.5 flex items-center gap-1.5" style={{ color: 'var(--muted)' }}>
            <span title={`run_id ${run?.run_id ?? ''} · generated ${stamp(run?.generated_at)}`}>
              run {shortId(run?.run_id)}
            </span>
            <span>·</span>
            {mismatch ? (
              <span
                className="rounded px-1 font-bold"
                title="League config changed since the frozen run — re-freeze from the CLI"
                style={{ color: '#fff', background: 'var(--bad)' }}
              >
                cfg {shortHash(run?.league_config_sha256)} ✕
              </span>
            ) : (
              <span title={`league_config_sha256 ${run?.league_config_sha256 ?? ''} — matches the pinned run`}>
                cfg {shortHash(run?.league_config_sha256)} ✓
              </span>
            )}
          </div>
        </div>

        {/* on the clock */}
        <Box label="On the clock">
          {otc ? (
            <div className="flex items-baseline gap-2">
              <span className="mono text-[17px] font-bold" style={{ color: otc.is_mine ? 'var(--accent)' : 'var(--text)' }}>
                R{otc.round} P{otc.live_pick ?? otc.overall_pick}
              </span>
              <span className="text-[11px]" style={{ color: otc.is_mine ? 'var(--accent)' : 'var(--muted)' }}>
                {otc.is_mine ? 'YOU' : `Team ${otc.team_slot}`}
              </span>
            </div>
          ) : (
            <span className="text-[12px]" style={{ color: 'var(--muted)' }}>Draft complete</span>
          )}
        </Box>

        {/* the headline number */}
        <div
          className={`flex items-center gap-3 px-4 h-full ${onClockNow ? 'pulse' : ''}`}
          style={{
            borderLeft: '1px solid var(--border)',
            background: onClockNow ? 'rgba(88,166,255,0.14)' : 'transparent',
          }}
        >
          <div className="flex flex-col justify-center">
            <div className="text-[9px] font-semibold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>
              {onClockNow ? "You're up" : 'My next pick in'}
            </div>
            <div className="flex items-baseline gap-2">
              <span
                className="mono font-bold leading-none"
                style={{ fontSize: 30, color: onClockNow ? 'var(--accent)' : until != null && until <= 3 ? 'var(--warn)' : 'var(--text)' }}
              >
                {until == null ? '—' : until}
              </span>
              <span className="text-[11px]" style={{ color: 'var(--muted)' }}>
                {until === 1 ? 'pick' : 'picks'}
              </span>
              {next && (
                <span className="mono text-[12px]" style={{ color: 'var(--text)' }}>
                  → R{next.round} P{next.live_pick ?? next.overall_pick}
                </span>
              )}
            </div>
          </div>
          {backToBack && next && after && (
            <div
              className="flex flex-col justify-center rounded px-2 py-1"
              style={{ background: 'var(--accent-dim)', border: '1px solid rgba(88,166,255,0.4)' }}
              title="Slot 10 of 10 — the turn. Your picks come in pairs, so plan two players at a time."
            >
              <div className="text-[9px] font-bold uppercase tracking-widest" style={{ color: 'var(--accent)' }}>Back-to-back</div>
              <div className="mono text-[12px] font-semibold">
                P{next.live_pick} &amp; P{after.live_pick}
                <span className="text-[10px] font-normal" style={{ color: 'var(--muted)' }}> · R{next.round}/R{after.round}</span>
              </div>
            </div>
          )}
        </div>

        {/* progress */}
        <Box label="Picks made">
          <div className="mono text-[14px]">
            {state?.picks_made ?? '—'}<span style={{ color: 'var(--muted)' }}> / {state?.total_picks ?? '—'}</span>
          </div>
          <div className="mt-1 h-[3px] rounded" style={{ width: 92, background: 'var(--border)' }}>
            <div className="h-full rounded" style={{ width: `${pctDone}%`, background: 'var(--accent)' }} />
          </div>
        </Box>

        {/* league + draft time */}
        <Box label="Draft">
          <div className="text-[11.5px] leading-tight">
            {dateOnly(run?.league.draft_time)}
            <div style={{ color: 'var(--muted)' }}>
              slot {run?.league.my_slot ?? '—'} of {run?.league.teams ?? '—'} · {run?.league.rounds ?? '—'} rds
            </div>
          </div>
        </Box>

        <div className="flex items-center gap-2 px-3 ml-auto shrink-0" style={{ borderLeft: '1px solid var(--border)' }}>
          {renderMs != null && (
            <span
              className="mono text-[10px]"
              title="Time from first board data to painted rows (Phase 7 gate: < 2000 ms)"
              style={{ color: renderMs < 2000 ? 'var(--good)' : 'var(--bad)' }}
            >
              {renderMs.toFixed(0)} ms
            </span>
          )}
          <button
            type="button"
            onClick={onExport}
            className="rounded px-2.5 py-1.5 text-[12px] font-semibold"
            style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}
            title="Download the current board view as CSV"
          >
            ⭳ Export CSV
          </button>
        </div>
      </div>
    </header>
  )
}
