# Build a DeFi X (Twitter) Posting Agent Dashboard

You are building a Next.js 14 admin dashboard for an existing X (Twitter)
posting agent. The agent's worker (ingest, scoring, drafting, posting) runs
on Fly.io and writes to a Supabase Postgres database. This dashboard is
**purely a UI over that database** — it does NOT contain any posting,
scheduling, or worker logic. All writes go through Supabase; the worker
detects them and acts.

The dashboard replaces an Excel spreadsheet (attached as PDF for visual
reference) that the operator currently uses for the same purpose.

## Tech stack

- **Next.js 14** with App Router and TypeScript
- **Tailwind CSS** + **shadcn/ui** components
- **@supabase/supabase-js** for database access
- **next-auth** with credentials provider for single-user password gate
- **@tanstack/react-query** for client-side data fetching with 30s polling
- Server actions for all mutations
- **Lucide React** for icons

Use the `app/` directory (not pages/). Server components by default.

## Database

Use the schema in `SCHEMA.sql`. Use `SAMPLE_DATA.json` to see real payload
shapes — especially the nested `circulating_market_value_dollar` object on
RWA.xyz signals and the markdown-formatted Telegram message text.

Two Supabase clients:
- `lib/supabase/server.ts` — uses `SUPABASE_SERVICE_ROLE_KEY`, used by
  server components and server actions. Bypasses Row Level Security.
- `lib/supabase/client.ts` — uses `NEXT_PUBLIC_SUPABASE_ANON_KEY`, only used
  if needed for realtime subscriptions in client components.

All mutations go through server actions, not client-side writes.

## Authentication

Single user. NextAuth credentials provider with one hardcoded user:
- Username field is unused (or fixed to "admin")
- Password field compares against `REVIEW_UI_PASSWORD` env var
- JWT session, 30-day expiry
- All routes except `/login` are protected. Middleware redirects to `/login`
  if no valid session.

## Pages (in order of priority)

### `/` → redirects to `/drafts`

### `/drafts` — THE primary page, polish this most

The operator spends 90% of their time here. It's the inbox.

**Layout:** main content is a table, with a header showing:
- Counts: "23 pending • 5 approved waiting to post • 142 posted lifetime"
- Quick filters: format chips (single/thread/reply/quote_tweet/hot_take),
  status chips (pending/approved/edited/rejected)
- Search bar: full-text search over draft body

**Table columns** (rows are drafts where status IN ('pending', 'approved', 'edited'); sorted by created_at desc):

| Column | Display | Behavior |
|---|---|---|
| Checkbox | for bulk select | Bulk Approve / Bulk Reject buttons appear when ≥1 checked |
| Format | badge (single=blue, thread=purple, reply=green, hot_take=orange) | |
| Headline | from joined `stories.headline`, truncated 60 chars | |
| Body | truncated 100 chars | Click → opens side drawer with full body, story context, AI flags |
| AI check | green check ✓ or red X with hover tooltip showing `ai_check_flags` | |
| Status | colored badge | |
| Scheduled | local ET time, e.g. "Fri 9:00 AM" or "—" if not yet scheduled | Editable inline (date+time picker). Blank = let worker auto-schedule. |
| Created | relative ("2h ago") | |
| Actions | three buttons: Approve (primary), Edit, Reject | |

**Row action behaviors:**

- **Approve**: server action sets `drafts.status = 'approved'`,
  `reviewed_at = now()`. Toast: "Draft approved. Worker will schedule
  within 60 seconds." Do NOT write to `scheduled_posts` — the Fly worker
  detects the status change and inserts the row at the next optimal slot.
- **Reject**: server action sets `drafts.status = 'rejected'`,
  `reviewed_at = now()`. Removes from inbox.
- **Edit**: opens modal with textarea pre-filled with current `body`. On
  Save, server action writes `edited_body = <new>` and sets
  `status = 'edited'`. Worker uses `edited_body` if non-null.

**Side drawer (body click):**

Opens on the right, ~600px wide. Shows:
- Full body text (rendered as plain text, no markdown)
- For threads: each tweet in `body_json` as a separate numbered card
- Story headline + narrative angle
- Source attribution handles (e.g. `@DefiLlama`, `@CoinDesk`)
- Entities to be tagged (e.g. `@BlackRock`, `@ondofinance`)
- Key data points table (from `stories.key_data_points` JSON)
- AI check flags as a list
- Created at, story id, draft id

Side drawer has its own Approve/Edit/Reject buttons at the bottom.

**Multi-select bulk actions:**

- Select all (header checkbox)
- Bulk Approve / Bulk Reject buttons appear when 1+ rows selected
- Show "12 selected" indicator

**Empty state:**

When no pending drafts: "Inbox zero. The worker will surface new drafts as
they're generated." With an illustration or just a calm icon.

### `/calendar` — read-only chronological view

Shows all `scheduled_posts` where `status IN ('queued', 'posting', 'posted')`
AND `post_at >= now() - interval '7 days'`. Sorted by `post_at` asc.

**Layout:** vertical timeline grouped by day. Day headers:
- "Today" / "Tomorrow" / day name + date for further out
- "Earlier this week" for past days

**Each card shows:**
- Time in local ET ("9:00 AM ET")
- Format badge
- Headline
- Body preview (140 chars)
- Status badge
- For posted: link to live tweet (external icon, opens x.com)
- For failed: red error message from `scheduled_posts.last_error`

**Header summary:**
- "12 scheduled across 5 days"
- Mini bar chart showing posts per day for the next 7 days
- Next post countdown ("Next post in 1h 23m")

### `/stories` — read-only

Recent stories (last 200) from the `stories` table. Sortable table with
filter chips for status.

Columns:
- Created (relative)
- Headline
- Status badge (open/drafted/posted/killed)
- Entities (chip list)
- Source handles (chip list)
- Hot take indicator (small ⚡ icon if true)
- Drafts count (count of drafts where story_id matches)

Click a row → side drawer showing the full story brief: narrative_angle,
key_data_points, format_recommendation, signals_ids.

### `/signals` — read-only debugging view

Recent signals (last 500) from `signals` table. Filterable by source.

Columns:
- Observed at (relative)
- Source (badge with color: defillama=blue, rwa_xyz=purple, telegram_newswire=orange)
- Signal type
- Entity
- Materiality score (0-100, color-coded: <50 gray, 50-70 yellow, ≥70 green)
- Novelty score (same scheme)
- Promoted? (checkmark if `promoted_to_story_id` is not null)
- Notes (truncated rationale)

Click row → drawer with full `payload` JSON pretty-printed.

### `/posts` — read-only, published content

Posts table joined with engagement. Columns:

- Posted at
- Format
- Body (truncated)
- Tweet link (external)
- 24h: impressions / likes / RTs / replies (small inline stats)
- 7d: same metrics
- Engagement rate (computed: likes+RTs+replies / impressions × 100)

Sort by posted_at desc by default. Allow sort by any engagement metric.

Highlight top decile by engagement with a subtle background tint.

### `/jobs` — editable run_jobs configuration

Table of all 13 run_jobs. Columns:

| Column | Editable | Notes |
|---|---|---|
| Name | no | e.g. `ingest_defillama` |
| Description | no | |
| Command | no | |
| Cron | YES | Inline editable. Validate cron syntax on save. |
| Enabled | YES | Toggle switch |
| Last run | no | Relative ("3 min ago") |
| Next run | no | Relative ("in 7 min") |
| Last status | no | ok/error/running badge |
| Last error | no | Hover to see full error |
| Run now | button | Click sets `run_now=true`. Toast: "Will run on next worker cycle (~60s)." |

Group jobs by category in the table:
- **Ingest:** ingest_defillama, ingest_rwa_xyz, ingest_telegram, etc.
- **Processing:** score, build_stories, draft
- **Scheduled:** hot_take, weekly_recap
- **Output:** post_due, engagement_24h, engagement_7d

### `/config` — editable thresholds

A simple settings page. Read from `app_config` table (single row,
JSONB `data` column) — if that table doesn't exist, create it on first
save.

Group settings into sections:

**Materiality**
- Default threshold (0-100 slider, default 60)
- Novelty threshold (0-100 slider, default 50)
- Minimum for thread (0-100 slider, default 75)

**Cadence**
- Daily post cap (number, default 8)
- Min minutes between posts (number, default 75)
- Thread max per day (number, default 2)

**Posting windows** (the high-virality slots)
- A list of (start hour, end hour) pairs in ET
- Defaults: 9-10am, 12-1pm, 5-6pm, 8-9pm
- Add/remove rows

**Onchain thresholds**
- TVL delta % threshold (default 5)
- APY shift bps threshold (default 50)

Auto-save 500ms after last change. Toast on save.

### `/watchlist` — editable monitored accounts

Read from `WATCHLIST.json` initially (the file provided to you).
Persist edits to an `app_config.data.watchlist` JSONB structure.

Table columns:
- Handle (e.g. `@imperiumpaper`)
- Category (voice_models / newsfeeds / issuers / protocols / tradfi_entrants / journalists)
- Weight (numeric, 0-3)
- Enabled (toggle)

Group by category. Add new handle button.

## Global UI

**Sidebar (left, collapsible):**
- App name / logo
- Drafts (pending count badge)
- Calendar (queued count badge)
- Stories
- Signals
- Posts (today count badge)
- Jobs
- Config
- Watchlist
- Sign out (bottom)

**Top bar:**
- Page title
- Manual refresh button (right side)
- Last refresh time ("Updated 12s ago")

**Auto-refresh:** every 30 seconds via React Query polling. Show a subtle
indicator when refreshing.

**Notifications:** toast on every server action result (success or error).

**Loading states:** skeleton tables, not spinners.

**Empty states:** thoughtful copy + small icon, never "No data."

## Authentication flow

- `/login` page: card with single password field, "Sign in" button
- On submit: NextAuth credentials provider, JWT cookie set, redirect to `/drafts`
- All other routes: middleware checks for valid JWT, redirects to `/login` if missing
- Sign out button at bottom of sidebar clears the cookie

## Environment variables

These will be set in v0 / Vercel:

```
NEXT_PUBLIC_SUPABASE_URL=https://<project>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<anon JWT>
SUPABASE_SERVICE_ROLE_KEY=<service role JWT, never exposed to client>
REVIEW_UI_PASSWORD=<the single login password>
NEXTAUTH_SECRET=<random 32-byte string>
NEXTAUTH_URL=<auto-set on Vercel>
```

## Style guidance

- Light theme primary, with a dark theme toggle in the sidebar
- Inter font (Google Fonts)
- Neutral grays for the base, single blue accent (#1F6FEB) for primary actions
- Data-dense — show numbers, not whitespace
- Reference: Linear, Stripe Dashboard, Supabase Dashboard
- Compact row heights (~40px) so more rows fit
- Sticky table headers
- All times displayed in local ET (America/New_York) — workers store UTC
- Hover states on every interactive element

## What NOT to build

- **No posting logic.** The Fly worker handles all X API calls.
- **No scheduling logic.** Approving a draft just sets status='approved'.
  The worker auto-schedules at the next optimal slot.
- **No Claude/AI calls.** All inference happens on the worker.
- **No Excel-related code.** This dashboard replaces the spreadsheet.

If you find yourself writing tweepy/X/anthropic/openai imports — stop.
This is purely a database UI.

## File layout to generate

```
app/
  layout.tsx                  # root layout, font, theme provider
  page.tsx                    # redirect to /drafts
  login/
    page.tsx
  (app)/                      # auth-required group
    layout.tsx                # sidebar + topbar
    drafts/
      page.tsx
    calendar/
      page.tsx
    stories/
      page.tsx
    signals/
      page.tsx
    posts/
      page.tsx
    jobs/
      page.tsx
    config/
      page.tsx
    watchlist/
      page.tsx
  actions/
    drafts.ts                 # approve, reject, edit, bulk
    jobs.ts                   # update cron, enable, run_now
    config.ts                 # save settings
    watchlist.ts              # toggle handles
lib/
  supabase/
    server.ts                 # service role client
    client.ts                 # anon client for realtime if needed
  auth.ts                     # next-auth config
  types.ts                    # generated from schema
components/
  data-table.tsx              # shared sortable/filterable table
  status-badge.tsx
  format-badge.tsx
  relative-time.tsx
  body-drawer.tsx             # the side drawer for draft details
  sidebar.tsx
  topbar.tsx
  theme-toggle.tsx
middleware.ts                 # auth check on protected routes
```

## Build order

Generate the Drafts page first and make it polished and functional. Stub the
other pages with placeholder content. The operator will iterate on each page
after seeing the Drafts page work end-to-end with their real data.
