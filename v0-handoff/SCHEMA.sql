-- Postgres schema for x-defi-agent. This is the EXISTING database in Supabase.
-- DO NOT run this — it's already applied. This file is for reference so the
-- dashboard knows the data model.

create extension if not exists "uuid-ossp";
create extension if not exists "pgcrypto";

-- =============================================================================
-- signals — raw events from ingest workers, one row per observed event
-- =============================================================================
create table signals (
  id                    uuid primary key default uuid_generate_v4(),
  created_at            timestamptz not null default now(),
  observed_at           timestamptz not null,
  source                text not null,        -- 'defillama' | 'rwa_xyz' | 'telegram_newswire' | 'alchemy' | 'x_firehose' | 'vaultsfyi' | 'bubblemaps'
  source_id             text,                 -- upstream id if available
  entity                text,                 -- canonical entity slug
  signal_type           text not null,        -- 'tvl_delta' | 'aum_delta' | 'new_deploy' | 'newsfeed' | 'x_post' | etc
  payload               jsonb not null,       -- shape varies by source — see SAMPLE_DATA.json
  dedup_hash            text not null unique,
  processed_at          timestamptz,          -- null = not yet scored
  materiality_score     integer,              -- 0-100
  novelty_score         integer,              -- 0-100
  promoted_to_story_id  uuid,                 -- null = not promoted; references stories(id)
  notes                 text                  -- Claude's rationale
);

-- =============================================================================
-- stories — clustered signals that the builder decided are worth drafting
-- =============================================================================
create table stories (
  id                    uuid primary key default uuid_generate_v4(),
  created_at            timestamptz not null default now(),
  headline              text not null,                              -- e.g. "BlackRock BUIDL: 24h TVL move +5.29%"
  narrative_angle       text,
  entities              text[] not null default '{}',               -- X handles to TAG (subjects)
  source_handles        text[] not null default '{}',               -- X handles to CREDIT (sources)
  key_data_points       jsonb not null default '[]',                -- array of {label, value, source}
  graphic_spec          jsonb,
  format_recommendation text[] not null default '{single}',         -- subset of {'single','thread','reply','hot_take'}
  signals_ids           uuid[] not null default '{}',
  hot_take              boolean not null default false,
  status                text not null default 'open'                -- 'open' | 'drafted' | 'posted' | 'killed'
);

-- =============================================================================
-- drafts — generated post candidates awaiting human approval
-- =============================================================================
create table drafts (
  id                    uuid primary key default uuid_generate_v4(),
  story_id              uuid not null references stories(id) on delete cascade,
  created_at            timestamptz not null default now(),
  format                text not null,                              -- 'single' | 'thread' | 'reply' | 'quote_tweet' | 'hot_take'
  variant_label         text,                                       -- 'A' | 'B' | 'C' if multiple variants
  body                  text not null,                              -- single tweet text OR \n\n-joined thread
  body_json             jsonb,                                      -- thread as array of strings; null for non-thread
  graphic_url           text,
  reply_to_tweet_id     text,                                       -- for 'reply' format only
  quote_tweet_id        text,                                       -- for 'quote_tweet' format only
  ai_check_passed       boolean,
  ai_check_flags        text[],                                     -- list of regex matches if check failed
  status                text not null default 'pending',            -- 'pending' | 'approved' | 'rejected' | 'edited' | 'scheduled' | 'posted'
  reviewer_notes        text,
  reviewed_at           timestamptz,
  edited_body           text                                        -- non-null if reviewer edited; worker uses this if set
);

-- =============================================================================
-- scheduled_posts — approved drafts queued for posting at a specific time
-- =============================================================================
create table scheduled_posts (
  id                    uuid primary key default uuid_generate_v4(),
  draft_id              uuid not null references drafts(id) on delete cascade,
  created_at            timestamptz not null default now(),
  post_at               timestamptz not null,                       -- when to post (UTC)
  status                text not null default 'queued',             -- 'queued' | 'posting' | 'posted' | 'failed'
  attempts              integer not null default 0,
  last_error            text
);

-- =============================================================================
-- posts — successfully posted tweets, source of truth for engagement tracking
-- =============================================================================
create table posts (
  id                    uuid primary key default uuid_generate_v4(),
  draft_id              uuid not null references drafts(id),
  scheduled_post_id     uuid references scheduled_posts(id),
  posted_at             timestamptz not null default now(),
  tweet_ids             text[] not null,                            -- array because threads have N ids
  root_tweet_id         text not null unique,                       -- first tweet of the chain
  format                text not null,
  body                  text not null
);

-- =============================================================================
-- engagement — impressions/likes/RTs snapshots at +24h and +7d
-- =============================================================================
create table engagement (
  id                    uuid primary key default uuid_generate_v4(),
  post_id               uuid not null references posts(id) on delete cascade,
  captured_at           timestamptz not null default now(),
  window_label          text not null,                              -- '24h' | '7d'
  impressions           integer,
  likes                 integer,
  retweets              integer,
  replies               integer,
  bookmarks             integer,
  quotes                integer,
  profile_clicks        integer,
  url_clicks            integer
);

-- =============================================================================
-- exemplars — top-decile and bottom-decile posts to inject into future prompts
-- =============================================================================
create table exemplars (
  id                    uuid primary key default uuid_generate_v4(),
  post_id               uuid not null references posts(id) on delete cascade,
  created_at            timestamptz not null default now(),
  kind                  text not null,                              -- 'exemplar' | 'anti_exemplar'
  reason                text,
  active                boolean not null default true
);

-- =============================================================================
-- run_jobs — the agent's scheduled tasks. Editable from the dashboard.
-- =============================================================================
create table run_jobs (
  id                    uuid primary key default uuid_generate_v4(),
  name                  text not null unique,                       -- e.g. 'ingest_defillama'
  description           text,
  command               text not null,                              -- CLI command the worker invokes
  cron                  text,                                       -- cron expression in UTC; null = manual-only
  enabled               boolean not null default true,
  last_run_at           timestamptz,
  next_run_at           timestamptz,
  last_status           text,                                       -- 'ok' | 'error' | 'running'
  last_error            text,
  run_now               boolean not null default false,             -- dashboard sets this to true to trigger ad-hoc
  sort_order            integer not null default 100
);

-- =============================================================================
-- app_config — single-row table holding dashboard-editable settings
-- (create this if it doesn't exist; dashboard reads/writes the 'data' JSONB)
-- =============================================================================
create table if not exists app_config (
  id    integer primary key default 1,
  data  jsonb not null default '{}'::jsonb,
  check (id = 1)
);

insert into app_config (id, data) values (1, '{}') on conflict do nothing;
