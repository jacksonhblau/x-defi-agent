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
    return flags


def generate_single(story_brief: dict[str, Any]) -> dict[str, Any]:
    """Generate a single-post draft from a story brief."""
    voice = config.prompt("voice")
    fmt = config.prompt("single_post")
    system = f"{voice}\n\n---\n\n# Format instructions\n\n{fmt}"
    user = f"Story brief (JSON):\n```json\n{json.dumps(story_brief, indent=2, default=str)}\n```\n\nWrite the post."
    body = llm.complete(system=system, user=user, max_tokens=600, temperature=0.7).strip()
    flags = check_ai_tells(body)
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
    flags: list[str] = []
    for i, t in enumerate(tweets):
        for f in check_ai_tells(t):
            flags.append(f"tweet{i}:{f}")
    return {
        "format": "thread",
        "body": "\n\n".join(tweets),
        "body_json": tweets,
        "ai_check_passed": len(flags) == 0,
        "ai_check_flags": flags,
    }


def generate_for_story(story_brief: dict[str, Any]) -> list[dict[str, Any]]:
    """Generate all recommended formats for a story."""
    out: list[dict[str, Any]] = []
    formats = story_brief.get("format_recommendation", ["single"])
    if "single" in formats:
        out.append(generate_single(story_brief))
    if "thread" in formats:
        out.append(generate_thread(story_brief))
    return out
