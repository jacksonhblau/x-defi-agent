'use client'

import { useRouter } from 'next/navigation'
import { useTransition, useMemo } from 'react'
import { ExternalLink } from 'lucide-react'
import { format, parseISO, isToday, isTomorrow, startOfDay, differenceInCalendarDays } from 'date-fns'
import { truncate } from '@/lib/utils'
import type { ScheduledPost } from '@/lib/types'
import { StatusBadge } from '@/components/status-badge'
import { FormatBadge } from '@/components/format-badge'
import { Topbar } from '@/components/topbar'

interface CalendarClientProps {
  initialPosts: ScheduledPost[]
}

function dayLabel(dateStr: string): string {
  const date = parseISO(dateStr)
  if (isToday(date)) return 'Today'
  if (isTomorrow(date)) return 'Tomorrow'
  const diff = differenceInCalendarDays(date, new Date())
  if (diff < 0) return format(date, 'EEE MMM d') + ' (past)'
  return format(date, 'EEEE, MMM d')
}

function formatTime(dateStr: string): string {
  return format(parseISO(dateStr), 'h:mm a') + ' ET'
}

export function CalendarClient({ initialPosts }: CalendarClientProps) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()

  const queued = initialPosts.filter((p) => p.status === 'queued')
  const days = useMemo(() => {
    const map = new Map<string, ScheduledPost[]>()
    for (const post of initialPosts) {
      const day = startOfDay(parseISO(post.post_at)).toISOString()
      const arr = map.get(day) ?? []
      arr.push(post)
      map.set(day, arr)
    }
    return Array.from(map.entries()).sort(([a], [b]) => a.localeCompare(b))
  }, [initialPosts])

  // Next post countdown
  const nextPost = queued[0]
  const msUntilNext = nextPost ? parseISO(nextPost.post_at).getTime() - Date.now() : null
  const countdown = msUntilNext != null && msUntilNext > 0
    ? (() => {
        const h = Math.floor(msUntilNext / 3600000)
        const m = Math.floor((msUntilNext % 3600000) / 60000)
        return h > 0 ? `${h}h ${m}m` : `${m}m`
      })()
    : null

  return (
    <>
      <Topbar title="Calendar" onRefresh={() => router.refresh()} isRefreshing={isPending} />

      <div className="flex-1 overflow-auto">
        {/* Summary bar */}
        <div className="px-4 py-3 border-b border-border bg-background flex items-center gap-4 text-xs text-muted flex-wrap">
          <span>
            <span className="font-semibold text-foreground tabular-nums">{queued.length}</span>{' '}
            posts queued across{' '}
            <span className="font-semibold text-foreground tabular-nums">
              {days.filter(([, ps]) => ps.some((p) => p.status === 'queued')).length}
            </span>{' '}
            days
          </span>
          {countdown && (
            <span>
              Next post in <span className="font-semibold text-accent tabular-nums">{countdown}</span>
            </span>
          )}
        </div>

        {initialPosts.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-64 gap-2 text-center">
            <p className="text-sm font-medium text-foreground">No scheduled posts</p>
            <p className="text-xs text-muted">Approve drafts to schedule them for posting.</p>
          </div>
        ) : (
          <div className="px-4 py-4 flex flex-col gap-6 max-w-3xl">
            {days.map(([dayKey, posts]) => (
              <div key={dayKey}>
                <h2 className="text-xs font-semibold text-muted uppercase tracking-wide mb-3">
                  {dayLabel(posts[0].post_at)}
                </h2>
                <div className="flex flex-col gap-1">
                  {posts.map((post) => {
                    const draft = post.drafts
                    const headline = (draft as { stories?: { headline?: string } })?.stories?.headline
                    const body = draft?.edited_body || draft?.body
                    return (
                      <div
                        key={post.id}
                        className="flex items-start gap-3 border border-border rounded p-3 bg-surface hover:bg-accent/5 transition-colors"
                      >
                        <div className="text-xs text-muted tabular-nums font-medium min-w-[80px] pt-0.5">
                          {formatTime(post.post_at)}
                        </div>
                        <div className="flex-1 min-w-0">
                          {headline && (
                            <p className="text-xs font-medium text-foreground mb-0.5">{headline}</p>
                          )}
                          {body && (
                            <p className="text-xs text-muted leading-4">{truncate(body, 140)}</p>
                          )}
                          {post.last_error && (
                            <p className="text-xs text-danger mt-1">{post.last_error}</p>
                          )}
                        </div>
                        <div className="flex items-center gap-2 shrink-0">
                          {draft?.format && <FormatBadge format={draft.format} />}
                          <StatusBadge status={post.status} />
                          {post.status === 'posted' && (
                            <a
                              href={`https://x.com/i/status/${(post as { root_tweet_id?: string }).root_tweet_id ?? ''}`}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="text-muted hover:text-accent"
                            >
                              <ExternalLink size={13} />
                            </a>
                          )}
                        </div>
                      </div>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </>
  )
}
