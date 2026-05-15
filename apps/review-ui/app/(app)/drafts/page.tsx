import { createServerClient } from '@/lib/supabase/server'
import { DraftsClient } from './drafts-client'
import type { Draft } from '@/lib/types'

async function getDrafts(): Promise<{ drafts: Draft[]; counts: { pending: number; approved: number; posted: number } }> {
  try {
    const db = createServerClient()
    const [draftsRes, pendingRes, approvedRes, postedRes] = await Promise.all([
      db
        .from('drafts')
        .select(
          '*, stories(id, headline, narrative_angle, entities, source_handles, key_data_points, format_recommendation, hot_take, status), media_assets(id, draft_id, kind, source, status, storage_url, model, canva_template_slug, canva_design_id, credits_used, created_at, ready_at)'
        )
        .in('status', ['pending', 'approved', 'edited'])
        .order('created_at', { ascending: false })
        .limit(200),
      db.from('drafts').select('id', { count: 'exact', head: true }).eq('status', 'pending'),
      db.from('drafts').select('id', { count: 'exact', head: true }).eq('status', 'approved'),
      db.from('drafts').select('id', { count: 'exact', head: true }).eq('status', 'posted'),
    ])
    return {
      drafts: (draftsRes.data ?? []) as Draft[],
      counts: {
        pending: pendingRes.count ?? 0,
        approved: approvedRes.count ?? 0,
        posted: postedRes.count ?? 0,
      },
    }
  } catch {
    return { drafts: [], counts: { pending: 0, approved: 0, posted: 0 } }
  }
}

export default async function DraftsPage() {
  const { drafts, counts } = await getDrafts()
  return <DraftsClient initialDrafts={drafts} counts={counts} />
}
