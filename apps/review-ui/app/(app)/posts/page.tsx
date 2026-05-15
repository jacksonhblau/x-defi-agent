import { createServerClient } from '@/lib/supabase/server'
import { PostsClient } from './posts-client'
import type { Post } from '@/lib/types'

async function getPosts(): Promise<Post[]> {
  try {
    const db = createServerClient()
    const { data } = await db
      .from('posts')
      .select('*, engagement(*)')
      .order('posted_at', { ascending: false })
      .limit(200)
    return (data ?? []) as Post[]
  } catch {
    return []
  }
}

export default async function PostsPage() {
  const posts = await getPosts()
  return <PostsClient initialPosts={posts} />
}
