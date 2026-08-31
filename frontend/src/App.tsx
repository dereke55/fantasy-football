/**
 * Composition root. Holds the board's view state (filters, sort, highlighted row, drawer, tab)
 * and wires the keyboard. Every number rendered below comes from the pinned run via TanStack Query;
 * nothing is computed here except filtering, sorting and which row is highlighted.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { ApiError, boardCsvUrl } from './api/client'
import {
  useAddKeeper, useAvailability, useDeleteKeeper, useDraftState, useKeepers, useMakePick,
  usePlayerProfile, useRankings, useRun, useSchedule, useUndoPick,
} from './api/queries'
import type { BoardPlayer, NextPick } from './api/types'
import { EMPTY_FILTERS, bestAvailable, buildRows, filterPlayers, sortPlayers } from './lib/boardModel'
import type { BoardFilters, SortDir, SortKey } from './lib/boardModel'
import { buildTeams } from './lib/teamsModel'
import { COLUMNS } from './components/columns'
import { AttributionFooter } from './components/AttributionFooter'
import { QuickPick } from './components/QuickPick'
import { Board } from './components/Board'
import { ConfigMismatchBanner, NoRunState, OfflineBanner } from './components/Banners'
import { DraftPanel } from './components/DraftPanel'
import { FilterRail } from './components/FilterRail'
import { KeeperPanel } from './components/KeeperPanel'
import { PlayerDrawer } from './components/PlayerDrawer'
import { TeamsPanel } from './components/TeamsPanel'
import { Toasts } from './components/Toasts'
import { TopBar } from './components/TopBar'
import type { Toast } from './components/Toasts'

const SHORTCUTS = 'quick pick: type a name + ⏎ (⇧⏎ = mine) · j/k move · d drafted · m my pick · ⏎ drawer · esc close · u undo · / search'

export default function App() {
  const run = useRun()
  const rankings = useRankings()
  const state = useDraftState()
  const schedule = useSchedule()
  const availability = useAvailability()
  const keepers = useKeepers()

  const [filters, setFilters] = useState<BoardFilters>(EMPTY_FILTERS)
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: 'rank', dir: 'asc' })
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [tab, setTab] = useState<'draft' | 'teams' | 'keepers'>('draft')
  const [toasts, setToasts] = useState<Toast[]>([])
  const [renderMs, setRenderMs] = useState<number | null>(null)
  const [scrollToIndex, setScrollToIndex] = useState<number | null>(null)
  const [teamOverride, setTeamOverride] = useState<number | null>(null)
  const [keeperError, setKeeperError] = useState<string | null>(null)
  const [keeperNote, setKeeperNote] = useState<string | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const selectedRef = useRef<number | null>(null)
  const toastSeq = useRef(0)

  /** One button that brings every query back after the API returns — not just the three the
   *  empty state happens to know about. */
  const retryAll = useCallback(() => {
    void run.refetch(); void rankings.refetch(); void state.refetch()
    void schedule.refetch(); void availability.refetch(); void keepers.refetch()
  }, [run, rankings, state, schedule, availability, keepers])

  const pushToast = useCallback((text: string, tone: Toast['tone'] = 'info') => {
    const id = ++toastSeq.current
    setToasts((t) => [...t.slice(-2), { id, text, tone }])
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === 'bad' ? 6000 : 2600)
  }, [])

  /* ---------- board rows ---------- */
  /**
   * `/api/rankings` reflects `draft_picks` but not the `keepers` table, so a declared keeper comes
   * back as undrafted and would sit on the board as if he were available. The two endpoints are
   * both authoritative, so the join happens here: a kept player is drafted, carries the K badge and
   * is attributed to the team that kept him.
   */
  const rawPlayers = useMemo(() => rankings.data?.players ?? [], [rankings.data])
  const keeperById = useMemo(() => {
    const m = new Map<number, { team_slot: number }>()
    for (const k of keepers.data?.keepers ?? []) m.set(k.player_id, { team_slot: k.team_slot })
    return m
  }, [keepers.data])
  const players = useMemo(() => {
    if (keeperById.size === 0) return rawPlayers
    return rawPlayers.map((p) => {
      const k = keeperById.get(p.player_id)
      if (!k || p.drafted) return p
      return {
        ...p,
        drafted: true,
        is_keeper: true,
        drafted_by: k.team_slot,
        is_mine: k.team_slot === (run.data?.league.my_slot ?? null),
      }
    })
  }, [rawPlayers, keeperById, run.data])
  const byId = useMemo(() => new Map(players.map((p) => [p.player_id, p])), [players])

  const makePick = useMakePick(
    (kind) => pushToast(kind === 'my-pick' ? 'Added to my roster' : 'Marked drafted', 'good'),
    (msg) => pushToast(msg, 'bad'),
  )
  const undo = useUndoPick(() => pushToast('Undid the last pick', 'good'), (msg) => pushToast(msg, 'bad'))
  const addKeeper = useAddKeeper(
    (note) => { setKeeperError(null); setKeeperNote(note ?? null); pushToast('Keeper added — pick schedule re-cut', 'good') },
    (msg) => { setKeeperError(msg); pushToast(msg, 'bad') },
  )
  const delKeeper = useDeleteKeeper(
    (note) => { setKeeperError(null); setKeeperNote(note ?? null); pushToast('Keeper removed — pick restored', 'good') },
    (msg) => { setKeeperError(msg); pushToast(msg, 'bad') },
  )
  const busy = makePick.isPending || undo.isPending || addKeeper.isPending || delKeeper.isPending

  /* ---------- derived board ---------- */
  const filtered = useMemo(() => filterPlayers(players, filters), [players, filters])
  const sorted = useMemo(() => sortPlayers(filtered, sort.key, sort.dir), [filtered, sort])
  // Bands are meaningful in ranked order (our value) and in ECR order; each follows the tier that is
  // monotonic under that sort (see buildRows).
  const bands = (sort.key === 'rank' || sort.key === 'ecr') && sort.dir === 'asc'
  const bandBy = sort.key === 'ecr' ? ('tier' as const) : ('value_tier' as const)
  const items = useMemo(
    () => buildRows(sorted, { bands, posFilter: filters.pos, bandBy }),
    [sorted, bands, filters.pos, bandBy],
  )

  const playerIds = useMemo(() => sorted.map((p) => p.player_id), [sorted])
  const itemIndexById = useMemo(() => {
    const m = new Map<number, number>()
    items.forEach((it, i) => { if (it.kind === 'player') m.set(it.player.player_id, i) })
    return m
  }, [items])

  const counts = useMemo(() => {
    const c: Record<string, number> = {}
    for (const p of players) {
      c[p.pos] = (c[p.pos] ?? 0) + 1
      for (const f of p.flags) c[f] = (c[f] ?? 0) + 1
    }
    return c
  }, [players])

  const best = useMemo(() => bestAvailable(filtered) ?? null, [filtered])
  const selected: BoardPlayer | null = selectedId != null ? (byId.get(selectedId) ?? null) : null
  const byeWarnWeeks = useMemo(
    () => new Set((state.data?.bye_stack_warnings ?? []).map((w) => w.bye_week)),
    [state.data],
  )

  /**
   * Every pick is entered by hand this draft, so the board can silently disagree with Yahoo's.
   * The reconstruction lives here rather than inside the Teams tab so the tab strip can carry the
   * warning badge — drift has to be visible from the Draft tab, where Derek actually is.
   */
  const teamsModel = useMemo(
    () => buildTeams({
      players,
      schedule: schedule.data?.picks,
      keepers: keepers.data?.keepers ?? [],
      league: run.data?.league,
      picksMade: state.data?.picks_made ?? 0,
      totalPicks: state.data?.total_picks ?? 0,
    }),
    [players, schedule.data, keepers.data, run.data, state.data],
  )
  const drifted = teamsModel.offenders.length > 0 || teamsModel.missingFromBoard !== 0

  /**
   * Single entry point for the highlight. The ref is written here rather than during render so a
   * burst of j/k inside one React batch still steps one row per press.
   */
  const select = useCallback((id: number | null) => {
    selectedRef.current = id
    setSelectedId(id)
  }, [])

  /* Keep the highlight meaningful: default to best available, and recover if a filter hides it. */
  useEffect(() => {
    if (sorted.length === 0) return
    if (selectedId != null && itemIndexById.has(selectedId)) return
    select(best?.player_id ?? sorted[0].player_id)
  }, [sorted, selectedId, itemIndexById, best, select])

  /* ---------- my upcoming picks (slot 10 of 10 → back-to-back pairs) ---------- */
  const myUpcoming: NextPick[] = useMemo(() => {
    const s = schedule.data
    const st = state.data
    if (!s?.my_slot || !st) return []
    const made = st.picks_made
    return s.picks
      .filter((p) => p.team_slot === s.my_slot && p.live_pick_no != null && p.live_pick_no > made)
      .slice(0, 2)
      .map((p) => ({ round: p.round, live_pick: p.live_pick_no, overall_pick: p.overall_pick }))
  }, [schedule.data, state.data])

  /* ---------- actions ---------- */
  const draft = useCallback((playerId: number, mine: boolean) => {
    const p = byId.get(playerId)
    if (p?.drafted) { pushToast(`${p.name} is already drafted`, 'bad'); return }
    makePick.mutate({
      player_id: playerId,
      ...(mine ? { my_pick: true } : {}),
      ...(!mine && teamOverride != null ? { team_slot: teamOverride } : {}),
    })
  }, [byId, makePick, pushToast, teamOverride])

  /**
   * The highlight is mirrored in a ref so a burst of j/k presses inside one React batch each move
   * one row; reading `selectedId` from the closure would make every press after the first a no-op.
   */
  const move = useCallback((delta: number) => {
    if (playerIds.length === 0) return
    const cur = selectedRef.current != null ? playerIds.indexOf(selectedRef.current) : -1
    const next = Math.max(0, Math.min(playerIds.length - 1, cur + delta))
    const id = playerIds[next]
    select(id)
    const idx = itemIndexById.get(id)
    if (idx != null) setScrollToIndex(idx)
  }, [playerIds, itemIndexById, select])

  const selectAndScroll = useCallback((id: number) => {
    select(id)
    const idx = itemIndexById.get(id)
    if (idx != null) setScrollToIndex(idx)
  }, [itemIndexById, select])

  const exportCsv = useCallback(() => {
    const a = document.createElement('a')
    a.href = boardCsvUrl(1000, filters.pos)
    a.download = 'draft_board.csv'
    document.body.appendChild(a)
    a.click()
    a.remove()
    pushToast(
      filters.presets.length
        ? 'CSV downloaded — the server export carries the position filter only, not presets'
        : 'CSV downloaded',
      filters.presets.length ? 'info' : 'good',
    )
  }, [filters.pos, filters.presets.length, pushToast])

  const onSort = useCallback((key: SortKey) => {
    setSort((s) => {
      if (s.key === key) return { key, dir: s.dir === 'asc' ? 'desc' : 'asc' }
      const col = COLUMNS.find((c) => c.sortKey === key)
      return { key, dir: col?.defaultDir ?? 'asc' }
    })
  }, [])

  /* ---------- keyboard (§8) ---------- */
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const typing = !!el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA' || el.tagName === 'SELECT' || el.isContentEditable)
      if (e.metaKey || e.ctrlKey || e.altKey) return
      if (typing) {
        if (e.key === 'Escape') { el?.blur(); e.preventDefault() }
        return
      }
      switch (e.key) {
        case 'j': e.preventDefault(); move(1); break
        case 'k': e.preventDefault(); move(-1); break
        case 'd': if (selectedId != null) { e.preventDefault(); draft(selectedId, false) } break
        case 'm': if (selectedId != null) { e.preventDefault(); draft(selectedId, true) } break
        case 'u': e.preventDefault(); undo.mutate(); break
        case 'Enter': if (selectedId != null) { e.preventDefault(); setDrawerOpen((o) => !o) } break
        case 'Escape': e.preventDefault(); setDrawerOpen(false); break
        case '/': e.preventDefault(); searchRef.current?.focus(); searchRef.current?.select(); break
        case 'q':
          e.preventDefault()
          document.querySelector<HTMLInputElement>('input[placeholder^="type a name"]')?.focus()
          break
        default: break
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [move, draft, selectedId, undo])

  /* ---------- profile for the drawer ---------- */
  const profile = usePlayerProfile(drawerOpen && selectedId != null ? selectedId : null)

  /* ---------- error states ---------- */
  const runErr = run.error instanceof ApiError ? run.error : (run.error as Error | null)
  const rankErr = rankings.error instanceof ApiError ? rankings.error : null
  const errStatus = run.error instanceof ApiError ? run.error.status : null
  // 503 is "no pinned run"; anything else that stops /api/run answering (including the vite proxy's
  // own 500 when uvicorn is down) means the API is unreachable.
  const offline = run.isError && errStatus !== 503
  const mismatch = (run.data != null && !run.data.config_hash_matches) || rankErr?.status === 409

  // Blank the page only if a run has never loaded. If the API drops out mid-draft the last good
  // board stays on screen behind a banner — losing the board at pick 40 would be far worse.
  if (run.isError && run.data == null) {
    return (
      <div className="h-full flex flex-col">
        <NoRunState
          detail={runErr?.message ?? 'unknown error'}
          offline={offline}
          onRetry={retryAll}
        />
        <AttributionFooter run={undefined} shortcutHint={SHORTCUTS} />
      </div>
    )
  }

  return (
    <div className="h-full flex flex-col">
      <TopBar
        run={run.data}
        state={state.data}
        myUpcoming={myUpcoming}
        onExport={exportCsv}
        renderMs={renderMs}
      />
      {mismatch && <ConfigMismatchBanner hash={run.data?.league_config_sha256 ?? ''} />}
      {run.isError && run.data != null && <OfflineBanner detail={runErr?.message ?? ''} onRetry={retryAll} />}

      <div className="px-3 pt-2 pb-1" style={{ background: 'var(--bg)' }}>
        <QuickPick players={players} state={state.data} busy={busy} onPick={(id, m) => draft(id, m)} />
      </div>

      <div className="flex flex-1 min-h-0">
        <FilterRail
          ref={searchRef}
          filters={filters}
          counts={counts}
          shown={sorted.length}
          total={players.length}
          undrafted={sorted.filter((p) => !p.drafted).length}
          onChange={setFilters}
        />

        <Board
          items={items}
          selectedId={selectedId}
          byeWarnWeeks={byeWarnWeeks}
          sort={sort}
          onSort={onSort}
          onSelect={select}
          onOpen={(id) => { select(id); setDrawerOpen(true) }}
          scrollToIndex={scrollToIndex}
          onRendered={setRenderMs}
          loading={rankings.isLoading}
        />

        <div
          className="relative shrink-0 flex flex-col min-h-0"
          style={{ width: 384, background: 'var(--panel)', borderLeft: '1px solid var(--border)' }}
        >
          <div className="flex shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
            {(['draft', 'teams', 'keepers'] as const).map((t) => (
              <button
                key={t}
                type="button"
                onClick={() => setTab(t)}
                className="flex-1 py-1.5 text-[12px] font-semibold uppercase tracking-wider"
                title={t === 'teams' && drifted ? 'A team\u2019s pick count disagrees with the snake' : undefined}
                style={{
                  color: tab === t ? 'var(--accent)' : 'var(--muted)',
                  background: tab === t ? 'var(--accent-dim)' : 'transparent',
                  borderBottom: tab === t ? '2px solid var(--accent)' : '2px solid transparent',
                }}
              >
                {t === 'draft' && 'Draft'}
                {t === 'teams' && (
                  <>Teams{drifted && <span style={{ color: 'var(--bad)' }}> ⚠</span>}</>
                )}
                {t === 'keepers' && `Keepers (${keepers.data?.keepers.length ?? 0})`}
              </button>
            ))}
          </div>

          {tab === 'draft' ? (
            <DraftPanel
              run={run.data}
              state={state.data}
              availability={availability.data}
              selected={selected}
              best={best}
              byeWarnWeeks={byeWarnWeeks}
              busy={busy}
              teamOverride={teamOverride}
              onTeamOverride={setTeamOverride}
              onDraft={draft}
              onUndo={() => undo.mutate()}
              onSelect={selectAndScroll}
              onOpenDrawer={(id) => { select(id); setDrawerOpen(true) }}
            />
          ) : tab === 'teams' ? (
            <TeamsPanel
              run={run.data}
              state={state.data}
              model={teamsModel}
              selectedId={selectedId}
              onSelect={selectAndScroll}
            />
          ) : (
            <KeeperPanel
              run={run.data}
              keepers={keepers.data?.keepers ?? []}
              players={players}
              busy={busy}
              error={keeperError}
              note={keeperNote}
              onAdd={(b) => { setKeeperError(null); setKeeperNote(null); addKeeper.mutate(b) }}
              onDelete={(id) => { setKeeperError(null); setKeeperNote(null); delKeeper.mutate(id) }}
              onDismiss={() => { setKeeperError(null); setKeeperNote(null) }}
            />
          )}

          {drawerOpen && selected && (
            <PlayerDrawer
              player={selected}
              profile={profile.data}
              loading={profile.isLoading}
              error={profile.error ? (profile.error as Error).message : null}
              busy={busy}
              onClose={() => setDrawerOpen(false)}
              onDraft={draft}
            />
          )}
        </div>
      </div>

      <AttributionFooter run={run.data} shortcutHint={SHORTCUTS} />
      <Toasts toasts={toasts} onDismiss={(id) => setToasts((t) => t.filter((x) => x.id !== id))} />
    </div>
  )
}
