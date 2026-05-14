"""Draft generator. Loads voice.md + format prompt, sends story brief, gets draft text."""

from __future__ import annotations

import json
import re
from typing import Any

from .. import config, llm


# AI-tell anti-patterns. Applied as a post-process check after generation.
BANNED_WORDS = [
    "delve", "tapestry", "navigate", "leverage", "robust", "vibrant",
    "seamless", "ecosystem", "landscape", "realm", "journey", "embark", "foster",
]
BANNED_PATTERNS = [
    r"—",                            # em-dash
    r"\bIt's not just\b.*\bit's\b",  # "It's not just X, it's Y"
    r"^Look,",                       # "Look,"
    r"^Listen,",                     # "Listen,"
    r"^Here's the thing,",
    r"#[A-Za-z][A-Za-z0-9_]*",       # hashtag
    r"\bMoreover\b",
    r"\bFurthermore\b",
    r"\bAdditionally\b",
    r"In conclusion",
    r"It's worth noting",
    r"It bears mentioning",
]

# "Punctuated contrast kicker" — a complete clause followed by a short fragment
# that negates, contrasts with, or emphasizes the prior clause. One of the strongest
# AI tells. See packages/prompts/voice.md for examples.
#
# We catch the most common surface forms. The regex looks for:
#   [. , or ;]
#   [whitespace]
#   [optional capital letter]
#   [one of: Not / Real / Big / Game / End / Welcome / Plain / And / Or / But / Sounds / Just]
#   [followed by ≤ 4 more short words]
#   [terminal punctuation: . ? or !]
#
# We're deliberately conservative — false positives just trigger regeneration,
# which is cheap. Better to flag too much than let kickers ship.
KICKER_PATTERNS = [
    # "X. Not Y." or "X, not Y." or "X; not Y." — the canonical case
    r"[.,;]\s+[Nn]ot\s+(?:a |an |the )?[A-Za-z][A-Za-z'-]{1,15}(?:\s[A-Za-z][A-Za-z'-]{1,15}){0,2}[.!?]",
    # Sentence-final fragments that are common AI kickers
    r"[.,;]\s+Real\s+\w{2,15}[.!?]",            # "Real money." "Real capital."
    r"[.,;]\s+Big\s+\w{2,15}[.!?]",             # "Big number." "Big move."
    r"[.,;]\s+Game\s+(over|changer|on)[.!?]",   # "Game over." "Game changer."
    r"[.,;]\s+End\s+of\s+\w{2,15}[.!?]",        # "End of story." "End of debate."
    r"[.,;]\s+Welcome\s+to\s+[^.!?]{1,30}[.!?]",# "Welcome to the new..."
    r"[.,;]\s+Plain\s+and\s+simple[.!?]",
    r"[.,;]\s+Just\s+\w{2,12}[.!?]",            # "Just math." "Just facts."
    r"[.,;]\s+Sounds\s+familiar[.!?]",
    r"[.,;]\s+Make\s+it\s+make\s+sense[.!?]",
    # "And X." / "But X." / "Or X." as standalone fragments (≤ 3 words after the conjunction)
    r"\.\s+(And|But|Or)\s+\w{2,12}[.!?]\s*$",
    r"\.\s+(And|But|Or)\s+\w{2,12}\s+\w{2,12}[.!?]\s*$",
]


def check_ai_tells(text: str) -> list[str]:
    """Return a list of flags. Empty list means clean."""
    flags: list[str] = []
    lower = text.lower()
    for word in BANNED_WORDS:
        if re.search(rf"\b{re.escape(word)}\b", lower):
            flags.append(f"banned_word:{word}")
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, text, re.MULTILINE | re.IGNORECASE):
            flags.append(f"banned_pattern:{pattern}")
    for pattern in KICKER_PATTERNS:
        m = re.search(pattern, text, re.MULTILINE)
        if m:
            flags.append(f"contrast_kicker:{m.group(0).strip()!r}")
    return flags


def check_source_attribution(text: str, source_handles: list[str]) -> list[str]:
    """Verify at least one required source handle is present in the post body.

    If source_handles is empty, attribution isn't required and we return no flags.
    """
    if not source_handles:
        return []
    lower = text.lower()
    for handle in source_handles:
        if handle.lower() in lower:
            return []
    return [f"missing_source_attribution:expected one of {source_handles}"]


def check_no_leading_mention(text: str) -> list[str]:
    """X suppresses reach on tweets starting with @-mentions (treated as directed replies).

    For single posts: the body must not start with @.
    For thread bodies (\n\n-joined string), only tweet 1 (before first \n\n) must not start with @.
    """
    first_tweet = text.split("\n\n", 1)[0].lstrip()
    if first_tweet.startswith("@"):
        return [f"leading_mention:'{first_tweet[:30]}...' — X will suppress this in the timeline"]
    return []


def regenerate_until_clean(
    generator_fn,
    *args,
    max_attempts: int = 3,
    **kwargs,
) -> dict[str, Any]:
    """Call a generator function and regenerate if any AI-tell flags fire.

    Up to max_attempts; if all attempts fail, return the last result with flags
    intact so the human reviewer sees what went wrong.
    """
    last = None
    for attempt in range(max_attempts):
        result = generator_fn(*args, **kwargs)
        if result.get("ai_check_passed"):
            return result
        last = result
    return last  # type: ignore[return-value]


def generate_single(story_brief: dict[str, Any]) -> dict[str, Any]:
    """Generate a single-post draft from a story brief."""
    voice = config.prompt("voice")
    fmt = config.prompt("single_post")
    system = f"{voice}\n\n---\n\n# Format instructions\n\n{fmt}"
    user = f"Story brief (JSON):\n```json\n{json.dumps(story_brief, indent=2, default=str)}\n```\n\nWrite the post."
    body = llm.complete(system=system, user=user, max_tokens=600, temperature=0.7).strip()
    source_handles = story_brief.get("source_handles", []) or []
    flags = (
        check_ai_tells(body)
        + check_source_attribution(body, source_handles)
        + check_no_leading_mention(body)
    )
    return {
        "format": "single",
        "body": body,
        "body_json": None,
        "ai_check_passed": len(flags) == 0,
        "ai_check_flags": flags,
    }


def generate_thread(story_brief: dict[str, Any]) -> dict[str, Any]:
    """Generate a thread draft. Expects JSON array output."""
    voice = config.prompt("voice")
    fmt = config.prompt("thread")
    system = f"{voice}\n\n---\n\n# Format instructions\n\n{fmt}"
    user = f"Story brief (JSON):\n```json\n{json.dumps(story_brief, indent=2, default=str)}\n```\n\nWrite the thread as a JSON array of strings."
    raw = llm.complete(system=system, user=user, max_tokens=1500, temperature=0.7).strip()
    # Tolerate ```json fences
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.removeprefix("json\n").strip()
    tweets = json.loads(raw)
    source_handles = story_brief.get("source_handles", []) or []
    flags: list[str] = []
    for i, t in enumerate(tweets):
        for f in check_ai_tells(t):
            flags.append(f"tweet{i}:{f}")
    # Source attribution is required ANYWHERE in the thread, not per-tweet
    full_thread = " ".join(tweets)
    for f in check_source_attribution(full_thread, source_handles):
        flags.append(f"thread:{f}")
    # Tweet 1 must not start with @ (reach suppression). Subsequent tweets can.
    if tweets:
        for f in check_no_leading_mention(tweets[0]):
            flags.append(f"tweet0:{f}")
    return {
        "format": "thread",
        "body": "\n\n".join(tweets),
        "body_json": tweets,
        "ai_check_passed": len(flags) == 0,
        "ai_check_flags": flags,
    }


def generate_for_story(story_brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate all recommended formats for a story. Regenerates up to 3 times
    per format if AI-tell flags fire on the first attempt."""
    out: list[dict[str, Any]] = []
    formats = story_brief.get("format_recommendation", ["single"])
    if "single" in formats:
        out.append(regenerate_until_clean(generate_single, story_brief))
    if "thread" in formats:
        out.append(regenerate_until_clean(generate_thread, story_brief))
    return out


def save_drafts_to_db(story_id: str, drafts: list[dict[str, Any]]) -> list[str]:
    """Insert generated drafts into the drafts table. Returns inserted ids."""
    from .. import db
    ids: list[str] = []
    with db.conn() as c, c.cursor() as cur:
        for d in drafts:
            cur.execute(
                """
                insert into drafts (story_id, format, body, body_json, ai_check_passed, ai_check_flags, status)
                values (%s::uuid, %s, %s, %s::jsonb, %s, %s, 'pending')
                returning id::text
                """,
                (
                    story_id,
                    d["format"],
                    d["body"],
                    json.dumps(d.get("body_json")) if d.get("body_json") else None,
                    d.get("ai_check_passed"),
                    d.get("ai_check_flags") or [],
                ),
            )
            row = cur.fetchone()
            if row:
                ids.append(row[0])
        cur.execute(
            "update stories set status = 'drafted' where id = %s::uuid",
            (story_id,),
        )
        c.commit()
    return ids


def draft_all_open(limit: int = 20) -> dict[str, int]:
    """Pull all open stories and generate + persist drafts for each one.

    Returns counts: {'stories': N, 'drafts': M}
    """
    from .. import db
    from psycopg.rows import dict_row

    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id::text, headline, entities, source_handles, key_data_points,
                   format_recommendation, narrative_angle
            from stories
            where status = 'open'
            order by created_at desc
            limit %s
            """,
            (limit,),
        )
        stories = cur.fetchall()

    n_drafts = 0
    for s in stories:
        brief = {
            "id": s["id"],
            "headline": s["headline"],
            "entities": s["entities"],
            "source_handles": s.get("source_handles") or [],
            "key_data_points": s["key_data_points"],
            "format_recommendation": s["format_recommendation"],
            "narrative_angle": s["narrative_angle"],
        }
        drafts = generate_for_story(brief)
        ids = save_drafts_to_db(s["id"], drafts)
        n_drafts += len(ids)
    return {"stories": len(stories), "drafts": n_drafts}
