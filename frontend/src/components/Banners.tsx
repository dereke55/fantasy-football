/**
 * Blocking states from docs/spec/ui.md §10: a config-hash mismatch never blanks the table, and a
 * missing pinned run shows the exact CLI command instead of an empty board.
 */
export function ConfigMismatchBanner({ hash }: { hash: string }) {
  return (
    <div
      className="px-3 py-1.5 text-[12px] flex items-center gap-2 shrink-0"
      style={{ background: 'rgba(248,81,73,0.16)', borderBottom: '1px solid rgba(248,81,73,0.5)', color: 'var(--bad)' }}
    >
      <span style={{ fontWeight: 700 }}>⚠ League config changed since the frozen run</span>
      <span style={{ color: 'var(--text)' }}>
        The table below is the last good pinned run ({hash.slice(0, 12)}…). Re-freeze from the CLI:
      </span>
      <code className="mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(0,0,0,0.35)', color: 'var(--text)' }}>
        uv run ff rank run &amp;&amp; uv run ff rank freeze
      </code>
    </div>
  )
}

export function NoRunState({ detail, offline, onRetry }: { detail: string; offline: boolean; onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center justify-center gap-3 flex-1 p-8 text-center">
      <div className="text-[15px] font-semibold">
        {offline ? 'The API is not answering' : 'No pinned run to draft from'}
      </div>
      <div className="text-[12.5px] max-w-lg" style={{ color: 'var(--muted)' }}>{detail}</div>
      <code
        className="mono text-[12px] px-3 py-2 rounded"
        style={{ background: 'var(--panel-3)', border: '1px solid var(--border)' }}
      >
        {offline
          ? 'cd backend && uv run uvicorn app.main:app --port 8000'
          : 'cd backend && uv run ff rank run && uv run ff rank freeze'}
      </code>
      <button
        type="button"
        onClick={onRetry}
        className="rounded px-3 py-1.5 text-[12.5px] font-semibold"
        style={{ background: 'var(--accent)', color: '#06121f', border: '1px solid var(--accent)' }}
      >
        Retry
      </button>
    </div>
  )
}

/** The API dropped out but the last good board is still on screen — never blank it mid-draft. */
export function OfflineBanner({ detail, onRetry }: { detail: string; onRetry: () => void }) {
  return (
    <div
      className="px-3 py-1.5 text-[12px] flex items-center gap-2 shrink-0"
      style={{ background: 'var(--warn-dim)', borderBottom: '1px solid rgba(210,153,34,0.5)', color: 'var(--warn)' }}
    >
      <span style={{ fontWeight: 700 }}>⚠ Lost the API</span>
      <span style={{ color: 'var(--text)' }}>
        Showing the last good data — picks and keeper edits will fail until it is back. {detail}
      </span>
      <button
        type="button"
        onClick={onRetry}
        className="ml-auto rounded px-2 py-0.5 text-[11px] font-semibold"
        style={{ border: '1px solid rgba(210,153,34,0.6)', color: 'var(--warn)' }}
      >
        Retry
      </button>
    </div>
  )
}
