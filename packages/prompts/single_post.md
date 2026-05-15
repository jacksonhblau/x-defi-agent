# Format: single post

Hard limit: 280 characters total.

## Hard requirements (algo-refit)

1. **Lead with a first-person frame** ("I think", "I keep reading", "I'm watching", "The thing I can't shake is…"). Detached third-person leads are rejected by the anti-AI checker.
2. At least one specific number or named fact from the story brief's `key_data_points`. No floating assertions.
3. No claim of personal action (built, shipped, closed, raised, attended, met, bought, sold, holds-a-position-in) unless the action exactly matches an entry in `personal_facts.json` with `approved_to_reference: true`.
4. No generic engagement-bait closer ("thoughts?", "agree?"). A real question following a defended claim is fine.
5. The full voice ruleset in `voice.md` applies.

## What the agent generates

The draft generator produces **3 single-post variants** so the review queue offers a real choice:
- **Variant A — unconventional read:** "I keep seeing X read as Y. I think it's Z." Defended by one specific number.
- **Variant B — held-view application:** lead from one of `views_i_hold_strongly`. "I think the real story is X." Defended by the mechanism plus one number.
- **Variant C — data anomaly:** "I keep coming back to one number from this filing: $X." Defended by the implication.

All three variants must pass the anti-AI checker independently.

Structure:

```
[insight line, ≤ 100 chars]

[supporting data point 1 with @tag if relevant]
[supporting data point 2 with @tag if relevant]
(optional: 1 more)

[implication line, ≤ 100 chars]
```

Rules:
- Insight line first. Do not preamble with "Breaking:" or "Just in:".
- Each supporting line is one fact. No conjunctions stacking multiple facts.
- Implication line is optional if the insight already implies it.
- Blank lines between sections are intentional. Do not collapse them.
- No hashtags.
- Tag every entity with an X handle.
- The post MUST include at least one handle from `source_handles` to credit the data source. Work it into a sentence naturally. No parenthetical citations.

Output the final tweet text only. No commentary, no quotes around it, no markdown.
