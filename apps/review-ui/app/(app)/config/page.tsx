import { createServerClient } from '@/lib/supabase/server'
import { ConfigClient } from './config-client'
import type { AppConfig } from '@/lib/types'

const DEFAULT_CONFIG: AppConfig['data'] = {
  materiality: { default_threshold: 60, novelty_threshold: 50, minimum_for_thread: 75 },
  cadence: { daily_post_cap: 8, min_minutes_between_posts: 75, thread_max_per_day: 2 },
  posting_windows_et: [
    { start_hour: 9, end_hour: 10 },
    { start_hour: 12, end_hour: 13 },
    { start_hour: 17, end_hour: 18 },
    { start_hour: 20, end_hour: 21 },
  ],
  onchain: { tvl_delta_threshold_pct: 5, apy_delta_threshold_bps: 50 },
}

async function getConfig(): Promise<AppConfig['data']> {
  try {
    const db = createServerClient()
    const { data } = await db.from('app_config').select('data').eq('id', 1).single()
    if (!data?.data || Object.keys(data.data).length === 0) return DEFAULT_CONFIG
    return data.data as AppConfig['data']
  } catch {
    return DEFAULT_CONFIG
  }
}

export default async function ConfigPage() {
  const config = await getConfig()
  return <ConfigClient initialConfig={config} />
}
