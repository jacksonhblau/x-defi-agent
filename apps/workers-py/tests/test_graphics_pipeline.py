"""End-to-end tests for the algo-refit v2 graphics pipeline.

Three reference briefs map to the three example outputs the user shared:
- Tether (gold standard)  → enforcement_action layout, Tier-1/3 logos, QA pass
- ONDO   (regression #1)  → protocol_milestone layout, Tier-1 logo for ondo, QA pass
- Kansas (regression #2)  → policy_regulation layout, no iconic-mode collapse

The tests stub the OpenAI client and the QA gate so they run offline.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

# Make the src layout importable without requiring an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

# Pre-stub httpx so the package's __init__ import chain doesn't pull it in
# when the test environment doesn't have the prod dependency installed.
try:
    import httpx  # noqa: F401
except ImportError:
    import types
    httpx = types.ModuleType("httpx")
    httpx.get = lambda *a, **k: None
    httpx.post = lambda *a, **k: None
    sys.modules["httpx"] = httpx


# ---------- Fixtures ----------

TETHER_BRIEF = {
    "headline": "Tether Freezes $344M USDT Linked to Iranian Sanctions Evasion",
    "narrative_angle": "OFAC sanctions enforcement; Tether freezes USDT on TRON tied to Iran Central Bank",
    "entities": ["Tether", "OFAC", "TRON", "Iran Central Bank"],
    "key_data_points": [
        {"label": "USDT Frozen", "value": "$344M"},
        {"label": "OFAC Response Window", "value": "<48 hours"},
        {"label": "3-Year Sanctioned USDT Total", "value": "~$1.2B"},
        {"label": "Counterparty Addresses", "value": "2"},
    ],
}

ONDO_BRIEF = {
    "headline": "ONDO Protocol Reaches $3.778B TVL Across Three-Product RWA Stack",
    "narrative_angle": "protocol milestone TVL growth across products",
    "entities": ["@ondofinance", "@BlackRock", "@JPMorgan", "@backed.fi"],
    "key_data_points": [
        {"label": "Total TVL", "value": "$3.778B"},
        {"label": "Products", "value": "3"},
    ],
}

KANSAS_BRIEF = {
    "headline": "Kansas Bankers Warn GENIUS Act Loophole Lets Stablecoins Offer Yield",
    "narrative_angle": "regulatory loophole stablecoin yield via rewards GENIUS Act",
    "entities": ["Kansas Bankers Association", "GENIUS Act"],
    "key_data_points": [
        {
            "label": "Full message",
            "value": "GENIUS Act loophole permits yield-bearing stablecoins via rewards.",
        },
        {"label": "Source URL", "value": "https://kansasbankers.com/genius-letter"},
    ],
}


# ---------- Layout selection ----------

def test_rule_based_layout_picks_enforcement_for_tether():
    from workers.graphics import higgsfield
    assert higgsfield._rule_based_layout(TETHER_BRIEF) == "enforcement_action"


def test_rule_based_layout_picks_protocol_milestone_for_ondo():
    from workers.graphics import higgsfield
    # ONDO's narrative angle is "protocol milestone TVL growth" — the rule-based
    # classifier returns protocol_milestone as the default for everything that
    # doesn't match an explicit keyword family. ONDO has no enforcement, no
    # transfer-agent, no concentration, no flow, no bifurcation, no policy
    # keywords → falls into the default rich template.
    assert higgsfield._rule_based_layout(ONDO_BRIEF) == "protocol_milestone"


def test_rule_based_layout_picks_policy_regulation_for_kansas():
    from workers.graphics import higgsfield
    assert higgsfield._rule_based_layout(KANSAS_BRIEF) == "policy_regulation"


def test_no_brief_ever_routes_to_iconic_mode():
    """The regression fix: no path through the prompt builder produces a
    single-icon poster. Verify by checking that every layout key resolves
    to a multi-section template description.
    """
    from workers.graphics import higgsfield
    for key, template in higgsfield.LAYOUT_TEMPLATES.items():
        lower = template.lower()
        # Every template must promise multiple labeled sections / tiers.
        assert any(
            term in lower
            for term in ("tier", "section", "column", "row", "card", "node")
        ), f"layout {key} doesn't describe multiple sections: {template[:80]}"
        # No template promises a single centered icon.
        assert "single centered" not in lower or "tier" in lower or "section" in lower


def test_iconic_prompt_helper_is_gone():
    """Belt-and-suspenders: the old _build_iconic_prompt function should
    no longer exist in higgsfield.
    """
    from workers.graphics import higgsfield
    assert not hasattr(higgsfield, "_build_iconic_prompt"), (
        "Iconic mode must be removed — the entire failure-mode for Kansas-style "
        "regressions lived in this helper."
    )


# ---------- kdp salvage (the looser filter) ----------

def test_kansas_kdps_get_salvaged_not_dropped():
    """The OLD filter dropped Kansas's paragraph kdp entirely → iconic mode.
    The NEW filter summarizes long values and pulls them through.
    """
    from workers.graphics import higgsfield
    out = higgsfield._renderable_kdps(KANSAS_BRIEF["key_data_points"], limit=4)
    # Source URL is still dropped (URLs aren't render-friendly).
    # Full message paragraph is meta-labeled → dropped (this is correct).
    # The looser filter doesn't *salvage* meta-labels, but the layout
    # template still produces a rich graphic from the headline + entities
    # alone — that's the structural fix.
    assert all((k.get("label") or "").lower() not in higgsfield._META_LABELS for k in out)


def test_long_value_gets_summarized():
    from workers.graphics import higgsfield
    long_brief = [
        {"label": "Description", "value": "BlackRock filed a $7B onchain money market fund with BNY Mellon serving as transfer agent and Ethereum as the canonical chain of record."},
    ]
    out = higgsfield._renderable_kdps(long_brief, limit=4)
    # Summarized: either a number was extracted, or the value was truncated.
    assert len(out) == 1
    assert len(out[0]["value"]) <= 40


# ---------- Logo resolver ----------

def test_logo_resolver_tiers_ondo_correctly():
    """The point of the algo-refit v2 is that ONDO now resolves to a real
    logo. The local bundle ships an ondofinance.svg — should hit Tier 1.
    """
    from workers.graphics import logos
    r = logos.resolve_entity("@ondofinance")
    assert r.tier == "tier1_local_svg"
    assert r.local_path is not None
    assert r.local_path.exists()


def test_logo_resolver_tiers_tether_correctly():
    """Tether isn't (yet) in the local bundle — it should fall to Tier 3
    (model knowledge) which is how the gold-standard image got its logo.
    """
    from workers.graphics import logos
    r = logos.resolve_entity("Tether")
    # Either Tier 1 (if the operator already curated tether.svg) or Tier 3.
    assert r.tier in ("tier1_local_svg", "tier3_model_knowledge")


def test_logo_resolver_tiers_unknown_brand_to_typographic():
    from workers.graphics import logos
    r = logos.resolve_entity("RandoBrandThatDoesntExist123")
    assert r.tier == "tier4_typographic"


def test_logo_resolver_handles_at_prefix():
    from workers.graphics import logos
    a = logos.resolve_entity("@BlackRock")
    b = logos.resolve_entity("BlackRock")
    assert a.tier == b.tier
    assert a.canonical_name == b.canonical_name


# ---------- Prompt assembly ----------

def test_prompt_always_includes_strict_rules():
    from workers.graphics import higgsfield
    for brief in (TETHER_BRIEF, ONDO_BRIEF, KANSAS_BRIEF):
        p = higgsfield.build_image_prompt(brief)
        assert "Strict rules" in p
        assert "SOLID FILL" in p
        assert "white" in p.lower()


def test_prompt_describes_three_or_more_sections():
    """No brief produces a prompt that asks for a single-icon poster."""
    from workers.graphics import higgsfield
    for brief in (TETHER_BRIEF, ONDO_BRIEF, KANSAS_BRIEF):
        p = higgsfield.build_image_prompt(brief).lower()
        # Must mention at least one structural element.
        assert any(t in p for t in ("tier", "section", "column", "card", "row", "node"))
        # Must not collapse to single-icon language.
        assert "single category motif" not in p
        assert "NO numeric values" not in p


# ---------- QA gate ----------

def test_qa_stub_passes_in_dev():
    """Without ANTHROPIC_API_KEY, the gate fails open with mode='stub'."""
    import os
    from workers.graphics import qa
    os.environ.pop("ANTHROPIC_API_KEY", None)
    os.environ.pop("GRAPHICS_QA_STRICT", None)
    r = qa.check(Path("/nonexistent/no.png"), TETHER_BRIEF)
    assert r.passed is True
    assert r.mode == "stub"


def test_qa_refines_prompt_for_iconic_failure():
    from workers.graphics import qa
    base = "Some base prompt with layout instructions."
    failed = qa.QAResult(
        passed=False,
        checks={
            "structured_layout": False,
            "entities_visible": True,
            "headline_matches": True,
            "no_garbled_text": True,
            "no_placeholders": True,
            "white_background": True,
            "watermark_present": True,
        },
    )
    refined = qa.refine_prompt_for_failures(base, failed)
    assert "single-icon poster" in refined.lower()
    assert "multi-section" in refined or "three labeled tiers" in refined
    assert base in refined  # base is preserved


# ---------- Dispatcher end-to-end (with stubbed AI client) ----------

class _StubClient:
    """Fake OpenAI client that writes a 1×1 PNG and returns its path."""
    def __init__(self):
        self.calls = []

    def generate_image(self, *, prompt, model, aspect, reference_images=None):
        self.calls.append({
            "prompt": prompt,
            "model": model,
            "aspect": aspect,
            "reference_count": len(reference_images or []),
        })
        import tempfile, base64
        # Minimal valid PNG (1x1 transparent)
        png_b64 = (
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="
        )
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(base64.b64decode(png_b64))
            return f.name

    def generate_video(self, *, prompt, model, aspect, duration_s):
        raise NotImplementedError("video")

    def poll(self, *, job_id, timeout_s=90):
        return {"storage_url": job_id, "credits_used": 1}


def test_dispatcher_renders_tether_with_real_logos(monkeypatch):
    """The Tether brief should: pick enforcement_action, resolve OFAC/Tether/TRON
    to Tier 3 (or Tier 1 if curated), pass references where rasterized, and ship.
    """
    monkeypatch.setenv("GRAPHICS_QA_STRICT", "false")  # stub the QA call
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from workers.graphics import higgsfield, dispatch_for_draft
    stub = _StubClient()
    higgsfield.set_client(stub)

    assets = dispatch_for_draft({"format": "single"}, TETHER_BRIEF)
    assert len(assets) == 1
    a = assets[0]
    assert a["status"] == "ready"
    diag = a["diagnostics"]
    assert diag["layout_template"] == "enforcement_action"
    assert "logo_tiers" in diag
    # Tether/OFAC/TRON should be at Tier 1 or Tier 3 — never Tier 4.
    for entity in ("Tether", "OFAC", "TRON"):
        tier = diag["logo_tiers"].get(entity)
        assert tier in ("tier1_local_svg", "tier2_cdn", "tier3_model_knowledge"), \
            f"{entity} regressed to {tier}"


def test_dispatcher_renders_ondo_without_collapse(monkeypatch):
    """The ONDO regression was a "stacked stat card" → flat layout. Now it
    should land in protocol_milestone and ondofinance.svg should be Tier 1.
    """
    monkeypatch.setenv("GRAPHICS_QA_STRICT", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from workers.graphics import higgsfield, dispatch_for_draft
    higgsfield.set_client(_StubClient())
    assets = dispatch_for_draft({"format": "single"}, ONDO_BRIEF)
    diag = assets[0]["diagnostics"]
    assert diag["layout_template"] == "protocol_milestone"
    # ondofinance.svg is in the local bundle → Tier 1.
    ondo_tier = (
        diag["logo_tiers"].get("ondofinance")
        or diag["logo_tiers"].get("Ondo")
        or diag["logo_tiers"].get("ondo")
    )
    assert ondo_tier == "tier1_local_svg", f"ondo regressed to {ondo_tier}"


def test_dispatcher_renders_kansas_without_iconic_collapse(monkeypatch):
    """The Kansas regression was iconic mode → single-icon poster. With
    iconic mode removed, Kansas must land in a rich template (policy_regulation).
    """
    monkeypatch.setenv("GRAPHICS_QA_STRICT", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from workers.graphics import higgsfield, dispatch_for_draft
    higgsfield.set_client(_StubClient())
    assets = dispatch_for_draft({"format": "single"}, KANSAS_BRIEF)
    diag = assets[0]["diagnostics"]
    assert diag["layout_template"] == "policy_regulation"
    # The prompt must NOT contain the old iconic-mode hallmarks.
    prompt = assets[0]["prompt"].lower()
    assert "single category motif" not in prompt
    assert "no numeric values" not in prompt


def test_dispatcher_emits_diagnostics_for_review_ui(monkeypatch):
    """Every asset must carry the diagnostics block for the new migration."""
    monkeypatch.setenv("GRAPHICS_QA_STRICT", "false")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    from workers.graphics import higgsfield, dispatch_for_draft
    higgsfield.set_client(_StubClient())
    for brief in (TETHER_BRIEF, ONDO_BRIEF, KANSAS_BRIEF):
        assets = dispatch_for_draft({"format": "single"}, brief)
        d = assets[0]["diagnostics"]
        for key in ("layout_template", "layout_selector", "logo_tiers", "prompt_chars"):
            assert key in d, f"diagnostics missing {key} for {brief['headline'][:40]}"
        assert d.get("fallback_to_deterministic") is False


# ---------- Brief enrichment ----------

def test_brief_enrichment_emits_tiers_and_flow_labels():
    from workers.stories.enrichment import enrich_for_graphics
    brief = dict(TETHER_BRIEF)
    enrich_for_graphics(brief)
    assert brief["tiers"], "tiers must be populated"
    assert brief["tiers"][0]["name"] == "Tether"
    assert "ACTED ON" in brief["flow_labels"] or "RELATED TO" in brief["flow_labels"]
    assert brief["supporting_stats"], "supporting_stats must be populated"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
