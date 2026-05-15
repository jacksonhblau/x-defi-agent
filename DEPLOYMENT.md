# Deployment guide

The DeFi X Posting Agent ships as three coordinated services. Each goes to the host that fits its runtime — they don't share a deployment, they share **Supabase**.

```
                ┌──────────────────────┐
                │   Vercel             │
                │   apps/review-ui     │ ── you approve drafts here
                │   (Next.js 16)       │
                └──────────┬───────────┘
                           │  read/write
                           ▼
                ┌──────────────────────┐
                │   Supabase           │ ── shared source of truth
                │   Postgres + Storage │    (drafts, signals, media_assets,
                └──────────┬───────────┘     canva_templates, reply_followups)
                           │  read/write
                           ▼
                ┌──────────────────────┐
                │   Fly.io             │
                │   apps/workers-py    │ ── ingest, score, draft, post,
                │   (Python 3.11)      │    reply-window poll
                └──────────────────────┘
                       │             │
                       ▼             ▼
              Anthropic API   Higgsfield / Canva / X API / RWA.xyz / Alchemy
```

**Why this split:**

- The review UI is a stock Next.js app — Vercel is the right host. Free hobby tier covers the load.
- The Python workers use long-lived connections (Telegram MTProto via Telethon), persistent state (croniter scheduler, Telethon session file), and run subprocess jobs up to 600s. Vercel Functions cap at 10–60s and don't keep state between invocations. The workers need a Docker host — Fly.io is the lightest one that fits, and `apps/workers-py/Dockerfile` is already written for it.
- Supabase is the integration plane. Neither the UI nor the workers call each other directly; both read/write the same Postgres tables. This keeps deploys independent and rolls back cleanly.

---

## Pre-flight (one-time)

### 1. Rotate the dev secrets that have ever been visible locally

The `NEXTAUTH_SECRET`, `SUPABASE_SERVICE_ROLE_KEY`, and `REVIEW_UI_PASSWORD` in `apps/review-ui/.env.local` were generated for local dev and shouldn't be reused in production.

```bash
# New NextAuth secret (production)
openssl rand -base64 32

# New review-UI password (production)
openssl rand -base64 24
```

The Supabase service role key rotates from the Supabase dashboard → Settings → API → "Generate new JWT secret" (this rotates BOTH the anon and service-role keys; you'll need to update both env stores after).

### 2. Apply the algo-refit schema migration

Run against your production Supabase Postgres (the local migrations live in `packages/db/migrations/`):

```bash
psql "$DATABASE_URL" -f packages/db/migrations/0001_initial.sql
psql "$DATABASE_URL" -f packages/db/migrations/0002_algo_refit.sql
```

This adds: `media_assets`, `canva_templates`, `canva_assets`, `reply_followup_candidates`, and the four algo-refit columns on `drafts` (`first_person_check_passed`, `personal_facts_check_passed`, `predicted_algo_score`, `ready_for_review`).

### 3. Confirm `.gitignore` covers your secrets

Already done — both root `.gitignore` and `apps/review-ui/.gitignore` exclude `.env`, `.env.local`, and `.env.*.local`. Verify before pushing:

```bash
git ls-files apps/review-ui/.env.local   # should print nothing
git ls-files .env                        # should print nothing
```

---

## Part 1 — Vercel (apps/review-ui)

### Project setup

1. Push the repo to GitHub if it isn't there:

   ```bash
   git remote -v   # check if origin exists
   # If you've been using PUSH_TO_GITHUB.sh, run it; otherwise:
   git remote add origin git@github.com:jacksonhblau/defi-x-poster.git
   git push -u origin main
   ```

2. In the Vercel dashboard:
   - **New Project** → Import Git Repository → pick this repo.
   - **Root Directory:** `apps/review-ui` (critical — this is a monorepo).
   - **Framework Preset:** Next.js (auto-detected).
   - **Build Command:** `next build` (the bundled `apps/review-ui/vercel.json` sets this).
   - **Install Command:** `npm install`.
   - **Output Directory:** `.next` (default).

3. Add Environment Variables (Production scope unless noted):

   | Key | Value | Notes |
   |---|---|---|
   | `NEXTAUTH_SECRET` | `<openssl rand -base64 32>` | Fresh — do NOT reuse the dev secret. |
   | `NEXTAUTH_URL` | `https://your-domain.vercel.app` | Or your custom domain. Must match the deployed URL. |
   | `NEXT_PUBLIC_SUPABASE_URL` | `https://hwqsfgfwdcbopybkadha.supabase.co` | From Supabase → Settings → API. |
   | `NEXT_PUBLIC_SUPABASE_ANON_KEY` | `<anon key>` | Public — fine to expose, but rotate after the dev value. |
   | `SUPABASE_SERVICE_ROLE_KEY` | `<service role key>` | Server-only. Never prefix with `NEXT_PUBLIC_`. |
   | `REVIEW_UI_PASSWORD` | `<new strong value>` | This is the login password (single-user gate). |

4. Click **Deploy**. The build is ~60–90s.

5. After the first successful deploy, set `NEXTAUTH_URL` to the production URL Vercel assigned, then redeploy (NextAuth refuses to issue tokens when the URL mismatches the configured one).

### Custom domain (optional)

Vercel Dashboard → your project → Settings → Domains → Add → point your DNS at Vercel. Then update `NEXTAUTH_URL` to match and redeploy.

### What the build will tolerate

`next.config.js` has `typescript.ignoreBuildErrors: true` — intentional, so a type-only error doesn't block a deploy. Remove this once the codebase is fully type-clean. ESLint is also skipped in Next 16; set `NEXT_DISABLE_ESLINT=1` in Vercel env if you re-enable it and want to skip during builds.

---

## Part 2 — Fly.io (apps/workers-py)

The existing `fly.toml` at the project root is already configured:

- App name: `x-defi-agent`
- Region: `iad`
- Process: `watch` runs `python -m workers.cli watch --interval 60`
- Volume: `agent_data` mounted at `/app/data` (1 GB)
- Release command on deploy: `python -m workers.cli migrate` (runs schema migrations automatically)
- `TELEGRAM_SESSION_PATH=/app/data/telegram.session` (set in `[env]`)

### One-time setup

```bash
# 1. Install flyctl: https://fly.io/docs/hands-on/install-flyctl/
fly auth login

# 2. Create the app + volume (only if you haven't run `fly launch` before;
# the fly.toml already exists so don't run `fly launch` again — it would
# overwrite the config).
fly apps create x-defi-agent
fly volumes create agent_data --region iad --size 1 --app x-defi-agent

# 3. Push all secrets. Easiest path: build your prod .env, then
fly secrets set --app x-defi-agent $(grep -v '^#' apps/workers-py/.env | xargs)

# Or set them one at a time, e.g.:
fly secrets set --app x-defi-agent ANTHROPIC_API_KEY=sk-ant-...
fly secrets set --app x-defi-agent DATABASE_URL='postgresql://...'
fly secrets set --app x-defi-agent HIGGSFIELD_API_KEY=...

# 4. Deploy. The release_command in fly.toml runs `workers.cli migrate`
# automatically, so Supabase gets the schema before the worker process starts.
fly deploy --app x-defi-agent
```

### First-run Telegram authentication

The Telethon client (RWAxyzNewswire poller) needs an interactive login the first time — log in with the phone in `TELEGRAM_PHONE` and enter the SMS code. The session persists to `/app/data/telegram.session` on the `agent_data` volume:

```bash
fly ssh console --app x-defi-agent
python -m workers.cli ingest_telegram_login   # follow the prompts
exit
```

### Scaling

`shared-cpu-1x` / 512MB is fine for the 3-posts/day cadence. If anti-AI regeneration loops or graphics polling push CPU, bump it:

```bash
fly scale vm shared-cpu-2x --memory 1024 --app x-defi-agent
```

---

## Part 3 — Higgsfield + Canva

### Higgsfield (already on starter tier)

Production runs the REST path; the Cowork-MCP path doesn't deploy. Set on Fly.io:

```bash
fly secrets set --app x-defi-agent HIGGSFIELD_API_KEY=<your_starter_tier_key>
fly secrets set --app x-defi-agent HIGGSFIELD_DEFAULT_IMAGE_MODEL=gpt_image_2
fly secrets set --app x-defi-agent HIGGSFIELD_DEFAULT_VIDEO_MODEL=kling-3
fly secrets set --app x-defi-agent HIGGSFIELD_CREDIT_MONTHLY_CAP=2000
```

The `HiggsfieldRESTClient` in `apps/workers-py/src/workers/graphics/higgsfield.py` currently raises `NotImplementedError` — the prod path is stubbed pending the Higgsfield enterprise/REST account being provisioned. Until then, the dispatcher returns a `queued` asset and the review UI shows it as media-pending. Wire `_HiggsfieldRESTClient.generate_image`/`poll` to the actual REST API when you turn it on.

### Canva (blocked on template authoring)

Build T1, T3, T5, T6 in Canva using `docs/canva_templates_pass_one_briefs.md`. After they exist, seed the IDs into Supabase:

```sql
INSERT INTO canva_templates (slug, canva_template_id, description, field_schema)
VALUES
  ('rwa_t1_adoption_snapshot', '<canva_id>', 'Asset-class adoption snapshot', '{}'::jsonb),
  ('rwa_t3_sector_leaderboard',  '<canva_id>', 'Sector leaderboard',  '{}'::jsonb),
  ('rwa_t5_asset_deep_dive',     '<canva_id>', 'Single-asset deep-dive', '{}'::jsonb),
  ('rwa_t6_deploy_card',         '<canva_id>', 'New-deploy announcement', '{}'::jsonb);
```

For production, decide:

- **Stay on the MCP-only dev path** (your algo-refit Q&A choice): the dispatcher returns `queued` for Canva assets in prod and someone (you, in a Cowork session) runs the MCP flow manually before approval. Sustainable for low cadence.
- **Upgrade to Canva Enterprise** ($30/seat/mo) to enable the REST path. Set `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, `CANVA_REFRESH_TOKEN`, `CANVA_BRAND_ORG_ID` on Fly; wire `_CanvaRESTClient` methods to the Connect endpoints.

---

## Part 4 — Verification

After both services are deployed:

1. **Vercel:** visit `https://your-domain.vercel.app/login`, log in with `REVIEW_UI_PASSWORD`, confirm the Drafts page loads. Empty state is fine — the workers populate it.

2. **Fly:** check the scheduler is running.

   ```bash
   fly logs --app x-defi-agent
   # Look for "watch: scheduler tick" messages.
   ```

3. **End-to-end smoke test:** trigger a draft generation manually.

   ```bash
   fly ssh console --app x-defi-agent
   python -m workers.cli generate_draft --story-id <some_story_uuid>
   exit
   ```

   Then refresh the Vercel UI's Drafts page — the new draft, its media_asset, anti-AI flags, and predicted score should be visible.

4. **Reply-window worker:** publish one real post via the X poster, then watch `reply_followup_candidates` populate after 5/15/30 minutes.

   ```bash
   fly ssh console --app x-defi-agent
   psql "$DATABASE_URL" -c "SELECT * FROM reply_followup_candidates ORDER BY created_at DESC LIMIT 10;"
   ```

---

## Secrets checklist (full list)

| Variable | Used by | Where |
|---|---|---|
| `NEXTAUTH_SECRET` | review-ui | Vercel |
| `NEXTAUTH_URL` | review-ui | Vercel |
| `NEXT_PUBLIC_SUPABASE_URL` | review-ui | Vercel |
| `NEXT_PUBLIC_SUPABASE_ANON_KEY` | review-ui | Vercel |
| `SUPABASE_SERVICE_ROLE_KEY` | review-ui | Vercel |
| `REVIEW_UI_PASSWORD` | review-ui | Vercel |
| `DATABASE_URL` | workers-py | Fly |
| `SUPABASE_URL`, `SUPABASE_SERVICE_KEY` | workers-py | Fly |
| `ANTHROPIC_API_KEY` | workers-py | Fly |
| `X_API_KEY`, `X_API_SECRET`, `X_BEARER_TOKEN`, `X_ACCESS_TOKEN`, `X_ACCESS_SECRET` | workers-py | Fly |
| `ALCHEMY_API_KEY` | workers-py | Fly |
| `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, `TELEGRAM_PHONE` | workers-py | Fly |
| `RWA_XYZ_API_KEY` | workers-py | Fly (when issued) |
| `HIGGSFIELD_API_KEY`, `HIGGSFIELD_DEFAULT_IMAGE_MODEL`, `HIGGSFIELD_DEFAULT_VIDEO_MODEL`, `HIGGSFIELD_CREDIT_MONTHLY_CAP` | workers-py | Fly |
| `CANVA_CLIENT_ID`, `CANVA_CLIENT_SECRET`, `CANVA_REFRESH_TOKEN`, `CANVA_BRAND_ORG_ID` | workers-py | Fly (optional, only for Enterprise REST) |

---

## Cost envelope (production, target 3 posts/day)

| Service | Tier | Monthly cost |
|---|---|---|
| Vercel (review-ui) | Hobby | $0 |
| Fly.io (workers) | shared-cpu-1x + 1GB volume | ~$3–5 |
| Supabase | Free tier OK for v1 | $0 (until DB or storage limits hit) |
| Anthropic API | pay-as-you-go | ~$30–80 (draft generation × 3 variants × 3 posts/day) |
| Higgsfield | Starter | already paid |
| X API v2 | Basic | $100 (required for posting) |
| Alchemy | Free tier | $0 |
| Telegram | n/a | $0 |

**Total: ~$135–185/month at the algo-refit 3-posts/day cadence.**

---

## What's not in this deploy (deferred)

- **Higgsfield REST production wire-up** — `_HiggsfieldRESTClient` is stubbed; raise an issue when the enterprise/REST account is provisioned, and the methods need ~30 lines each.
- **Canva Enterprise REST** — same posture. The MCP-only dev path stays available in Cowork sessions; prod uses queued-pending-manual-approval semantics until you upgrade.
- **Cloudflare R2 for media** — Supabase Storage covers v1. Move to R2 if storage bills bite at scale.
- **Sentry / Axiom for observability** — env-var slots exist in `.env.example` (`SENTRY_DSN`, `AXIOM_TOKEN`); wire after the first month of live data so you know what to alert on.
