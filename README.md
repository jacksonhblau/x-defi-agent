# x-defi-agent

A long-running agent that ingests RWA/DeFi onchain data and X chatter, scores stories for materiality, drafts posts in a calibrated mechanism-design analyst voice, generates supporting graphics, and queues everything for human approval before posting to X as [@jacksonblau](https://x.com/jacksonblau).

Cadence target: 4 to 8 posts/day across four formats — onchain alerts, analyst threads, reply/QT engagement on a curated watchlist, and scheduled recaps. On slow news days, the agent generates an original hot take on existing relevant stories before falling back to recap content.

See [`BUILD_PLAN.md`](./BUILD_PLAN.md) for the full architecture, voice rules, and milestone breakdown.

## Status

Active development. Not for public use.

## Repo layout

```
apps/
  workers-py/    Python workers (ingest, scoring, story building, draft generation)
  poster-ts/     TypeScript worker that drains the scheduled-posts queue to X API v2
  review-ui/     Next.js draft-review UI

packages/
  prompts/       Voice prompt and per-format templates
  db/            Postgres schema and migrations

config/
  watchlist.json     Monitored X accounts (~40)
  thresholds.json    Materiality / novelty / cadence thresholds

data/              Local runtime artifacts (sessions, sqlite caches). Gitignored.
```

## Local setup

1. Copy `.env.example` → `.env` and fill in real values. See comments in the file for where each credential lives.
2. Python workers:
   ```
   cd apps/workers-py
   python3 -m venv .venv && source .venv/bin/activate
   pip install -e . --config-settings editable_mode=compat
   ```
   The `editable_mode=compat` flag is **required** because the project path contains spaces ("DeFi X Poster"). Without it, modern pip's editable install will break intermittently and you'll see `ModuleNotFoundError: No module named 'workers'`.
3. Run the v0 end-to-end test:
   ```
   agent test-e2e --source defillama
   ```
   This pulls signals from DeFiLlama, scores them, builds stories, and generates drafts. Output goes to `data/drafts/` and to the `drafts` table in Postgres.

### Day-to-day operation

```
agent watch          # long-running loop: ingest, score, draft, post on schedule
agent excel-export   # rebuild agent_dashboard.xlsx from current DB state
```

Open `agent_dashboard.xlsx` at the project root to approve/reject drafts, tune thresholds, and toggle jobs.

### Troubleshooting

If you ever see `ModuleNotFoundError: No module named 'workers'`, repair with:

```
cd apps/workers-py && source .venv/bin/activate
pip install -e . --config-settings editable_mode=compat
```

Do NOT run `pip install --upgrade pip` in this venv — it's the most common cause of the editable install breaking.

## Production deployment

Workers run on Fly.io. See `fly.toml` (added in a later commit). Secrets are injected via `fly secrets set` — never commit `.env`.

## License

Proprietary. All rights reserved. See [`LICENSE`](./LICENSE).
