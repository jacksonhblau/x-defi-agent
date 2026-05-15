# Higgsfield Integration Brief

Higgsfield is **one of two** media generators for the DeFi X Poster agent. It handles editorial and cinematic concept imagery — the "soul" image for a news-led or narrative-led post. The other path, Canva (see `docs/canva_integration.md`), handles data-driven asset and sector graphics with real issuer logos pulled from RWA.xyz.

Every draft must exit the draft generator with at least one ready media asset attached (Higgsfield, Canva, or both). The graphics dispatcher routes between the two based on the story brief's `graphic_kind` field — see the routing table in `docs/canva_integration.md §1`.

## 1. Access path

Two options, ordered by integration cost:

### Option A — Hosted MCP server (default, recommended)

- Endpoint: `https://mcp.higgsfield.ai/mcp`
- Auth: Higgsfield account session (browser-based first-run, then persisted).
- Surfaces 30+ image and video models as MCP tools — Seedance 2.0, GPT Image 2, Sora 2, Veo, Kling, WAN, Flux 2, Nano Banana Pro, Soul 2.0, Seedream 5.0 Lite, and others.
- Plug into the Claude Agent SDK runtime that already powers the worker — no key file to manage, billing flows through the existing Higgsfield plan.
- Asynchronous: jobs return a job_id; poll until ready.

### Option B — REST API (fallback, enterprise)

- Endpoint: enterprise-only on Higgsfield Cloud (`cloud.higgsfield.ai`). Third-party mirrors (Segmind, Unifically, Pixazo) wrap individual models with their own REST adapters.
- Use only if MCP latency or rate limits become a problem.

The agent will be wired against Option A first.

## 2. Model selection policy

Higgsfield only runs when the story brief's `graphic_kind` is `editorial` (or when a high-materiality post wants both an editorial hero AND a Canva data card). **Output style is infographic-first, NOT abstract metaphor** (see §3) — model selection prioritizes text rendering and diagram capability.

| Draft format             | Default model              | Aspect ratio | Notes |
|--------------------------|----------------------------|--------------|-------|
| Single post (POV-led)    | GPT Image 2 or Nano Banana Pro | 1:1      | Infographic, text-forward, real values rendered |
| Single post (hot take)   | GPT Image 2                | 1:1          | Same — labeled stat blocks, named entities visible |
| Thread (high materiality)| Kling 3.0 (6–12s)          | 16:9         | Short animated infographic — labels resolve in, bars draw, numbers count up |
| Reply / QT               | Nano Banana 2 (Flash) or Seedream 5.0 Lite | 1:1 | Faster model — reply latency matters |
| Long-form (>1500 chars)  | GPT Image 2 hero + Canva data card combo | 16:9 + 1:1 | Higgsfield for hero infographic, Canva for inside |
| Weekly recap             | Veo 3.1 (10–15s) hero + Canva T7 grid | 16:9 + 1:1 | Two-asset package |

Data-led posts with a Canva-shaped payload (asset-class snapshots, leaderboards, issuer comparisons, deploy cards) prefer Canva — see `docs/canva_integration.md §1`. Higgsfield handles the editorial/POV cases that don't fit a fixed template, but still produces a **purpose-built infographic specific to the post's content**, not abstract art.

Flux 2 is reserved for the rare case where the post is genuinely metaphorical (a held-view essay with no anchoring numbers and no entity relationships to diagram).

## 3. Visual identity (locked) — Infographic-first

Higgsfield output is a **tightly-curated visual infographic that reproduces the specific data, entities, and relationships discussed in the post** — not abstract concept art that loosely connects to the message. Think Bloomberg Terminal or a financial analyst's slide deck, not editorial illustration.

Every Higgsfield generation must:

1. **Render the actual data verbatim.** Every value from `key_data_points` (e.g., "$7B", "$1.7B over 14 months", "BNY Mellon Investment Servicing") appears as legible text in the image, with its label.
2. **Name the entities.** Every entity in the brief's `entities` array is rendered as a text label inside the image. Logos optional and only when bundled.
3. **Visualize the relationship.** The brief's `narrative_angle` drives the layout. Sovereignty/authority story → vertical three-tier hierarchy with labeled arrows. Consolidation story → ranked horizontal bars. Bifurcation → side-by-side comparison. Flow → directional diagram. New-deploy → hero card with metadata grid.
4. **Match the visual identity.** Light background `#FAFAFA`–`#FFFFFF`; primary blue `#1F6FEB` used sparingly for emphasis; near-black `#0F172A` for headlines; dark gray `#64748B` for labels. Inter (or similar geometric sans) only, tabular numbers, semibold for values, regular for labels.
5. **Include the watermark.** `@jacksonblau` bottom-left, `#64748B`, 10pt.
6. **Avoid stock finance clichés.** No piggy banks, no rising-arrow-with-dollar-sign, no robot handshakes, no generic crypto art, no abstract concept illustration where a structured infographic would serve.

The bar: a reader who only sees the image (without the post text) should still understand the substantive point. The image is the post in another modality, not decoration for the post.

## 4. Prompt construction

The Higgsfield prompt is built deterministically by `apps/workers-py/src/workers/graphics/higgsfield.py`. The shape, in order:

1. **Subject line** — derived from `narrative_angle`.
2. **Headline to render** — `brief.headline`, quoted, with a directive to place it at the top in semibold near-black.
3. **Labeled values block** — every `(label, value)` pair from `key_data_points` listed with explicit instruction to render verbatim and legibly inside the layout.
4. **Entity list** — names from `brief.entities` to be rendered as text labels.
5. **Layout directive** — chosen by `pick_layout(brief, format_hint)` from the brief's `narrative_angle` (see §3 item 3). Override with `brief.visual_layout` to be explicit.
6. **Visual identity suffix** — the locked color/typography/watermark/no-cliché block from §3.
7. **Aspect ratio.**

Example (the BlackRock $7B sovereignty story):

```
Editorial financial infographic about: regulated transfer agent treating an L1
as canonical state of ownership. Headline to render at the top, semibold, near-black:
"BlackRock files $7B onchain MMF with BNY Mellon as transfer agent". Render these
exact labeled values verbatim, legibly, inside the layout: "$7B" labeled "Filed AUM";
"BNY Mellon Investment Servicing" labeled "Transfer agent"; "Ethereum" labeled
"Canonical chain"; "$1.7B over 14 months" labeled "BUIDL comparable"; "$31B" labeled
"Tokenized treasury TVL". Named entities to include, rendered as text labels: BlackRock,
BNYMellon, Securitize. Layout: Vertical three-tier hierarchy with labeled connecting
arrows showing the operational relationship between entities. … [visual identity suffix]
… 1:1 aspect ratio.
```

`pick_layout` returns one of:

| Trigger in `narrative_angle` | Layout |
|---|---|
| transfer agent / custodian / canonical / authority / sovereign / registrar | Vertical three-tier hierarchy with labeled arrows |
| consolidat / concentrat / absorb / leading / top issuer | Horizontal ranked-bar layout |
| fragment / bifurcat / split / vs / twin / native | Side-by-side two-column comparison |
| flow / inflow / rotation / migrat | Left-to-right directional flow diagram |
| deploy / launch / filed / filing / new fund / new product | Hero announcement card with metadata grid |
| (default, ≥ 4 data points) | Hero figure + 2×2 supporting grid |
| (default, 2–3 data points) | Stacked stat card |
| (default, 1 data point) | Single centered hero stat |

For video formats, `build_video_prompt` returns the same infographic spec plus motion: labels resolve in with a subtle fade, numbers count up, bars/arrows draw on with a single sweep; the end frame matches the still infographic and holds for 1–2s. Duration: 8s for threads, 12s for recap heroes.

## 5. Workflow inside the agent

```
draft_generator
      │
      ├─→ produces 3 single variants + thread + reply candidates
      │
      ▼
graphics_dispatcher (NEW)
      │
      ├─→ for each accepted variant:
      │     1. build_image_prompt(story_brief, format)
      │     2. higgsfield_mcp.generate_image(prompt, model, aspect)
      │     3. poll until ready
      │     4. post-process: apply watermark, store in Supabase Storage
      │     5. write row to media_assets table linked to draft
      │
      ▼
review_queue
      │
      └─→ shows draft + media asset side by side
```

Failure modes:

- **Higgsfield job fails / times out (>90s):** retry once with a slightly simpler prompt. If second attempt also fails, surface the draft into the review queue with a `media_pending` flag and a "regenerate media" button. Never let a missing media asset block a high-materiality post from review — the human can always upload manually.
- **Content policy refusal:** rare given the subject matter, but fall back to a generic "chart-on-light-background" template render.

## 6. Cost envelope

Higgsfield credits per generation depend on model and resolution. Rough estimates from public pricing pages:

| Asset                      | Credits/call | Approx USD |
|----------------------------|--------------|------------|
| Flux 2 image 1:1           | 2–4          | $0.02–0.04 |
| GPT Image 2 image          | 6–10         | $0.06–0.10 |
| Veo 3.1 6s video           | 30–50        | $0.30–0.50 |
| Kling 3.0 8s video         | 20–40        | $0.20–0.40 |
| Sora 2 12s video           | 60–100       | $0.60–1.00 |

At 5 posts/day with 4 of those being images and 1 being a thread with a short video:
`(4 × $0.05) + (1 × $0.40) = $0.60/day ≈ $18/month` baseline; budget $40–60/month with regenerations and weekly recap videos.

Add `HIGGSFIELD_CREDIT_MONTHLY_CAP` to env config; refuse to queue new generations if the running monthly spend exceeds the cap.

## 7. Required schema additions

```sql
CREATE TABLE media_assets (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  draft_id     UUID NOT NULL REFERENCES drafts(id) ON DELETE CASCADE,
  kind         TEXT NOT NULL CHECK (kind IN ('image','video')),
  model        TEXT NOT NULL,
  prompt       TEXT NOT NULL,
  higgsfield_job_id TEXT,
  storage_url  TEXT,             -- final Supabase Storage URL after watermark
  status       TEXT NOT NULL CHECK (status IN ('queued','running','ready','failed')),
  credits_used INTEGER,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  ready_at     TIMESTAMPTZ
);

CREATE INDEX idx_media_assets_draft ON media_assets(draft_id);
CREATE INDEX idx_media_assets_status ON media_assets(status);
```

## 8. Env additions

```
# Higgsfield
HIGGSFIELD_MCP_URL=https://mcp.higgsfield.ai/mcp
HIGGSFIELD_DEFAULT_IMAGE_MODEL=flux-2
HIGGSFIELD_DEFAULT_VIDEO_MODEL=kling-3
HIGGSFIELD_CREDIT_MONTHLY_CAP=2000
```
