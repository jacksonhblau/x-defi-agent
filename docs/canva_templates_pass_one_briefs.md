# Canva pass-one template briefs (T1, T3, T5, T6)

Build these four templates inside Canva. Each one must inherit the visual identity locked in `docs/canva_integration.md §4` ("Quiet Cartography") — light backgrounds, single primary `#1F6FEB` accent, Inter typography (tabular numbers), `@jacksonblau` watermark bottom-left at 10pt.

Once each template is built, `search-brand-templates` returns its `id`. Seed the `canva_templates` table:

```sql
INSERT INTO canva_templates (slug, canva_template_id, description, field_schema) VALUES
  ('rwa_t1_adoption_snapshot', '<canva id from search-brand-templates>', 'Asset-class adoption snapshot', '{}'::jsonb),
  ('rwa_t3_sector_leaderboard',  '<canva id>', 'Sector leaderboard',  '{}'::jsonb),
  ('rwa_t5_asset_deep_dive',     '<canva id>', 'Single-asset deep-dive', '{}'::jsonb),
  ('rwa_t6_deploy_card',         '<canva id>', 'New-deploy announcement', '{}'::jsonb);
```

The agent reads template IDs from this table at render time. Missing templates are surfaced as a blocker in the review queue.

---

## T1 — Asset-class adoption snapshot

**Use:** "Tokenized private credit, who's leading adoption right now."

**Aspect:** 1:1 (1080×1080) or 16:9 (1920×1080). 1:1 preferred for in-feed.

**Field schema (autofill names must match exactly):**

| Field | Type | Example | Notes |
|---|---|---|---|
| `title` | text | "Tokenized Private Credit · May 2026" | Top of card |
| `subtitle` | text | "By issuer, 30-day net flow" | Below title |
| `as_of_date` | text | "May 15, 2026" | Bottom-right |
| `source_line` | text | "Source: RWA.xyz · @jacksonblau" | Footer |
| `issuer_1_logo` … `issuer_8_logo` | image | (Canva asset_id) | Left of each bar |
| `issuer_1_name` … `issuer_8_name` | text | "Maple" | To the right of the logo |
| `issuer_1_value` … `issuer_8_value` | text | "$840M" | Right of the bar, semibold |
| `issuer_1_bar_pct` … `issuer_8_bar_pct` | text | "100" | 0–100, drives bar width |

**Layout:** ranked horizontal bar chart. Up to 8 rows. Logo (square, 48×48px) left of each bar. Bar fills the middle 60% of the card width. Value right-aligned at the end of each bar. Generous row spacing (≥ 20px). The bar fill color is `#1F6FEB` at 100% opacity; bars below 50% fill use `#1F6FEB` at 70% opacity. Empty rows (issuers 6–8 unused) collapse cleanly.

**Test fixture:** `data/test_briefs/private_credit_adoption_t1.json` — 5 issuers (Maple, Centrifuge, Goldfinch, Ondo, OpenEden) with logos resolved from the local bundle.

---

## T3 — Sector leaderboard

**Use:** "Top 10 tokenized treasury issuers by AUM, today."

**Aspect:** 1:1 (1080×1080) or 16:9 (1920×1080).

**Field schema:**

| Field | Type | Example | Notes |
|---|---|---|---|
| `title` | text | "Top 10 Tokenized Treasury Issuers" | |
| `subtitle` | text | "By AUM, May 2026" | |
| `as_of_date` | text | "May 15, 2026" | |
| `source_line` | text | "Source: RWA.xyz · @jacksonblau" | |
| `rank_1` … `rank_10` | text | "1" through "10" | Usually static |
| `rank_1_logo` … `rank_10_logo` | image | (asset_id) | Small logo per row |
| `rank_1_name` … `rank_10_name` | text | "BlackRock BUIDL" | |
| `rank_1_aum` … `rank_10_aum` | text | "$3.0B" | Right-aligned |
| `rank_1_delta` … `rank_10_delta` | text | "+5.29%" or "-1.2%" | Color is conditional |

**Layout:** 10-row table. Alternating row tint (`#FFFFFF` and `#F8FAFC`). Rank numerals at left, small logo (32×32px), name, AUM right-aligned, delta colored: positive delta `#10B981`, negative delta `#EF4444`. The conditional coloring is set up as a Canva style rule on the delta text fields ("if starts with -, color red; else green").

---

## T5 — Single-asset deep-dive

**Use:** "Everything you need to know about BUIDL on one card."

**Aspect:** 1:1 (1080×1080).

**Field schema:**

| Field | Type | Example |
|---|---|---|
| `asset_logo` | image | (asset_id) |
| `asset_name` | text | "BUIDL" |
| `issuer_name` | text | "BlackRock" |
| `issuer_logo` | image | (asset_id) |
| `aum` | text | "$3.0B" |
| `aum_delta_30d` | text | "+12.4%" |
| `apy` | text | "4.85%" |
| `chain` | text | "Ethereum (multi-chain available)" |
| `transfer_agent` | text | "BNY Mellon Investment Servicing" |
| `custodian` | text | "BNY Mellon" |
| `structure_type` | text | "Tokenized MMF" |
| `holders_count` | text | "82" |
| `first_deploy_date` | text | "Mar 2024" |
| `description_line_1` | text | "Regulated transfer agent treats the chain as canonical state." |
| `description_line_2` | text | "Largest tokenized MMF, now multi-chain." |
| `source_line` | text | "Source: RWA.xyz · @jacksonblau" |
| `as_of_date` | text | "May 15, 2026" |

**Layout:** hero card. Big asset logo top-left (~25% of the card height). Asset name + issuer name to the right. Two-column metric grid below: AUM, 30-day delta, APY, chain | transfer agent, custodian, structure type, holders. Two-line description across the bottom. Issuer logo small (24×24px) inline near the issuer name.

---

## T6 — New-deploy announcement

**Use:** "BlackRock just filed for a $7B onchain MMF."

**Aspect:** 16:9 (1920×1080).

**Field schema:**

| Field | Type | Example |
|---|---|---|
| `headline` | text | "BlackRock files $7B onchain MMF" |
| `issuer_logo` | image | (asset_id) |
| `issuer_name` | text | "BlackRock" |
| `chain_logo` | image | (asset_id) |
| `chain_name` | text | "Ethereum" |
| `aum_at_launch` | text | "$7B filed" |
| `structure_type` | text | "Tokenized MMF" |
| `transfer_agent` | text | "BNY Mellon Investment Servicing" |
| `source_line` | text | "Source: SEC filing · @jacksonblau" |
| `as_of_date` | text | "May 15, 2026" |

**Layout:** banner-style. Large issuer logo center-left (~30% of card height). Headline right, semibold, weight 600. Key fields in a row below the headline: AUM at launch | structure | transfer agent. Chain logo small (24×24px) inline with chain name. Generous breathing room above and below the headline.

---

## Visual identity reminders (apply to all four)

- Light backgrounds (`#FAFAFA` to `#FFFFFF`).
- Single primary accent `#1F6FEB`.
- Type: Inter — Regular for body, Semibold for values, weight 500 for labels.
- Numbers tabular.
- No serifs. No drop shadows. No gradients. No 3D.
- Watermark `@jacksonblau` in `#64748B`, bottom-left, 10pt.
- Logos are the loudest objects on the card. Generous breathing room around them.
