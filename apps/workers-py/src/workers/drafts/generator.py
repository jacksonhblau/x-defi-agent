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

# OPENER VARIETY enforcement. The drafter keeps reaching for "I think" as the
# first two words of every post, which reads as AI slop and triggers X's
# repetition heuristics. "I think" mid-post is fine (the exemplars use it that
# way); only the literal opener is banned. Add other formulaic openers here as
# they emerge.
BANNED_OPENERS = [
    r"^I\s+think\b",
    r"^Look,",
    r"^Listen,",
    r"^Here's\s+the\s+thing\b",
    r"^So,",
    r"^Honestly,",
    r"^Let's\s+be\s+honest\b",
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


def check_opener_variety(text: str) -> list[str]:
    """Reject drafts that open with a formulaic AI-slop phrase.

    Only inspects the first non-empty line — mid-post usage of "I think" etc.
    is intentional and matches the exemplars. The phrase is banned only as the
    LITERAL opener of the post (or tweet 1 of a thread).
    """
    first_line = text.lstrip().split("\n", 1)[0].lstrip()
    if not first_line:
        return []
    for pattern in BANNED_OPENERS:
        if re.match(pattern, first_line, re.IGNORECASE):
            return [f"banned_opener:'{first_line[:40]}...' — rotate to a different first-person frame"]
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
        + check_opener_variety(body)
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
    try:
        tweets = json.loads(raw)
    except json.JSONDecodeError:
        # Claude returned something that isn't a JSON array (e.g. empty string,
        # prose, or NO_TAKE_AVAILABLE marker). Surface as a failed draft rather
        # than crashing the whole pipeline.
        return {
            "format": "thread",
            "body": raw[:2000] if raw else "(empty response from model)",
            "body_json": None,
            "ai_check_passed": False,
            "ai_check_flags": [f"json_parse_failed:'{raw[:100]}'"],
        }
    if not isinstance(tweets, list) or not all(isinstance(t, str) for t in tweets):
        return {
            "format": "thread",
            "body": str(tweets)[:2000],
            "body_json": None,
            "ai_check_passed": False,
            "ai_check_flags": [f"thread_shape_invalid:expected list of strings, got {type(tweets).__name__}"],
        }
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
        # Opener variety only applies to tweet 1 — mid-thread "I think" is fine.
        for f in check_opener_variety(tweets[0]):
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


def save_drafts_to_db(
    story_id: str,
    drafts: list[dict[str, Any]],
    brief: dict[str, Any] | None = None,
) -> list[str]:
    """Insert generated drafts into the drafts table. Returns inserted ids.

    Order of operations matters: graphics are dispatched BEFORE the draft row
    is inserted, so the post-graphics anti-AI check (`require_media=True`) and
    the predicted-algo-score calculation can see the actual media_assets. The
    computed values are then written into the same INSERT so the row lands on
    the frontend's review queue with `ready_for_review` correctly populated.

    If `brief` is None, graphics dispatch is skipped and ready_for_review will
    be False (since the media-presence check will fail).
    """
    from .. import db
    from . import anti_ai

    # Load personal facts once for this batch. If absent we still save drafts —
    # they just won't pass first_person/personal_facts checks.
    try:
        facts = anti_ai.load_personal_facts()
    except anti_ai.PersonalFactsNotConfiguredError as e:
        print(f"[warn] personal_facts.json not loaded: {e}")
        facts = {}

    ids: list[str] = []
    with db.conn() as c, c.cursor() as cur:
        for d in drafts:
            # 1) Dispatch graphics FIRST so the anti-AI checker sees media.
            assets: list[dict[str, Any]] = []
            if brief is not None:
                try:
                    from ..graphics import dispatch_for_draft
                    assets = dispatch_for_draft({"format": d["format"]}, brief) or []
                except Exception as e:  # noqa: BLE001
                    print(f"[story={story_id} fmt={d['format']}] graphics dispatch failed: {type(e).__name__}: {e}")
                    assets = []

            # 2) Build a complete draft dict for anti-AI evaluation.
            eval_draft = {
                "format": d["format"],
                "body": d.get("body", ""),
                "body_json": d.get("body_json"),
                "story_brief": brief or {},
                "media_assets": assets,
            }

            # 3) Run the post-graphics anti-AI check and compute the algo score.
            #    These populate the columns the frontend filters on.
            try:
                final_check = anti_ai.check_draft(eval_draft, facts=facts, require_media=True)
            except Exception as e:  # noqa: BLE001
                print(f"[story={story_id} fmt={d['format']}] anti_ai.check_draft failed: {type(e).__name__}: {e}")
                final_check = anti_ai.CheckResult(passed=False, rejections=[f"check_exception:{type(e).__name__}"])

            try:
                algo_score = anti_ai.predicted_algo_score(eval_draft)
            except Exception as e:  # noqa: BLE001
                print(f"[story={story_id} fmt={d['format']}] predicted_algo_score failed: {type(e).__name__}: {e}")
                algo_score = 0

            # Granular column values for the dashboard
            first_person_passed = not any("missing_first_person_frame" in r for r in final_check.rejections)
            personal_facts_passed = not any(
                r.startswith(("unverified_personal_action", "unverified_position_claim", "off_limits_reference"))
                for r in final_check.rejections
            )
            has_ready_media = any((m or {}).get("status") == "ready" for m in assets)
            ready_for_review = bool(
                final_check.passed
                and (brief is None or has_ready_media)
            )
            # Merge generator-level ai_check_flags with any final-check flags
            # so reviewers see the full story.
            combined_flags = list(d.get("ai_check_flags") or []) + list(final_check.flags) + list(final_check.rejections)

            # 4) Insert the draft with ALL the columns the frontend cares about.
            cur.execute(
                """
                insert into drafts (
                    story_id, format, body, body_json,
                    ai_check_passed, ai_check_flags,
                    first_person_check_passed, personal_facts_check_passed,
                    predicted_algo_score, ready_for_review,
                    status
                )
                values (%s::uuid, %s, %s, %s::jsonb,
                        %s, %s,
                        %s, %s,
                        %s, %s,
                        'pending')
                returning id::text
                """,
                (
                    story_id,
                    d["format"],
                    d["body"],
                    json.dumps(d.get("body_json")) if d.get("body_json") else None,
                    bool(d.get("ai_check_passed")) and final_check.passed,
                    combined_flags,
                    first_person_passed,
                    personal_facts_passed,
                    int(algo_score),
                    ready_for_review,
                ),
            )
            row = cur.fetchone()
            if not row:
                continue
            draft_id = row[0]
            ids.append(draft_id)

            # 5) Persist the media_assets rows tied to the new draft_id.
            for asset in assets:
                try:
                    cur.execute(
                        """
                        insert into media_assets
                            (draft_id, kind, source, model, prompt,
                             higgsfield_job_id, canva_template_slug, canva_design_id,
                             storage_url, status, credits_used, ready_at)
                        values
                            (%s::uuid, %s, %s, %s, %s,
                             %s, %s, %s,
                             %s, %s, %s, %s)
                        """,
                        (
                            draft_id,
                            asset.get("kind", "image"),
                            asset.get("source", "custom"),
                            asset.get("model"),
                            asset.get("prompt") or "",
                            asset.get("higgsfield_job_id"),
                            asset.get("canva_template_slug"),
                            asset.get("canva_design_id"),
                            asset.get("storage_url"),
                            asset.get("status", "queued"),
                            asset.get("credits_used"),
                            asset.get("ready_at"),
                        ),
                    )
                except Exception as e:  # noqa: BLE001
                    print(f"[draft={draft_id}] media_assets insert failed: {type(e).__name__}: {e}")

        cur.execute(
            "update stories set status = 'drafted' where id = %s::uuid",
            (story_id,),
        )
        c.commit()
    return ids


def draft_all_open(limit: int = 20, verbose: bool = True) -> dict[str, int]:
    """Pull all open stories and generate + persist drafts for each one.

    Prints progress to stdout as each story is drafted (set verbose=False to silence).
    Returns counts: {'stories': N, 'drafts': M}
    """
    import sys
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

    if verbose:
        print(f"Drafting {len(stories)} open stories...", flush=True)

    n_drafts = 0
    n_failed = 0
    for i, s in enumerate(stories, start=1):
        brief = {
            "id": s["id"],
            "headline": s["headline"],
            "entities": s["entities"],
            "source_handles": s.get("source_handles") or [],
            "key_data_points": s["key_data_points"],
            "format_recommendation": s["format_recommendation"],
            "narrative_angle": s["narrative_angle"],
        }
        formats = brief["format_recommendation"]
        if verbose:
            print(f"  [{i}/{len(stories)}] {brief['headline'][:60]:60s} formats={formats}", flush=True)
        try:
            drafts = generate_for_story(brief)
            ids = save_drafts_to_db(s["id"], drafts, brief)
            n_drafts += len(ids)
            if verbose:
                # Summarize the AI-check pass/fail per draft
                for d in drafts:
                    status = "ok" if d.get("ai_check_passed") else f"FLAGS: {d.get('ai_check_flags')}"
                    print(f"      {d['format']:10s} → {status}", flush=True)
        except Exception as e:
            n_failed += 1
            if verbose:
                print(f"      ERROR: {type(e).__name__}: {str(e)[:200]}", flush=True)
            # Don't crash the whole batch on one story's failure
            continue
    if verbose:
        print(f"Done. {n_drafts} drafts saved, {n_failed} stories failed.", flush=True)
    return {"stories": len(stories), "drafts": n_drafts, "failed": n_failed}
