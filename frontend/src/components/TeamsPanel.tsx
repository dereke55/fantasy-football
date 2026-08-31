/**
 * Teams tab — all ten rosters as they have been recorded, and the drift check over them.
 *
 * Every pick this draft is typed by hand (Yahoo's API was not approved in time), so the board can
 * disagree with the real draft without anything going red: a missed pick, a double entry, or a pick
 * credited to the wrong team. The header answers "does our board still match Yahoo's?" in one look —
 * how many picks we hold, how many the snake says each team should hold by now, and which team is
 * off — and the rosters below let that be checked name by name against Yahoo's own board.
 *
 * Nothing here is computed from the players' numbers; it is pure bookkeeping over
 * `/api/rankings`, `/api/schedule`, `/api/keepers` and `/api/state` (see `lib/teamsModel.ts`).
 */
import { useState } from 'react'
import type { DraftState, RunInfo } from '../api/types'
import type { SlotTally, TeamSummary, TeamsModel } from '../lib/teamsModel'
import { DASH } from '../lib/format'
import { PosChip } from './Chips'

interface Props {
  run: RunInfo | undefined
  state: DraftState | undefined
  model: TeamsModel
  selectedId: number | null
  onSelect: (playerId: number) => void
}

export function TeamsPanel({ run, state, model, selectedId, onSelect }: Props) {
  /**
   * The one number the board cannot know: how many picks Yahoo has actually completed. Typing it in
   * turns "picks recorded" from a tautology into a real comparison — everything else on this panel
   * is derived from our own entries and would agree with itself even if we had missed three picks.
   */
  const [yahoo, setYahoo] = useState('')
  const yahooMade = yahoo.trim() === '' ? null : Number(yahoo)
  const yahooDelta = yahooMade != null && Number.isFinite(yahooMade) ? model.picksMade - yahooMade : null

  if (model.teams.length === 0) {
    return <div className="px-3 py-3 text-[11.5px]" style={{ color: 'var(--muted)' }}>Waiting for the schedule and the board…</div>
  }

  const otc = state?.on_the_clock
  const clean = model.offenders.length === 0 && model.missingFromBoard === 0

  return (
    <div className="flex flex-col overflow-y-auto min-h-0 flex-1">
      {/* ---------------- drift check ---------------- */}
      <div
        className="sticky top-0 z-10 px-3 py-2 flex flex-col gap-1.5"
        style={{ background: 'var(--panel)', borderBottom: '1px solid var(--border)' }}
      >
        <div className="flex items-baseline gap-1.5">
          <h3 className="text-[10px] font-bold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>Drift check</h3>
          <span className="mono num text-[15px] font-bold ml-auto">{model.picksMade}</span>
          <span className="mono text-[11px]" style={{ color: 'var(--muted)' }}>/ {model.totalPicks} picks</span>
        </div>

        <div className="mono text-[10.5px]" style={{ color: 'var(--muted)' }}>
          {otc
            ? <>snake says next is <span style={{ color: 'var(--text)' }}>R{otc.round} P{otc.live_pick} · T{otc.team_slot}</span>{otc.is_mine ? ' (me)' : ''}</>
            : 'draft complete'}
          {' · '}{model.keeperCount} keeper{model.keeperCount === 1 ? '' : 's'}
        </div>

        {/* per-team counts, and the ones that do not add up */}
        {clean ? (
          <div
            className="rounded px-2 py-1 text-[11.5px] flex items-center gap-1.5"
            style={{ background: 'var(--good-dim)', border: '1px solid rgba(63,185,80,0.35)', color: 'var(--good)' }}
          >
            <span aria-hidden>✓</span>
            <span>All {model.teams.length} teams match the snake{model.picksMade === 0 ? ' — no picks yet' : ''}.</span>
          </div>
        ) : (
          <div
            className="rounded px-2 py-1.5 text-[11.5px] flex flex-col gap-1"
            style={{ background: 'var(--bad-dim)', border: '1px solid rgba(248,81,73,0.5)' }}
          >
            <div className="font-bold flex items-center gap-1.5" style={{ color: 'var(--bad)' }}>
              <span aria-hidden>⚠</span>
              <span>
                {model.offenders.length > 0
                  ? `${model.offenders.length} team${model.offenders.length === 1 ? '' : 's'} off the snake`
                  : 'Picks missing from the board'}
              </span>
            </div>
            {model.offenders.map((t) => (
              <div key={t.slot} className="mono text-[11px]" style={{ color: 'var(--text)' }}>
                <span style={{ color: 'var(--bad)', fontWeight: 700 }}>T{t.slot}</span>
                {' has '}<span className="font-bold">{t.actual}</span>
                {', expected '}<span className="font-bold">{t.expected}</span>
                {' — '}
                <span style={{ color: 'var(--muted)' }}>
                  {t.delta > 0
                    ? `${t.delta} too many (a pick credited to T${t.slot} that was not theirs?)`
                    : `${-t.delta} missing (a pick of theirs recorded on another team?)`}
                </span>
              </div>
            ))}
            {model.missingFromBoard !== 0 && (
              <div className="text-[11px]" style={{ color: 'var(--muted)' }}>
                {model.picksMade} picks recorded but {model.boardPicks} appear on the board — a player outside the
                pinned run was drafted, so the round/pick numbers below may be shifted.
              </div>
            )}
          </div>
        )}

        {/* the external reference: what Yahoo's own board says */}
        <label className="flex items-center gap-1.5 text-[10.5px]" style={{ color: 'var(--muted)' }}>
          Yahoo picks made
          <input
            value={yahoo}
            onChange={(e) => setYahoo(e.target.value.replace(/[^0-9]/g, ''))}
            placeholder={DASH}
            inputMode="numeric"
            spellCheck={false}
            className="num mono rounded px-1 py-0.5 text-[11px] outline-none"
            style={{ background: 'var(--bg)', border: '1px solid var(--border)', width: 48 }}
            title="Type the number of picks Yahoo's draft board shows as completed — the one fact this app cannot derive"
          />
          {yahooDelta != null && (
            yahooDelta === 0 ? (
              <span style={{ color: 'var(--good)' }}>✓ in sync</span>
            ) : (
              <span className="font-bold" style={{ color: 'var(--bad)' }}>
                ⚠ we are {Math.abs(yahooDelta)} pick{Math.abs(yahooDelta) === 1 ? '' : 's'}{' '}
                {yahooDelta > 0 ? 'ahead — a pick was entered twice' : 'behind — a pick was missed'}
              </span>
            )
          )}
        </label>
      </div>

      {/* ---------------- rosters ---------------- */}
      <div className="flex flex-col gap-1.5 px-2 py-2">
        {model.teams.map((t) => (
          <TeamCard
            key={t.slot}
            team={t}
            rounds={run?.league.rounds ?? 16}
            selectedId={selectedId}
            onSelect={onSelect}
          />
        ))}
      </div>

      <div className="px-3 pb-3 text-[9.5px] leading-snug" style={{ color: 'var(--muted)' }}>
        Round and pick come from the pick schedule: the n-th pick recorded is the n-th live slot of the snake.
        A team's own tally counts keepers, which occupy a roster slot before the draft starts. Click any player
        to highlight him on the board.
      </div>
    </div>
  )
}

function TeamCard({
  team, rounds, selectedId, onSelect,
}: { team: TeamSummary; rounds: number; selectedId: number | null; onSelect: (id: number) => void }) {
  const off = team.delta !== 0
  const border = off ? 'rgba(248,81,73,0.55)' : team.isMine ? 'rgba(88,166,255,0.5)' : 'var(--border)'

  return (
    <section
      className="rounded"
      style={{
        border: `1px solid ${border}`,
        background: team.isMine ? 'rgba(88,166,255,0.05)' : 'var(--panel-3)',
      }}
    >
      <header className="flex items-center gap-1.5 px-1.5 py-1" style={{ borderBottom: '1px solid var(--border)' }}>
        <span
          className="mono text-[10px] font-bold rounded px-1"
          style={{
            color: team.isMine ? 'var(--accent)' : 'var(--muted)',
            background: team.isMine ? 'var(--accent-dim)' : 'transparent',
            border: `1px solid ${team.isMine ? 'rgba(88,166,255,0.45)' : 'var(--border)'}`,
          }}
        >T{team.slot}</span>
        <span className="text-[11.5px] font-semibold" style={{ color: team.isMine ? 'var(--accent)' : 'var(--text)' }}>
          {team.isMine ? 'My team' : `Team ${team.slot}`}
        </span>
        {team.keepers > 0 && (
          <span className="mono text-[9.5px] font-bold" style={{ color: 'var(--warn)' }} title="keepers held">
            {team.keepers}K
          </span>
        )}
        <span className="ml-auto flex items-baseline gap-1">
          <span className="num mono text-[12px] font-bold" style={{ color: off ? 'var(--bad)' : 'var(--text)' }}>
            {team.actual}
          </span>
          <span className="mono text-[10px]" style={{ color: 'var(--muted)' }}>/ {team.expected}</span>
          {off && (
            <span
              className="mono text-[10px] font-bold rounded px-1"
              style={{ color: 'var(--bad)', background: 'var(--bad-dim)', border: '1px solid rgba(248,81,73,0.45)' }}
              title={`recorded ${team.actual}, the snake expects ${team.expected} by now`}
            >{team.delta > 0 ? `+${team.delta}` : team.delta}</span>
          )}
        </span>
      </header>

      {/* positional tally against the league's starting requirements */}
      <div className="flex flex-wrap items-center gap-1 px-1.5 py-1">
        {team.tally.map((s) => <TallyChip key={s.label} slot={s} loud={team.isMine} />)}
        <span
          className="mono text-[9.5px] rounded px-1"
          style={{ color: 'var(--muted)', border: '1px dotted var(--border)', lineHeight: '15px' }}
          title={`bench ${team.benchFilled} of ${team.benchRequired}`}
        >
          BN {team.benchFilled}/{team.benchRequired}
        </span>
        {team.isMine && team.openStarters.length > 0 && (
          <span
            className="text-[10px] font-bold rounded px-1.5 ml-auto"
            style={{
              color: 'var(--accent)', background: 'rgba(88,166,255,0.12)',
              border: '1px dashed rgba(88,166,255,0.6)', lineHeight: '16px',
            }}
            title="starter slots still open on my roster"
          >
            OPEN {team.openStarters.join(' · ')}
          </span>
        )}
      </div>

      {/* picks in pick order */}
      {team.entries.length === 0 ? (
        <div className="px-1.5 pb-1 text-[10.5px]" style={{ color: 'var(--muted)' }}>No picks yet.</div>
      ) : (
        <div className="flex flex-col pb-0.5">
          {team.entries.map((e) => {
            const misattributed = e.scheduledSlot != null && e.scheduledSlot !== team.slot
            const selected = selectedId === e.playerId
            return (
              <button
                key={`${e.playerId}-${e.round}`}
                type="button"
                disabled={!e.onBoard}
                onClick={() => onSelect(e.playerId)}
                title={
                  e.isKeeper
                    ? `Keeper — costs round ${e.costRound} (schedule hole at overall pick ${e.overallPick ?? DASH})`
                    : `Live pick ${e.livePick} · overall ${e.overallPick}${misattributed ? ` — the snake gave this pick to T${e.scheduledSlot}` : ''}`
                }
                className="flex items-center gap-1.5 px-1.5 text-left text-[11.5px]"
                style={{
                  height: 20,
                  background: selected ? 'var(--row-selected)' : 'transparent',
                  cursor: e.onBoard ? 'pointer' : 'default',
                }}
              >
                <span
                  className="num mono text-[9.5px] shrink-0"
                  style={{ color: 'var(--muted)', width: 42 }}
                >
                  R{e.round}{e.round > rounds ? '?' : ''} {e.livePick == null ? ` ${DASH}` : `P${e.livePick}`}
                </span>
                <PosChip pos={e.pos} />
                <span className="truncate flex-1">{e.name}</span>
                {misattributed && (
                  <span className="mono text-[9px] font-bold shrink-0" style={{ color: 'var(--bad)' }} title={`slot ${e.scheduledSlot} owned this pick`}>
                    ≠T{e.scheduledSlot}
                  </span>
                )}
                <span className="mono text-[9.5px] shrink-0" style={{ color: 'var(--muted)', width: 26 }}>{e.team ?? DASH}</span>
                {e.isKeeper && (
                  <span className="mono text-[9px] font-bold shrink-0" style={{ color: 'var(--warn)' }} title={`keeper — cost round ${e.costRound}`}>
                    K{e.costRound}
                  </span>
                )}
              </button>
            )
          })}
        </div>
      )}
    </section>
  )
}

/**
 * `QB 0/1` — an unfilled starter slot reads as unfilled. Only my own team gets a filled chip:
 * at pick 3 every one of the ten rosters is empty, and ten cards of solid warning blocks would be
 * wallpaper by round 2. Colour carries the signal for the other nine; the fill is reserved for the
 * row Derek has to act on.
 */
function TallyChip({ slot, loud }: { slot: SlotTally; loud: boolean }) {
  const open = slot.filled < slot.required
  const color = open ? (loud ? 'var(--accent)' : 'var(--warn)') : 'var(--muted)'
  return (
    <span
      className="mono text-[9.5px] rounded px-1"
      style={{
        color,
        lineHeight: '15px',
        fontWeight: open && loud ? 700 : 400,
        background: open && loud ? 'rgba(88,166,255,0.12)' : 'transparent',
        border: `1px ${open ? 'dashed' : 'solid'} ${open ? (loud ? 'rgba(88,166,255,0.55)' : 'rgba(210,153,34,0.32)') : 'var(--border)'}`,
      }}
      title={`${slot.label}: ${slot.filled} of ${slot.required} starting slots filled`}
    >
      {slot.label} {slot.filled}/{slot.required}
    </span>
  )
}
