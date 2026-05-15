"""Reply-window worker — surfaces incoming replies for fast author-followup.

The X algorithm awards +75 weight when the author replies to a replier. This
is the single biggest lever in the algo's heavy-rail formula (see
docs/x_algorithm_2026_signals.md §1). This worker fires at 5/15/30 min after
every published post, polls the reply tree, scores each new reply, and
inserts the top N (default 3) into the review queue as
`format=author_followup_reply` candidates.

The X API client is plug-injected so this module remains testable without
a live X connection. In production, pass `workers.poster.x_client`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional

log = logging.getLogger(__name__)

DEFAULT_WINDOWS_MIN = [5, 15, 30]
DEFAULT_MAX_FOLLOWUPS = 3
DEFAULT_VOICE_MODEL_WEIGHT = 2.0


def _load_watchlist(path: Optional[str] = None) -> dict[str, Any]:
    if not path:
        import os
        path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "..", "..", "config", "watchlist.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}


def is_voice_model_handle(handle: str, watchlist: Optional[dict[str, Any]] = None) -> bool:
    """Return True if `handle` (with or without leading @) is in the voice_models list."""
    wl = watchlist or _load_watchlist()
    voice = (wl.get("voice_models") or {}).get("handles") or []
    norm = handle.lstrip("@").lower()
    return any(h.lower() == norm for h in voice)


def score_reply(reply_text: str, *, is_voice_model: bool = False) -> int:
    """Score a reply 0-100 on substantive-and-relevant.

    Heuristic: length (longer → more substantive), question marks, named entities,
    and the voice-model multiplier from watchlist.json.
    """
    text = (reply_text or "").strip()
    if not text:
        return 0
    score = 0
    # Length: 0–30 chars = 5, 30–80 = 15, 80–160 = 25, 160+ = 35
    n = len(text)
    if n >= 160:
        score += 35
    elif n >= 80:
        score += 25
    elif n >= 30:
        score += 15
    else:
        score += 5
    # Question mark in the reply suggests it's a real question to engage with.
    if "?" in text:
        score += 15
    # Named entity (@-handle) suggests they're tagging someone relevant.
    if "@" in text:
        score += 10
    # Specific number suggests data-grounded reply.
    import re
    if re.search(r"\$\d|\d+%", text):
        score += 15
    # Voice-model boost.
    if is_voice_model:
        score = int(score * DEFAULT_VOICE_MODEL_WEIGHT)
    return max(0, min(100, score))


# ---------- X API contract ----------

# The X client must expose: fetch_post_replies(post_id, since=None) -> list[dict]
# where each dict has at minimum: tweet_id, author_handle, text, created_at.

FetchRepliesFn = Callable[..., list[dict[str, Any]]]


# ---------- Top-level entry ----------

def poll_window(
    *,
    parent_post_id: str,
    parent_published_at: datetime,
    window_min: int,
    fetch_replies: FetchRepliesFn,
    db_insert_candidate: Callable[..., None],
    watchlist: Optional[dict[str, Any]] = None,
    max_followups: int = DEFAULT_MAX_FOLLOWUPS,
) -> int:
    """Poll a single reply window. Returns the number of new candidates inserted."""
    cutoff = parent_published_at + timedelta(minutes=window_min)
    if datetime.now(timezone.utc) < cutoff - timedelta(seconds=30):
        log.debug("Window %d min not yet elapsed for %s", window_min, parent_post_id)
        return 0

    replies = fetch_replies(post_id=parent_post_id, since=parent_published_at)
    if not replies:
        return 0

    watchlist = watchlist or _load_watchlist()
    scored = []
    for r in replies:
        author = (r.get("author_handle") or "").lstrip("@")
        text = r.get("text") or ""
        vm = is_voice_model_handle(author, watchlist)
        s = score_reply(text, is_voice_model=vm)
        scored.append({**r, "score": s, "is_voice_model": vm})

    scored.sort(key=lambda r: r["score"], reverse=True)
    top = scored[:max_followups]
    inserted = 0
    for r in top:
        try:
            db_insert_candidate(
                parent_post_id=parent_post_id,
                reply_tweet_id=r["tweet_id"],
                reply_author=r.get("author_handle", ""),
                reply_text=r.get("text", ""),
                detected_at_min=window_min,
                is_voice_model=r["is_voice_model"],
                score=r["score"],
            )
            inserted += 1
        except Exception as e:  # noqa: BLE001
            # Likely a unique-constraint hit on (parent_post_id, reply_tweet_id).
            log.debug("Insert skipped (likely duplicate): %s", e)
    log.info("reply_window: post=%s window=%dmin inserted=%d/%d", parent_post_id, window_min, inserted, len(replies))
    return inserted


def run_for_recent_posts(
    *,
    fetch_recent_published_posts: Callable[..., list[dict[str, Any]]],
    fetch_replies: FetchRepliesFn,
    db_insert_candidate: Callable[..., None],
    windows_min: list[int] = DEFAULT_WINDOWS_MIN,
    lookback_hours: int = 1,
) -> dict[str, int]:
    """Run the reply-window poller across all recently-published posts.

    Returns a dict of {window_label: insertions_count}.
    """
    posts = fetch_recent_published_posts(within_hours=lookback_hours)
    totals = {f"{w}min": 0 for w in windows_min}
    for post in posts:
        pid = post["post_id"]
        pub_at = post["published_at"]
        if isinstance(pub_at, str):
            pub_at = datetime.fromisoformat(pub_at.replace("Z", "+00:00"))
        for w in windows_min:
            n = poll_window(
                parent_post_id=pid,
                parent_published_at=pub_at,
                window_min=w,
                fetch_replies=fetch_replies,
                db_insert_candidate=db_insert_candidate,
            )
            totals[f"{w}min"] += n
    return totals
