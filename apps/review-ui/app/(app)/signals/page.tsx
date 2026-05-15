import { createServerClient } from '@/lib/supabase/server'
import { SignalsClient } from './signals-client'
import type { Signal } from '@/lib/types'

async function getSignals(): Promise<Signal[]> {
  try {
    const db = createServerClient()
    const { data } = await db
      .from('signals')
      .select('*')
      .order('observed_at', { ascending: false })
      .limit(500)
    return (data ?? []) as Signal[]
  } catch {
    return []
  }
}

export default async function SignalsPage() {
  const signals = await getSignals()
  return <SignalsClient initialSignals={signals} />
}
