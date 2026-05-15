# Canva Integration Brief

Canva is the agent's second media path, sitting alongside Higgsfield. Higgsfield handles editorial and cinematic imagery; Canva handles data-driven asset and sector graphics rendered into pre-designed brand templates with real issuer logos pulled from RWA.xyz.

## 1. The split — which generator runs when

| Draft type | Default media generator | Why |
|---|---|---|
| News-driven hot take, narrative-led single | Higgsfield image | Editorial concept art, visual metaphor |
| Reply or QT | Higgsfield image (fast model) | Lightweight, atmospheric |
| Thread, materiality ≥ 80 | Higgsfield short video | Hero motion piece |
| Asset-class snapshot (e.g., tokenized private credit adoption) | **Canva template** | Logos + bars + named issuers |
| Issuer comparison (BUIDL vs FOBXX vs USDY) | **Canva template** | Side-by-side data card |
| Sector leaderboard / top-N | **Canva template** | Ranked logo table |
| Weekly recap | **Canva template** for the data spread + Higgsfield hero | Two assets, one post |
| New-deploy announcement card | **Canva template** | Logo + AUM at launch + structure |
| Single-asset deep-dive | **Canva template** | Logo-anchored stat card |

The graphics dispatcher decides based on `story_brief.format_recommendation` and a new `graphic_kind` field on the story brief: one of `editorial`, `data_card`, `comparison`, `leaderboard`, `time_series`, `deploy_card`, `recap_grid`.

A single post can carry up to 4 images on X. The dispatcher MAY produce a Higgsfield hero + a Canva data card as a pair for high-materiality posts.

## 2. Access path

### Canva Connect API (REST, official)

- Docs: https://www.canva.dev/docs/connect/
- Endpoints used:
  - `GET /v1/brand-templates` — list available templates
  - `GET /v1/brand-templates/{id}/dataset` — read the autofill fields a template exposes (returns field names + types: `text`, `image`, `chart_data`)
  - `POST /v1/autofills` — create an asynchronous autofill job with the data payload
  - `GET /v1/autofills/{job_id}` — poll until job completes
  - `POST /v1/exports` — export the finished design to PNG/JPG/PDF
  - `POST /v1/asset-uploads` — upload an image (e.g., a logo) and get an `asset_id` for use in the autofill payload
- Auth: OAuth 2.0 with PKCE. Requires the agent to be a member of a Canva Enterprise organization (Canva Connect's hard requirement, as of late 2025).
- Async: autofill jobs are polled, typically ready in 5–30s.

### Canva MCP server (already available in this runtime)

The MCP toolkit `mcp__96182097-…` exposes the same surface as Connect, plus interactive editing:
- `search-brand-templates`
- `get-brand-template-dataset`
- `create-design-from-brand-template`
- `upload-asset-from-url`
- `export-design`
- `perform-editing-operations` (transactional edits — `start-editing-transaction`, mutations, `commit-editing-transaction`)

For agent-driven generation, the autofill path is enough. The editing-transaction path is reserved for cases where the dispatcher needs to nudge text after autofill (e.g., truncate a long issuer name).

Strategy: when running inside Cowork/Claude Code, prefer the MCP server (zero key management, the user is already authenticated). For the production VPS deploy, wire Canva Connect REST directly using a service account.

## 3. Template library — the seven starter templates

These are the brand templates Jackson needs to create once in Canva, then the agent autofills them on demand. All seven inherit the visual identity in §4.

### T1 — Asset-class adoption snapshot

Use: "Tokenized private credit, who's leading adoption right now"

Fields:
- `title` (text) — "Tokenized Private Credit · May 2026"
- `subtitle` (text) — "By issuer, last 30 days net flow"
- `issuer_1_logo` … `issuer_8_logo` (image) — up to 8 issuer logos
- `issuer_1_name` … `issuer_8_name` (text)
- `issuer_1_value` … `issuer_8_value` (text) — e.g., "$840M", "+$120M"
- `issuer_1_bar_pct` … `issuer_8_bar_pct` (text) — drives bar width via chart_data, 0–100
- `source_line` (text) — "Source: RWA.xyz, DeFiLlama · @jacksonblau"
- `as_of_date` (text)

Layout: ranked horizontal bar chart, logos left of each bar, values right, generous whitespace, light mode.

### T2 — Issuer comparison

Use: "BUIDL vs FOBXX vs USDY"

Fields:
- `title`, `subtitle`, `as_of_date`, `source_line`
- `slot_A_logo`, `slot_A_name`, `slot_A_aum`, `slot_A_chain`, `slot_A_transfer_agent`, `slot_A_structure`, `slot_A_apy`
- `slot_B_…` and `slot_C_…` mirroring slot A

Layout: 3-column comparison card, identical rows, logo top of each column. Visual hierarchy emphasizes the column where the metric is best (handled by an `accent_slot` text field the autofill writes: "A" / "B" / "C").

### T3 — Sector leaderboard

Use: "Top 10 tokenized treasury issuers by AUM, today"

Fields:
- `title`, `subtitle`, `as_of_date`, `source_line`
- `rank_1` … `rank_10` (text — usually just "1" through "10")
- `rank_1_logo` … `rank_10_logo` (image)
- `rank_1_name` … `rank_10_name` (text)
- `rank_1_aum` … `rank_10_aum` (text)
- `rank_1_delta` … `rank_10_delta` (text — "+5.29%" green / "-1.2%" red)

Layout: 10-row table, alternating row tint, ranks numerically prefixed, delta colored.

### T4 — Time series

Use: "Tokenized treasury TVL, last 90 days, by issuer"

Fields:
- `title`, `subtitle`, `as_of_date`, `source_line`
- `chart_data` (chart_data) — Canva's tabular chart binding; columns = issuers, rows = dates
- `legend_1_name` … `legend_5_name` (text)
- `legend_1_logo` … `legend_5_logo` (image) — small logo next to each legend entry

Layout: stacked-area or line chart depending on data shape. The agent picks via a `chart_type` text field.

### T5 — Single-asset deep-dive

Use: "Everything you need to know about BUIDL on one card"

Fields:
- `asset_logo`, `asset_name`, `issuer_name`, `issuer_logo`
- `aum`, `aum_delta_30d`, `apy`, `chain`, `transfer_agent`, `custodian`, `structure_type`
- `holders_count`, `first_deploy_date`
- `description_line_1`, `description_line_2` (text — 1-line each, short)
- `source_line`, `as_of_date`

Layout: hero card, big logo top-left, key metrics in a grid, two-line description bottom.

### T6 — New-deploy announcement

Use: "BlackRock just filed for a $7B onchain MMF"

Fields:
- `headline` (text — short, ≤ 80 chars)
- `issuer_logo`, `issuer_name`
- `chain_logo`, `chain_name`
- `aum_at_launch` (text)
- `structure_type` (text)
- `transfer_agent` (text — optional)
- `source_line`, `as_of_date`

Layout: banner-style, large logo center-left, headline right, key fields below.

### T7 — Weekly recap grid

Use: "RWA flows recap, week of May 11"

Fields:
- `title`, `subtitle`, `as_of_date`, `source_line`
- `tile_1_kind` … `tile_6_kind` (text — "treasury", "private_credit", "stablecoin", etc.)
- `tile_1_value` … `tile_6_value` (text)
- `tile_1_delta` … `tile_6_delta` (text)
- `tile_1_icon` … `tile_6_icon` (image — sector glyph, not issuer logo)
- `headline_callout` (text — one-line punchline for the week)

Layout: 2×3 grid of tiles, callout banner across the top.

## 4. Visual identity (mandatory across all seven templates)

Inherits from the chart aesthetic locked in `BUILD_PLAN.md §4.5`, sharpened by the canvas-design philosophy invoked during planning:

**Movement: Quiet Cartography.**

The templates render financial data the way a cartographer renders terrain — every element earns its place, the eye is led by negative space, and the typography whispers rather than shouts. Light backgrounds (`#FAFAFA` to `#FFFFFF`) host a single primary accent (`#1F6FEB`) and a restrained secondary palette (`#0F172A` near-black for type, `#64748B` for labels, `#10B981` green delta, `#EF4444` red delta). Logos are the loudest objects on the page — set in generous breathing room, never crowded, never decorated.

Type: Inter throughout (Regular for body, Semibold for values, weight-500 for labels). Numbers are tabular. No serif accents. No drop shadows. No gradients. No 3D anywhere.

Density: ample. Every template should look like the same hand made it, deliberate and unhurried, the product of careful calibration rather than a dashboard print-out. Master craftsmanship is non-negotiable — these will sit alongside posts from RWA.xyz, DeFiLlama, and Bloomberg-style accounts, and they need to read as built, not generated.

Watermark: `@jacksonblau` in `#64748B`, bottom-left, 10pt, never larger.

## 5. Logo sourcing

Logos come from two paths, in priority order:

1. **Local logo bundle** at `packages/graphics/logos/issuers/{slug}.svg`. The agent maintains a curated set of clean SVGs for the issuers and protocols on the watchlist (~50 logos). Local is preferred because the agent controls trim, padding, and color treatment.
2. **RWA.xyz API** — the agent queries the issuer endpoint for the asset's metadata; when a `logo_url` field is present, the dispatcher uploads the URL to Canva via `POST /v1/asset-uploads` (or `upload-asset-from-url` via MCP) and uses the returned `asset_id` in the autofill payload.
3. **Fallback** — when neither path yields a logo (a new issuer the agent has never seen), the template substitutes a typographic "monogram tile" with the issuer's first two initials in the brand accent color. The dispatcher writes the issuer name to `issuer_X_name` and a sentinel `MONOGRAM` value to `issuer_X_logo`; the template's autofill rules render the monogram tile in place of the image.

Maintain the local bundle in version control. When the agent encounters a new issuer with non-trivial materiality, surface a "missing logo" card in the review UI so Jackson can drop in a clean SVG before the next time that issuer shows up.

## 6. RWA.xyz data binding

The story builder is extended to populate a `canva_payload` block on the story brief when `graphic_kind` is anything other than `editorial`. The payload is template-specific. For T1 (asset-class adoption snapshot), the payload looks like:

```json
{
  "template_id": "rwa_t1_adoption_snapshot",
  "fields": {
    "title": "Tokenized Private Credit · May 2026",
    "subtitle": "By issuer, 30-day net flow",
    "as_of_date": "2026-05-15",
    "source_line": "Source: RWA.xyz · @jacksonblau",
    "issuer_1_name": "Maple",
    "issuer_1_value": "$840M",
    "issuer_1_bar_pct": "100",
    "issuer_1_logo": { "kind": "local", "slug": "maplefinance" },
    "issuer_2_name": "Centrifuge",
    "issuer_2_value": "$520M",
    "issuer_2_bar_pct": "62",
    "issuer_2_logo": { "kind": "local", "slug": "centrifuge" }
  }
}
```

A new `apps/workers-py/src/workers/graphics/canva.py` module:

```python
def render(brief: StoryBrief) -> MediaAsset:
    payload = brief.canva_payload
    template = payload["template_id"]
    fields = resolve_logos(payload["fields"])     # uploads any non-local logos, returns asset_ids
    job = canva.create_autofill_job(template, fields)
    design = canva.wait_for_job(job.id, timeout_s=60)
    png = canva.export_png(design.id)
    asset = supabase.upload(png, watermarked=True)
    return MediaAsset(kind="image", source="canva", template=template, ...)
```

`resolve_logos` walks each `issuer_X_logo` field:
- `kind=local` → reads `packages/graphics/logos/issuers/{slug}.svg`, uploads to Canva, caches the `asset_id` (Canva asset IDs are stable across the org, so we only upload once per logo per year).
- `kind=url` → uploads the URL directly via `upload-asset-from-url`.
- `kind=monogram` → writes the sentinel; the template handles it.

Cache the Canva asset_id for each logo in a new `canva_assets` table keyed by logo SHA so the agent doesn't re-upload on every render.

## 7. Schema additions

```sql
CREATE TABLE canva_templates (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  slug         TEXT UNIQUE NOT NULL,         -- e.g., 'rwa_t1_adoption_snapshot'
  canva_template_id TEXT NOT NULL,            -- the Canva-side brand template ID
  description  TEXT,
  field_schema JSONB NOT NULL,                -- canonical field names + types
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE canva_assets (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  logo_sha256    TEXT UNIQUE NOT NULL,
  canva_asset_id TEXT NOT NULL,
  source_path    TEXT,                        -- 'logos/issuers/maplefinance.svg' or URL
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Extend media_assets to support canva-source assets
ALTER TABLE media_assets
  ADD COLUMN source TEXT NOT NULL DEFAULT 'higgsfield'
    CHECK (source IN ('higgsfield','canva','custom')),
  ADD COLUMN canva_template_slug TEXT,
  ADD COLUMN canva_design_id TEXT;
```

## 8. Env additions

```
# Canva Connect (production / VPS)
CANVA_CLIENT_ID=
CANVA_CLIENT_SECRET=
CANVA_REFRESH_TOKEN=
CANVA_BRAND_ORG_ID=

# Canva MCP (dev / Cowork / Claude Code)
# No env needed — auth is handled by the MCP server interactively on first use.
```

## 9. Test fixtures

Add two synthetic stories under `data/test_briefs/` for the implementing session to exercise the templates end-to-end:

- `private_credit_adoption_t1.json` — exercises T1 with five real private-credit issuers from the watchlist.
- `buidl_fobxx_usdy_t2.json` — exercises T2 with three tokenized treasury products.

Each fixture provides a complete `canva_payload` so the renderer can run without depending on a live RWA.xyz call.
