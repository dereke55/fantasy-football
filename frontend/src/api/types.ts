/**
 * Typed mirrors of the FastAPI draft-board contract (`backend/app/api/board.py`, `players.py`).
 * Every number the board shows comes from the pinned run — nothing here is recomputed in the browser.
 */

export type Position = 'QB' | 'RB' | 'WR' | 'TE' | 'K' | 'DEF'

export interface LeagueInfo {
  teams: number
  rounds: number
  my_slot: number | null
  draft_time: string | null
  slots: Record<string, number>
  flex_eligible: string[]
  bench: number
  max_keepers: number
  keeper_deadline: string | null
}

export interface RunInfo {
  run_id: string
  generated_at: string
  is_frozen: boolean
  model_version: string
  spearman_top150: number | null
  n_players_ranked: number
  league_config_sha256: string
  config_hash_matches: boolean
  scoring_source: string
  weights: Record<string, number | boolean>
  league: LeagueInfo
  attribution: string[]
}

export interface PlayerSignals {
  risk?: string[]
  support?: string[]
  pos_gap?: number | null
  draftable?: boolean
  disagreement_cut?: number | null
}

export interface BoardPlayer {
  player_id: number
  name: string
  yahoo_id: string | null
  pos: string
  team: string | null
  rank: number
  pos_rank: number | null
  tier: number | null
  value_tier: number | null
  proj_ppg: number | null
  proj_season: number | null
  e_games: number | null
  value: number | null
  vols: number | null
  ecr: number | null
  ecr_sd: number | null
  adp_yahoo_site: number | null
  ffc_adp: number | null
  sleeper_adp: number | null
  composite_adp: number | null
  room_adp: number | null
  gap: number | null
  gap_z: number | null
  p_avail: number | null
  vona: number | null
  flags: string[]
  signals: PlayerSignals
  is_kdst: boolean
  bye: number | null
  depth_rank: number | null
  current_injury_status: string | null
  td_diff_2025: number | null
  ppg_2025: number | null
  age_2026: number | null
  drafted_by: number | null
  is_keeper: boolean | null
  pick_id: number | null
  drafted: boolean
  is_mine: boolean
  tags: string[]
}

export interface RankingsResponse {
  run_id: string
  count: number
  players: BoardPlayer[]
}

export interface OnTheClock {
  round: number
  overall_pick: number
  live_pick: number | null
  team_slot: number
  is_mine: boolean
}

export interface NextPick {
  round: number
  live_pick: number | null
  overall_pick: number
}

export interface RosterPlayer {
  id: number
  name: string
  position: string
  team: string | null
  bye: number | null
  is_keeper: boolean
  cost_round: number | null
}

export interface RecentPick {
  id: number
  overall_pick: number
  round: number
  team_slot: number
  player_id: number | null
  is_keeper: boolean
  source: string
  picked_at: string
  name: string | null
  position: string | null
  team: string | null
}

export interface ByeStackWarning {
  bye_week: number
  players: string[]
}

export interface DraftState {
  mode: string
  picks_made: number
  total_picks: number
  on_the_clock: OnTheClock | null
  my_slot: number | null
  my_next_pick: NextPick | null
  picks_until_mine: number | null
  my_roster: RosterPlayer[]
  open_slots: Record<string, number>
  bye_stack_warnings: ByeStackWarning[]
  recent_picks: RecentPick[]
}

export interface SchedulePick {
  overall_pick: number
  round: number
  team_slot: number
  is_keeper_slot: boolean
  live_pick_no: number | null
}

export interface ScheduleResponse {
  picks: SchedulePick[]
  my_slot: number | null
}

export interface VonaCandidate {
  player_id: number
  name: string
  team: string | null
  value_now: number
  expected_value_at_next: number
  vona: number
  p_avail: number
}

export interface VonaPosition {
  slot_weight: number
  open_slots: number
  candidates: VonaCandidate[]
}

export interface AvailabilityResponse {
  my_next_pick: NextPick | null
  positions: Record<string, VonaPosition>
}

export interface Keeper {
  id: number
  team_slot: number
  cost_round: number
  status: string
  source: string
  player_id: number
  name: string
  position: string
  team: string | null
}

export interface KeepersResponse {
  keepers: Keeper[]
}

export interface KeeperMutationResponse {
  ok: boolean
  keepers: Keeper[]
  state: DraftState
  note?: string
}

export interface PickMutationResponse {
  ok: boolean
  state: DraftState
}

/* ---- player profile ---- */

export interface SeasonRow {
  season: number
  position: string | null
  team: string | null
  role_key: string | null
  games: number | null
  points: number | null
  ppg: number | null
  pos_rank_ppg: number | null
  pos_rank_points: number | null
  targets: number | null
  targets_pg: number | null
  target_share: number | null
  air_yards_share: number | null
  wopr: number | null
  carries: number | null
  carries_pg: number | null
  carry_share: number | null
  receptions: number | null
  receiving_yards: number | null
  rushing_yards: number | null
  opportunities_pg: number | null
  ppg_diff: number | null
  td_diff: number | null
  weekly_sd: number | null
  floor_p25: number | null
  ceiling_p90: number | null
  pct_weeks_above_starter: number | null
}

export interface WhyBullet {
  rule_id: string
  text: string
  kind: string
  polarity: number
  priority: number
  inputs: Record<string, unknown>
  seasons: string | null
  source_url: string | null
  template_version: string | null
}

export interface MarketRow {
  source: string
  format: string | null
  kind: string | null
  rank: number | null
  adp: number | null
  std: number | null
  min_pick: number | null
  max_pick: number | null
  as_of: string | null
}

export interface PlayerIdentity {
  id: number
  name: string
  position: string | null
  team: string | null
  birth_date: string | null
  years_exp: number | null
  draft_year: number | null
  draft_round: number | null
  draft_pick: number | null
  draft_team: string | null
  is_rookie: boolean | null
  college: string | null
  yahoo_id: string | null
}

export type FeatureSummary = Record<string, unknown> | null

export interface TeamContextSource {
  confidence?: string
  source_url?: string
  source_url_2?: string
  last_checked?: string
}

export interface TeamContext {
  team: string
  hc: string | null
  hc_new: boolean | null
  oc: string | null
  play_caller: string | null
  play_caller_2025: string | null
  play_caller_new: boolean | null
  projected_qb1: string | null
  qb1_2025: string | null
  qb_status: string | null
  qb_quality_tier: number | null
  qb_backup: string | null
  ol_delta: number | null
  ol_rank_2026: number | null
  ol_adds: string[] | null
  ol_losses: string[] | null
  ol_injuries: string[] | null
  sources: Record<string, TeamContextSource> | null
}

export interface PlayerProfile {
  player: PlayerIdentity
  seasons: SeasonRow[]
  summary: FeatureSummary
  why: WhyBullet[]
  ranking: Record<string, unknown> | null
  market: MarketRow[]
  team_context: TeamContext | null
  provenance: Record<string, unknown> | null
}
