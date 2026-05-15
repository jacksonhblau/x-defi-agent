# X Ranking Algorithm — Signal Reference (May 2026)

Source of truth: https://github.com/xai-org/x-algorithm (published Jan 2026 by the X Engineering team, updated May 15, 2026).

This document is the working reference the DeFi X Poster agent uses to (a) score drafts against the algo's incentives before they hit the review queue, and (b) shape the voice prompt so generations skew toward what gets pushed.

---

## 1. Heavy-rail predicted-action weights

The Heavy Ranker predicts a probability for each of ~15 actions on every candidate post, then combines them with fixed weights into a single score. The widely-cited simplified formula derived from the published weights is:

```
score =
    1.0  * P(favorite)
 + 13.5  * P(reply)
 + 20.0  * P(repost)
 + 12.0  * P(profile_click)
 + 11.0  * P(link_click)
 + 10.0  * P(bookmark)
 + 10.0  * P(dwell)
 + 75.0  * P(author_replies_to_replier)    // the single largest positive signal
 -  3.0  * P(block_author)
 -  X    * P(mute_author / not_interested / report)
```

**Implications for our agent:**

- **Replies and reposts are ~13–20× a like.** Drafts should explicitly leave openings for reply (a question that has a real answer, an arguable claim, a number that invites a counter-number).
- **Bookmarks (×10) reward save-worthy structure.** Numbered playbooks, "screenshot this" calls, dense data tables, and long-form breakdowns over 1500 chars all increase save rate.
- **Dwell (×10) rewards posts that take time to read.** Long-form (>2 min read, which is roughly >1500 chars for normal prose) carries an additional dwell weight on top of base dwell.
- **Author replying back is +75 per replier engaged.** This is by far the biggest lever — the agent must surface incoming replies fast so Jackson (or the agent under review) can respond inside the first 30 min.
- **Negative signals matter more than they look.** A single block is −3 vs a like at +1; one block roughly cancels three likes. Drafts that read as bait, spam, or low-effort are net-negative because the marginal "not interested" tap subtracts more than the marginal like adds.

## 2. Candidate generation and out-of-network discovery

- **SimClusters + TwHIN embeddings** drive out-of-network candidate generation. Posts the model thinks "look like" content the user already engaged with surface even from accounts they don't follow.
- **First-person concrete posts cluster differently** in embedding space than abstract third-person market commentary. The former cluster with builder/operator content (high-engagement); the latter cluster with newsletter-style content (lower engagement on average).
- **Media-bearing posts are flagged in the Hydrator stage** and receive different downstream feature values — photo expand and video view become available as positive signals, which abstract text posts can never earn.
- **Out-of-network reach has been weighted up** in the May 2026 commit window. Smaller accounts with original takes can now break out of their follower graph if the embedding is distinctive.

## 3. Penalties (heuristic rails that run before or alongside the ranker)

- **Author dilution / repetitive posting:** posts from authors who post very frequently in a short window get a partial discount in the candidate ranker. The threshold isn't a hard number in the public code but ~5+ posts/day from one author with similar content triggers measurable suppression.
- **Duplicate / near-duplicate content:** the dedup classifier checks against the author's last 30 days and against the global trending text. Near-duplicates get heavily down-weighted.
- **Engagement bait closers** ("what do you think?", "thoughts?", "agree or disagree?" without a substantive setup) are detected and discounted. Real questions that follow a substantive claim are fine.
- **External link penalty** is real but smaller than commonly cited. Links to high-quality domains (gov, edu, primary sources, established media) are penalized less than to low-quality referrers. Putting the link in a reply rather than the lead post recovers most of the lost signal.
- **"Not interested" taps and mutes** are the single most damaging signals. They feed both the user-level filter and the global author reputation score.

## 4. Media handling specifics

The Hydrator emits a `has_media` flag plus per-asset features (photo count, video duration, video qualified-view fraction). The ranker can then condition on these:

- **Photo expand** has its own predicted probability and weight. Native photos out-perform photos linked in replies.
- **Video qualified views** (defined as ≥50% watched or ≥6s if shorter) and **completion rate** are scored separately. A 45s video watched to completion beats a 5-minute video abandoned at 10s.
- **Aspect ratio matters in practice.** 16:9 and 1:1 perform well in-feed; 9:16 vertical wins inside the video tab but not the main feed.

## 5. What this means for the DeFi X Poster agent

Concretely:

1. **Every post must ship with a media asset** — photo for singles/replies, short native video for threads and high-materiality news.
2. **First-person specific voice beats third-person abstract** for embedding clustering, dwell, and out-of-network reach.
3. **Drafts must be opinions defended with evidence**, not statements of fact about the author's actions unless those actions are verifiable from a `personal_facts` ledger.
4. **Schedule a "reply-window worker" that fires 5/15/30 min after a post** to surface incoming replies into the review queue for fast author response (chasing the +75 weight).
5. **Cap posting cadence** at the lower end of the current 4–8/day band (5 ceiling) when no story is genuinely material, to stay below the author-dilution rail.
6. **Long-form (>1500 char) variants** should be generated for high-materiality stories specifically because dwell-time weighting kicks in harder.
7. **Bookmark-bait structure** (numbered, screenshottable, dense) is the right move for thread tweet #1 and for the long-form variant.

---

## 6. Sanity check before shipping

Before any draft hits the review queue, run a heuristic "predicted score" pass:

- Has media? (+ large)
- First-person specific, with at least one "I/I'm/I've" referring to Jackson's view? (required)
- One concrete number per ~80 chars of prose? (+ medium)
- A natural reply-opener (substantive question or arguable claim) in the body? (+ medium)
- Length ≥ 800 chars for non-reply formats? (+ small for dwell)
- Any forbidden patterns from the anti-AI checklist? (gate, not score)
- Any "I built / I shipped / I closed / I raised" verb not present in `personal_facts.json`? (gate)

Drafts below a configurable threshold get regenerated up to N times before being downgraded to a "for-review only, don't auto-suggest" state.
