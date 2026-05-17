-- 0003_media_diagnostics.sql
--
-- Adds a structured diagnostics column to media_assets so the graphics
-- pipeline (routing, logo resolution tiers, QA gate, retry/fallback)
-- emits durable telemetry. The graphics dispatcher writes one JSONB blob
-- per asset, the review UI surfaces it, and Phase 7 of the algo-refit
-- analyzes the distribution to tune layout/logo coverage.
--
-- Expected shape (informally):
--   {
--     "layout_template": "enforcement_action",        -- one of 7
--     "layout_selector": "llm" | "rule_based",
--     "logo_tiers": {                                  -- entity → resolution tier
--       "Tether":   "tier1_local_svg",
--       "OFAC":     "tier1_local_svg",
--       "TRON":     "tier3_model_knowledge",
--       "Iran Central Bank": "tier4_typographic"
--     },
--     "qa": {
--       "attempts": 1,
--       "passed":   true,
--       "failures": []
--     },
--     "fallback_to_deterministic": false,
--     "prompt_chars": 1842,
--     "elapsed_ms": 21803
--   }

alter table media_assets
  add column if not exists diagnostics jsonb;

create index if not exists media_assets_diagnostics_layout_idx
  on media_assets ((diagnostics ->> 'layout_template'));

create index if not exists media_assets_diagnostics_fallback_idx
  on media_assets ((diagnostics ->> 'fallback_to_deterministic'))
  where (diagnostics ->> 'fallback_to_deterministic') = 'true';
