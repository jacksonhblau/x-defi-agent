# Prompt — paste this into a fresh Cowork or Claude Code session

> Run from inside the `DeFi X Poster` workspace folder. The session needs file write access to that folder. If you're in Claude Code, `cd` to the project root first. If you're in Cowork, select the `DeFi X Poster` folder when prompted.

---

You are working on the DeFi X Posting Agent in this directory. Read these four files first, in order, before you touch anything:

1. `ALGO_REFIT_PLAN.md` — the spec for this work.
2. `docs/x_algorithm_2026_signals.md` — the X ranking algo reference; this is the "why" behind every change.
3. `docs/higgsfield_integration.md` — Higgsfield is the editorial / concept-imagery path.
4. `docs/canva_integration.md` — Canva is the data-led path: brand templates autofilled with real issuer logos and RWA.xyz data.

Then read `BUILD_PLAN.md` for the existing agent architecture, and skim:
- `packages/prompts/hot_take.md` and `reply.md` (existing voice files)
- `config/watchlist.json` and `config/thresholds.json` (existing config)
- `config/personal_facts.example.json` (new, schema only — do not assume content)
- `apps/workers-py/src/workers/scoring/materiality.py` (the only worker that is more than a stub)
- `data/drafts/91751dcf-9408-43a5-b0e2-b11c06775efa.json` (a real prior draft, will be the test fixture)

## Your goal

Refit the agent to match the May 2026 X algorithm and three voice constraints:

1. **Every draft ships with at least one generated media asset.** The graphics dispatcher routes between Higgsfield (editorial / concept imagery) and Canva (data-led brand templates) based on `story_brief.graphic_kind`. High-materiality posts may produce two assets — typically a Higgsfield hero plus a Canva data card. A draft with zero `media_assets` rows in `ready` status is not allowed to reach the review queue.
2. **First-person specific voice everywhere.** Singles, threads, replies, recaps, long-form — every format leads with or contains an "I" frame. Detached third-person market-commentary voice is rejected by the anti-AI checker.
3. **No hallucinated personal actions.** The agent never claims Jackson built, shipped, closed, raised, attended, met, spoke-with, bought, sold, or holds-a-position-in anything, unless the verb+object matches an entry in `personal_facts.json` with `approved_to_reference: true`. All other content is framed as views ("I read this as…", "I think…", "I'm watching X because…") backed by data points from the story brief.

The full change spec lives in `ALGO_REFIT_PLAN.md`. Follow its "Changes by file" section. Implement in the order listed under "Build order".

## How to work

- Start by surfacing the seven "Open decisions" in `ALGO_REFIT_PLAN.md` to Jackson as a single batched question (use the AskUserQuestion tool, one question per decision, recommended defaults pre-selected). Use the recommended defaults if Jackson doesn't pick one; don't block on them.
- Use a task list to track each item in "Changes by file" and "Build order". Mark items in_progress when you start and completed when each passes the verification step listed at the bottom of the plan.
- Prefer small commits with clear messages over one giant push.
- For Higgsfield: try the MCP path first (`https://mcp.higgsfield.ai/mcp`). If the MCP server isn't reachable from this runtime, fall back to the REST option documented in `docs/higgsfield_integration.md §1B` and ask Jackson for credentials at that point. Don't silently no-op the media step.
- For Canva: in a Cowork or Claude Code dev session, use the Canva MCP server already wired into the runtime (tools prefixed `mcp__96182097-…`). For production, use Canva Connect REST. The pass-one templates (T1, T3, T5, T6) need to be created by Jackson inside Canva itself, using the exact field-name schemas in `docs/canva_integration.md §3`. Once they exist, you read their template IDs via `search-brand-templates`, write the IDs into the `canva_templates` table, and the autofill flow takes over. If Jackson hasn't built the templates yet when you reach build step 4, surface that as a blocker, generate a one-page brief for each template (visual layout description + complete field list) that Jackson can use as a Canva spec, and proceed to other build steps until the templates exist.
- For the anti-AI checks, write unit tests against the test fixtures listed in the plan's verification section. The bar is: caught all three constructed bad drafts, passed the existing real one.
- Don't modify `BUILD_PLAN.md`. It's the spec for the original build; this work layers on top.
- Don't edit any file under `.git/`, `.venv/`, or `__pycache__/`.

## Style and voice

The agent you are building writes in first-person as Jackson Blau (@jacksonblau). When you write or update voice prompts, the calibration exemplars at `BUILD_PLAN.md §13` are good, but they're third-person. Rewrite at least one as a first-person variant inside `voice.md`'s "CALIBRATION EXEMPLARS" section. Example transformation:

Original (third-person, current `BUILD_PLAN.md §13` Single Variant B):
> The interesting part of BlackRock's $7B onchain filing isn't the AUM.
> It's that BNY Mellon Investment Servicing is the transfer agent...

First-person rewrite:
> I keep seeing the BlackRock $7B filing read as a size story.
> I think it's a sovereignty story.
> BNY Mellon Investment Servicing is the named transfer agent. Ownership records live on Ethereum. A regulated transfer agent is treating an L1 as canonical state.
> That's what every tokenized MMF after this gets to point at.
> The bottleneck on RWAs was never demand. I'm pretty sure it was always: who has the authority to call the chain the source of truth. This filing answers it.

Notice: first-person ("I keep seeing", "I think", "I'm pretty sure"), but every factual claim is grounded in the public filing — no hallucinated personal action.

## What "done" looks like

- All the items in `ALGO_REFIT_PLAN.md` "Changes by file" are implemented.
- The verification checklist at the bottom of the plan passes end-to-end on the BlackRock BUIDL fixture (Higgsfield editorial + Canva T6 deploy card both attached).
- A separate end-to-end test on a synthetic "tokenized private credit adoption" brief renders Canva T1 correctly with five real issuer logos resolved from the local bundle.
- `media_assets` table exists and has rows from both a real Higgsfield call and a real Canva autofill call.
- `canva_templates` table is seeded with the four pass-one template IDs Jackson created in Canva (T1, T3, T5, T6). If Jackson hasn't built the templates yet, leave that table empty and document the blocker.
- `packages/graphics/logos/issuers/` contains the initial ~20 SVG bundle.
- `personal_facts.example.json` is unchanged; a new `personal_facts.json` is NOT created by you — that's Jackson's to fill in. The anti-AI check should error gracefully (with a clear "personal_facts.json not configured" message) if Jackson runs the agent before populating it.
- A short `CHANGELOG_ALGO_REFIT.md` at the project root summarizing every file changed, with the test results from the verification step.

If you get stuck on something Jackson didn't pre-decide, ask. Don't guess on architecture decisions; defaults are documented in the plan for the seven known open decisions only.
