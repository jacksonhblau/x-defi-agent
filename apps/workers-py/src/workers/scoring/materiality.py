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
- category: one of 'treasury_flow', 'new_deploy', 'governance', 'yield_shift', 'x_chatter', 'recap_seed'
- rationale: one sentence explaining the score, no fluff

Calibration:
- 90+: would be a top headline on RWAxyzNewswire or DefiLlama Twitter
- 70-89: meaningful enough to post about with context
- 50-69: borderline; only worth posting if combined with another signal
- below 50: ignore

Be skeptical. Generic 'TVL went up' signals score low unless the magnitude or actor is notable. New deploys from known issuers (BlackRock, Ondo, Maple, Centrifuge, Goldfinch, Superstate, OpenEden, RealT) get a novelty bonus.

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


def score_unprocessed(limit: int = 20) -> int:
    """Score up to N unprocessed signals. Returns the count actually scored."""
    rows = db.fetch_unprocessed_signals(limit=limit)
    scored = 0
    for row in rows:
        result = score_signal(row)
        db.mark_signal_scored(
            row["id"],
            materiality=int(result.get("score", 0)),
            novelty=int(result.get("novelty", 0)),
            notes=result.get("rationale", "")[:500],
        )
        scored += 1
    return scored
