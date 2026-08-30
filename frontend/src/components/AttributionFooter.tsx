/** Licensing attribution required by the README sources table; the run stamp lives here too. */
import type { RunInfo } from '../api/types'
import { stamp } from '../lib/format'

export function AttributionFooter({ run, shortcutHint }: { run: RunInfo | undefined; shortcutHint: string }) {
  return (
    <footer
      className="shrink-0 flex items-center gap-3 px-3 text-[10px] flex-wrap"
      style={{ height: 26, background: 'var(--panel)', borderTop: '1px solid var(--border)', color: 'var(--muted)' }}
    >
      <span className="mono">{shortcutHint}</span>
      <span className="ml-auto flex items-center gap-2 flex-wrap">
        {(run?.attribution ?? []).map((a) => <span key={a}>{a}</span>)}
        {run && (
          <span title={`model ${run.model_version} · scoring from ${run.scoring_source}`}>
            · run {stamp(run.generated_at)} · Spearman {run.spearman_top150?.toFixed(3) ?? '—'} on top-150
          </span>
        )}
      </span>
    </footer>
  )
}
