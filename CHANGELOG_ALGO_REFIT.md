# CHANGELOG — Algo-Refit (May 15, 2026)

Refit of the DeFi X Posting Agent to match the May 2026 X ranking algorithm + Jackson's three voice constraints:

1. Every draft ships with at least one generated media asset (Higgsfield editorial OR Canva data-led template).
2. First-person specific voice everywhere — singles, threads, replies, recaps, long-form.
3. No hallucinated personal actions — the agent states Jackson's opinions, never narrates actions, except for verb+object pairs whitelisted in `config/personal_facts.json` with `approved_to_reference: true`.

See `ALGO_REFIT_PLAN.md` for the original spec and `docs/x_algorithm_2026_signals.md`, `docs/higgsfield_integration.md`, `docs/canva_integration.md` for the supporting references.

---

## Open decisions Jackson made (Q&A)

| # | Decision | Choice |
|---|---|---|
| 1 | Daily post cap | **3/day** (was 8). More conservative than the recommendation of 5 — stays well below the author-dilution rail. |
| 2 | Reply-window worker | **Build it.** 5/15/30 min poll after each post → top 3 candidates into the review queue. |
| 3 | Higgsfield video on threads | **Materiality ≥ 80 only.** Image-only below that. |
| 4 | Personal facts ledger | **Build from Q&A.** Resume + investment disclosures → populated `personal_facts.json` (draft; Jackson edits before live). |
| 5 | Canva Enterprise seat | **MCP-only for now.** Skip the $30/seat upgrade; use Canva MCP in dev, defer prod REST wire-up. |
| 6 | Issuer logo bundle strategy | **Preemptive scrape** (when the agent first encounters an issuer). |
| 7 | Canva pass-one templates | **T1 + T3 + T5 + T6** (adoption snapshot + leaderboard + asset deep-dive + deploy card). |

---

## Files changed / added

### Voice prompts

- **`packages/prompts/voice.md`** — added algo-refit rules: first-person default (rule 1), evidence-required (rule 3), no-hallucinated-actions (rule 8), algo-incentives (rule 9). Added `engagement-bait-closer` to forbidden patterns. Replaced the two third-person calibration exemplars with four first-person exemplars (single sovereignty take, single native-vs-twins held-view take, thread argument-first, reply additive). Preserved the existing @-mention-first rule and punctuated-contrast-kicker rule.
- **`packages/prompts/single_post.md`** — added a "Hard requirements (algo-refit)" block at top: first-person lead, key_data_point grounding, no unwhitelisted personal action, no bait closers. Added the three-variant generation spec (A unconventional read / B held view / C data anomaly).
- **`packages/prompts/thread.md`** — added first-person frame requirement on tweet 1, graphics dispatch note, long-form variant spec (≥1500 chars for materiality ≥ 80).
- **`packages/prompts/hot_take.md`** — added first-person frame requirement to hard requirements; added the no-hallucinated-action rule.
- **`packages/prompts/reply.md`** — replies must lead with a first-person frame OR be a short factual counter-data-point.

### Personal facts ledger

- **`config/personal_facts.json`** — NEW, populated from Q&A:
  - Identity: Manager of DeFi and Crypto at Inveniam, reporting to CSO. Prior VP/Director/Head roles at infineo. Michigan econ grad 2023.
  - 16 entries in `things_i_have_done` (current role, past roles, education, 4 conferences, 19+ podcasts/Spaces, EXOD arbitrage at STM in 2022 generating +146%, GRT advocate + Graph Foundation grant recipient, early Cardano).
  - 3 entries in `things_i_have_built` (Inveniam Chain NVNM whitepaper, DIOL Foundation whitepaper, Inveniam IO Ecosystem Map).
  - 18 entries in `positions_i_hold` — BTC/ETH DCA, SPiCE VC, RedSwan, FIGR, the full stock account (TSLA, TSM, AAPL, NVDA, COIN, AMZN, MSFT, BBBY, SPY, BBBYWS), EXOD (past arb), GRT/ADA (past), Detroit Lions cards. **No $ amounts disclosed.**
  - 3 entries in `views_i_hold_strongly`: vault infrastructure is the institutional onramp, tokenized private credit/ABS is the next leg up, onchain-native assets > digital twins (with three defending points).
  - 11 entries in `things_off_limits` — specific Inveniam deal sizes ($125M ABS, $200M-valuation token, $5B UAE, $50M xGold, $200B+/$600B+ allocator sizes, NVNM FDV scenarios), named MNDA counterparties, internal product/chain decisions, FSRA/OCC/Fed meeting content, $ amounts of personal positions, Inveniam firm POV.
  - Tone calibration: 6 first-person voice examples + 6 anti-examples; voice-tic "lead with the unconventional read".
- `config/personal_facts.example.json` — unchanged (per spec).

### Anti-AI checker (NEW)

- **`apps/workers-py/src/workers/drafts/anti_ai.py`** — implements all six checks from the plan:
  - `check_first_person` — required for singles/replies/hot_takes and thread tweet 1.
  - `check_personal_action` — matches `I [adverb?] <verb> <object>` against `things_i_have_done` + `things_i_have_built`; verb-stem + object-token matching.
  - `check_off_limits` — scans for any $-figure substring listed in things_off_limits.
  - `check_engagement_bait_closer` — rejects "thoughts?" / "agree or disagree?" closers absent a substantive question setup.
  - `check_floating_assertion` — soft flag for numbers not in `key_data_points`.
  - `check_em_dash` — em/en-dash hard reject.
  - `check_media_present` — hard reject if no `media_assets` row in `ready` status.
  - `predicted_algo_score` — 0-100 heuristic combining media bonus, first-person, number density, reply-opener, length-for-dwell, and entity tags.
- Errors via `PersonalFactsNotConfiguredError` with a clear message if `config/personal_facts.json` is missing.

### Draft generator (wired up)

- **`apps/workers-py/src/workers/drafts/__init__.py`** — replaces the empty stub. Loads voice.md + format template + redacted personal_facts (identity + views + first-person voice examples ONLY — off-limits never sent to model). Generates 3 single variants (A/B/C hints), 1 thread variant if recommended, 1 long-form variant if materiality ≥ 80. Calls graphics dispatcher. Runs anti_ai.check_draft with up to 3 regenerations. Flips `ready_for_review` only when all anti-AI checks pass AND ≥1 ready media asset AND predicted score ≥ threshold.
- `apps/workers-py/src/workers/drafts/generator.py` — pre-existing v1 generator preserved unchanged for backward compatibility.

### Graphics pipeline (NEW)

- **`apps/workers-py/src/workers/graphics/__init__.py`** — dispatcher. Routes by `story_brief.graphic_kind`: editorial → Higgsfield, data_card/comparison/leaderboard/time_series/deploy_card → Canva, recap_grid → both, materiality ≥ 80 + editorial + thread → Higgsfield video hero + Canva data card.
- **`apps/workers-py/src/workers/graphics/higgsfield.py`** — prompt construction (deterministic, testable). `build_image_prompt` + `build_video_prompt` apply the Quiet Cartography visual identity, pick metaphors from narrative_angle, set composition by format. Client abstraction: MCP path (Cowork dev) via `record_higgsfield_asset` after manual MCP invocation; REST path (prod) stubbed for enterprise wire-up.
- **`apps/workers-py/src/workers/graphics/canva.py`** — autofill payload preparation. `resolve_logos` walks `*_logo` fields, looks up local SVG bundle first, falls back to URL upload, falls back to MONOGRAM sentinel. Asset-id cache keyed by SHA-256. Client abstraction same shape as Higgsfield; `record_canva_asset` for MCP-mediated dev.

### Engagement / reply-window worker (NEW)

- **`apps/workers-py/src/workers/engagement/__init__.py`** + **`reply_window.py`** — polls reply trees at 5/15/30 min after each published post. Scores replies on length + question-mark + named-entity + specific number; 2x boost for voice-model handles from `watchlist.json`. Inserts top 3 into `reply_followup_candidates` table.

### Materiality scorer (extended)

- **`apps/workers-py/src/workers/scoring/materiality.py`** — added `personal_take` category, `touches_view` boolean, and `_apply_view_bonus` (+10 novelty when the signal touches a `view_i_hold_strongly`). Updated SYSTEM_PROMPT to instruct the scorer to flag view-touching signals.

### Schema migration

- **`packages/db/migrations/0002_algo_refit.sql`** — adds:
  - `media_assets` table (id, draft_id FK, kind image|video, source higgsfield|canva|custom, model, prompt, higgsfield_job_id, canva_template_slug, canva_design_id, storage_url, status queued|running|ready|failed, credits_used).
  - `canva_templates` table (slug unique, canva_template_id, description, field_schema JSONB).
  - `canva_assets` table (logo_sha256 unique, canva_asset_id, source_path).
  - `reply_followup_candidates` table (parent_post_id, reply_tweet_id, reply_author, score, status, draft_id FK).
  - ALTER `drafts` adds `first_person_check_passed`, `personal_facts_check_passed`, `predicted_algo_score`, `ready_for_review`.

### Configuration

- **`config/thresholds.json`** — added `cadence.daily_post_cap: 3` (was 8), `cadence.min_minutes_between_posts: 60` (was 45), `cadence.long_form_max_per_day: 1`. Added `engagement.reply_window_minutes: [5, 15, 30]`. Added top-level blocks for `algo_scoring` (threshold + max regenerations), `media` (required_for_every_post=true, video_materiality_floor=80, higgsfield_monthly_credit_cap=2000), `anti_ai` (personal_facts_path, max_regenerations_per_draft).
- **`.env.example`** — added Higgsfield block (MCP URL, REST URL, default image/video model, monthly credit cap), Canva block (Connect REST creds, MCP note), `DAILY_POST_CAP=3` with comment.

### Documentation

- **`docs/x_algorithm_2026_signals.md`** — full X-algo reference (heavy-rail weights, candidate generation, penalties, media handling, sanity-check checklist).
- **`docs/higgsfield_integration.md`** — MCP/REST access paths, model selection table, visual identity, prompt construction, workflow, cost envelope, schema, env.
- **`docs/canva_integration.md`** — routing matrix, MCP/REST access, full seven-template spec, visual identity, logo sourcing strategy, RWA.xyz binding, schema, env, test fixtures.
- **`docs/canva_templates_pass_one_briefs.md`** — one-page Canva-authoring spec per template for T1, T3, T5, T6 with exact field schemas + visual identity reminders.
- **`ALGO_REFIT_PLAN.md`** — copied into project root (lightweight pointer to the uploaded spec).

### Test fixtures + logo bundle

- `data/test_briefs/private_credit_adoption_t1.json` — five-issuer asset-class snapshot (Maple, Centrifuge, Goldfinch, Ondo, OpenEden) with complete canva_payload for T1.
- `data/test_briefs/blackrock_buidl_deploy_t6.json` — BlackRock $7B filing as T6 deploy-card fixture.
- `packages/graphics/logos/issuers/*.svg` — 7 monogram placeholders for the test fixtures (maplefinance, centrifuge, goldfinch_fi, ondofinance, openeden_X, BlackRock, ethereum). Each is a `#1F6FEB` 2-letter monogram on `#FAFAFA`. Replace with clean SVGs from each issuer's press kit as Jackson curates.
- `packages/graphics/logos/issuers/README.md` — naming convention, sourcing rules, monogram generator script.

### Tests

- **`apps/workers-py/tests/test_anti_ai.py`** — 20 tests covering: personal_facts loading + error path, malformed-JSON error, first-person variant pass, held-view pass, third-person rejection, hallucinated-action rejection, bait-closer rejection, em-dash rejection, missing-media rejection, disclosed-position pass (ETH), undisclosed-position rejection (Pepe), whitelisted-conference pass (ETH Denver), unwhitelisted-meeting rejection (BlackRock call), off-limits dollar-figure rejection ($125M ABS), thread-tweet-1 first-person pass + fail, legacy-v1-draft fails under algo-refit (documented behavior change), predicted-algo-score smoke tests.

---

## Test results

```
============================= test session starts ==============================
collected 20 items

tests/test_anti_ai.py::test_personal_facts_loads PASSED                  [  5%]
tests/test_anti_ai.py::test_missing_personal_facts_raises PASSED         [ 10%]
tests/test_anti_ai.py::test_malformed_json_raises PASSED                 [ 15%]
tests/test_anti_ai.py::test_first_person_blackrock_variant_passes PASSED [ 20%]
tests/test_anti_ai.py::test_held_view_native_vs_twins_passes PASSED      [ 25%]
tests/test_anti_ai.py::test_bad_third_person_rejected PASSED             [ 30%]
tests/test_anti_ai.py::test_bad_hallucinated_action_rejected PASSED      [ 35%]
tests/test_anti_ai.py::test_bad_engagement_bait_closer_rejected PASSED   [ 40%]
tests/test_anti_ai.py::test_em_dash_rejected PASSED                      [ 45%]
tests/test_anti_ai.py::test_missing_media_rejected PASSED                [ 50%]
tests/test_anti_ai.py::test_disclosed_eth_position_allowed PASSED        [ 55%]
tests/test_anti_ai.py::test_undisclosed_pepe_position_rejected PASSED    [ 60%]
tests/test_anti_ai.py::test_attended_eth_denver_allowed PASSED           [ 65%]
tests/test_anti_ai.py::test_unwhitelisted_meeting_rejected PASSED        [ 70%]
tests/test_anti_ai.py::test_off_limits_125m_abs_rejected PASSED          [ 75%]
tests/test_anti_ai.py::test_thread_first_person_on_tweet_1 PASSED        [ 80%]
tests/test_anti_ai.py::test_thread_missing_first_person_on_tweet_1_rejected PASSED [ 85%]
tests/test_anti_ai.py::test_legacy_v1_draft_fails_under_algo_refit PASSED [ 90%]
tests/test_anti_ai.py::test_predicted_algo_score_first_person_with_media PASSED [ 95%]
tests/test_anti_ai.py::test_predicted_algo_score_third_person_no_media PASSED [100%]

============================== 20 passed in 0.02s ==============================
```

**Verification bar from the plan: caught all three constructed bad drafts (third-person, hallucinated action, bait closer); passed a first-person variant of the BlackRock fixture.** ✓

The legacy v1 draft (`data/drafts/91751dcf-9408-43a5-b0e2-b11c06775efa.json`) correctly fails under algo-refit rules — it's third-person (no "I" frame). This is a documented behavior change. The agent will regenerate fresh first-person variants when this story re-enters the pipeline.

---

## Higgsfield prompt philosophy — refined to infographic-first (May 15, 2026 v2)

The first smoke-test image came back as an abstract metaphor — a single conceptual subject ("a rooted form against open space"). That's the wrong direction. Higgsfield output must be a **tightly-curated infographic that visually reproduces the specific data, entities, and relationships discussed in the post**, not editorial concept art.

Code changes:
- `apps/workers-py/src/workers/graphics/higgsfield.py`:
  - `MODEL_DEFAULTS` switched from Flux 2 → **GPT Image 2** for singles/hot-takes/long-form (Flux 2 reserved for rare metaphor-only posts).
  - `VISUAL_IDENTITY_SUFFIX` rewritten — "editorial financial infographic", explicit "render the actual data verbatim", "structured visual reproduction not abstract concept".
  - `pick_metaphor` removed; replaced with `pick_layout(brief, format_hint)` — returns a structured layout description (three-tier hierarchy, ranked bars, side-by-side comparison, flow diagram, hero announcement card) keyed off the brief's `narrative_angle`.
  - `build_image_prompt` rewritten — emits headline + verbatim labeled-value pairs from `key_data_points` + entity name list + layout directive + identity suffix.
  - `build_video_prompt` updated — animates the infographic (labels resolve in, numbers count up, bars draw), end frame matches the still spec.
- `docs/higgsfield_integration.md` §2-§4 rewritten:
  - §2 model selection table reordered (GPT Image 2 / Nano Banana Pro / Kling 3 prioritized; Flux 2 noted as last resort for metaphor-only posts).
  - §3 visual identity locked as infographic-first with six explicit rules.
  - §4 prompt construction documented with the seven-element shape + layout-trigger table.

## Live end-to-end smoke test — PASSED (May 15, 2026)

Jackson upgraded Higgsfield to the starter tier (202.5 credits available). Ran the BlackRock BUIDL sovereignty story through the algo-refit pipeline twice — v1 with the abstract prompt, v2 after the infographic-first rewrite.

**v2 (current — what ships):**
- Model: **GPT Image 2**, 1:1 aspect, 1k resolution, medium quality
- Cost: 2 credits
- Job ID: `81b6efb6-eff1-4bed-b4ef-726ab67b9c37`
- Generated image: [hf_20260515_211737_81b6efb6-…png](https://d8j0ntlcm91z4.cloudfront.net/user_3D5IkYNX7ZkwyQmUBfriG1gzMRy/hf_20260515_211737_81b6efb6-eff1-4bed-b4ef-726ab67b9c37.png) — also saved locally to `data/drafts/media/smoke_blackrock_infographic_v2.png`
- **What it renders:** vertical three-tier hierarchy with labeled arrows. Top: "BlackRock — ISSUER / EVENT — $7B Filed AUM". Arrow labeled "APPOINTS & DELEGATES AUTHORITY TO". Middle: "BNY Mellon Investment Servicing — TRANSFER AGENT — Maintains investor records and executes transfers". Arrow labeled "AUTHORITY OVER CANONICAL STATE". Bottom: "Ethereum — CANONICAL CHAIN — L1 ledger that serves as the single, canonical state of token ownership". Supporting figures bottom: "$1.7B over 14 months — BUIDL comparable" and "$31B — Tokenized treasury TVL". `@jacksonblau` watermark bottom-left. Headline at the top.
- Anti-AI result: passed (no rejections, no soft flags)
- Predicted algo score: 65/100 (threshold: 60)
- Status: `ready_for_review`
- Saved fixture: `data/drafts/smoke_blackrock_sovereignty_2026-05-15.json` (tagged `version: v2_infographic`)

**v1 (deprecated — the abstract metaphor attempt):**
- Model: Flux 2 pro, 1:1, 1k. 1 credit.
- Job ID: `92ceccf2-27ce-468d-86bf-713abf811a02`
- Output: abstract column-against-plain visual metaphor. Read as "loosely connected to the message" rather than "reinforces every claim in the text". Triggered the rewrite documented above.

Body (260/280 chars):

> I keep seeing the @BlackRock $7B filing read as a size story.
>
> I think it's a sovereignty story. @BNYMellon is the named transfer agent. Ownership records live on Ethereum.
>
> The bottleneck was never demand. It was who has authority to call the chain canonical.

The pipeline produced a publishable draft on the first generation: first-person voice ("I keep seeing", "I think"), every factual claim grounded in `key_data_points` (BNY Mellon as transfer agent, Ethereum as canonical chain, $7B AUM), entities tagged, no hashtags, no engagement bait, no hallucinated personal action, media asset attached and ready.

## Remaining blockers

1. **Canva templates need to be built.** The pass-one templates (T1, T3, T5, T6) must be authored in Canva using the field schemas in `docs/canva_templates_pass_one_briefs.md`. Once built, `search-brand-templates` returns the IDs; seed them into `canva_templates` with the SQL block at the top of that doc. Until templates exist, `canva.render()` returns a `queued` asset with a clear note in the review queue. The Higgsfield path is now fully verified independently.

2. **Real reply-window worker firing on a published post** (plan verification item 5) — requires the X poster to actually publish a real post first. The `reply_window` module is implemented and unit-tested via `score_reply` and `is_voice_model_handle`; the live polling path is contingent on X API write credentials and the cron scheduler picking it up.

---

## What's deferred to a second pass

- **Review UI updates** (`apps/review-ui`) — pass-one ships the agent-side logic but does not modify the Next.js UI. The new fields needed in the UI (media asset preview per draft, regenerate-media button, Canva design URL link, predicted algo score with decomposition, missing-logo card with SVG upload, reply-window panel for published posts) are documented in `ALGO_REFIT_PLAN.md` "Review UI" and can be added in a follow-up.
- **Real-logo curation** — 7 monogram placeholders ship pre-bundled; replace with real issuer logos as Jackson surfaces each issuer via the review queue's missing-logo card. See `packages/graphics/logos/issuers/README.md`.
- **Pass-two Canva templates** (T2, T4, T7) — issuer comparison, time-series, weekly recap grid. Build after the pass-one autofill flow is proven on a real post.
- **Higgsfield REST production wire-up** — `_HiggsfieldRESTClient` is stubbed. Wire to Higgsfield Cloud once enterprise account is provisioned.
- **Canva Connect REST production wire-up** — `_CanvaRESTClient` is stubbed. Wire after the MCP-only iteration validates the autofill flow and Jackson upgrades to Canva Enterprise.

---

## Quick start (for the next session)

```bash
cd "DeFi X Poster"

# 1. Run the anti-AI tests
cd apps/workers-py && PYTHONPATH=src pytest tests/test_anti_ai.py -v

# 2. Apply the schema migration (Supabase or local Postgres)
psql "$DATABASE_URL" -f packages/db/migrations/0002_algo_refit.sql

# 3. Build the four Canva pass-one templates per docs/canva_templates_pass_one_briefs.md.
#    Then INSERT into canva_templates (slug, canva_template_id, ...).

# 4. Top up or upgrade the Higgsfield account.

# 5. Smoke-test the dispatcher end-to-end:
#    python -c "from workers.graphics import dispatch_for_draft; import json; \
#               brief = json.load(open('data/test_briefs/blackrock_buidl_deploy_t6.json'))['story']; \
#               print(dispatch_for_draft({'format': 'thread'}, brief))"

# 6. When everything's green, run the draft generator on a real story:
#    python -m workers.cli draft_open --limit 1
```
