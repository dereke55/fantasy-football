/**
 * Player drawer — slides over the right panel for the highlighted row.
 * WHY bullets are the deterministic rule output: template text, rule_id, the period the numbers
 * cover and the source link. No free text and no LLM anywhere in here.
 */
import type { BoardPlayer, PlayerProfile } from '../api/types'
import { DASH, bool, num, one, pct, sourceLabel, str, int, signedOne } from '../lib/format'
import { FlagChips, PosChip, Pill } from './Chips'
import { PpgLine } from './PpgLine'

interface Props {
  player: BoardPlayer
  profile: PlayerProfile | undefined
  loading: boolean
  error: string | null
  busy: boolean
  onClose: () => void
  onDraft: (playerId: number, mine: boolean) => void
}

const POLARITY: Record<number, { color: string; mark: string }> = {
  1: { color: 'var(--good)', mark: '▲' },
  0: { color: 'var(--muted)', mark: '•' },
  [-1]: { color: 'var(--bad)', mark: '▼' },
}

export function PlayerDrawer({ player, profile, loading, error, busy, onClose, onDraft }: Props) {
  const s = profile?.summary ?? null
  const g = (k: string) => (s ? (s as Record<string, unknown>)[k] : undefined)
  const s2025 = profile?.seasons.find((x) => x.season === 2025) ?? null

  return (
    <div
      className="absolute inset-0 z-30 flex flex-col slide-in"
      style={{ background: 'var(--panel)', borderLeft: '1px solid var(--border)' }}
      role="dialog"
      aria-label={`${player.name} detail`}
    >
      {/* header */}
      <div className="px-3 pt-2.5 pb-2 shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-start gap-2">
          <div className="min-w-0 flex-1">
            <div className="text-[16px] font-semibold leading-tight truncate" style={{ textDecoration: player.drafted ? 'line-through' : 'none' }}>
              {player.name}
            </div>
            <div className="flex items-center gap-1.5 mt-1 flex-wrap">
              <PosChip pos={player.pos} />
              <span className="mono text-[11px]" style={{ color: 'var(--muted)' }}>
                {player.team ?? DASH} · bye {player.bye ?? DASH}
              </span>
              <Pill tone="info" title="Overall rank / GMM tier / value tier">
                #{player.rank} · T{player.tier ?? DASH} · VT{player.value_tier ?? DASH}
              </Pill>
              {player.drafted && (
                <Pill tone={player.is_mine ? 'accent' : 'info'}>
                  {player.is_keeper ? 'KEEPER' : player.is_mine ? 'MY PICK' : `TEAM ${player.drafted_by}`}
                </Pill>
              )}
            </div>
            <div className="mt-1.5"><FlagChips flags={player.flags} tags={player.tags} /></div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded px-1.5 py-0.5 text-[12px] shrink-0"
            style={{ border: '1px solid var(--border)', color: 'var(--muted)' }}
            title="Close (Esc)"
          >Esc ×</button>
        </div>

        {!player.drafted && (
          <div className="grid grid-cols-2 gap-1.5 mt-2">
            <button
              type="button" disabled={busy} onClick={() => onDraft(player.player_id, false)}
              className="rounded py-1.5 text-[12.5px] font-semibold"
              style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}
            >Drafted <kbd className="mono text-[10px]" style={{ color: 'var(--muted)' }}>d</kbd></button>
            <button
              type="button" disabled={busy} onClick={() => onDraft(player.player_id, true)}
              className="rounded py-1.5 text-[12.5px] font-bold"
              style={{ background: 'var(--accent)', color: '#06121f', border: '1px solid var(--accent)' }}
            >My pick <kbd className="mono text-[10px]" style={{ opacity: 0.65 }}>m</kbd></button>
          </div>
        )}
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto">
        {loading && <div className="p-3 text-[12px]" style={{ color: 'var(--muted)' }}>Loading profile…</div>}
        {error && <div className="p-3 text-[12px]" style={{ color: 'var(--bad)' }}>{error}</div>}

        {profile && (
          <>
            {/* WHY */}
            <Sec title={`Why · ${profile.why.length} rules`}>
              <ol className="flex flex-col gap-1.5">
                {profile.why.map((b, i) => {
                  const p = POLARITY[b.polarity] ?? POLARITY[0]
                  return (
                    <li key={`${b.rule_id}-${i}`} className="rounded px-2 py-1.5" style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}>
                      <div className="flex gap-1.5 text-[12px] leading-snug">
                        <span style={{ color: p.color }} aria-hidden>{p.mark}</span>
                        <span className="flex-1">{b.text}</span>
                      </div>
                      <div className="flex items-center gap-1.5 mt-1 text-[9.5px]" style={{ color: 'var(--muted)' }}>
                        <span title={`rule_id: ${b.rule_id} · template ${b.template_version ?? '—'}`} className="mono">{b.rule_id}</span>
                        <span>·</span>
                        <span>{b.seasons ?? '—'}</span>
                        <span>·</span>
                        {b.source_url
                          ? <a href={b.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>{sourceLabel(b.source_url)}</a>
                          : <span>curated</span>}
                      </div>
                    </li>
                  )
                })}
                {profile.why.length === 0 && <li className="text-[12px]" style={{ color: 'var(--muted)' }}>No bullets for this player.</li>}
              </ol>
            </Sec>

            {/* 3-season line */}
            <Sec title="PPG by season · league scoring">
              <PpgLine seasons={profile.seasons} refRole={str(g('ref_role_key'))} />
            </Sec>

            {/* key metrics */}
            <Sec title="Key metrics">
              <Group label="Opportunity">
                <M k="Targets/g" v={one(s2025?.targets_pg)} />
                <M k="Target share" v={pct(s2025?.target_share, 1)} />
                <M k="Air-yards share" v={pct(s2025?.air_yards_share, 1)} />
                <M k="WOPR" v={one(s2025?.wopr)} />
                <M k="Carries/g" v={one(s2025?.carries_pg)} />
                <M k="Opp/g" v={one(s2025?.opportunities_pg)} />
                <M k="Depth rank" v={num(g('depth_rank')) != null ? `${g('depth_pos')}${num(g('depth_rank'))}` : DASH} />
                <M k="Δ depth 30d" v={num(g('depth_rank_change_30d')) != null ? signedOne(num(g('depth_rank_change_30d'))) : DASH} />
              </Group>
              <Group label="Luck">
                <M k="TD diff 25" v={signedOne(num(g('td_diff_2025')))} />
                <M k="TD diff 24" v={signedOne(num(g('td_diff_2024')))} />
                <M k="PPG diff 25" v={signedOne(num(g('ppg_diff_2025')))} />
                <M k="Exp / act pts" v={`${int(num(g('exp_points_2025')))} / ${int(num(g('act_points_2025')))}`} />
              </Group>
              <Group label="Durability">
                <M k="Missed / elig" v={`${int(num(g('games_missed_3yr')))} / ${int(num(g('games_eligible_3yr')))}`} />
                <M k="Miss rate" v={pct(num(g('miss_rate_3yr')), 1)} />
                <M k="E[games]" v={one(num(g('e_games')))} />
                <M k="Causes" v={str(g('injury_causes')) ?? DASH} wide />
                <M k="Known missed" v={str(g('known_missed_weeks')) ?? DASH} wide />
                <M k="Status" v={str(g('current_injury_status')) ?? 'healthy'} />
              </Group>
              <Group label="Consistency 2025">
                <M k="Mean" v={one(s2025?.ppg)} />
                <M k="SD" v={one(num(g('weekly_sd_2025')))} />
                <M k="Floor p25" v={one(num(g('floor_p25_2025')))} />
                <M k="Ceiling p90" v={one(num(g('ceiling_p90_2025')))} />
                <M k="Starter wks" v={pct(num(g('pct_weeks_above_starter_2025')))} />
                <M k="Boom / bust" v={`${pct(num(g('boom_rate_2025')))} / ${pct(num(g('bust_rate_2025')))}`} />
              </Group>
              <Group label="Projection blend">
                <M k="Vendor PPG" v={one(num(profile.ranking?.ppg_vendor))} />
                <M k="In-house PPG" v={one(num(profile.ranking?.ppg_inhouse))} />
                <M k="Weights" v={`${one(num(profile.ranking?.w_vendor))} / ${one(num(profile.ranking?.w_inhouse))}`} />
                <M k="Bonus/g" v={signedOne(num(profile.ranking?.bonus_pg))} />
                <M k="Blend PPG" v={one(num(profile.ranking?.ppg_blend))} />
                <M k="Replacement" v={one(num(profile.ranking?.replacement_ppg))} />
                <M k="Age 2026" v={one(num(g('age_2026')))} />
                <M k="Draft capital" v={num(g('draft_round')) != null ? `R${num(g('draft_round'))} #${num(g('draft_pick'))}` : (bool(g('is_rookie')) ? 'UDFA' : DASH)} />
              </Group>
            </Sec>

            {/* market */}
            <Sec title="Market">
              <div className="grid text-[11px]" style={{ gridTemplateColumns: '1fr 36px 40px 32px 56px 64px', columnGap: 4 }}>
                {['Source', 'Rank', 'ADP', 'SD', 'Hi/Lo', 'as_of'].map((h) => (
                  <div key={h} className="text-[9px] font-bold uppercase tracking-wider pb-1" style={{ color: 'var(--muted)' }}>{h}</div>
                ))}
                {profile.market.map((m, i) => (
                  <Row key={`${m.source}-${i}`} m={m} />
                ))}
              </div>
            </Sec>

            {/* team context */}
            {profile.team_context && (
              <Sec title={`Team context · ${profile.team_context.team}`}>
                <div className="flex flex-col gap-1.5">
                  <Ctx
                    label="Coaching"
                    value={`${profile.team_context.play_caller ?? DASH} calls plays${profile.team_context.play_caller_new ? ' (new)' : ''} · HC ${profile.team_context.hc ?? DASH}`}
                    prev={profile.team_context.play_caller_2025}
                    src={profile.team_context.sources?.coaching_changes}
                  />
                  <Ctx
                    label="QB room"
                    value={`${profile.team_context.projected_qb1 ?? DASH} · ${profile.team_context.qb_status ?? DASH}`}
                    prev={profile.team_context.qb1_2025 ? `2025: ${profile.team_context.qb1_2025}` : null}
                    src={profile.team_context.sources?.qb_situations}
                  />
                  <Ctx
                    label="O-line"
                    value={`rank ${profile.team_context.ol_rank_2026 ?? DASH} · Δ ${profile.team_context.ol_delta ?? 0}`}
                    prev={[...(profile.team_context.ol_adds ?? []), ...(profile.team_context.ol_losses ?? [])].join(' · ') || null}
                    src={profile.team_context.sources?.ol_changes}
                  />
                </div>
              </Sec>
            )}
          </>
        )}
      </div>
    </div>
  )
}

function Row({ m }: { m: PlayerProfile['market'][number] }) {
  const label = m.source === 'yahoo_pub' ? 'Yahoo (site-wide)'
    : m.source === 'fantasypros_mirror' ? 'FantasyPros ECR'
      : m.source === 'ffc' ? 'FFC' : m.source
  return (
    <>
      <div className="py-0.5 truncate" title={`${m.source} · ${m.format ?? ''} · ${m.kind ?? ''}`}>{label}</div>
      <div className="num mono py-0.5">{one(m.rank)}</div>
      <div className="num mono py-0.5">{one(m.adp)}</div>
      <div className="num mono py-0.5" style={{ color: 'var(--muted)' }}>{one(m.std)}</div>
      <div className="num mono py-0.5 text-[10px]" style={{ color: 'var(--muted)' }} title="best / worst pick seen">
        {m.min_pick != null ? `${one(m.min_pick)}/${one(m.max_pick)}` : DASH}
      </div>
      <div className="num mono py-0.5 text-[10px]" style={{ color: 'var(--muted)' }}>{m.as_of ?? DASH}</div>
    </>
  )
}

function Ctx({ label, value, prev, src }: {
  label: string; value: string; prev: string | null | undefined
  src: { confidence?: string; source_url?: string; last_checked?: string } | undefined
}) {
  return (
    <div className="rounded px-2 py-1.5" style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}>
      <div className="text-[9px] font-bold uppercase tracking-widest" style={{ color: 'var(--muted)' }}>{label}</div>
      <div className="text-[12px] leading-snug">{value}</div>
      {prev && <div className="text-[10.5px] leading-snug mt-0.5" style={{ color: 'var(--muted)' }}>{prev}</div>}
      <div className="flex items-center gap-1.5 mt-1 text-[9.5px]" style={{ color: 'var(--muted)' }}>
        <span>confidence {src?.confidence ?? DASH}</span><span>·</span>
        <span>checked {src?.last_checked ?? DASH}</span>
        {src?.source_url && (
          <>
            <span>·</span>
            <a href={src.source_url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>{sourceLabel(src.source_url)}</a>
          </>
        )}
      </div>
    </div>
  )
}

function Sec({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="px-3 py-2.5" style={{ borderBottom: '1px solid var(--border)' }}>
      <h3 className="text-[10px] font-bold uppercase tracking-widest mb-1.5" style={{ color: 'var(--muted)' }}>{title}</h3>
      {children}
    </section>
  )
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2">
      <div className="text-[9.5px] font-semibold uppercase tracking-wider mb-0.5" style={{ color: 'var(--accent)', opacity: 0.85 }}>{label}</div>
      <div className="grid grid-cols-2 gap-x-2">{children}</div>
    </div>
  )
}

function M({ k, v, wide }: { k: string; v: string; wide?: boolean }) {
  return (
    <div className="flex items-baseline gap-1.5 text-[11.5px] py-[1px]" style={wide ? { gridColumn: 'span 2' } : undefined}>
      <span style={{ color: 'var(--muted)' }}>{k}</span>
      <span className="flex-1" style={{ borderBottom: '1px dotted var(--border)' }} />
      <span className="mono" title={v}>{wide ? <span className="text-[10.5px]">{v}</span> : v}</span>
    </div>
  )
}
