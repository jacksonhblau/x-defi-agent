import { createServerClient } from '@/lib/supabase/server'
import { WatchlistClient } from './watchlist-client'
import type { WatchlistData } from '@/lib/types'

// Default from WATCHLIST.json
const DEFAULT_WATCHLIST: WatchlistData = {
  voice_models: {
    weight: 2.0,
    handles: ['imperiumpaper','sebventures','adcv_','monetsupply','francescoweb3','definikola','bobmurphyecon','mcagney','jessepollak','zeusrwa','talkintokens'],
  },
  newsfeeds: {
    weight: 1.5,
    handles: ['rwa_xyz','DefiLlama','bubblemaps','vaultsfyi'],
    telegram_channels: ['RWAxyzNewswire'],
  },
  issuers: {
    weight: 1.0,
    handles: ['ondofinance','maplefinance','centrifuge','goldfinch_fi','realtplatform','SuperstateInc','openeden_X','backed_fi','swarm_markets'],
  },
  protocols: {
    weight: 1.0,
    handles: ['sky_money','MorphoLabs','sparkdotfi','aave','eulerfinance','gauntlet_'],
  },
  tradfi_entrants: {
    weight: 1.0,
    handles: ['BlackRock','Securitize','franklintempleton','Fidelity','CircleConsumer','BNYMellon','JPMorgan','WisdomTreeFunds'],
  },
  journalists: {
    weight: 0.75,
    handles: ['MilkRoadDaily','DefiantNews','BanklessHQ','CoinDesk','TheBlock__','rwa_io'],
  },
}

async function getWatchlist(): Promise<WatchlistData> {
  try {
    const db = createServerClient()
    const { data } = await db.from('app_config').select('data').eq('id', 1).single()
    if (data?.data?.watchlist && Object.keys(data.data.watchlist).length > 0) {
      return data.data.watchlist as WatchlistData
    }
  } catch {}
  return DEFAULT_WATCHLIST
}

export default async function WatchlistPage() {
  const watchlist = await getWatchlist()
  return <WatchlistClient initialWatchlist={watchlist} />
}
