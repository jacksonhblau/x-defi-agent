-- Migration 0002: algo-refit (May 2026)
-- Adds media_assets, canva_templates, canva_assets tables.
-- Extends drafts with algo-refit gate columns.
-- Extends stories.brief_json with graphic_kind and canva_payload (handled at the
-- application layer — brief_json is JSONB; no DDL change needed).
--
-- Apply via: python -m workers.cli migrate

-- ---------- Media assets ----------

CREATE TABLE IF NOT EXISTS media_assets (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id      UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  kind          TEXT NOT NULL CHECK (kind IN ('image','video')),
  source        TEXT NOT NULL DEFAULT 'higgsfield'
                  CHECK (source IN ('higgsfield','canva','custom')),
  model         TEXT,
  prompt        TEXT,
  higgsfield_job_id   TEXT,
  canva_template_slug TEXT,
  canva_design_id     TEXT,
  storage_url   TEXT,
  status        TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed')),
  credits_used  INTEGER,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  ready_at      TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_media_assets_draft  ON media_assets(draft_id);
CREATE INDEX IF NOT EXISTS idx_media_assets_status ON media_assets(status);
CREATE INDEX IF NOT EXISTS idx_media_assets_source ON media_assets(source);


-- ---------- Canva template registry ----------

CREATE TABLE IF NOT EXISTS canva_templates (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug              TEXT UNIQUE NOT NULL,
  canva_template_id TEXT NOT NULL,
  description       TEXT,
  field_schema      JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE canva_templates IS
  'Registry of brand templates Jackson built in Canva. The agent reads canva_template_id at render time. See docs/canva_templates_pass_one_briefs.md for the pass-one templates (T1, T3, T5, T6).';


-- ---------- Canva asset cache (logo uploads) ----------

CREATE TABLE IF NOT EXISTS canva_assets (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  logo_sha256    TEXT UNIQUE NOT NULL,
  canva_asset_id TEXT NOT NULL,
  source_path    TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE canva_assets IS
  'Cache of issuer logo uploads to Canva, keyed by file SHA-256, so the same logo only uploads once per Canva org.';


-- ---------- Drafts gate columns ----------

ALTER TABLE drafts
  ADD COLUMN IF NOT EXISTS first_person_check_passed   BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS personal_facts_check_passed BOOLEAN DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS predicted_algo_score        INTEGER,
  ADD COLUMN IF NOT EXISTS ready_for_review            BOOLEAN DEFAULT FALSE;

-- ready_for_review flips true only when:
--   1. all anti-AI checks pass, AND
--   2. at least one media_assets row exists in 'ready' status for this draft, AND
--   3. predicted_algo_score >= algo_scoring.predicted_score_threshold (from thresholds.json).


-- ---------- Reply-window followups ----------

CREATE TABLE IF NOT EXISTS reply_followup_candidates (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  parent_post_id  TEXT NOT NULL,            -- X tweet id of the published post
  reply_tweet_id  TEXT NOT NULL,            -- X tweet id of the incoming reply
  reply_author    TEXT,                     -- X handle of replier
  reply_text      TEXT NOT NULL,
  detected_at_min INTEGER NOT NULL,         -- 5, 15, or 30 (minutes after publish)
  is_voice_model  BOOLEAN DEFAULT FALSE,
  score           INTEGER,                  -- 0-100 relevance/substantiveness
  status          TEXT NOT NULL DEFAULT 'pending'
                    CHECK (status IN ('pending','drafted','approved','rejected','expired')),
  draft_id        UUID REFERENCES drafts(id) ON DELETE SET NULL,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (parent_post_id, reply_tweet_id)
);

CREATE INDEX IF NOT EXISTS idx_reply_followups_status ON reply_followup_candidates(status);
CREATE INDEX IF NOT EXISTS idx_reply_followups_parent ON reply_followup_candidates(parent_post_id);
