'use client'

import { useState, useMemo, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Check } from 'lucide-react'
import { truncate, scoreBg } from '@/lib/utils'
import type { Signal, SignalSource } from '@/lib/types'
import { RelativeTime } from '@/components/relative-time'
import { Topbar } from '@/components/topbar'
import { cn } from '@/lib/utils'

const SOURCES: SignalSource[] = ['defillama', 'rwa_xyz', 'telegram_newswire', 'alchemy', 'x_firehose', 'vaultsfyi', 'bubblemaps']

const sourceBadge: Record<string, string> = {
  defillama: 'bg-[#dbeafe] text-[#1e40af]',
  rwa_xyz: 'bg-[#ede9fe] text-[#5b21b6]',
  telegram_newswire: 'bg-[#ffedd5] text-[#9a3412]',
  alchemy: 'bg-[#d1fae5] text-[#065f46]',
  x_firehose: 'bg-[#f0f9ff] text-[#0369a1]',
  vaultsfyi: 'bg-[#fef3c7] text-[#92400e]',
  bubblemaps: 'bg-[#fce7f3] text-[#9d174d]',
}

interface SignalsClientProps {
  initialSignals: Signal[]
}

export function SignalsClient({ initialSignals }: SignalsClientProps) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [sourceFilter, setSourceFilter] = useState<Set<SignalSource>>(new Set())
  const [selected, setSelected] = useState<Signal | null>(null)

  const signals = useMemo(() => {
    if (!sourceFilter.size) return initialSignals
    return initialSignals.filter((s) => sourceFilter.has(s.source))
  }, [initialSignals, sourceFilter])

  function toggleSource(s: SignalSource) {
    setSourceFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })
  }

  return (
    <>
      <Topbar title="Signals" onRefresh={() => router.refresh()} isRefreshing={isPending} />
      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Filters */}
        <div className="px-4 py-2.5 border-b border-border flex items-center gap-2 flex-wrap">
          {SOURCES.filter((s) => initialSignals.some((sig) => sig.source === s)).map((s) => (
            <button
              key={s}
              onClick={() => toggleSource(s)}
              className={cn(
                'h-6 px-2.5 text-2xs rounded border transition-colors',
                sourceFilter.has(s)
                  ? 'border-accent bg-accent/10 text-accent font-medium'
                  : 'border-border text-muted hover:text-foreground'
              )}
            >
              {s}
            </button>
          ))}
          <span className="ml-auto text-xs text-muted tabular-nums">{signals.length} signals</span>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="sticky top-0 bg-surface border-b border-border z-10">
                <th className="px-3 py-2 text-left font-medium text-muted w-28">Observed</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-36">Source</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-36">Type</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-36">Entity</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-20">Mat.</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-20">Nov.</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-12">↑</th>
                <th className="px-3 py-2 text-left font-medium text-muted">Notes</th>
              </tr>
            </thead>
            <tbody>
              {signals.map((sig, idx) => (
                <tr
                  key={sig.id}
                  onClick={() => setSelected(selected?.id === sig.id ? null : sig)}
                  className={cn(
                    'border-b border-border h-10 cursor-pointer transition-colors',
                    idx % 2 === 1 ? 'bg-surface/50' : 'bg-background',
                    selected?.id === sig.id ? 'bg-accent/5' : 'hover:bg-accent/5'
                  )}
                >
                  <td className="px-3 text-muted tabular-nums">
                    <RelativeTime dateStr={sig.observed_at} />
                  </td>
                  <td className="px-3">
                    <span className={cn('inline-flex items-center px-1.5 py-0.5 rounded text-2xs font-medium', sourceBadge[sig.source] ?? 'bg-[#f3f4f6] text-[#374151]')}>
                      {sig.source}
                    </span>
                  </td>
                  <td className="px-3 text-muted">{sig.signal_type}</td>
                  <td className="px-3 text-foreground">{truncate(sig.entity, 28)}</td>
                  <td className="px-3 tabular-nums">
                    {sig.materiality_score != null ? (
                      <span className={cn('px-1.5 py-0.5 rounded text-2xs font-medium', scoreBg(sig.materiality_score))}>
                        {sig.materiality_score}
                      </span>
                    ) : <span className="text-muted">—</span>}
                  </td>
                  <td className="px-3 tabular-nums">
                    {sig.novelty_score != null ? (
                      <span className={cn('px-1.5 py-0.5 rounded text-2xs font-medium', scoreBg(sig.novelty_score))}>
                        {sig.novelty_score}
                      </span>
                    ) : <span className="text-muted">—</span>}
                  </td>
                  <td className="px-3">
                    {sig.promoted_to_story_id && <Check size={13} className="text-success" />}
                  </td>
                  <td className="px-3 text-muted">{truncate(sig.notes, 80)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Payload drawer */}
        {selected && (
          <div className="border-t border-border bg-surface px-5 py-4 shrink-0 max-h-64 overflow-y-auto">
            <div className="flex items-start justify-between mb-2">
              <p className="text-xs font-semibold text-foreground font-mono">{selected.signal_type} — {selected.source}</p>
              <button onClick={() => setSelected(null)} className="text-muted hover:text-foreground text-xs">Close</button>
            </div>
            <pre className="text-2xs text-muted bg-background border border-border rounded p-3 overflow-x-auto leading-relaxed">
              {JSON.stringify(selected.payload, null, 2)}
            </pre>
          </div>
        )}
      </div>
    </>
  )
}
