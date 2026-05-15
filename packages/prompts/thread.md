# Format: thread (argument-first)

3 to 7 tweets total. Each tweet ≤ 280 chars.

## Hard requirements (algo-refit)

1. **Tweet 1 leads with a first-person frame** ("I keep reading X as Y. I think it's Z.") AND states the thesis in one paragraph. No preamble.
2. At least one specific number or named fact per tweet. No floating assertions.
3. No claim of personal action unless the action matches an entry in `personal_facts.json` with `approved_to_reference: true`.
4. Last tweet is either (a) a one-line restatement of the thesis, or (b) a substantive question — a named counter-position, a specific number to argue against, or a falsifiable prediction. No generic engagement-bait closers.
5. The full voice ruleset in `voice.md` applies on every tweet.

## Graphics dispatch

If `materiality_score >= 80` AND `graphic_kind == "editorial"`, the graphics dispatcher attaches a Higgsfield short video (6–12s) in addition to or instead of the Canva data card. Otherwise an editorial image (Flux 2 / Soul 2.0) or a Canva data card per the dispatcher's routing in `docs/canva_integration.md §1`.

## Long-form variant (≥ 1500 chars, materiality ≥ 80)

When `materiality_score >= 80`, the draft generator additionally produces a long-form variant in the X "long post" format. Structure:
- **Lede** (≤ 200 chars): the first-person take.
- **Body** (4–6 paragraphs): each anchored by one `key_data_point`. Paragraphs 150–300 chars each.
- **Close** (≤ 200 chars): a falsifiable prediction OR a sharp named-counter-position question.

Total length 1500–3000 chars. This clears the 2-minute dwell bonus described in `docs/x_algorithm_2026_signals.md §1` and earns extra bookmark weight.

Structure:

```
Tweet 1: the thesis. Single paragraph. Reads as a standalone post.
Tweet 2: first piece of evidence. Specific number or named entity.
Tweet 3: second piece of evidence. Different angle or scale.
Tweet 4: third piece of evidence. Optional. Counterargument or scope-narrowing fact.
Tweet 5: implication or comparison.
Tweet N: closing. Either a one-line restatement of the thesis or a question to the room. Never a CTA. Never "follow for more".
```

Rules:
- No "1/", "2/", "3/" numbered prefixes.
- Tweet 1 must make sense as a standalone post. If someone only reads tweet 1, they should get the take.
- Each tweet is one paragraph. No multi-paragraph tweets.
- Tag every entity with an X handle.
- No hashtags.
- The thread MUST include at least one handle from `source_handles` to credit the data source. Put it in tweet 1 or any other single tweet, never repeated across multiple tweets. Work it into prose naturally; no parenthetical citations.
- Vary sentence length within and across tweets.

Output as a JSON array of strings, one per tweet, in order. No commentary, no markdown.

Example output:
```json
["The $7B BlackRock filing is being read as a size story. It's a sovereignty story.", "@BNYMellon Investment Servicing is the transfer agent. Ownership records live on Ethereum.", "That answers the question every RWA team has been quietly asking for two years: who has authority to call the chain the source of truth.", "Answer: a BlackRock counterparty, with SEC sign-off, at a $7B AUM launch.", "Every tokenized MMF that comes after gets to point at this filing. The compliance unlock is the moat, not the rails."]
```
