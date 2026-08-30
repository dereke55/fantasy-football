import { useEffect, useState } from 'react'

type Health = { status: string; db: boolean }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  useEffect(() => {
    fetch('/api/health').then(r => r.json()).then(setHealth).catch(() => setHealth({ status: 'unreachable', db: false }))
  }, [])
  return (
    <div className="min-h-full flex flex-col">
      <header className="flex items-center justify-between px-5 h-12 border-b" style={{ borderColor: 'var(--border)', background: 'var(--panel)' }}>
        <div className="font-semibold tracking-tight">Draft Board <span style={{ color: 'var(--muted)' }}>· 2026</span></div>
        <div className="text-xs" style={{ color: 'var(--muted)' }}>
          backend: {health ? `${health.status} (db ${health.db ? 'ok' : 'down'})` : '…'}
        </div>
      </header>
      <main className="flex-1 p-5">
        <p style={{ color: 'var(--muted)' }}>Board arrives in Phase 7 (day 6). See <code>docs/PLAN.md</code>.</p>
      </main>
    </div>
  )
}
