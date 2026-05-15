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
