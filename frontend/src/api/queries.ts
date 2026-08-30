/**
 * TanStack Query keys and hooks. Keys are exactly the set listed in docs/spec/ui.md §10.
 *
 * Rankings are pinned-run data: fetched once, `staleTime: Infinity`, invalidated only by a mutation
 * (a pick or a keeper edit changes `drafted`, room ADP holes and P(avail)) or by a new run id.
 * `state` and `availability` are invalidated after every mutation.
 */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'

export const qk = {
  run: ['run'] as const,
  rankings: (filters: { limit: number }) => ['rankings', filters] as const,
  player: (id: number) => ['player', id] as const,
  schedule: ['schedule'] as const,
  state: ['state'] as const,
  availability: ['availability'] as const,
  keepers: ['keepers'] as const,
  teamContext: ['team_context'] as const,
}

// The pinned run holds 631 ranked players and the API caps `limit` at 1000. Asking for 600 silently
// cut the tail of the pool — including Derek's own keeper at rank 631 — so the board asks for all of it.
const RANKINGS_LIMIT = 1000

export function useRun() {
  return useQuery({ queryKey: qk.run, queryFn: api.run, staleTime: 60_000 })
}

export function useRankings() {
  return useQuery({
    queryKey: qk.rankings({ limit: RANKINGS_LIMIT }),
    queryFn: () => api.rankings(RANKINGS_LIMIT),
    staleTime: Infinity,
  })
}

export function useDraftState() {
  return useQuery({ queryKey: qk.state, queryFn: api.state, staleTime: 5_000 })
}

export function useSchedule() {
  return useQuery({ queryKey: qk.schedule, queryFn: api.schedule, staleTime: Infinity })
}

export function useAvailability() {
  return useQuery({ queryKey: qk.availability, queryFn: () => api.availability(3), staleTime: 5_000 })
}

export function useKeepers() {
  return useQuery({ queryKey: qk.keepers, queryFn: api.keepers, staleTime: 30_000 })
}

export function usePlayerProfile(id: number | null) {
  return useQuery({
    queryKey: qk.player(id ?? -1),
    queryFn: () => api.profile(id as number),
    enabled: id != null,
    staleTime: Infinity,
  })
}

/** Everything a pick or keeper edit can move: the board rows, the panel, VONA and the pick schedule. */
export function useInvalidateBoard() {
  const qc = useQueryClient()
  return () => {
    void qc.invalidateQueries({ queryKey: ['rankings'] })
    void qc.invalidateQueries({ queryKey: qk.state })
    void qc.invalidateQueries({ queryKey: qk.availability })
    void qc.invalidateQueries({ queryKey: qk.keepers })
    void qc.invalidateQueries({ queryKey: qk.schedule })
  }
}

export function useMakePick(onDone?: (msg: string) => void, onError?: (msg: string) => void) {
  const invalidate = useInvalidateBoard()
  return useMutation({
    mutationFn: api.makePick,
    onSuccess: (_d, vars) => { invalidate(); onDone?.(vars.my_pick ? 'my-pick' : 'drafted') },
    onError: (e: Error) => onError?.(e.message),
  })
}

export function useUndoPick(onDone?: (msg: string) => void, onError?: (msg: string) => void) {
  const invalidate = useInvalidateBoard()
  return useMutation({
    mutationFn: api.undoPick,
    onSuccess: () => { invalidate(); onDone?.('undo') },
    onError: (e: Error) => onError?.(e.message),
  })
}

export function useAddKeeper(onDone?: (note?: string) => void, onError?: (msg: string) => void) {
  const invalidate = useInvalidateBoard()
  return useMutation({
    mutationFn: api.addKeeper,
    onSuccess: (d) => { invalidate(); onDone?.(d.note) },
    onError: (e: Error) => onError?.(e.message),
  })
}

export function useDeleteKeeper(onDone?: (note?: string) => void, onError?: (msg: string) => void) {
  const invalidate = useInvalidateBoard()
  return useMutation({
    mutationFn: api.deleteKeeper,
    onSuccess: (d) => { invalidate(); onDone?.(d.note) },
    onError: (e: Error) => onError?.(e.message),
  })
}
