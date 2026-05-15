"""Tests for the anti_ai module (algo-refit anti-AI checker).

Verification bar (from ALGO_REFIT_PLAN):
  - Catches all three constructed bad drafts (third-person, hallucinated action, bait closer).
  - Passes a first-person variant of the real BlackRock BUIDL fixture.
  - Errors gracefully when personal_facts.json is missing.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make `workers` importable from src/ without requiring an install.
ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

REPO_ROOT = Path(__file__).resolve().parents[3]
PERSONAL_FACTS = REPO_ROOT / "config" / "personal_facts.json"
LEGACY_DRAFT = REPO_ROOT / "data" / "drafts" / "91751dcf-9408-43a5-b0e2-b11c06775efa.json"

from workers.drafts import anti_ai  # noqa: E402


# ---------- Fixtures ----------

@pytest.fixture(scope="module")
def facts():
    return anti_ai.load_personal_facts(PERSONAL_FACTS)


def _draft(body, fmt="single", media_ready=True, story_brief=None, body_json=None):
    media = [{"status": "ready"}] if media_ready else []
    d = {
        "format": fmt,
        "body": body,
        "media_assets": media,
        "story_brief": story_brief or {},
    }
    if body_json is not None:
        d["body_json"] = body_json
    return d


# ---------- Loading ----------

def test_personal_facts_loads(facts):
    assert facts["identity"]["handle"] == "jacksonblau"
    assert any(v.get("category") == "thesis" for v in facts["views_i_hold_strongly"])


def test_missing_personal_facts_raises():
    with pytest.raises(anti_ai.PersonalFactsNotConfiguredError):
        anti_ai.load_personal_facts("/tmp/nonexistent_personal_facts_definitely.json")


def test_malformed_json_raises(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{ not valid json")
    with pytest.raises(anti_ai.PersonalFactsNotConfiguredError):
        anti_ai.load_personal_facts(p)


# ---------- The "passing" case: real BUIDL story, first-person variant ----------

def test_first_person_blackrock_variant_passes(facts):
    """The constructed first-person variant of the real BlackRock fixture should pass."""
    body = (
        "I keep seeing the BlackRock $7B filing read as a size story.\n\n"
        "I think it's a sovereignty story. BNY Mellon Investment Servicing "
        "is the named transfer agent. Ownership records live on Ethereum. "
        "A regulated transfer agent is treating an L1 as canonical state.\n\n"
        "I'm watching for which issuers move first."
    )
    result = anti_ai.check_draft(
        _draft(body, story_brief={"key_data_points": [{"value": "$7B"}]}),
        facts=facts,
    )
    assert result.passed, f"Expected pass, got rejections: {result.rejections}"


def test_held_view_native_vs_twins_passes(facts):
    """The native-vs-twins held-view exemplar (in voice.md) should pass."""
    body = (
        "I think the conversation about 'tokenized RWAs' is going to bifurcate this year.\n\n"
        "One half is digital twins. The other half is natively-issued onchain assets.\n\n"
        "Twins inherit every settlement risk the underlying instrument has. "
        "I'm watching for which issuers move first."
    )
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert result.passed, f"Expected pass, got: {result.rejections}"


# ---------- The three constructed BAD drafts (per the plan) ----------

def test_bad_third_person_rejected(facts):
    """Bad #1: detached third-person market commentary, no 'I' frame."""
    body = (
        "BlackRock BUIDL added ~$150M in 24 hours. TVL now $2.99B. "
        "Capital is treating onchain T-bills like infrastructure."
    )
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed
    assert "missing_first_person_frame" in result.rejections


def test_bad_hallucinated_action_rejected(facts):
    """Bad #2: 'I just bought $1M of BUIDL' — BUIDL is NOT in positions_i_hold."""
    body = "I just bought $1M of BUIDL because I think it's the best onchain MMF."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed
    # Either flagged as unverified position OR off-limits ($-specific personal trade)
    assert any(
        "unverified" in r or "off_limits" in r for r in result.rejections
    ), result.rejections


def test_bad_engagement_bait_closer_rejected(facts):
    """Bad #3: ends with 'thoughts?' without a substantive question setup."""
    body = "I think tokenized treasuries are slowing. Thoughts?"
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed
    assert "engagement_bait_closer" in result.rejections


# ---------- Additional rails ----------

def test_em_dash_rejected(facts):
    body = "I think this is a sovereignty story — not a size story."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed
    assert "em_dash_present" in result.rejections


def test_missing_media_rejected(facts):
    body = "I keep seeing the BlackRock filing read as a size story."
    result = anti_ai.check_draft(_draft(body, media_ready=False), facts=facts)
    assert not result.passed
    assert "missing_media" in result.rejections


def test_disclosed_eth_position_allowed(facts):
    """ETH is disclosed in positions_i_hold so 'I'm long ETH' should pass."""
    body = "I'm long ETH after rotating out of BTC. I think this filing changes how I read inflows."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not any("unverified_position" in r for r in result.rejections), result.rejections


def test_undisclosed_pepe_position_rejected(facts):
    body = "I just took a big long on Pepe coin. I think it's set up for a run."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed


def test_attended_eth_denver_allowed(facts):
    """ETH Denver 2026 is in things_i_have_done with approved_to_reference: true."""
    body = "I attended ETH Denver 2026 and the institutional vibe was different from 2025."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not any("unverified_personal_action" in r for r in result.rejections), result.rejections


def test_unwhitelisted_meeting_rejected(facts):
    """'I had a call with the BlackRock team' is NOT in things_i_have_done."""
    body = "I had a call with the BlackRock team last week. I think they get it."
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed


def test_off_limits_125m_abs_rejected(facts):
    """The $125M ABS Inveniam deal is explicitly off-limits."""
    body = (
        "I've been thinking about the $125M ABS tokenization program. "
        "I think the subordination tranching is the right move."
    )
    result = anti_ai.check_draft(_draft(body), facts=facts)
    assert not result.passed
    assert any("off_limits" in r for r in result.rejections), result.rejections


def test_thread_first_person_on_tweet_1(facts):
    body_json = [
        "I keep reading the $7B filing as a size story. I think it's a sovereignty story.",
        "BNY Mellon Investment Servicing is the named transfer agent.",
        "I think the compliance unlock is the moat. Not the rails.",
    ]
    result = anti_ai.check_draft(
        _draft("", fmt="thread", body_json=body_json, story_brief={"key_data_points": [{"value": "$7B"}]}),
        facts=facts,
    )
    assert result.passed, f"Expected pass, got: {result.rejections}"


def test_thread_missing_first_person_on_tweet_1_rejected(facts):
    body_json = [
        "BlackRock BUIDL added $150M in 24 hours.",
        "I think this looks like allocator behavior.",
    ]
    result = anti_ai.check_draft(
        _draft("", fmt="thread", body_json=body_json),
        facts=facts,
    )
    assert not result.passed
    assert "missing_first_person_frame" in result.rejections


def test_legacy_v1_draft_fails_under_algo_refit(facts):
    """The legacy 91751dcf draft is third-person — algo-refit correctly fails it.

    This documents the behavior change. The v1 draft was acceptable under the
    v1 voice prompt; the v2 rules now require a first-person frame.
    """
    if not LEGACY_DRAFT.exists():
        pytest.skip("legacy draft fixture not present")
    payload = json.loads(LEGACY_DRAFT.read_text())
    single_body = next(d["body"] for d in payload["drafts"] if d["format"] == "single")
    result = anti_ai.check_draft(_draft(single_body), facts=facts)
    assert not result.passed
    assert "missing_first_person_frame" in result.rejections


# ---------- Predicted algo score smoke test ----------

def test_predicted_algo_score_first_person_with_media():
    body = (
        "I keep seeing the BlackRock $7B filing read as a size story. "
        "I think it's a sovereignty story. @BNYMellon Investment Servicing "
        "is the named transfer agent."
    )
    draft = {
        "format": "single",
        "body": body,
        "media_assets": [{"status": "ready"}],
    }
    score = anti_ai.predicted_algo_score(draft)
    assert score >= 50, f"Expected score >= 50 for a clean first-person draft, got {score}"


def test_predicted_algo_score_third_person_no_media():
    body = "BlackRock BUIDL added $150M in 24 hours."
    draft = {"format": "single", "body": body, "media_assets": []}
    score = anti_ai.predicted_algo_score(draft)
    assert score < 40
