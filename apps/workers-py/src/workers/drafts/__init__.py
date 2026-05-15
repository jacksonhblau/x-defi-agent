"""Draft generator (algo-refit, May 2026).

Composes the voice prompt + format template + story brief + a redacted slice
of personal_facts.json into Anthropic API calls, runs the anti-AI checker on
every variant, dispatches the graphics pipeline, and persists drafts only
when `ready_for_review` conditions are met:

  1. Anti-AI checks pass (first-person, no off-limits, no unverified action).
  2. At least one media_assets row in 'ready' status.
  3. Predicted algo score >= threshold (default 60).

Up to 3 regenerations per variant. Below threshold after retries → downgrade
to `review_only` status (still surfaced in the queue but flagged).

See ALGO_REFIT_PLAN.md "Draft generator" section.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Optional

from . import anti_ai

# `llm` and `..graphics` are imported lazily inside the functions that need them
# so that this package can be imported (and `anti_ai` used) in environments
# that don't have the Anthropic SDK installed (e.g., test collection).

log = logging.getLogger(__name__)

REPO_ROOT = Path(__file__).resolve().parents[5]
PROMPTS_DIR = REPO_ROOT / "packages" / "prompts"
DOCS_DIR = REPO_ROOT / "docs"

DEFAULT_PREDICTED_SCORE_THRESHOLD = 60
DEFAULT_MAX_REGENERATIONS = 3


# ---------- Prompt assembly ----------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _redacted_personal_facts(facts: dict[str, Any]) -> dict[str, Any]:
    """Return only the subset of personal_facts safe to send to the model.

    Per ALGO_REFIT_PLAN: identity, views_i_hold_strongly, and
    tone_calibration.first_person_voice_examples. The off-limits list is
    NEVER sent to the model; it's enforced server-side by anti_ai.
    """
    tone = (facts.get("tone_calibration") or {})
    return {
        "identity": facts.get("identity", {}),
        "views_i_hold_strongly": facts.get("views_i_hold_strongly", []),
        "first_person_voice_examples": tone.get("first_person_voice_examples", []),
    }


def build_system_prompt() -> str:
    """Assemble the system prompt: voice.md + algo-incentive summary.

    Format-specific templates are injected as user-side context per call.
    """
    voice = _read(PROMPTS_DIR / "voice.md")
    algo_signals = _read(DOCS_DIR / "x_algorithm_2026_signals.md")
    # Trim algo doc to just §1 (weight summary) to keep token cost reasonable.
    algo_excerpt = ""
    if algo_signals:
        marker_in = "## 1. Heavy-rail predicted-action weights"
        marker_out = "## 2. "
        i = algo_signals.find(marker_in)
        if i >= 0:
            j = algo_signals.find(marker_out, i + 1)
            algo_excerpt = algo_signals[i : j if j > 0 else i + 4000]
    return f"{voice}\n\n---\n\n# X Algorithm Weights (reference)\n\n{algo_excerpt}"


def build_user_prompt(*, brief: dict[str, Any], facts: dict[str, Any], format_template: str, format_name: str) -> str:
    """Per-call user prompt: story brief + format template + redacted facts."""
    redacted = _redacted_personal_facts(facts)
    return (
        f"# Story brief\n\n"
        f"```json\n{json.dumps(brief, indent=2)}\n```\n\n"
        f"# Format template ({format_name})\n\n"
        f"{format_template}\n\n"
        f"# Personal facts (identity + held views + voice examples only)\n\n"
        f"```json\n{json.dumps(redacted, indent=2)}\n```\n\n"
        f"# Your task\n\nProduce the requested format. Output the post text only — no commentary, no quotes, no markdown fences."
    )


# ---------- Single-variant generation ----------

def _generate_one_variant(
    *,
    brief: dict[str, Any],
    facts: dict[str, Any],
    format_name: str,
    variant_hint: Optional[str] = None,
    max_tokens: int = 800,
    temperature: float = 0.7,
) -> str:
    """Call Anthropic once, return body text (single tweet) or JSON-stringified array (thread)."""
    template_file = {
        "single": "single_post.md",
        "thread": "thread.md",
        "reply": "reply.md",
        "hot_take": "hot_take.md",
        "long_form": "thread.md",  # uses thread template's long-form section
    }.get(format_name, "single_post.md")
    template = _read(PROMPTS_DIR / template_file)
    user_prompt = build_user_prompt(
        brief=brief, facts=facts, format_template=template, format_name=format_name
    )
    if variant_hint:
        user_prompt += f"\n\nVariant hint: {variant_hint}"
    system = build_system_prompt()
    from .. import llm  # lazy
    return llm.complete_text(system=system, user=user_prompt, max_tokens=max_tokens, temperature=temperature)


VARIANT_HINTS = [
    "Variant A — unconventional read. Lead 'I keep seeing X read as Y. I think it's Z.'",
    "Variant B — held-view application. Lead from one of views_i_hold_strongly.",
    "Variant C — data anomaly. Lead 'I keep coming back to one number from this filing: $X.'",
]


# ---------- Top-level generator ----------

def generate_drafts(
    brief: dict[str, Any],
    *,
    facts: Optional[dict[str, Any]] = None,
    max_regenerations: int = DEFAULT_MAX_REGENERATIONS,
    predicted_score_threshold: int = DEFAULT_PREDICTED_SCORE_THRESHOLD,
    media_required: bool = True,
) -> list[dict[str, Any]]:
    """Generate all draft variants for a story brief.

    Returns:
      list of draft dicts, each with:
        - format: 'single' | 'thread' | 'reply' | 'long_form'
        - body or body_json
        - media_assets: list (from graphics dispatcher)
        - anti_ai_result: CheckResult-shaped dict
        - predicted_algo_score: int
        - ready_for_review: bool
    """
    facts = facts or anti_ai.load_personal_facts()
    drafts: list[dict[str, Any]] = []

    formats: list[tuple[str, Optional[str]]] = [
        ("single", VARIANT_HINTS[0]),
        ("single", VARIANT_HINTS[1]),
        ("single", VARIANT_HINTS[2]),
    ]
    fmt_rec = (brief.get("format_recommendation") or [])
    if "thread" in fmt_rec:
        formats.append(("thread", None))
    if brief.get("materiality_score", 0) >= 80:
        formats.append(("long_form", None))

    for format_name, hint in formats:
        draft = _generate_with_regeneration(
            brief=brief,
            facts=facts,
            format_name=format_name,
            hint=hint,
            max_regenerations=max_regenerations,
            predicted_score_threshold=predicted_score_threshold,
            media_required=media_required,
        )
        drafts.append(draft)

    return drafts


def _generate_with_regeneration(
    *,
    brief: dict[str, Any],
    facts: dict[str, Any],
    format_name: str,
    hint: Optional[str],
    max_regenerations: int,
    predicted_score_threshold: int,
    media_required: bool,
) -> dict[str, Any]:
    """Generate one variant, regenerate up to N times if anti-AI rejects it."""
    last_result = None
    last_body: Optional[str] = None
    for attempt in range(max_regenerations + 1):
        raw = _generate_one_variant(brief=brief, facts=facts, format_name=format_name, variant_hint=hint)
        if format_name == "thread":
            try:
                body_json = json.loads(raw)
                if not isinstance(body_json, list):
                    raise ValueError("thread output not a JSON array")
            except (ValueError, json.JSONDecodeError) as e:
                log.warning("Thread JSON parse failed (%s); retrying.", e)
                continue
            draft = {
                "format": format_name,
                "body": "\n\n".join(body_json),
                "body_json": body_json,
                "story_brief": brief,
                "media_assets": [],
            }
        else:
            draft = {
                "format": format_name,
                "body": raw.strip(),
                "story_brief": brief,
                "media_assets": [],
            }
        # Run anti-AI WITHOUT media-presence check (media dispatched below).
        check = anti_ai.check_draft(draft, facts=facts, require_media=False)
        last_result = check
        last_body = draft.get("body")
        if check.passed:
            break
        log.info("Anti-AI rejected attempt %d for %s: %s", attempt, format_name, check.rejections)

    # Dispatch graphics regardless of pass/fail so the human can still see something.
    try:
        from ..graphics import dispatch_for_draft  # lazy
        media_assets = dispatch_for_draft(draft, brief)
    except Exception as e:  # noqa: BLE001
        log.error("Graphics dispatch failed: %s", e)
        media_assets = []
    draft["media_assets"] = media_assets

    # Final check WITH media-presence enforcement.
    final = anti_ai.check_draft(draft, facts=facts, require_media=media_required)
    predicted = anti_ai.predicted_algo_score(draft)

    ready = bool(
        final.passed
        and predicted >= predicted_score_threshold
        and (not media_required or any((m or {}).get("status") == "ready" for m in media_assets))
    )

    draft["anti_ai_result"] = {
        "passed": final.passed,
        "rejections": final.rejections,
        "flags": final.flags,
        "notes": final.notes,
    }
    draft["predicted_algo_score"] = predicted
    draft["ready_for_review"] = ready
    draft["status"] = "ready_for_review" if ready else "review_only"
    return draft
