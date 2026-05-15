import { createServerClient } from '@/lib/supabase/server'
import { StoriesClient } from './stories-client'
import type { Story } from '@/lib/types'

async function getStories(): Promise<Story[]> {
  try {
    const db = createServerClient()
    const { data } = await db
      .from('stories')
      .select('*')
      .order('created_at', { ascending: false })
      .limit(200)
    return (data ?? []) as Story[]
  } catch {
    return []
  }
}

export default async function StoriesPage() {
  const stories = await getStories()
  return <StoriesClient initialStories={stories} />
}
