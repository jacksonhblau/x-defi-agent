"""Anti-AI-writing checker for draft posts (algo-refit, May 2026).

Enforces the voice constraints set by the algo-refit:

1. First-person frame required in singles, thread tweet 1, replies, and hot takes.
2. No personal-action claim that isn't whitelisted in personal_facts.json under
   things_i_have_done / things_i_have_built / positions_i_hold with
   approved_to_reference: true.
3. No off-limits topic from personal_facts.json.things_off_limits.
4. No engagement-bait closer.
5. Floating assertions flagged (soft, not auto-reject).
6. Media-presence check (called by draft generator after graphics dispatch).
7. No em-dash / en-dash.

Reads `config/personal_facts.json`. Errors gracefully via
`PersonalFactsNotConfiguredError` if the file is absent.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional


# ---------- Configuration ----------

PERSONAL_FACTS_PATH_DEFAULT = Path(__file__).resolve().parents[4].parent / "config" / "personal_facts.json"

# First-person pronouns / contractions that count as a "first-person frame".
# Case-insensitive so "My read on..." and "Me, I think..." (capitalized at the
# start of a sentence) count. Without IGNORECASE, "My" failed the check because
# the regex only matched lowercase "my" — which broke the voice-prompt-blessed
# "My read on..." opener pattern.
FIRST_PERSON_REGEX = re.compile(r"\b(I|I'm|I've|I'd|I'll|me|my|mine|myself)\b", re.IGNORECASE)

# Verbs that, when used first-person, assert a real-world personal action.
# Requires a matching entry in personal_facts.json's
# things_i_have_done / things_i_have_built with approved_to_reference: true.
PERSONAL_ACTION_VERBS = {
    "built", "shipped", "closed", "raised", "launched", "attended",
    "met", "met with", "spoke", "spoke with", "talked", "talked with",
    "sat down with", "had a call with", "bought", "sold", "longed",
    "shorted", "allocated", "invested", "negotiated", "signed",
    "structured", "executed", "advised", "founded", "co-founded",
    "joined", "left", "led", "wrote", "authored", "co-authored",
    "lead-authored", "led-authored", "received", "co-host", "co-hosted",
    "appeared on", "took",
}

# Position-claim verbs that require a positions_i_hold match.
POSITION_CLAIM_VERBS = {
    "hold", "own", "long", "short", "stake", "stack", "bought", "sold",
    "took",
}

# Adverbs that can sit between the first-person pronoun and the action verb.
# ("I just bought…", "I recently attended…")
_ADVERB_OPTIONAL = (
    r"(?:(?:just|recently|finally|already|once|never|always|usually|"
    r"sometimes|now|then|long|short)\s+)?"
)

# Engagement-bait closer regex. Matches when one of these is the last
# sentence and there is no substantive question setup before it.
ENGAGEMENT_BAIT_REGEX = re.compile(
    r"\b(thoughts|what do you think|agree or disagree|let me know)\b\??\s*$",
    re.IGNORECASE,
)

# Em-dash / en-dash forbidden.
EM_DASH_REGEX = re.compile(r"[—–]")


# ---------- Result type ----------

@dataclass
class CheckResult:
    passed: bool = True
    flags: list[str] = field(default_factory=list)        # soft (human review)
    rejections: list[str] = field(default_factory=list)   # hard (regenerate)
    notes: list[str] = field(default_factory=list)        # informational

    def merge(self, other: "CheckResult") -> "CheckResult":
        return CheckResult(
            passed=self.passed and other.passed,
            flags=self.flags + other.flags,
            rejections=self.rejections + other.rejections,
            notes=self.notes + other.notes,
        )


class PersonalFactsNotConfiguredError(RuntimeError):
    """Raised when personal_facts.json is absent or invalid.

    Surface this clearly so Jackson knows the agent cannot draft until he
    populates the ledger.
    """


# ---------- Loading personal facts ----------

def load_personal_facts(path: Optional[str | Path] = None) -> dict[str, Any]:
    """Load personal_facts.json. Errors loudly if missing.

    The agent should not draft posts without this file because the anti-AI
    check cannot validate first-person action claims without it.
    """
    p = Path(path) if path else PERSONAL_FACTS_PATH_DEFAULT
    if not p.exists():
        raise PersonalFactsNotConfiguredError(
            f"personal_facts.json not configured at {p}. The anti-AI checker "
            f"requires this file. Copy config/personal_facts.example.json to "
            f"config/personal_facts.json and populate before running the agent."
        )
    try:
        with p.open("r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError as e:
        raise PersonalFactsNotConfiguredError(
            f"personal_facts.json at {p} is not valid JSON: {e}"
        ) from e


# ---------- Individual checks ----------

def check_first_person(body: str, *, required: bool = True) -> CheckResult:
    """Pass if body contains at least one first-person pronoun (when required)."""
    if not required:
        return CheckResult()
    if FIRST_PERSON_REGEX.search(body):
        return CheckResult()
    return CheckResult(
        passed=False,
        rejections=["missing_first_person_frame"],
        notes=["No first-person pronoun (I, I'm, I've, etc.) found. Add a first-person frame."],
    )


def _collect_approved_actions(facts: dict[str, Any]) -> list[tuple[str, str]]:
    """Return list of (verb, object) tuples for approved personal actions."""
    out: list[tuple[str, str]] = []
    for bucket in ("things_i_have_done", "things_i_have_built"):
        for entry in facts.get(bucket, []) or []:
            if not entry.get("approved_to_reference"):
                continue
            v = (entry.get("verb") or "").lower().strip()
            o = (entry.get("object") or "").lower().strip()
            if v and o:
                out.append((v, o))
    return out


def _collect_approved_positions(facts: dict[str, Any]) -> list[str]:
    """Return list of asset names from positions_i_hold (approved only)."""
    out: list[str] = []
    for entry in facts.get("positions_i_hold", []) or []:
        if not entry.get("approved_to_reference"):
            continue
        asset = (entry.get("asset") or "").strip()
        if asset:
            out.append(asset.lower())
    return out


def _verb_root(verb: str) -> str:
    """Strip common verb suffixes for canonical matching."""
    v = verb.lower().strip()
    for suf in ("ied", "ed", "ing", "s"):
        if v.endswith(suf) and len(v) > len(suf) + 1:
            return v[: -len(suf)]
    return v


def check_personal_action(body: str, facts: dict[str, Any]) -> CheckResult:
    """Detect first-person personal-action claims and verify against the ledger."""
    approved_actions = _collect_approved_actions(facts)
    approved_positions = _collect_approved_positions(facts)

    verb_alt = "|".join(
        sorted({re.escape(v) for v in PERSONAL_ACTION_VERBS}, key=len, reverse=True)
    )
    pos_verb_alt = "|".join(
        sorted({re.escape(v) for v in POSITION_CLAIM_VERBS}, key=len, reverse=True)
    )

    # "I [optional adverb] <verb> <object>..." capture. Catches "I just bought…",
    # "I recently attended…", "I'm long X" via _ADVERB_OPTIONAL.
    action_pat = re.compile(
        rf"\b(I|I've|I'm|I'd|I'll)\s+{_ADVERB_OPTIONAL}({verb_alt})\b([^.!?\n]{{0,200}})",
        re.IGNORECASE,
    )
    position_pat = re.compile(
        rf"\b(I|I'm|I've|I'd|I'll)\s+{_ADVERB_OPTIONAL}({pos_verb_alt})\b([^.!?\n]{{0,200}})",
        re.IGNORECASE,
    )

    result = CheckResult()

    # 1) Personal-action claims.
    for match in action_pat.finditer(body):
        verb = match.group(2).lower().strip()
        object_phrase = re.sub(r"\s+", " ", match.group(3).lower().strip())
        verb_canonical = _verb_root(verb)

        # Match approved actions by verb-stem AND token-overlap on object.
        matched = False
        for (v, o) in approved_actions:
            v_canonical = _verb_root(v)
            if not (verb_canonical and (verb_canonical in v_canonical or v_canonical in verb_canonical)):
                continue
            # Token overlap: require at least one ≥5-char object token to appear.
            object_tokens = [tok for tok in re.findall(r"[A-Za-z0-9]+", o) if len(tok) >= 5]
            if any(tok in object_phrase for tok in object_tokens):
                matched = True
                break

        if not matched:
            result.passed = False
            preview = object_phrase[:80].rstrip(", ").strip()
            result.rejections.append(
                f"unverified_personal_action: 'I {verb} {preview}…' not whitelisted in personal_facts.json"
            )

    # 2) Position-claim verbs.
    for match in position_pat.finditer(body):
        verb = match.group(2).lower().strip()
        object_phrase = re.sub(r"\s+", " ", match.group(3).lower().strip())

        # Skip benign "I think" / "I read" cases that don't make a position claim.
        if verb in ("read", "think"):
            continue

        # Token overlap with any approved position asset.
        matched = False
        for asset in approved_positions:
            asset_tokens = [tok for tok in re.findall(r"[A-Za-z0-9$]+", asset) if len(tok) >= 2]
            if any(tok in object_phrase for tok in asset_tokens if tok not in {"the", "a", "an", "and", "of"}):
                matched = True
                break

        if not matched:
            preview = object_phrase[:80].rstrip(", ").strip()
            result.passed = False
            result.rejections.append(
                f"unverified_position_claim: 'I {verb} {preview}…' not in positions_i_hold"
            )

    return result


def check_off_limits(body: str, facts: dict[str, Any]) -> CheckResult:
    """Hard-reject specific off-limits dollar figures or named entity tokens."""
    result = CheckResult()
    body_norm = body.lower()
    # Off-limits dollar figure tokens (from rule strings).
    for rule in facts.get("things_off_limits", []) or []:
        if not isinstance(rule, str):
            continue
        for dollar in re.findall(r"\$\d[\d.,]*\s*[BMK]?", rule):
            d_norm = dollar.lower().replace(" ", "")
            if d_norm in body_norm.replace(" ", ""):
                result.passed = False
                result.rejections.append(
                    f"off_limits_reference: body contains '{dollar}' (off-limits rule)"
                )
    return result


def check_engagement_bait_closer(body: str) -> CheckResult:
    """Reject generic engagement-bait closers unless a substantive question setup precedes."""
    if not ENGAGEMENT_BAIT_REGEX.search(body):
        return CheckResult()
    sentences = re.split(r"(?<=[.!?])\s+", body.strip())
    if len(sentences) >= 2:
        prev = sentences[-2]
        if prev.rstrip().endswith("?") and not ENGAGEMENT_BAIT_REGEX.search(prev):
            return CheckResult(flags=["soft_engagement_bait_with_substantive_setup"])
    return CheckResult(
        passed=False,
        rejections=["engagement_bait_closer"],
        notes=["Generic engagement-bait closer. Replace with substantive question or remove."],
    )


def check_floating_assertion(body: str, key_data_points: list[dict]) -> CheckResult:
    """Flag (soft) numbers in body not traceable to key_data_points."""
    nums_in_body = set(re.findall(r"\$[\d,.]+[BMK]?|\d+(?:\.\d+)?%|\b\d{4,}\b", body))
    if not nums_in_body:
        return CheckResult()
    kdp_corpus = " ".join(str(p.get("value", "")) for p in (key_data_points or []))
    unmatched = sorted(n for n in nums_in_body if n not in kdp_corpus)
    if unmatched:
        return CheckResult(
            flags=[f"floating_assertion:{','.join(unmatched[:5])}"],
            notes=[f"Numbers in body not in key_data_points: {unmatched[:5]}. Verify before posting."],
        )
    return CheckResult()


def check_em_dash(body: str) -> CheckResult:
    if EM_DASH_REGEX.search(body):
        return CheckResult(
            passed=False,
            rejections=["em_dash_present"],
            notes=["Em-dash or en-dash detected. Replace with period or comma."],
        )
    return CheckResult()


def check_media_present(draft: dict[str, Any]) -> CheckResult:
    """Hard-reject if no media_assets row is in 'ready' status."""
    media = draft.get("media_assets", []) or []
    ready = [m for m in media if (m or {}).get("status") == "ready"]
    if not ready:
        return CheckResult(
            passed=False,
            rejections=["missing_media"],
            notes=["No media_assets row in 'ready' status. Run graphics dispatcher before review."],
        )
    return CheckResult()


# ---------- Top-level entry ----------

def check_draft(
    draft: dict[str, Any],
    *,
    facts: Optional[dict[str, Any]] = None,
    facts_path: Optional[str | Path] = None,
    require_media: bool = True,
) -> CheckResult:
    """Run all anti-AI checks on a draft.

    Args:
      draft: dict with at minimum:
        - format: 'single' | 'thread' | 'reply' | 'hot_take' | 'long_form'
        - body: str (used for non-thread formats)
        - body_json: list[str] (used for threads, one tweet per element)
        - media_assets: list[dict] (graphics dispatcher output, used when require_media=True)
        - story_brief: dict with key_data_points (for floating-assertion check)
      facts: pre-loaded personal_facts dict; if None, loads from facts_path.
      facts_path: override path to personal_facts.json (default: config/personal_facts.json).
      require_media: when True, hard-reject drafts without a ready media asset.

    Returns:
      CheckResult with passed (bool), rejections (hard fails), flags (soft),
      and notes.
    """
    if facts is None:
        facts = load_personal_facts(facts_path)

    result = CheckResult()
    fmt = draft.get("format", "single")

    if fmt == "thread" and draft.get("body_json"):
        body_chunks: list[str] = list(draft["body_json"])
    else:
        body_chunks = [draft.get("body", "")]

    tone = facts.get("tone_calibration") or {}
    require_fp = {
        "single": tone.get("first_person_required_in_singles", True),
        "thread": tone.get("first_person_required_in_threads", True),
        "reply": tone.get("first_person_required_in_replies", True),
        "hot_take": True,
        "long_form": True,
    }.get(fmt, True)

    key_data_points = (draft.get("story_brief") or {}).get("key_data_points") or []

    # First-person check on tweet 1 (or single body)
    first_chunk = body_chunks[0] if body_chunks else ""
    result = result.merge(check_first_person(first_chunk, required=require_fp))

    # Per-chunk checks: action, off-limits, em-dash, floating-assertions
    for chunk in body_chunks:
        result = result.merge(check_personal_action(chunk, facts))
        result = result.merge(check_off_limits(chunk, facts))
        result = result.merge(check_em_dash(chunk))
        result = result.merge(check_floating_assertion(chunk, key_data_points))

    # Engagement-bait closer on the LAST chunk only.
    if body_chunks:
        result = result.merge(check_engagement_bait_closer(body_chunks[-1]))

    if require_media:
        result = result.merge(check_media_present(draft))

    return result


# ---------- Convenience: predicted algo score (heuristic) ----------

def predicted_algo_score(draft: dict[str, Any]) -> int:
    """Heuristic 0-100 score per docs/x_algorithm_2026_signals.md §6.

    Used by the draft generator to decide whether to regenerate (below threshold)
    or downgrade to `review_only`. Not a calibrated number — directional only.
    """
    score = 0
    fmt = draft.get("format", "single")
    body = draft.get("body", "") if fmt != "thread" else " ".join(draft.get("body_json", []) or [])
    body_len = len(body)

    # Media bonus.
    media = draft.get("media_assets", []) or []
    if any((m or {}).get("status") == "ready" for m in media):
        score += 30
    if sum(1 for m in media if (m or {}).get("status") == "ready") >= 2:
        score += 5

    # First-person frame.
    if FIRST_PERSON_REGEX.search(body):
        score += 15

    # Number density (~ one specific number per 80 chars).
    nums = len(re.findall(r"\$[\d,.]+[BMK]?|\d+(?:\.\d+)?%|\b\d{2,}\b", body))
    target = max(1, body_len // 80)
    score += min(15, int(15 * (nums / target)))

    # Reply-opener: question mark or arguable-claim marker.
    if "?" in body or re.search(r"\bI (think|read|push back|disagree|'m watching)\b", body, re.IGNORECASE):
        score += 10

    # Long-form dwell bonus.
    if body_len >= 1500:
        score += 15
    elif body_len >= 800:
        score += 5

    # Entity tag present.
    if re.search(r"@[A-Za-z0-9_]+", body):
        score += 5

    return max(0, min(100, score))
