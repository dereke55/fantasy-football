/**
 * Quick pick — the draft-day entry path.
 *
 * Yahoo's API was not approved in time (1-2 week turnaround), so every one of the ~159 picks is entered by hand
 * while the draft clock runs. That makes keystrokes-per-pick the thing worth optimising: type two or three
 * letters, press Enter, and the top match is recorded against whoever is on the clock. The box re-focuses itself
 * so consecutive picks need no mouse at all.
 *
 * Enter        draft the highlighted match to the team on the clock
 * Shift+Enter  draft it to MY team (a correction, or my own pick)
 * ArrowDown/Up cycle matches      Tab completes to the highlighted name
 * Escape       leave the box and return to board navigation (j/k/d/m)
 */
import { useEffect, useMemo, useRef, useState } from 'react'

import type { BoardPlayer, DraftState } from '../api/types'
import { posColor } from '../lib/positions'

const norm = (s: string): string =>
  s.toLowerCase().normalize('NFKD').replace(/[̀-ͯ]/g, '').replace(/[^a-z0-9 ]/g, '')

/**
 * Player rank is worth this many places of match quality. Strict tiering is wrong here: typing "chas" put
 * Chase McLaughlin (a kicker, rank 140) and Chase Roberts (rank 564) above Ja'Marr Chase (rank 4), purely
 * because their FIRST name matched. Under time pressure a fast Enter on that list records the wrong player.
 * Trading one match tier for ~60 board places puts the two plausible answers first and keeps the noise below.
 */
const TIER_WEIGHT = 60

/** Matches ordered by how well the query fits AND how likely the player is to be the one meant. */
export function matchPlayers(players: BoardPlayer[], query: string, limit = 6): BoardPlayer[] {
  const q = norm(query).trim()
  if (!q) return []
  const parts = q.split(' ').filter(Boolean)
  const scored: { p: BoardPlayer; s: number }[] = []
  for (const p of players) {
    if (p.drafted) continue
    const n = norm(p.name)
    const words = n.split(' ')
    const last = words[words.length - 1] ?? ''
    let tier = -1
    if (n.startsWith(q)) tier = 0
    else if (last.startsWith(q)) tier = 0            // surnames are how players are actually called
    else if (words.some((w) => w.startsWith(q))) tier = 1
    else if (parts.length > 1 && parts.every((part) => words.some((w) => w.startsWith(part)))) tier = 1
    else if (n.includes(q)) tier = 2
    if (tier >= 0) scored.push({ p, s: tier * TIER_WEIGHT + Math.min(p.rank ?? 9999, 9999) })
  }
  scored.sort((a, b) => a.s - b.s)
  return scored.slice(0, limit).map((x) => x.p)
}

export function QuickPick({
  players, state, busy, onPick,
}: {
  players: BoardPlayer[]
  state: DraftState | undefined
  busy: boolean
  onPick: (playerId: number, mine: boolean) => void
}) {
  const [q, setQ] = useState('')
  const [i, setI] = useState(0)
  const ref = useRef<HTMLInputElement>(null)
  const matches = useMemo(() => matchPlayers(players, q), [players, q])
  useEffect(() => { setI(0) }, [q])

  const otc = state?.on_the_clock
  const mine = otc?.is_mine ?? false

  const submit = (asMine: boolean) => {
    const p = matches[i]
    if (!p || busy) return
    onPick(p.player_id, asMine)
    setQ('')
    setI(0)
    ref.current?.focus()
  }

  return (
    <div className="relative">
      <div
        className="flex items-center gap-2 rounded px-2 h-9 border"
        style={{
          background: 'var(--panel)',
          borderColor: mine ? 'var(--accent)' : 'var(--border)',
          boxShadow: mine ? '0 0 0 1px var(--accent)' : undefined,
        }}
      >
        <span className="text-[10px] uppercase tracking-wide shrink-0" style={{ color: mine ? 'var(--accent)' : 'var(--muted)' }}>
          {otc ? (mine ? 'YOUR PICK' : `R${otc.round} P${otc.live_pick} · T${otc.team_slot}`) : 'DRAFT OVER'}
        </span>
        <input
          ref={ref}
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="type a name, Enter to record…"
          spellCheck={false}
          autoComplete="off"
          className="flex-1 bg-transparent outline-none text-sm min-w-0"
          style={{ color: 'var(--text)' }}
          onKeyDown={(e) => {
            if (e.key === 'Enter') { e.preventDefault(); submit(e.shiftKey) }
            else if (e.key === 'ArrowDown') { e.preventDefault(); setI((v) => Math.min(v + 1, matches.length - 1)) }
            else if (e.key === 'ArrowUp') { e.preventDefault(); setI((v) => Math.max(v - 1, 0)) }
            else if (e.key === 'Tab' && matches[i]) { e.preventDefault(); setQ(matches[i].name) }
          }}
        />
        {q && (
          <span className="text-[10px] shrink-0" style={{ color: 'var(--muted)' }}>
            {matches.length ? `${i + 1}/${matches.length} · ⇧⏎ = mine` : 'no match'}
          </span>
        )}
      </div>

      {q && matches.length > 0 && (
        <ul
          className="absolute z-30 left-0 right-0 mt-1 rounded border overflow-hidden"
          style={{ background: 'var(--panel)', borderColor: 'var(--border)' }}
        >
          {matches.map((p, n) => (
            <li
              key={p.player_id}
              onMouseEnter={() => setI(n)}
              onMouseDown={(e) => { e.preventDefault(); setI(n); submit(false) }}
              className="flex items-center gap-2 px-2 py-1.5 text-sm cursor-pointer"
              style={{ background: n === i ? 'var(--border)' : 'transparent' }}
            >
              <span className="tabular-nums text-[11px] w-8 text-right" style={{ color: 'var(--muted)' }}>
                {p.rank ?? '—'}
              </span>
              <span
                className="text-[10px] font-semibold px-1 rounded"
                style={{ color: posColor(p.pos).fg, background: posColor(p.pos).bg, border: `1px solid ${posColor(p.pos).border}` }}
              >
                {p.pos}
              </span>
              <span className="flex-1 truncate">{p.name}</span>
              <span className="text-[11px]" style={{ color: 'var(--muted)' }}>{p.team ?? ''}</span>
              <span className="text-[11px] tabular-nums" style={{ color: 'var(--muted)' }}>
                ADP {p.composite_adp?.toFixed(0) ?? '—'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
