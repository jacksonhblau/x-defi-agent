export type DraftStatus = 'pending' | 'approved' | 'rejected' | 'edited' | 'scheduled' | 'posted'
export type DraftFormat = 'single' | 'thread' | 'reply' | 'quote_tweet' | 'hot_take'
export type StoryStatus = 'open' | 'drafted' | 'posted' | 'killed'
export type ScheduledPostStatus = 'queued' | 'posting' | 'posted' | 'failed'
export type JobStatus = 'ok' | 'error' | 'running'
export type SignalSource = 'defillama' | 'rwa_xyz' | 'telegram_newswire' | 'alchemy' | 'x_firehose' | 'vaultsfyi' | 'bubblemaps'

export interface Story {
  id: string
  created_at: string
  headline: string
  narrative_angle: string | null
  entities: string[]
  source_handles: string[]
  key_data_points: { label: string; value: string; source: string }[]
  graphic_spec: unknown | null
  format_recommendation: string[]
  signals_ids: string[]
  hot_take: boolean
  status: StoryStatus
}

export interface Draft {
  id: string
  story_id: string
  created_at: string
  format: DraftFormat
  variant_label: string | null
  body: string
  body_json: string[] | null
  graphic_url: string | null
  reply_to_tweet_id: string | null
  quote_tweet_id: string | null
  ai_check_passed: boolean | null
  ai_check_flags: string[] | null
  status: DraftStatus
  reviewer_notes: string | null
  reviewed_at: string | null
  edited_body: string | null
  // joined
  stories?: Story
}

export interface ScheduledPost {
  id: string
  draft_id: string
  created_at: string
  post_at: string
  status: ScheduledPostStatus
  attempts: number
  last_error: string | null
  // joined
  drafts?: Draft & { stories?: Story }
}

export interface Post {
  id: string
  draft_id: string
  scheduled_post_id: string | null
  posted_at: string
  tweet_ids: string[]
  root_tweet_id: string
  format: DraftFormat
  body: string
  // joined
  engagement?: Engagement[]
}

export interface Engagement {
  id: string
  post_id: string
  captured_at: string
  window_label: '24h' | '7d'
  impressions: number | null
  likes: number | null
  retweets: number | null
  replies: number | null
  bookmarks: number | null
  quotes: number | null
  profile_clicks: number | null
  url_clicks: number | null
}

export interface Signal {
  id: string
  created_at: string
  observed_at: string
  source: SignalSource
  source_id: string | null
  entity: string | null
  signal_type: string
  payload: unknown
  dedup_hash: string
  processed_at: string | null
  materiality_score: number | null
  novelty_score: number | null
  promoted_to_story_id: string | null
  notes: string | null
}

export interface RunJob {
  id: string
  name: string
  description: string | null
  command: string
  cron: string | null
  enabled: boolean
  last_run_at: string | null
  next_run_at: string | null
  last_status: JobStatus | null
  last_error: string | null
  run_now: boolean
  sort_order: number
}

export interface AppConfig {
  id: number
  data: {
    materiality?: {
      default_threshold?: number
      novelty_threshold?: number
      minimum_for_thread?: number
    }
    cadence?: {
      daily_post_cap?: number
      min_minutes_between_posts?: number
      thread_max_per_day?: number
    }
    posting_windows_et?: { start_hour: number; end_hour: number }[]
    onchain?: {
      tvl_delta_threshold_pct?: number
      apy_delta_threshold_bps?: number
    }
    watchlist?: WatchlistData
  }
}

export interface WatchlistEntry {
  handle: string
  category: string
  weight: number
  enabled: boolean
}

export type WatchlistData = Record<string, {
  weight: number
  handles: string[]
  telegram_channels?: string[]
}>
