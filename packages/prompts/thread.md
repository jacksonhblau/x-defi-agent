# Format: thread (argument-first)

3 to 7 tweets total. Each tweet ≤ 280 chars.

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
