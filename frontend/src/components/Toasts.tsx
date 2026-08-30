/** Transient confirmations. Picks are never confirmed with a modal — Undo is the safety net (§8). */
export interface Toast { id: number; text: string; tone: 'good' | 'bad' | 'info' }

export function Toasts({ toasts, onDismiss }: { toasts: Toast[]; onDismiss: (id: number) => void }) {
  if (!toasts.length) return null
  const tone = {
    good: { color: 'var(--good)', border: 'rgba(63,185,80,0.45)', bg: 'rgba(9,26,14,0.96)' },
    bad: { color: 'var(--bad)', border: 'rgba(248,81,73,0.5)', bg: 'rgba(34,12,11,0.96)' },
    info: { color: 'var(--text)', border: 'var(--border)', bg: 'rgba(17,24,33,0.96)' },
  }
  return (
    <div className="fixed z-50 flex flex-col gap-1.5" style={{ bottom: 40, left: '50%', transform: 'translateX(-50%)' }}>
      {toasts.map((t) => {
        const s = tone[t.tone]
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => onDismiss(t.id)}
            className="rise rounded px-3 py-1.5 text-[12.5px] font-medium text-left"
            style={{ color: s.color, background: s.bg, border: `1px solid ${s.border}`, boxShadow: '0 6px 22px rgba(0,0,0,0.55)' }}
          >
            {t.text}
          </button>
        )
      })}
    </div>
  )
}
