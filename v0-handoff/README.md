# v0 handoff — DeFi X Posting Agent Dashboard

This folder is a self-contained package to give v0.dev. It replaces the
Excel-based dashboard with a Next.js web UI. The Fly.io worker that does
ingest/scoring/drafting/posting stays untouched — this is purely a UI over
the existing Supabase database.

## How to use this folder

1. **Generate a PDF of your current Excel dashboard** to give v0 a visual
   reference of the layout you want to replicate:
   - Open `agent_dashboard.xlsx` in Excel
   - File → Save As → PDF
   - In the dialog, change "What to publish" to **"Entire Workbook"**
   - Save as `agent_dashboard.pdf` into THIS folder

2. **Go to https://v0.dev** and start a new generation.

3. **Upload these files** to the v0 chat:
   - `PROMPT.md` (the main brief — drag it into the message)
   - `SCHEMA.sql` (the Postgres schema)
   - `SAMPLE_DATA.json` (example data shapes so v0 handles edge cases)
   - `DESIGN.md` (visual style guide)
   - `WATCHLIST.json` (current watchlist for the Watchlist page)
   - `agent_dashboard.pdf` (the visual reference you exported in step 1)

4. **Paste this as your message** (or just say "build what's described in
   PROMPT.md, using SCHEMA.sql as the data model and the PDF as visual
   reference for layout"):

   > Build the Next.js admin dashboard described in PROMPT.md. Use SCHEMA.sql
   > as the exact Postgres data model. Use SAMPLE_DATA.json to understand the
   > real shape of payloads (especially the nested RWA.xyz market value
   > object and the Telegram message markdown). Use the attached PDF as the
   > visual reference for what each page should look like.

5. **Configure environment variables in v0** (top right gear icon → Environment Variables):
   - `NEXT_PUBLIC_SUPABASE_URL` — from Supabase Settings → API
   - `NEXT_PUBLIC_SUPABASE_ANON_KEY` — same page
   - `SUPABASE_SERVICE_ROLE_KEY` — same page (the long `service_role` JWT)
   - `REVIEW_UI_PASSWORD` — pick a strong password
   - `NEXTAUTH_SECRET` — generate with `openssl rand -base64 32` in terminal
   - `NEXTAUTH_URL` — leave blank for v0 preview; set after deploy

   **Do NOT click "Add Supabase Integration"** — that tries to create a new
   Supabase project. Use plain environment variables instead.

6. **Verify the connection** by asking v0 to add a debug page:

   > Add a temporary `/debug` page that shows the row count of every table:
   > signals, stories, drafts, scheduled_posts, posts, engagement, run_jobs.
   > This is just to confirm the Supabase connection works.

   The numbers should match what `agent schedule-status` shows on your Mac.
   Once verified, ask v0 to delete the debug page.

7. **Iterate.** v0 will not produce a perfect dashboard on the first try.
   After the initial generation, use short follow-up prompts to refine each
   page. Examples:
   - "Make the Drafts table show 50 rows per page with sticky header"
   - "Add a side drawer that opens when I click a body cell"
   - "The Calendar should group entries by day with date headers"

8. **Deploy.** v0 has a one-click Deploy to Vercel button. Connect your
   GitHub repo `jacksonhblau/x-defi-agent` and let it create a new branch
   or sub-folder for the UI. After deploy, set `NEXTAUTH_URL` to your
   Vercel domain (e.g. `https://x-defi-agent.vercel.app`).

## Architecture reminder

```
┌─────────────────────────────────────────────────────────────────┐
│                    Supabase Postgres (existing)                  │
│  signals, stories, drafts, scheduled_posts, posts, run_jobs...  │
└─────────────────────────────────────────────────────────────────┘
         ▲                                          ▲
         │ reads/writes                             │ reads/writes
         │                                          │
┌────────┴──────────┐                  ┌────────────┴──────────┐
│  Fly.io worker    │                  │  Vercel dashboard      │
│  (existing)       │                  │  (NEW, built with v0)  │
│                   │                  │                        │
│  - ingests        │                  │  - read-only views     │
│  - scores         │                  │  - approve/reject      │
│  - drafts         │                  │  - edit body           │
│  - posts to X     │                  │  - tune config         │
│  - schedules      │                  │                        │
│  - engages        │                  │  NO posting logic.     │
│                   │                  │  NO scheduling logic.  │
└───────────────────┘                  └────────────────────────┘
```

The Vercel app is ONLY a UI. It writes `drafts.status='approved'` to Supabase
and the Fly worker handles everything from there. Do not let v0 build any
scheduling or posting code into the Vercel app.

## After v0 generates a working version

Test the full loop:
1. On your Mac, the Fly logs should still show the watch loop running every 60s
2. Open your new Vercel dashboard, find a pending draft, click Approve
3. Within 60 seconds, Fly's apply step should detect the change and queue the
   post (or post immediately if past the scheduled time)
4. Check `flyctl logs` to confirm `Applied: {'drafts_updated': 1, ...}` and
   then `Poster: {'posted': 1, ...}` if the time has come

If that round-trip works, the Excel sheet can be retired (or kept as a
backup).
