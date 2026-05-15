'use server'

import { createServerClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'

export async function saveConfig(data: Record<string, unknown>) {
  const db = createServerClient()
  const { error } = await db
    .from('app_config')
    .upsert({ id: 1, data }, { onConflict: 'id' })
  if (error) throw new Error(error.message)
  revalidatePath('/config')
}
