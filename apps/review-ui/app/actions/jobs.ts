'use server'

import { createServerClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'

export async function updateJobCron(id: string, cron: string | null) {
  const db = createServerClient()
  const { error } = await db.from('run_jobs').update({ cron }).eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/jobs')
}

export async function toggleJobEnabled(id: string, enabled: boolean) {
  const db = createServerClient()
  const { error } = await db.from('run_jobs').update({ enabled }).eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/jobs')
}

export async function triggerRunNow(id: string) {
  const db = createServerClient()
  const { error } = await db.from('run_jobs').update({ run_now: true }).eq('id', id)
  if (error) throw new Error(error.message)
  revalidatePath('/jobs')
}

/**
 * Set run_now=true on the full news → drafts pipeline (in sort_order):
 *   ingest_telegram → ingest_rwa_xyz → ingest_defillama → score →
 *   build_stories → draft
 *
 * The Fly watch loop processes due jobs in sort_order ascending, so flipping
 * the flag on all of them at once fires them in the right sequence on the
 * next tick (~60s). Returns the count of jobs queued.
 */
export async function triggerFullRefresh(): Promise<{ queued: number; names: string[] }> {
  const pipeline = [
    'ingest_telegram',
    'ingest_rwa_xyz',
    'ingest_defillama',
    'score',
    'build_stories',
    'draft',
  ]
  const db = createServerClient()
  const { data, error } = await db
    .from('run_jobs')
    .update({ run_now: true })
    .in('name', pipeline)
    .eq('enabled', true)
    .select('name')
  if (error) throw new Error(error.message)
  revalidatePath('/jobs')
  revalidatePath('/drafts')
  return { queued: data?.length ?? 0, names: data?.map((d) => d.name) ?? [] }
}
