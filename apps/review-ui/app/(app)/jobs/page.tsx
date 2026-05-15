import { createServerClient } from '@/lib/supabase/server'
import { JobsClient } from './jobs-client'
import type { RunJob } from '@/lib/types'

async function getJobs(): Promise<RunJob[]> {
  try {
    const db = createServerClient()
    const { data } = await db.from('run_jobs').select('*').order('sort_order')
    return (data ?? []) as RunJob[]
  } catch {
    return []
  }
}

export default async function JobsPage() {
  const jobs = await getJobs()
  return <JobsClient initialJobs={jobs} />
}
