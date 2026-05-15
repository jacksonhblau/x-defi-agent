"""Materiality scorer. Wraps Claude with a tight prompt that returns a JSON score."""

from __future__ import annotations

import json
from typing import Any

from .. import db, llm


SYSTEM_PROMPT = """You are a materiality scorer for an RWA / tokenized-DeFi analyst account on X.

You receive one normalized signal (an event observed on a public data source) and decide whether it's worth turning into an X post.

Return a single JSON object with these fields:
- score: integer 0-100 (overall materiality)
- novelty: integer 0-100 (how unique this is vs. the consensus story)
- category: one of 'treasury_flow', 'new_deploy', 'governance', 'yield_shift', 'x_chatter', 'recap_seed', 'personal_take'
- rationale: one sentence explaining the score, no fluff
- touches_view: boolean — true when the signal touches one of Jackson's views_i_hold_strongly (vault infrastructure, tokenized private credit / ABS, onchain-native vs digital twins)

Calibration:
- 90+: would be a top headline on RWAxyzNewswire or DefiLlama Twitter
- 70-89: meaningful enough to post about with context
- 50-69: borderline; only worth posting if combined with another signal
- below 50: ignore

Bonuses (applied by the wrapping code, not by you):
- +10 novelty when the signal touches a view Jackson already holds — the agent should preferentially write about positions Jackson can defend without inventing new claims.

Be skeptical. Generic 'TVL went up' signals score low unless the magnitude or actor is notable. New deploys from known issuers (BlackRock, Ondo, Maple, Centrifuge, Goldfinch, Superstate, OpenEden, RealT) get a novelty bonus.

The 'personal_take' category is reserved for signals that would naturally produce a first-person Jackson opinion piece — typically a thesis touching one of Jackson's held views with fresh data attached. Use sparingly.

Output JSON only. No prose, no markdown fence."""


def score_signal(signal: dict[str, Any]) -> dict[str, Any]:
    """Score one signal. Returns the parsed JSON response."""
    user = json.dumps(
        {
            "source": signal.get("source"),
            "signal_type": signal.get("signal_type"),
            "entity": signal.get("entity"),
            "observed_at": signal.get("observed_at").isoformat()
            if signal.get("observed_at")
            else None,
            "payload": signal.get("payload"),
        },
        default=str,
    )
    return llm.complete_json(system=SYSTEM_PROMPT, user=user, max_tokens=400, temperature=0.2)


VIEW_BONUS_NOVELTY = 10


def _apply_view_bonus(result: dict[str, Any]) -> dict[str, Any]:
    """If the scorer flagged `touches_view: true`, bump novelty by VIEW_BONUS_NOVELTY.

    Algo-refit (May 2026): the agent preferentially drafts stories that touch
    Jackson's pre-declared views because those are the ones the anti-AI checker
    can defend without inventing personal actions.
    """
    if not isinstance(result, dict):
        return result
    if result.get("touches_view"):
        novelty = int(result.get("novelty", 0) or 0)
        result["novelty"] = min(100, novelty + VIEW_BONUS_NOVELTY)
        result["novelty_bonus_applied"] = VIEW_BONUS_NOVELTY
    return result


def score_unprocessed(limit: int = 20) -> int:
    """Score up to N unprocessed signals. Returns the count actually scored."""
    rows = db.fetch_unprocessed_signals(limit=limit)
    scored = 0
    for row in rows:
        result = _apply_view_bonus(score_signal(row))
        db.mark_signal_scored(
            row["id"],
            materiality=int(result.get("score", 0)),
            novelty=int(result.get("novelty", 0)),
            notes=result.get("rationale", "")[:500],
        )
        scored += 1
    return scored
