'use client'

import { useRouter, useTransition } from 'next/navigation'
import { ExternalLink } from 'lucide-react'
import { truncate } from '@/lib/utils'
import type { Post, Engagement } from '@/lib/types'
import { FormatBadge } from '@/components/format-badge'
import { RelativeTime } from '@/components/relative-time'
import { Topbar } from '@/components/topbar'
import { cn } from '@/lib/utils'

interface PostsClientProps {
  initialPosts: Post[]
}

function getEngagement(post: Post, window: '24h' | '7d'): Engagement | undefined {
  return post.engagement?.find((e) => e.window_label === window)
}

function engRate(e: Engagement | undefined): string {
  if (!e || !e.impressions) return '—'
  const rate = ((e.likes ?? 0) + (e.retweets ?? 0) + (e.replies ?? 0)) / e.impressions * 100
  return rate.toFixed(2) + '%'
}

// Top decile: compute impressions 90th percentile
function topDecileThreshold(posts: Post[]): number {
  const vals = posts
    .map((p) => getEngagement(p, '24h')?.impressions ?? 0)
    .sort((a, b) => a - b)
  const idx = Math.floor(vals.length * 0.9)
  return vals[idx] ?? Infinity
}

export function PostsClient({ initialPosts }: PostsClientProps) {
  const router = useRouter()
  const [isPending, startTransition] = useTransition()

  const threshold = topDecileThreshold(initialPosts)

  return (
    <>
      <Topbar title="Posts" onRefresh={() => router.refresh()} isRefreshing={isPending} />
      <div className="flex-1 overflow-auto">
        <table className="w-full text-xs border-collapse">
          <thead>
            <tr className="sticky top-0 bg-surface border-b border-border z-10">
              <th className="px-3 py-2 text-left font-medium text-muted w-28">Posted</th>
              <th className="px-3 py-2 text-left font-medium text-muted w-20">Format</th>
              <th className="px-3 py-2 text-left font-medium text-muted">Body</th>
              <th className="px-3 py-2 text-left font-medium text-muted w-8"></th>
              <th className="px-3 py-2 text-center font-medium text-muted w-16" colSpan={1}>24h Imp.</th>
              <th className="px-3 py-2 text-center font-medium text-muted w-12">❤</th>
              <th className="px-3 py-2 text-center font-medium text-muted w-12">RT</th>
              <th className="px-3 py-2 text-center font-medium text-muted w-12">💬</th>
              <th className="px-3 py-2 text-center font-medium text-muted w-16">7d Imp.</th>
              <th className="px-3 py-2 text-center font-medium text-muted w-12">Eng%</th>
            </tr>
          </thead>
          <tbody>
            {initialPosts.map((post, idx) => {
              const e24 = getEngagement(post, '24h')
              const e7d = getEngagement(post, '7d')
              const topDecile = (e24?.impressions ?? 0) >= threshold && threshold < Infinity
              return (
                <tr
                  key={post.id}
                  className={cn(
                    'border-b border-border h-10 transition-colors hover:bg-accent/5',
                    topDecile ? 'bg-[#f0fdf4]' : idx % 2 === 1 ? 'bg-surface/50' : 'bg-background'
                  )}
                >
                  <td className="px-3 text-muted tabular-nums">
                    <RelativeTime dateStr={post.posted_at} />
                  </td>
                  <td className="px-3"><FormatBadge format={post.format} /></td>
                  <td className="px-3 text-muted">{truncate(post.body, 100)}</td>
                  <td className="px-3">
                    <a
                      href={`https://x.com/i/status/${post.root_tweet_id}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-muted hover:text-accent"
                    >
                      <ExternalLink size={12} />
                    </a>
                  </td>
                  <td className="px-3 text-center tabular-nums">{e24?.impressions?.toLocaleString() ?? '—'}</td>
                  <td className="px-3 text-center tabular-nums">{e24?.likes ?? '—'}</td>
                  <td className="px-3 text-center tabular-nums">{e24?.retweets ?? '—'}</td>
                  <td className="px-3 text-center tabular-nums">{e24?.replies ?? '—'}</td>
                  <td className="px-3 text-center tabular-nums">{e7d?.impressions?.toLocaleString() ?? '—'}</td>
                  <td className="px-3 text-center tabular-nums text-muted">{engRate(e24)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
        {initialPosts.length === 0 && (
          <div className="flex flex-col items-center justify-center h-64 text-center gap-2">
            <p className="text-sm font-medium text-foreground">No posts yet</p>
            <p className="text-xs text-muted">Published tweets will appear here.</p>
          </div>
        )}
      </div>
    </>
  )
}
