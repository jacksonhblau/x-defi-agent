-- x-defi-agent — Postgres schema
-- Apply to your Supabase database via the migration runner (`python -m workers.cli migrate`)
-- or paste into the Supabase SQL editor.

-- =============================================================================
-- Extensions
-- =============================================================================

create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- =============================================================================
-- signals
-- Raw events from ingest workers. One row per observed event after deduplication.
-- =============================================================================

create table if not exists signals (
  id              uuid primary key default uuid_generate_v4(),
  created_at      timestamptz not null default now(),
  observed_at     timestamptz not null,
  source          text not null,                    -- 'defillama', 'rwa_xyz', 'telegram_newswire', 'alchemy', 'x_firehose', 'vaultsfyi', 'bubblemaps'
  source_id       text,                             -- upstream id if available (e.g. tweet id, telegram message id)
  entity          text,                             -- canonical entity slug (e.g. 'blackrock_buidl', 'ondo_ousg')
  signal_type     text not null,                    -- 'tvl_delta', 'apy_shift', 'treasury_flow', 'new_deploy', 'governance', 'x_post', 'newsfeed'
  payload         jsonb not null,                   -- normalized data
  dedup_hash      text not null,
  processed_at    timestamptz,
  materiality_score integer,
  novelty_score   integer,
  promoted_to_story_id uuid,
  notes           text
);

create unique index if not exists signals_dedup_hash_idx on signals (dedup_hash);
create index if not exists signals_observed_at_idx on signals (observed_at desc);
create index if not exists signals_source_entity_idx on signals (source, entity);
create index if not exists signals_unprocessed_idx on signals (processed_at) where processed_at is null;

-- =============================================================================
-- stories
-- Clusters of related signals that the story builder decided are worth drafting.
-- =============================================================================

create table if not exists stories (
  id              uuid primary key default uuid_generate_v4(),
  created_at      timestamptz not null default now(),
  headline        text not null,
  narrative_angle text,
  entities        text[] not null default '{}',     -- X handles to TAG as subject of analysis
  source_handles  text[] not null default '{}',     -- X handles to CREDIT for data attribution
  key_data_points jsonb not null default '[]',
  graphic_spec    jsonb,
  format_recommendation text[] not null default '{single}',  -- subset of {'single','thread','reply','hot_take'}
  signals_ids     uuid[] not null default '{}',
  hot_take        boolean not null default false,
  status          text not null default 'open'      -- 'open', 'drafted', 'posted', 'killed'
);

-- Idempotent migration for the source_handles column on existing tables.
alter table stories add column if not exists source_handles text[] not null default '{}';

-- Backfill source_handles on existing stories whose array is empty,
-- derived from each story's underlying signals.
update stories s
set source_handles = array(
    select distinct case sig.source
        when 'defillama'         then '@DefiLlama'
        when 'rwa_xyz'           then '@rwa_xyz'
        when 'telegram_newswire' then '@RWAxyzNewswire'
        when 'vaultsfyi'         then '@vaultsfyi'
        when 'bubblemaps'        then '@bubblemaps'
        when 'etherscan'         then '@etherscan'
        else null
    end
    from signals sig
    where sig.id = any(s.signals_ids)
      and sig.source in ('defillama','rwa_xyz','telegram_newswire','vaultsfyi','bubblemaps','etherscan')
)
where (source_handles is null or source_handles = '{}');

create index if not exists stories_status_idx on stories (status, created_at desc);

-- =============================================================================
-- drafts
-- Draft posts generated from stories. Multiple variants per story allowed.
-- =============================================================================

create table if not exists drafts (
  id              uuid primary key default uuid_generate_v4(),
  story_id        uuid not null references stories(id) on delete cascade,
  created_at      timestamptz not null default now(),
  format          text not null,                    -- 'single' | 'thread' | 'reply' | 'quote_tweet' | 'hot_take'
  variant_label   text,                             -- 'A', 'B', 'C' when multiple variants exist
  body            text not null,                    -- single tweet text OR newline-joined thread
  body_json       jsonb,                            -- structured representation (thread as array, reply target id, etc.)
  graphic_url     text,
  reply_to_tweet_id text,
  quote_tweet_id  text,
  ai_check_passed boolean,
  ai_check_flags  text[],
  status          text not null default 'pending',  -- 'pending', 'approved', 'rejected', 'edited', 'scheduled', 'posted'
  reviewer_notes  text,
  reviewed_at     timestamptz,
  edited_body     text                              -- if reviewer edited before approving
);

create index if not exists drafts_status_idx on drafts (status, created_at desc);
create index if not exists drafts_story_idx on drafts (story_id);

-- =============================================================================
-- scheduled_posts
-- Approved drafts waiting to be posted at a specific time.
-- =============================================================================

create table if not exists scheduled_posts (
  id              uuid primary key default uuid_generate_v4(),
  draft_id        uuid not null references drafts(id) on delete cascade,
  created_at      timestamptz not null default now(),
  post_at         timestamptz not null,
  status          text not null default 'queued',   -- 'queued', 'posting', 'posted', 'failed'
  attempts        integer not null default 0,
  last_error      text
);

create index if not exists scheduled_posts_due_idx on scheduled_posts (post_at) where status = 'queued';

-- =============================================================================
-- posts
-- Successfully posted tweets. Source of truth for engagement tracking.
-- =============================================================================

create table if not exists posts (
  id              uuid primary key default uuid_generate_v4(),
  draft_id        uuid not null references drafts(id),
  scheduled_post_id uuid references scheduled_posts(id),
  posted_at       timestamptz not null default now(),
  tweet_ids       text[] not null,                  -- array because threads have many ids
  root_tweet_id   text not null,
  format          text not null,
  body            text not null
);

create unique index if not exists posts_root_tweet_idx on posts (root_tweet_id);

-- =============================================================================
-- engagement
-- Engagement snapshots pulled at +24h and +7d after post.
-- =============================================================================

create table if not exists engagement (
  id              uuid primary key default uuid_generate_v4(),
  post_id         uuid not null references posts(id) on delete cascade,
  captured_at     timestamptz not null default now(),
  window_label    text not null,                    -- '24h' | '7d'
  impressions     integer,
  likes           integer,
  retweets        integer,
  replies         integer,
  bookmarks       integer,
  quotes          integer,
  profile_clicks  integer,
  url_clicks      integer
);

create unique index if not exists engagement_post_window_idx on engagement (post_id, window_label);

-- =============================================================================
-- exemplars
-- Top-decile and bottom-decile posts surfaced into the prompt for future drafts.
-- Populated by the learning loop.
-- =============================================================================

create table if not exists exemplars (
  id              uuid primary key default uuid_generate_v4(),
  post_id         uuid not null references posts(id) on delete cascade,
  created_at      timestamptz not null default now(),
  kind            text not null,                    -- 'exemplar' | 'anti_exemplar'
  reason          text,
  active          boolean not null default true
);

create index if not exists exemplars_active_kind_idx on exemplars (kind, active);

-- =============================================================================
-- run_jobs
-- One row per agent script/command. Edited by the user via the Excel dashboard.
-- The 'agent watch' loop reads this table to decide what to run when.
-- =============================================================================

create table if not exists run_jobs (
  id              uuid primary key default uuid_generate_v4(),
  name            text not null unique,             -- 'ingest_defillama', 'score', etc.
  description     text,
  command         text not null,                    -- CLI command to invoke
  cron            text,                             -- cron expression (UTC). null = manual-only.
  enabled         boolean not null default true,
  last_run_at     timestamptz,
  next_run_at     timestamptz,
  last_status     text,                             -- 'ok', 'error', 'running'
  last_error      text,
  run_now         boolean not null default false,   -- user-triggered ad-hoc run flag
  sort_order      integer not null default 100
);

create index if not exists run_jobs_next_run_idx on run_jobs (next_run_at) where enabled;

-- Seed default jobs if the table is empty.
insert into run_jobs (name, description, command, cron, sort_order) values
  ('ingest_defillama',  'Pull RWA-tagged protocols from DeFiLlama; emit TVL-delta signals',  'ingest --source defillama',  '*/10 * * * *', 10),
  ('ingest_rwa_xyz',    'Pull tokenized treasury / credit data from RWA.xyz API',             'ingest --source rwa_xyz',    '*/15 * * * *', 11),
  ('ingest_telegram',   'Stream messages from RWAxyzNewswire Telegram channel',               'ingest --source telegram',   '*/2 * * * *',  12),
  ('ingest_x_firehose', 'Poll watchlist X accounts for new posts',                            'ingest --source x_firehose', '*/2 * * * *',  13),
  ('ingest_alchemy',    'Watch onchain wallets and contract deploys',                         'ingest --source alchemy',    '*/5 * * * *',  14),
  ('score',             'Run materiality scorer over unprocessed signals',                    'score',                      '*/5 * * * *',  20),
  ('build_stories',     'Promote scored signals to stories',                                  'build-stories',              '*/10 * * * *', 30),
  ('draft',             'Generate drafts for open stories (all formats)',                     'draft --all-open',           '*/15 * * * *', 40),
  ('hot_take',          'Slow-day fallback: generate one non-obvious take per day',           'hot-take',                   '0 15 * * *',   50),
  ('weekly_recap',      'Friday digest: top RWA flows and movers this week',                  'recap --weekly',             '0 13 * * 5',   51),
  ('post_due',          'Drain scheduled_posts queue: publish anything past its post_at',     'post-due',                   '* * * * *',    60),
  ('engagement_24h',    'Capture impressions/likes/RTs at +24h on each post',                 'engagement --window 24h',    '*/30 * * * *', 70),
  ('engagement_7d',     'Capture impressions/likes/RTs at +7d on each post',                  'engagement --window 7d',     '0 */6 * * *',  71)
on conflict (name) do nothing;
