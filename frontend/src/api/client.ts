/**
 * Thin typed fetch layer. Every non-2xx response is turned into an `ApiError` that carries the
 * HTTP status and the FastAPI `detail` string verbatim — the keeper form and the pick buttons
 * show that string to the user rather than inventing their own wording.
 */
import type {
  AvailabilityResponse, DraftState, KeeperMutationResponse, KeepersResponse,
  PickMutationResponse, PlayerProfile, RankingsResponse, RunInfo, ScheduleResponse,
} from './types'

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, {
      ...init,
      headers: init?.body ? { 'content-type': 'application/json', ...(init?.headers ?? {}) } : init?.headers,
    })
  } catch {
    throw new ApiError(0, 'Cannot reach the API — is `uv run uvicorn app.main:app --port 8000` running?')
  }
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`
    try {
      const body = (await res.json()) as { detail?: unknown }
      if (typeof body.detail === 'string') detail = body.detail
      else if (body.detail) detail = JSON.stringify(body.detail)
    } catch {
      /* non-JSON error body: keep the status line */
    }
    throw new ApiError(res.status, detail)
  }
  return (await res.json()) as T
}

export const api = {
  run: () => request<RunInfo>('/api/run'),
  rankings: (limit = 600) => request<RankingsResponse>(`/api/rankings?limit=${limit}`),
  state: () => request<DraftState>('/api/state'),
  schedule: () => request<ScheduleResponse>('/api/schedule'),
  availability: (top = 3) => request<AvailabilityResponse>(`/api/availability?top=${top}`),
  keepers: () => request<KeepersResponse>('/api/keepers'),
  profile: (id: number) => request<PlayerProfile>(`/api/players/${id}/profile`),

  makePick: (body: { player_id: number; my_pick?: boolean; team_slot?: number }) =>
    request<PickMutationResponse>('/api/draft/picks', { method: 'POST', body: JSON.stringify(body) }),
  undoPick: () => request<PickMutationResponse>('/api/draft/undo', { method: 'POST' }),

  addKeeper: (body: { player_id: number; team_slot: number; cost_round: number; status?: string }) =>
    request<KeeperMutationResponse>('/api/keepers', { method: 'POST', body: JSON.stringify(body) }),
  deleteKeeper: (id: number) =>
    request<KeeperMutationResponse>(`/api/keepers/${id}`, { method: 'DELETE' }),
}

/** CSV export is a browser download, not a fetch — the server sets content-disposition. */
export function boardCsvUrl(limit: number, position: string | null): string {
  const q = new URLSearchParams({ limit: String(limit) })
  if (position) q.set('position', position)
  return `/api/export/board.csv?${q.toString()}`
}
