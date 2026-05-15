# Issuer logo bundle

Curated SVG logos used by the Canva renderer (`apps/workers-py/src/workers/graphics/canva.py`) when populating brand templates.

## Filename convention

`{slug}.svg` — slug matches the X handle from `config/watchlist.json` (case-preserved). Examples:

- `maplefinance.svg` (issuer @maplefinance)
- `centrifuge.svg`
- `goldfinch_fi.svg`
- `ondofinance.svg`
- `openeden_X.svg`
- `BlackRock.svg`
- `Securitize.svg`

## Sourcing

Per the algo-refit Q&A, Jackson opted for the "preemptive scrape" path: when the agent first encounters a new issuer, it should fetch a clean SVG and add it here. The agent should NOT scrape preemptively for issuers it hasn't surfaced yet — that creates noise and brand-policy issues.

For each issuer:

1. Find the official press kit on the issuer's site.
2. Pull the `logo-mark` (square, not the wordmark).
3. Strip ambient padding so the mark fills ~90% of the viewBox.
4. Normalize colors if needed — most issuers ship a primary color; keep it.
5. Save as `{slug}.svg` with `viewBox="0 0 100 100"` and no embedded fonts (text → paths).

If a clean SVG isn't available, render a temporary monogram in this bundle using the placeholder generator at the bottom of this file and queue the issuer for a real-logo upload in the review UI's "missing logo" card.

## Pass-one bundle (algo-refit)

The 11 voice-model issuers + 8 TradFi entrants from `config/watchlist.json` are the priority bundle. Placeholders (monogram tiles in `#1F6FEB` on `#FAFAFA`) ship pre-bundled and should be replaced with real logos as Jackson curates them.

## Monogram placeholder generator

Run inside this directory to generate a `{slug}.svg` monogram tile when the real logo isn't yet available:

```bash
python3 - <<'PY'
slug = "maplefinance"
initials = slug[:2].upper()
svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
  <rect width="100" height="100" rx="12" fill="#FAFAFA"/>
  <text x="50" y="62" text-anchor="middle" font-family="Inter, sans-serif" font-weight="600" font-size="42" fill="#1F6FEB">{initials}</text>
</svg>'''
open(f"{slug}.svg", "w").write(svg)
PY
```
