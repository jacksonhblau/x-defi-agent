# Format: hot take (slow-day fallback)

Triggers when no signal in the last 6 hours clears the materiality threshold. The agent looks at the prior 7 days of stories and onchain data, then writes a non-obvious take.

## Input

You are given a body of recent stories (last 7 days) and onchain data deltas (TVL, APYs, treasury flows, cluster changes). None of these individually crossed the news bar. You must find a connection or pattern that hasn't been said.

## Hard requirements

1. The take must reference at least 3 distinct data points from the input.
2. The take must NOT restate the surface news from any single story. The point is the connection.
3. The take must NOT restate any of @jacksonblau's recent posts (last 30 days, provided in the input).
4. The take must NOT restate any post from the voice-model influencers (provided in the input as `recent_voice_model_posts`).
5. The take must be falsifiable. If someone disagreed, they should be able to point at a specific fact.

## Output format

Default to a single post per `single_post.md`. Output a thread only if the connection requires more than 280 chars to defend.

## Originality filter

After generating, self-assess: "Has anyone in the input said something close to this in the last 30 days?" If yes, regenerate from a different angle. Up to 3 regeneration attempts; if all fail, return the literal string `NO_TAKE_AVAILABLE` and the agent will fall back to recap content.
