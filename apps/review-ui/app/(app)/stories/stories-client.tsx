'use client'

import { useState, useMemo, useTransition } from 'react'
import { useRouter } from 'next/navigation'
import { Zap } from 'lucide-react'
import { truncate } from '@/lib/utils'
import type { Story, StoryStatus } from '@/lib/types'
import { StatusBadge } from '@/components/status-badge'
import { RelativeTime } from '@/components/relative-time'
import { Topbar } from '@/components/topbar'
import { cn } from '@/lib/utils'

const STATUSES: StoryStatus[] = ['open', 'drafted', 'posted', 'killed']

interface StoriesClientProps {
  initialStories: Story[]
}

export function StoriesClient({ initialStories }: StoriesClientProps) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()
  const [statusFilter, setStatusFilter] = useState<Set<StoryStatus>>(new Set())
  const [selected, setSelected] = useState<Story | null>(null)

  const stories = useMemo(() => {
    if (!statusFilter.size) return initialStories
    return initialStories.filter((s) => statusFilter.has(s.status))
  }, [initialStories, statusFilter])

  function toggleStatus(s: StoryStatus) {
    setStatusFilter((prev) => {
      const next = new Set(prev)
      next.has(s) ? next.delete(s) : next.add(s)
      return next
    })
  }

  return (
    <>
      <Topbar title="Stories" onRefresh={() => router.refresh()} isRefreshing={isPending} />
      <div className="flex-1 overflow-hidden flex flex-col">
        {/* Filters */}
        <div className="px-4 py-2.5 border-b border-border flex items-center gap-2">
          {STATUSES.map((s) => (
            <button
              key={s}
              onClick={() => toggleStatus(s)}
              className={cn(
                'h-6 px-2.5 text-xs rounded border transition-colors',
                statusFilter.has(s)
                  ? 'border-accent bg-accent/10 text-accent font-medium'
                  : 'border-border text-muted hover:text-foreground'
              )}
            >
              {s}
            </button>
          ))}
          <span className="ml-auto text-xs text-muted tabular-nums">{stories.length} stories</span>
        </div>

        {/* Table */}
        <div className="flex-1 overflow-auto">
          <table className="w-full text-xs border-collapse">
            <thead>
              <tr className="sticky top-0 bg-surface border-b border-border z-10">
                <th className="px-3 py-2 text-left font-medium text-muted w-28">Created</th>
                <th className="px-3 py-2 text-left font-medium text-muted">Headline</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-24">Status</th>
                <th className="px-3 py-2 text-left font-medium text-muted w-16">Hot</th>
                <th className="px-3 py-2 text-left font-medium text-muted">Entities</th>
                <th className="px-3 py-2 text-left font-medium text-muted">Sources</th>
              </tr>
            </thead>
            <tbody>
              {stories.map((story, idx) => (
                <tr
                  key={story.id}
                  onClick={() => setSelected(selected?.id === story.id ? null : story)}
                  className={cn(
                    'border-b border-border h-10 cursor-pointer transition-colors',
                    idx % 2 === 1 ? 'bg-surface/50' : 'bg-background',
                    selected?.id === story.id ? 'bg-accent/5' : 'hover:bg-accent/5'
                  )}
                >
                  <td className="px-3 text-muted tabular-nums">
                    <RelativeTime dateStr={story.created_at} />
                  </td>
                  <td className="px-3 text-foreground font-medium">{truncate(story.headline, 80)}</td>
                  <td className="px-3"><StatusBadge status={story.status} /></td>
                  <td className="px-3">
                    {story.hot_take && <Zap size={13} className="text-warning" />}
                  </td>
                  <td className="px-3">
                    <div className="flex gap-1 flex-wrap">
                      {story.entities.slice(0, 3).map((e) => (
                        <span key={e} className="bg-[#dbeafe] text-[#1e40af] px-1.5 py-0.5 rounded text-2xs font-medium">{e}</span>
                      ))}
                      {story.entities.length > 3 && <span className="text-muted">+{story.entities.length - 3}</span>}
                    </div>
                  </td>
                  <td className="px-3">
                    <div className="flex gap-1 flex-wrap">
                      {story.source_handles.slice(0, 3).map((h) => (
                        <span key={h} className="bg-[#f3f4f6] text-[#374151] px-1.5 py-0.5 rounded text-2xs font-medium">{h}</span>
                      ))}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Story detail drawer (inline below) */}
        {selected && (
          <div className="border-t border-border bg-surface px-5 py-4 shrink-0 max-h-64 overflow-y-auto">
            <div className="flex items-start justify-between mb-3">
              <p className="text-sm font-semibold text-foreground">{selected.headline}</p>
              <button onClick={() => setSelected(null)} className="text-muted hover:text-foreground text-xs">Close</button>
            </div>
            {selected.narrative_angle && (
              <p className="text-xs text-muted italic mb-3">{selected.narrative_angle}</p>
            )}
            {selected.key_data_points?.length > 0 && (
              <table className="w-full text-xs mb-3">
                <tbody>
                  {selected.key_data_points.map((dp, i) => (
                    <tr key={i} className="border-b border-border last:border-0">
                      <td className="py-1 pr-3 text-muted font-medium w-1/4">{dp.label}</td>
                      <td className="py-1 pr-3 text-foreground tabular-nums">{dp.value}</td>
                      <td className="py-1 text-muted">{dp.source}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            <div className="flex gap-2 flex-wrap text-xs text-muted">
              <span>Formats: {selected.format_recommendation.join(', ')}</span>
              <span>·</span>
              <span>Signals: {selected.signals_ids.length}</span>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
