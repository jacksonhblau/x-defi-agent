import { createServerClient } from '@/lib/supabase/server'
import { CalendarClient } from './calendar-client'
import type { ScheduledPost } from '@/lib/types'

async function getScheduledPosts(): Promise<ScheduledPost[]> {
  try {
    const db = createServerClient()
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString()
    const { data } = await db
      .from('scheduled_posts')
      .select('*, drafts(id, format, edited_body, body, story_id, stories(headline))')
      .in('status', ['queued', 'posting', 'posted', 'failed'])
      .gte('post_at', sevenDaysAgo)
      .order('post_at', { ascending: true })
      .limit(300)
    return (data ?? []) as ScheduledPost[]
  } catch {
    return []
  }
}

export default async function CalendarPage() {
  const posts = await getScheduledPosts()
  return <CalendarClient initialPosts={posts} />
}
