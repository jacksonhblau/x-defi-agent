'use client'

import { useState, useTransition } from 'react'
import { Plus, Trash2, Save } from 'lucide-react'
import type { WatchlistData } from '@/lib/types'
import { Topbar } from '@/components/topbar'
import { useToast } from '@/components/toast'
import { saveWatchlist } from '@/app/actions/watchlist'
import { cn } from '@/lib/utils'

interface WatchlistClientProps {
  initialWatchlist: WatchlistData
}

const CATEGORY_LABELS: Record<string, string> = {
  voice_models: 'Voice Models',
  newsfeeds: 'Newsfeeds',
  issuers: 'Issuers',
  protocols: 'Protocols',
  tradfi_entrants: 'TradFi Entrants',
  journalists: 'Journalists',
}

export function WatchlistClient({ initialWatchlist }: WatchlistClientProps) {
  const { toast } = useToast()
  const [isPending, startTransition] = useTransition()
  const [watchlist, setWatchlist] = useState(initialWatchlist)
  const [newHandle, setNewHandle] = useState<Record<string, string>>({})
  // Track disabled handles (not in original schema, stored locally for now)
  const [disabled, setDisabled] = useState<Set<string>>(new Set())

  function addHandle(cat: string) {
    const handle = (newHandle[cat] ?? '').trim().replace(/^@/, '')
    if (!handle) return
    setWatchlist((prev) => ({
      ...prev,
      [cat]: {
        ...prev[cat],
        handles: [...(prev[cat]?.handles ?? []), handle],
      },
    }))
    setNewHandle((p) => ({ ...p, [cat]: '' }))
  }

  function removeHandle(cat: string, handle: string) {
    setWatchlist((prev) => ({
      ...prev,
      [cat]: {
        ...prev[cat],
        handles: (prev[cat]?.handles ?? []).filter((h) => h !== handle),
      },
    }))
  }

  function updateWeight(cat: string, weight: number) {
    setWatchlist((prev) => ({
      ...prev,
      [cat]: { ...prev[cat], weight },
    }))
  }

  function toggleHandle(handle: string) {
    setDisabled((prev) => {
      const next = new Set(prev)
      next.has(handle) ? next.delete(handle) : next.add(handle)
      return next
    })
  }

  async function handleSave() {
    startTransition(async () => {
      try {
        await saveWatchlist(watchlist)
        toast('Watchlist saved.', 'success')
      } catch (e) {
        toast((e as Error).message, 'error')
      }
    })
  }

  const totalHandles = Object.values(watchlist).reduce(
    (sum, cat) => sum + (cat?.handles?.length ?? 0),
    0
  )

  return (
    <>
      <Topbar title="Watchlist" isRefreshing={isPending} />
      <div className="flex-1 overflow-auto">
        {/* Header */}
        <div className="px-4 py-3 border-b border-border flex items-center justify-between">
          <p className="text-xs text-muted">
            <span className="font-semibold text-foreground tabular-nums">{totalHandles}</span> handles across{' '}
            <span className="font-semibold text-foreground tabular-nums">{Object.keys(watchlist).length}</span> categories
          </p>
          <button
            onClick={handleSave}
            disabled={isPending}
            className="flex items-center gap-1.5 px-3 h-7 text-xs font-medium rounded bg-accent text-white hover:opacity-90 disabled:opacity-50 transition-opacity"
          >
            <Save size={12} />
            Save changes
          </button>
        </div>

        <div className="px-4 py-4 flex flex-col gap-6">
          {Object.entries(watchlist).map(([cat, catData]) => (
            <div key={cat}>
              <div className="flex items-center gap-3 mb-3">
                <h2 className="text-xs font-semibold text-foreground">
                  {CATEGORY_LABELS[cat] ?? cat}
                </h2>
                <div className="flex items-center gap-1.5">
                  <span className="text-2xs text-muted">Weight</span>
                  <input
                    type="number"
                    value={catData?.weight ?? 1}
                    step={0.25}
                    min={0}
                    max={5}
                    onChange={(e) => updateWeight(cat, Number(e.target.value))}
                    className="w-16 px-1.5 h-6 text-xs border border-border rounded bg-background text-foreground focus:outline-none focus:ring-1 focus:ring-accent/40 tabular-nums text-right"
                  />
                </div>
                <span className="text-2xs text-muted">{catData?.handles?.length ?? 0} handles</span>
              </div>

              <div className="border border-border rounded overflow-hidden">
                <table className="w-full text-xs border-collapse">
                  <thead>
                    <tr className="bg-surface border-b border-border">
                      <th className="px-3 py-2 text-left font-medium text-muted">Handle</th>
                      <th className="px-3 py-2 text-left font-medium text-muted w-20">Enabled</th>
                      <th className="px-3 py-2 text-left font-medium text-muted w-16"></th>
                    </tr>
                  </thead>
                  <tbody>
                    {(catData?.handles ?? []).map((handle, idx) => (
                      <tr
                        key={handle}
                        className={cn(
                          'border-b border-border last:border-0 h-9',
                          idx % 2 === 1 ? 'bg-surface/40' : 'bg-background'
                        )}
                      >
                        <td className="px-3 font-medium text-foreground">@{handle}</td>
                        <td className="px-3">
                          <button
                            role="switch"
                            aria-checked={!disabled.has(handle)}
                            onClick={() => toggleHandle(handle)}
                            className={cn(
                              'relative inline-flex h-4 w-7 items-center rounded-full transition-colors',
                              !disabled.has(handle) ? 'bg-accent' : 'bg-border'
                            )}
                          >
                            <span className={cn(
                              'inline-block h-3 w-3 transform rounded-full bg-white transition-transform',
                              !disabled.has(handle) ? 'translate-x-3.5' : 'translate-x-0.5'
                            )} />
                          </button>
                        </td>
                        <td className="px-3">
                          <button
                            onClick={() => removeHandle(cat, handle)}
                            className="text-muted hover:text-danger p-1 rounded hover:bg-[#fef2f2] transition-colors"
                          >
                            <Trash2 size={12} />
                          </button>
                        </td>
                      </tr>
                    ))}
                    {/* Add handle row */}
                    <tr className="border-t border-border bg-surface/30">
                      <td colSpan={3} className="px-3 py-2">
                        <div className="flex items-center gap-2">
                          <span className="text-muted text-xs">@</span>
                          <input
                            type="text"
                            value={newHandle[cat] ?? ''}
                            onChange={(e) => setNewHandle((p) => ({ ...p, [cat]: e.target.value }))}
                            onKeyDown={(e) => e.key === 'Enter' && addHandle(cat)}
                            placeholder="Add handle…"
                            className="flex-1 px-2 h-6 text-xs border border-border rounded bg-background text-foreground placeholder:text-muted focus:outline-none focus:ring-1 focus:ring-accent/40"
                          />
                          <button
                            onClick={() => addHandle(cat)}
                            disabled={!(newHandle[cat] ?? '').trim()}
                            className="flex items-center gap-1 px-2 h-6 text-2xs rounded border border-border text-muted hover:text-foreground hover:border-foreground/30 disabled:opacity-40 transition-colors"
                          >
                            <Plus size={11} />
                            Add
                          </button>
                        </div>
                      </td>
                    </tr>
                  </tbody>
                </table>

                {/* Telegram channels if any */}
                {catData?.telegram_channels && catData.telegram_channels.length > 0 && (
                  <div className="border-t border-border px-3 py-2 bg-surface/50">
                    <p className="text-2xs text-muted mb-1">Telegram channels</p>
                    <div className="flex gap-1.5 flex-wrap">
                      {catData.telegram_channels.map((ch) => (
                        <span key={ch} className="text-2xs bg-[#ffedd5] text-[#9a3412] px-1.5 py-0.5 rounded font-medium">
                          t.me/{ch}
                        </span>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      </div>
    </>
  )
}
