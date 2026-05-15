'use server'

import { createServerClient } from '@/lib/supabase/server'
import { revalidatePath } from 'next/cache'
import type { WatchlistData } from '@/lib/types'

export async function saveWatchlist(watchlist: WatchlistData) {
  const db = createServerClient()
  // Read existing config first to merge
  const { data: existing } = await db.from('app_config').select('data').eq('id', 1).single()
  const merged = { ...(existing?.data ?? {}), watchlist }
  const { error } = await db
    .from('app_config')
    .upsert({ id: 1, data: merged }, { onConflict: 'id' })
  if (error) throw new Error(error.message)
  revalidatePath('/watchlist')
}
