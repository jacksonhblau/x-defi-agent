# review-ui

Next.js app for reviewing and approving drafts before they're posted to X.

**Status:** stub. Will be implemented after the workers and poster are functional.

## Future structure

```
app/
  layout.tsx
  page.tsx              # draft inbox
  drafts/[id]/page.tsx  # single draft detail
  api/
    drafts/route.ts     # list + update
    approve/route.ts    # mark approved, schedule, or reject

components/
  draft-card.tsx
  variant-picker.tsx
  graphic-preview.tsx
```

Auth is a single password (`REVIEW_UI_PASSWORD` from env) gated via a JWT cookie signed with `REVIEW_UI_JWT_SECRET`. Single-user; no need for OAuth.
