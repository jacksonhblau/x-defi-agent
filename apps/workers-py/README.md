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

```
# Run a one-shot ingest cycle for a single source
agent ingest --source defillama

# Score unprocessed signals (one-shot)
agent score

# Build stories from scored signals (one-shot)
agent build-stories

# Generate drafts from open stories (one-shot)
agent draft

# End-to-end test: ingest → score → build → draft, write final JSON to data/drafts/
agent test-e2e --source defillama

# Apply database migrations
agent migrate
```

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
