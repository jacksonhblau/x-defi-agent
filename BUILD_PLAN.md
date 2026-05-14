# DeFi X Posting Agent — Build Plan

**Owner:** Jackson Blau (@jacksonblau)
**Drafted:** May 14, 2026
**Stack target:** Claude Agent SDK on VPS, X API v2, Postgres, Python + TypeScript

---

## 1. Executive summary

A long-running agent that ingests RWA/DeFi onchain data and X chatter, scores stories for materiality, drafts posts in a calibrated mechanism-design analyst voice, generates supporting graphics, and queues everything for human approval before posting to X. Cadence target is 4 to 8 posts/day across four formats: onchain alerts, analyst threads, reply/QT engagement on a curated watchlist, and scheduled recaps. On slow news days, the agent first tries to generate a custom hot take on existing relevant stories or onchain data; recap content is the final fallback if even that bar isn't met.

---

## 2. Locked preferences (from Q&A rounds)

| Dimension | Choice |
|---|---|
| Autonomy | Draft + approve (review queue gates every post) |
| Cadence | 4–8 posts/day |
| Formats | Alerts, threads, replies/QTs, recaps + deploy spotting |
| Voice priority | imperium/sebventures, adcv\_/monetsupply, definikola/francescoweb3 |
| Single-post voice | Mechanism-design POV (one core insight, defended) |
| Thread voice | Argument-first thesis, data underneath |
| Tags / hashtags | @-mentions only, no hashtags |
| Compliance rails | Full latitude; approval is the only gate |
| Reply voice | Same voice everywhere |
| Data sources | RWA.xyz + RWAxyzNewswire Telegram, DeFiLlama + VaultsFYI, Bubblemaps + Etherscan/Alchemy RPC, X firehose for watchlist |
| Graphics | Hybrid: custom-rendered + sourced screenshots |
| Chart aesthetic | Light mode, RWA.xyz-inspired |
| Runtime | Claude Agent SDK on a VPS |
| Beat | All tokenized RWA, weighted toward yield-generating assets |
| Watchlist | Expanded: 11 influencers + RWAxyzNewswire + ~30 RWA-adjacent |
| Slow-day fallback | 1) Custom hot take on existing relevant stories/data, then 2) recap content |

---

## 3. Architecture

```
              ┌──────────────────────────────────────────────┐
              │              INGEST WORKERS                  │
              │                                              │
              │  rwa-xyz/api ──┐                             │
              │  defillama  ──┤                              │
              │  vaultsfyi  ──┤                              │
              │  bubblemaps ──┤── signal normalizer ─┐       │
              │  alchemy-rpc──┤                      │       │
              │  telegram   ──┤                      │       │
              │  x-firehose ──┘                      │       │
              └──────────────────────────────────────┼───────┘
                                                     ▼
                                          ┌──────────────────┐
                                          │  signals table   │
                                          │  (postgres)      │
                                          └────────┬─────────┘
                                                   ▼
                                ┌─────────────────────────────────┐
                                │  MATERIALITY SCORER (Claude)    │
                                │  rates novelty + size + fit     │
                                └────────────────┬────────────────┘
                                                 ▼
                          ┌──────────────────────────────────────────┐
                          │   STORY BUILDER (Claude)                 │
                          │   bundles signals, pulls supporting data │
                          └──────────────────┬───────────────────────┘
                                             ▼
                ┌────────────────────────────────────────────────────────┐
                │  DRAFT GENERATOR (Claude, voice prompt locked)         │
                │   ├── single post draft                                │
                │   ├── thread draft (if material warrants it)           │
                │   ├── graphic spec (custom chart or source screenshot) │
                │   └── reply/QT drafts (if from watchlist signal)       │
                └──────────────────────────────┬─────────────────────────┘
                                               ▼
                          ┌─────────────────────────────────┐
                          │  GRAPHICS RENDERER              │
                          │   ├── matplotlib/Plotly charts  │
                          │   └── Playwright screenshots    │
                          └────────────────┬────────────────┘
                                           ▼
                          ┌─────────────────────────────────┐
                          │  REVIEW QUEUE (Next.js)         │
                          │   approve / edit / reject /     │
                          │   schedule                      │
                          └────────────────┬────────────────┘
                                           ▼
                          ┌─────────────────────────────────┐
                          │  X POSTER (X API v2)            │
                          │   single / thread / reply / QT  │
                          └────────────────┬────────────────┘
                                           ▼
                          ┌─────────────────────────────────┐
                          │  LEARNING LOOP                  │
                          │  pulls engagement at 24h + 7d,  │
                          │  feeds top performers back into │
                          │  draft generator as exemplars   │
                          └─────────────────────────────────┘
```

---

## 4. Components

### 4.1 Ingest workers

Each source is a small worker that polls (or subscribes) on its own cadence and writes normalized `signal` rows.

| Source | Method | Cadence | Notes |
|---|---|---|---|
| RWA.xyz | REST API | 10 min | Need API key. Pull issuer-level AUM deltas, new product listings. |
| RWA.xyz Newswire (Telegram) | Telegram MTProto (Telethon) | Real-time push | Public channel; can subscribe as a regular client. Each message becomes a high-priority signal. |
| DeFiLlama | REST API (public) | 15 min | Pull TVL deltas at protocol + chain + category granularity. Yields endpoint for vault APYs. |
| VaultsFYI | REST API | 1h | APY shifts > X bps trigger signal. |
| Bubblemaps | API (or scraped via Playwright on free tier) | 4h | Cluster changes on watched tokens. |
| Onchain RPC (Alchemy / Etherscan) | Webhooks + getLogs | Real-time + 5 min sweep | Watch list of treasury wallets, RWA contract deploys, large transfers (configurable threshold per token). |
| X firehose | X API v2 user timeline poller | 2 min per account, rotated | Pulls latest posts from the watchlist. Each new post is a signal with type = `x_post`. |

**Deduplication:** every signal has a `dedup_hash` of (source, entity, ts_bucket, payload_canonical). The normalizer rejects duplicates within a 24h window.

### 4.2 Materiality scorer

A short Claude prompt that takes a signal and recent agent post history and returns:

```json
{
  "score": 0..100,
  "category": "treasury_flow | new_deploy | governance | yield_shift | x_chatter | recap_seed",
  "novelty": 0..100,
  "rationale": "..."
}
```

Threshold for promotion to story builder is configurable. Default: `score >= 60` and `novelty >= 50`.

### 4.3 Story builder

Takes 1 to N material signals that cluster (same protocol, same theme, same 6h window) and produces a `story_brief`:

```json
{
  "headline": "BlackRock files $7B onchain MMF; BNY Mellon as transfer agent",
  "entities": ["@BlackRock", "@Securitize", "@BNYMellon"],
  "key_data_points": [
    {"label": "Filed AUM", "value": "$7B", "source": "sec.gov/..."},
    {"label": "BUIDL comp", "value": "$1.7B over 14mo", "source": "rwa.xyz/buidl"},
    {"label": "Tokenized treasury TVL", "value": "$31B", "source": "rwa.xyz/treasuries"}
  ],
  "narrative_angle": "regulated transfer agent treating L1 as canonical state",
  "format_recommendation": "single + thread + chart",
  "graphic_spec": {...},
  "reply_candidates": [...]
}
```

### 4.4 Draft generator

Single Claude call with the voice prompt (Section 6) plus the story brief. Returns:
- 3 single-post variants
- 1 thread variant (if `format_recommendation` includes thread)
- 1 graphic caption
- 0 to 3 reply/QT drafts targeted at watchlist accounts mentioned in the story

Anti-AI-writing checklist (Section 7) is run as a second pass on every draft.

### 4.5 Graphics renderer

Two paths:

**Custom charts** (`matplotlib` or `plotly`, RWA.xyz-inspired light theme):
- Background: `#FAFAFA`
- Primary accent: `#1F6FEB` (configurable)
- Font: Inter (or system sans)
- No gridlines on x-axis, faint y-axis gridlines only
- Title top-left, source bottom-right
- Always include "@jacksonblau" watermark bottom-left

**Source screenshots** (`Playwright`):
- Pre-rendered URL list (RWA.xyz dashboards, DeFiLlama charts, Bubblemaps maps) cropped to chart area
- Cached for 1h to avoid re-rendering
- Adds same watermark + light "via [source]" footer

### 4.6 Review queue

Minimum viable: a Next.js app with one page listing pending drafts. Each card shows:
- Story headline + materiality score
- All three single-post variants
- Thread variant (if any)
- Graphic preview
- Reply/QT drafts
- Buttons: Approve & post now / Schedule / Edit / Reject

Auth: just protect with a single password or Tailscale-only access. No need for multi-user.

### 4.7 X poster

Wraps X API v2:
- `POST /2/tweets` for singles
- Chained `POST /2/tweets` with `reply.in_reply_to_tweet_id` for threads
- `POST /2/tweets` with `quote_tweet_id` for QTs
- Media upload via v1.1 endpoint (still required for images)

Rate-limit-aware via shared token bucket. Posts queued in `scheduled_posts` table with a `post_at` timestamp; a worker drains the queue every minute.

### 4.8 Hot-take generator (slow-day primary fallback)

Runs when no signal in the last N hours (default 6h) clears the materiality threshold for a fresh news post. Steps:

1. Pull the top 20 signals from the last 7 days that are still relevant (entity is still active, no superseding story has fired, no agent post on this angle in the last 14 days).
2. Pull the top 10 onchain data deltas from the same window (TVL shifts, APY shifts, treasury wallet movement, cluster changes) that didn't individually clear the news bar but cluster into a takeable pattern.
3. Claude is asked: "Looking at this body of recent stories + data, what is one non-obvious take that hasn't been said? Mechanism-design POV. Defended with at least one specific number from the inputs."
4. Output is scored against an `originality` filter: reject if it restates the consensus, restates a prior agent post, or restates any voice-model's recent posts.
5. Surviving hot takes go into the review queue with a `hot_take` flag so they are visually distinguished from news-driven drafts.

This runs once daily by default, scheduled for 11am ET (mid-morning, before lunch lull). If a fresh news story fires later in the day, the hot take can be deferred or killed.

### 4.9 Recap generator (last-resort fallback)

Only triggers if hot-take generation also produces nothing publishable (originality filter rejects everything, or the input set is too thin). Generates a structured digest from the same materiality/data backlog. Default templates: weekly RWA flows recap (auto-fires Friday regardless), daily top-5 movers (only on slow days when hot-take fails).

### 4.10 Learning loop

24h and 7d after every post, agent pulls engagement (impressions, likes, RTs, replies, bookmarks). Top decile of posts gets stored as `exemplars` and injected into future draft generations as few-shot examples. Bottom decile gets stored as `anti-exemplars` with a note about why they underperformed.

---

## 5. Data flow walkthrough (worked example)

Using today's BlackRock $7B story:

1. **Ingest:** Telegram newswire pushes "BlackRock filed S-1 for $7B onchain MMF via Securitize." → signal row created with score-hint = high.
2. **Within 30s:** RWA.xyz API poller catches the new product listing → second signal, same entity.
3. **Normalizer:** dedups, links the two signals under one entity cluster.
4. **Scorer:** returns `{score: 92, category: "new_deploy", novelty: 88}`.
5. **Story builder:** pulls BUIDL comp ($1.7B / 14mo) from RWA.xyz, total tokenized treasury TVL ($31B), confirms BNY Mellon is named as transfer agent, drafts brief.
6. **Draft generator:** produces single post (mechanism-design POV variant, ~280 chars), thread (5 tweets, argument-first), 1 reply candidate to @rwa_xyz's announcement post.
7. **Graphics:** renders a "BUIDL vs. new filing — AUM at launch" bar chart, plus screenshots RWA.xyz tokenized treasury TVL chart for the thread.
8. **Review queue:** notification fires (email or push). Jackson approves the thread variant, edits one number, schedules for 9:15am ET.
9. **Poster:** publishes thread at 9:15am, captures tweet IDs.
10. **Learning loop:** at +24h, pulls engagement, stores as exemplar if top decile.

---

## 6. Voice system prompt (v1)

This is the prompt loaded into every draft generation. Save as `/prompts/voice.md`.

```
You are drafting X posts for @jacksonblau, a tokenized RWA analyst.

His voice is mechanism-design POV: one core insight, defended with specific numbers. He treats followers as sophisticated readers who already know the surface news. Originals, threads, and replies all use the same register.

VOICE RULES

1. Lead with the structural insight, not the headline. Assume the reader already saw the news.
2. Defend the insight with at least one specific number sourced from the story brief.
3. Tag every entity that has an X account. Use the handles in the story brief. Never use hashtags.
4. Vary sentence length aggressively. Short fragments are allowed and welcome.
5. Contractions are allowed. First person is allowed but used sparingly.
6. Threads: tweet 1 is the thesis. Tweets 2 to N defend it. Last tweet is either a one-line restatement or a question to the room. No numbered prefixes ("1/", "2/") unless the format is explicitly numbered-spine.

FORBIDDEN PATTERNS (these are AI tells; remove them)

- Em-dashes (— or –). Use a period or comma instead.
- The "It's not just X, it's Y" rhetorical structure.
- The "X is no longer the experiment. Y is." rhetorical structure (over-used by Claude specifically). Vary it.
- Words: delve, tapestry, navigate, leverage (as verb), robust, vibrant, seamless, unlock (as noun), landscape, ecosystem (when used metaphorically), realm, journey, embark, foster (when used metaphorically).
- Hedging phrases: "It's worth noting", "It bears mentioning", "One thing to consider".
- Sentence-final intensifiers: "...and that matters.", "...and that's the point.", "...full stop."
- Conclusions that start with "In conclusion", "Ultimately", "At the end of the day".
- Three-item lists where the third item is the rhetorical kicker.
- Question-as-headline followed by the answer ("Why does this matter? Because...").
- Bullet lists in single posts. Use line breaks and white space instead.
- "Moreover", "Furthermore", "Additionally" as sentence starters.

ANTI-PATTERNS FOR THIS SPECIFIC ACCOUNT

- Do not use the word "thesis" more than once per post.
- Do not start posts with "Look,", "Listen,", or "Here's the thing,".
- Do not end posts with "Bullish" or "Bearish" as a one-word kicker.
- Do not reference "the algo" or X algorithm meta-commentary.
- Do not make price predictions or set price targets.

FORMAT TEMPLATES

Single post (~280 chars max):
  Line 1: the insight (≤ 100 chars)
  Blank line
  Lines 2-N: 2 to 4 supporting data points, each on its own line, with the tag for the relevant entity inline
  Blank line (optional)
  Last line: the implication (≤ 100 chars)

Thread (5-7 tweets):
  Tweet 1: the thesis. Single paragraph, no preamble.
  Tweets 2 to N-1: supporting evidence, one cluster of data per tweet. Plain prose, not numbered.
  Tweet N: either a question to the room or a one-line restatement of the thesis. Never a "follow me for more" CTA.

Reply / QT:
  1 to 3 lines.
  Adds a data point, an alternative interpretation, or a sharp question.
  Never just agrees. Never just praises.
  Tag the OP if the OP has an X account.

CALIBRATION EXEMPLARS

[Insert 3 to 5 top-performing prior posts here once the learning loop has data. For v1, use the four hand-drafted variants from the Q&A round (Variant B for singles, Thread Variant B).]
```

---

## 7. Anti-AI-writing post-process checklist

Run on every draft before it hits the review queue. Reject and regenerate if any apply:

| Check | Trigger | Action |
|---|---|---|
| Em-dash | Contains `—` or `–` | Replace with period or comma; regenerate if structure depends on it |
| Banned word | Contains any of: delve, tapestry, navigate, leverage, robust, vibrant, seamless, ecosystem (metaphor), landscape (metaphor), realm, journey | Flag for human review |
| "Not X, it's Y" structure | Regex match | Regenerate |
| Hashtag | Contains `#[A-Za-z]+` | Strip the hashtag, keep the rest |
| Bullet list in single post | Contains `^\s*[-*•]` lines outside a thread | Reformat to line breaks |
| Length | Single > 280 chars, thread tweet > 280 chars | Trim or split |
| Missing tag | Entity in story brief has X handle but isn't tagged in the draft | Inject tag |

---

## 8. Watchlist (v1)

Save as `/config/watchlist.json`. ~40 handles total.

**Voice models (high weight for reply/QT drafting):**
@imperiumpaper, @sebventures, @adcv_, @monetsupply, @francescoweb3, @definikola, @bobmurphyecon, @mcagney, @jessepollak, @zeusrwa, @talkintokens

**Newsfeeds:**
@RWAxyzNewswire (Telegram, primary), @rwa_xyz, @DefiLlama, @bubblemaps, @vaultsfyi

**Issuers (RWA-adjacent):**
@ondofinance, @maplefinance, @centrifuge, @goldfinch_fi, @realtplatform, @SuperstateInc, @openeden_X, @backed_fi, @swarm_markets

**Protocols:**
@sky_money, @MorphoLabs, @sparkdotfi, @aave, @eulerfinance, @gauntlet_

**TradFi entrants:**
@BlackRock, @Securitize, @franklintempleton, @Fidelity, @CircleConsumer, @BNYMellon, @JPMorgan, @WisdomTreeFunds

**Journalists / outlets:**
@MilkRoadDaily, @DefiantNews, @BanklessHQ, @CoinDesk, @TheBlock__, @rwa_io

Reply/QT candidate scoring weights tags from voice-models 2x, then issuers, then everyone else.

---

## 9. Graphics templates (custom chart library)

Standard chart types to support out of the gate, each with a saved matplotlib template:

1. **Single-metric time series** ("Tokenized treasury TVL, last 90 days")
2. **Stacked area** ("RWA category breakdown over time")
3. **Horizontal bar comparison** ("BUIDL vs. FOBXX vs. FYHXX, current AUM")
4. **Delta callout** ("This protocol absorbed $Y this week" with sparkline)
5. **Two-metric overlay** ("APY vs. TVL, scatter")

All inherit from `chart_base.py` which sets:
- Figure size 1200x675 (X card-optimized)
- Light theme palette
- Inter font
- Watermark + source line

---

## 10. Infrastructure setup

### 10.1 VPS choice

**Recommended: Fly.io** (low-friction deploys, good for Claude SDK long-running processes, scales to zero for cost). Alternative: Railway (similar) or Hetzner (cheapest, more setup).

### 10.2 Services to provision

| Service | Purpose | Cost estimate |
|---|---|---|
| Fly.io machines (2x shared-cpu-1x) | Workers + API + UI | $5-15/mo |
| Supabase (Postgres + storage) | Signals DB, drafts, graphics | Free tier OK at start |
| Cloudflare R2 | Graphics CDN (optional, can use Supabase storage) | <$1/mo |
| Alchemy | Onchain RPC + webhooks | Free tier OK |
| X API v2 Basic | Posting at 4-8/day | $100/mo (required for posting) |
| Anthropic API | Claude calls | $50-200/mo depending on volume |
| Telegram Bot (or MTProto client) | Newswire ingest | Free |
| Domain (optional) | Review UI | $10/yr |

Total: ~$160-330/mo at the target cadence.

### 10.3 Secrets needed

```
ANTHROPIC_API_KEY
X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET, X_BEARER_TOKEN
RWA_XYZ_API_KEY
ALCHEMY_API_KEY
TELEGRAM_API_ID, TELEGRAM_API_HASH (if using MTProto) or TELEGRAM_BOT_TOKEN
DEFILLAMA_API_KEY (optional, public endpoints work)
DATABASE_URL (Supabase)
SUPABASE_SERVICE_KEY (for storage)
REVIEW_UI_PASSWORD
```

### 10.4 Repo structure

```
defi-x-agent/
├── apps/
│   ├── workers/          # ingest, scorer, story-builder, drafter
│   ├── poster/           # X posting worker
│   └── review-ui/        # Next.js review queue
├── packages/
│   ├── agents/           # Claude Agent SDK definitions
│   ├── prompts/          # voice.md + format templates
│   ├── graphics/         # chart templates + Playwright runners
│   ├── db/               # Prisma or Drizzle schema + migrations
│   └── shared/           # types, utils
├── config/
│   ├── watchlist.json
│   └── thresholds.json
├── fly.toml
└── README.md
```

---

## 11. Build order (4-week plan)

### Week 1: Foundation

- [ ] Provision VPS, Supabase, Anthropic key, X dev account credentials
- [ ] Stand up Postgres schema (`signals`, `stories`, `drafts`, `scheduled_posts`, `posts`, `engagement`)
- [ ] Build RWA.xyz API ingest worker
- [ ] Build DeFiLlama ingest worker
- [ ] Build minimal materiality scorer (Claude prompt)
- [ ] Build draft generator with voice prompt v1 (no graphics yet, no thread support)
- [ ] Build review UI (one page, login-gated, three buttons)
- [ ] Wire up X poster (singles only)
- [ ] Manual end-to-end test: ingest a real story, approve a draft, post it

### Week 2: Multi-source + graphics

- [ ] Add RWAxyzNewswire Telegram ingest
- [ ] Add VaultsFYI ingest
- [ ] Add Bubblemaps + Alchemy onchain ingest (watch list of contracts)
- [ ] Build chart template library (5 chart types)
- [ ] Build Playwright screenshot runner for RWA.xyz / DeFiLlama / Bubblemaps
- [ ] Wire graphics into draft generator output
- [ ] Add thread support to draft generator + poster

### Week 3: Engagement

- [ ] Build X firehose poller for watchlist
- [ ] Build reply/QT drafter (uses same voice prompt with `format: reply`)
- [ ] Surface reply candidates in review UI
- [ ] Build hot-take generator (slow-day primary fallback, originality filter, daily 11am ET cron)
- [ ] Build scheduled-recap generator (weekly digest, daily top-5)
- [ ] Wire slow-day fallback chain: fresh news → hot take → recap (in priority order)

### Week 4: Hardening + learning

- [ ] Add engagement puller (24h + 7d)
- [ ] Build exemplar / anti-exemplar storage and inject into prompts
- [ ] Run anti-AI-writing checklist as a hard post-process
- [ ] Add observability: Sentry for errors, simple dashboard for signal volume + post throughput
- [ ] Backup / restore for Postgres
- [ ] Document runbook (how to pause posting, how to adjust thresholds, how to retrain voice)

---

## 12. Open questions / decisions deferred

1. **X API tier:** Basic ($100/mo) supports the target cadence, but Pro ($5K/mo) gives firehose access for watchlist polling. Start on Basic, poll user timelines individually, upgrade only if rate-limited.
2. **Telegram ingest method:** Bot API only sees channels the bot is added to. RWAxyzNewswire is public, so MTProto via Telethon as a regular client account is simpler. Decision: use Telethon, register a throwaway Telegram account for the agent.
3. **Reply auto-fire:** all replies still gate through the review queue per the current preference. Revisit after 2 months of data once we trust the reply drafter.
4. **Image generation for non-chart graphics:** if we want occasional editorial graphics (not data charts), consider an image gen step. Out of scope for v1.
5. **Multi-account support:** v1 is single account (@jacksonblau). If the agent gets good, it could be extended to a roster, but that is post-launch.
6. **Bubblemaps API access:** unclear if their public API is sufficient. If not, fall back to Playwright scraping on a 4h cadence with their permission.

---

## 13. Today's-news test posts (for v1 calibration)

Locked drafts from the Q&A rounds, ready to be the first calibration examples in the prompt:

**Single (Variant B):**

> The interesting part of BlackRock's $7B onchain filing isn't the AUM.
>
> It's that BNY Mellon Investment Servicing is the transfer agent, and the official ownership records live on Ethereum.
>
> A regulated transfer agent treating an L1 as canonical state. That's a precedent.
>
> Every tokenized MMF after this gets to point at this filing and say "we're doing what @BlackRock got cleared to do."
>
> The bottleneck on RWAs was never demand. It was who has authority to call the chain the source of truth. This answers it.

**Thread (Variant B, argument-first):**

> 1. The $7B BlackRock filing is being read as a size story. It's a sovereignty story.
> 2. @BNYMellon Investment Servicing is the transfer agent. Ownership records live on Ethereum. A regulated transfer agent is treating a public L1 as canonical state.
> 3. That answers the question every RWA team has been quietly asking for two years: who has authority to call the chain the source of truth.
> 4. Answer: a BlackRock counterparty, with SEC sign-off, at a $7B AUM launch.
> 5. Every tokenized MMF that comes after gets to point at this filing. The compliance unlock is the moat, not the rails.

These get pasted into `/prompts/voice.md` as the v1 exemplars under the "CALIBRATION EXEMPLARS" section.

---

## 14. Next actions

1. Confirm the X dev account is on Basic tier ($100/mo) with read + write scopes.
2. Provision Fly.io, Supabase, Alchemy, Anthropic keys.
3. Spin up the repo from the structure in Section 10.4.
4. Start Week 1 work; first end-to-end demo target = 5 working days from kickoff.

Sources used in scoping the news examples:
- [RWA.xyz](https://app.rwa.xyz/)
- [BlackRock deepens tokenization push with new onchain fund offerings — CoinDesk](https://www.coindesk.com/business/2026/05/09/blackrock-deepens-tokenization-push-with-new-onchain-fund-offerings)
- [Ondo Finance Surges 23% As RWA Tokenization Crosses $20B On-Chain](https://yellow.com/research/ondo-finance-rwa-tokenization-20-billion-2026)
