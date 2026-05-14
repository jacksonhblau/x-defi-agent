# workers-py

Python workers for x-defi-agent. Handles ingest, materiality scoring, story building, and draft generation. Posting to X is handled by `../poster-ts`.

## Setup

```
cd apps/workers-py
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
```

Environment variables are read from `../../.env` (project root). See `../../.env.example` for the full list.

## Commands

The primary command for day-to-day use is `agent watch`. The others are for ad-hoc runs and debugging.

```
# THE MAIN COMMAND — long-lived control loop, runs everything
agent watch                       # default 60s interval
agent watch --interval 30         # tighter loop
agent watch --once                # run one cycle and exit (for cron use)

# Excel dashboard (called automatically by watch, exposed for manual use)
agent excel-export                # DB → agent_dashboard.xlsx
agent excel-apply                 # agent_dashboard.xlsx → DB

# Individual pipeline stages (also runnable via the Excel "Run Jobs" sheet)
agent ingest --source defillama   # one ingest cycle
agent score                       # score unprocessed signals
agent build-stories               # promote scored signals to stories
agent draft                       # generate drafts for open stories
agent post-due                    # drain scheduled_posts queue → publish to X

# End-to-end test (manual)
agent test-e2e --source defillama

# Schema migrations
agent migrate
```

## How the Excel dashboard works

After `agent migrate` runs once, start the control loop:

```
agent watch
```

This populates `agent_dashboard.xlsx` at the project root and refreshes it every 60 seconds. Open it in Excel or Numbers. Seven sheets:

- **README** — usage notes pinned as the first sheet
- **Drafts** — pending posts. Edit `status` to `approved` / `rejected`, edit `scheduled_for` to schedule a specific time, edit `body` if you want to revise (then set `status` to `edited`)
- **Run Jobs** — every script the agent runs. Edit `cron` to change frequency, `enabled` to disable, set `run_now` to `YES` to trigger an ad-hoc run within ~60 seconds
- **Stories** — story-level state (read-only)
- **Signals** — recent signal log (read-only)
- **Posts** — published tweets with engagement metrics at 24h and 7d (read-only)
- **Config** — editable thresholds (materiality, novelty, daily post cap, etc.)
- **Watchlist** — toggle monitored X accounts on/off

Yellow cells are editable. Gray cells are read-only — edits there are ignored.

If you have the file open in Excel when the agent tries to write, it skips that cycle and retries on the next one. Save the file (Cmd+S) to release the lock briefly so the agent can read your edits.

## Layout

```
src/workers/
  config.py             # env + thresholds loader
  db.py                 # psycopg pool + helpers
  llm.py                # anthropic client wrapper
  cli.py                # typer entry point
  ingest/
    defillama.py        # public DeFiLlama API poller
    rwa_xyz.py          # (later) RWA.xyz API poller
    telegram_newswire.py# (later) Telethon listener
    alchemy.py          # (later) onchain RPC watcher
    x_firehose.py       # (later) watchlist X poster
  scoring/
    materiality.py      # Claude-scored signal materiality
  stories/
    builder.py          # cluster signals → story_brief
  drafts/
    generator.py        # voice prompt → draft
  graphics/
    custom.py           # matplotlib chart renderer (later)
    sourced.py          # Playwright screenshot runner (later)
```
