"""Vision QA gate for the AI-rendered infographic path.

Runs claude-haiku with the generated PNG attached, plus the brief that
generated it, and asks for a structured pass/fail verdict. The dispatcher
uses the verdict to decide between (a) shipping, (b) one retry with a
refined prompt, or (c) falling back to the deterministic plate.

The checklist (forced output schema):
  - headline_matches:   the rendered headline matches brief.headline within 5% Levenshtein
  - entities_visible:   every entity in brief.entities has a visible mark
                        (real logo OR typographic wordmark) — NOT just a generic icon
  - no_garbled_text:    every glyph is a real character, no hallucinated soup
  - structured_layout:  ≥3 distinct sections / tiers / cards visible
                        (NOT a single centered icon poster)
  - no_placeholders:    no "N/A", "TBD", "Unknown" rendered as literal text
  - white_background:   background is white/light, not dark
  - watermark_present:  "@jacksonblau" visible bottom-left

Pass = all seven checks True. Returns the full breakdown so the dispatcher
can log failures and the prompt-refiner can target the specific failures
in the retry.

When ANTHROPIC_API_KEY is unset (or claude unavailable), the gate degrades
to a deterministic stub that passes everything — production fail-closed
would block all posts, which is worse than the alternative. The dispatcher
treats `passed=True, mode="stub"` as a "trusted" pass.
"""

from __future__ import annotations

import base64
import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


# ---------- Checklist schema ----------

CHECK_KEYS = (
    "headline_matches",
    "entities_visible",
    "no_garbled_text",
    "structured_layout",
    "no_placeholders",
    "white_background",
    "watermark_present",
)


@dataclass
class QAResult:
    passed: bool
    checks: dict[str, bool] = field(default_factory=dict)
    failure_details: dict[str, str] = field(default_factory=dict)
    mode: str = "live"            # "live" | "stub" | "error"
    raw_response: str = ""        # for debugging
    attempt: int = 1

    @property
    def failed_checks(self) -> list[str]:
        return [k for k, v in self.checks.items() if v is False]

    def as_diagnostics(self) -> dict[str, Any]:
        return {
            "attempts": self.attempt,
            "passed": self.passed,
            "mode": self.mode,
            "checks": self.checks,
            "failures": self.failure_details,
        }


# ---------- Vision QA call ----------

_QA_SYSTEM = (
    "You are a strict graphics QA reviewer for a finance infographic pipeline. "
    "You will be shown one generated PNG and the brief that produced it. "
    "Return ONLY a JSON object with the exact schema requested — no prose."
)


def _build_user_prompt(brief: dict[str, Any], required_entities: list[str]) -> str:
    headline = (brief or {}).get("headline", "")
    entities_str = ", ".join(required_entities) if required_entities else "(none)"
    return f"""Evaluate this generated infographic against the brief.

BRIEF HEADLINE: {headline!r}
REQUIRED ENTITIES (each must appear as a real logo, typographic wordmark, or labeled card — NOT a generic icon): {entities_str}

Return a JSON object with exactly these keys, all booleans, plus a `details` object mapping any failed check to a one-line explanation:

{{
  "headline_matches":   bool,   // rendered headline matches brief headline within ~5% character diff
  "entities_visible":   bool,   // every required entity has a visible mark in the image
  "no_garbled_text":    bool,   // every glyph is a real character, no hallucinated soup
  "structured_layout":  bool,   // 3+ distinct sections / tiers / cards (NOT a single centered icon poster)
  "no_placeholders":    bool,   // no "N/A" / "TBD" / "Unknown" / "—" rendered as literal text
  "white_background":   bool,   // background is white/light, not dark mode
  "watermark_present":  bool,   // "@jacksonblau" visible bottom-left
  "details": {{ "failed_check_key": "one-line reason", ... }}
}}

Return ONLY the JSON. No preamble, no postscript."""


def _stub_pass(attempt: int = 1) -> QAResult:
    """The fail-open verdict when claude isn't wired."""
    return QAResult(
        passed=True,
        checks={k: True for k in CHECK_KEYS},
        mode="stub",
        attempt=attempt,
    )


def check(
    image_path: Path,
    brief: dict[str, Any],
    *,
    attempt: int = 1,
    model: str = "claude-haiku-4-5-20251001",
    timeout_s: float = 30.0,
) -> QAResult:
    """Run the QA gate. Always returns a QAResult — never raises.

    image_path may be a local file OR a remote URL (e.g., Supabase Storage).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key or os.environ.get("GRAPHICS_QA_STRICT", "true").lower() == "false":
        return _stub_pass(attempt=attempt)

    # Load image bytes (local path or URL).
    try:
        if isinstance(image_path, str) and image_path.startswith(("http://", "https://")):
            r = httpx.get(image_path, timeout=timeout_s, follow_redirects=True)
            r.raise_for_status()
            img_bytes = r.content
        else:
            p = Path(image_path)
            img_bytes = p.read_bytes()
        b64 = base64.b64encode(img_bytes).decode("ascii")
    except Exception as e:  # noqa: BLE001
        log.warning("QA gate could not read image at %s: %s", image_path, e)
        return QAResult(
            passed=False,
            checks={k: False for k in CHECK_KEYS},
            failure_details={"_image_read": str(e)},
            mode="error",
            attempt=attempt,
        )

    required_entities = [
        ((e or "").lstrip("@").strip())
        for e in (brief or {}).get("entities", []) or []
        if e
    ][:8]

    user_prompt = _build_user_prompt(brief, required_entities)

    payload = {
        "model": model,
        "max_tokens": 600,
        "system": _QA_SYSTEM,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": b64,
                        },
                    },
                    {"type": "text", "text": user_prompt},
                ],
            }
        ],
    }

    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=timeout_s,
        )
        r.raise_for_status()
        body = r.json()
        text_block = next(
            (b for b in body.get("content", []) if b.get("type") == "text"),
            None,
        )
        raw = (text_block or {}).get("text", "").strip()
    except Exception as e:  # noqa: BLE001
        log.warning("QA gate call failed: %s", e)
        return QAResult(
            passed=False,
            checks={k: False for k in CHECK_KEYS},
            failure_details={"_qa_call": str(e)},
            mode="error",
            attempt=attempt,
        )

    return _parse_response(raw, attempt=attempt)


def _parse_response(raw: str, *, attempt: int) -> QAResult:
    """Extract the JSON object from claude's response. Lenient — strips
    code fences if present, finds the outermost {...} block.
    """
    text = raw.strip()
    if text.startswith("```"):
        # strip ```json ... ``` fences
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    # locate the first {...} substring as a safety net
    try:
        start = text.index("{")
        end = text.rindex("}")
        text = text[start : end + 1]
    except ValueError:
        return QAResult(
            passed=False,
            checks={k: False for k in CHECK_KEYS},
            failure_details={"_parse": "no JSON object found in response"},
            mode="error",
            attempt=attempt,
            raw_response=raw,
        )

    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as e:
        return QAResult(
            passed=False,
            checks={k: False for k in CHECK_KEYS},
            failure_details={"_parse": f"JSON decode error: {e}"},
            mode="error",
            attempt=attempt,
            raw_response=raw,
        )

    checks: dict[str, bool] = {}
    for k in CHECK_KEYS:
        v = parsed.get(k)
        checks[k] = bool(v) if isinstance(v, bool) else False

    details_raw = parsed.get("details") or {}
    failure_details: dict[str, str] = {
        k: str(details_raw.get(k, "")) for k in checks if checks[k] is False and details_raw.get(k)
    }

    passed = all(checks.values())
    return QAResult(
        passed=passed,
        checks=checks,
        failure_details=failure_details,
        mode="live",
        attempt=attempt,
        raw_response=raw,
    )


# ---------- Prompt refinement on retry ----------

def refine_prompt_for_failures(base_prompt: str, qa: QAResult) -> str:
    """Append targeted corrective hints to the prompt based on QA failures.

    The dispatcher uses this on the retry attempt. Hints are appended (not
    replaced) so the underlying layout/logo guidance stays intact.
    """
    if qa.passed:
        return base_prompt
    hints: list[str] = []
    if not qa.checks.get("structured_layout", True):
        hints.append(
            "CRITICAL: the previous attempt produced a single-icon poster. "
            "This must be a multi-section infographic with at least three "
            "labeled tiers/cards stacked vertically and labeled connecting "
            "arrows between them. NEVER produce a single centered icon."
        )
    if not qa.checks.get("entities_visible", True):
        hints.append(
            "CRITICAL: the previous attempt did not render every named entity. "
            "Each entity in the brief MUST appear as a labeled card with its "
            "real logo (or its typographic wordmark if no logo is provided)."
        )
    if not qa.checks.get("headline_matches", True):
        hints.append(
            "CRITICAL: render the headline VERBATIM at the top of the image, "
            "in bold near-black sans-serif type."
        )
    if not qa.checks.get("no_garbled_text", True):
        hints.append(
            "CRITICAL: every word must be spelled correctly. If a word will "
            "not fit at legible size, shrink the surrounding layout — never "
            "render an approximation or hallucinated glyphs."
        )
    if not qa.checks.get("no_placeholders", True):
        hints.append(
            "CRITICAL: do NOT render 'N/A', 'TBD', 'Unknown', '—' or any "
            "placeholder string as literal text. Omit the slot entirely."
        )
    if not qa.checks.get("white_background", True):
        hints.append("CRITICAL: background must be solid white (#FFFFFF). Not dark mode.")
    if not qa.checks.get("watermark_present", True):
        hints.append(
            "CRITICAL: include the watermark '@jacksonblau' in light gray "
            "at the bottom-left corner."
        )
    if not hints:
        return base_prompt
    return base_prompt + "\n\n[RETRY HINTS]\n" + "\n".join(hints)
