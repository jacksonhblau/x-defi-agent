"""AI infographic renderer — gpt-image-1 with real-logo references.

The pipeline is intentionally hybrid. This module owns the AI path; it
classifies every brief into one of seven *all-rich* layout templates,
resolves entity logos through `logos.py`, and calls OpenAI's image-edits
endpoint so the model composites real brand marks instead of hallucinating.

Iconic mode is GONE. Every brief gets a multi-tier layout. Thin briefs
are enriched at the story-builder layer (see stories/builder.py) so the
prompt always has tier and supporting-stats content to render. If a brief
still arrives thin, we synthesize a minimal three-tier shape from the
headline rather than collapse to a single-icon poster.

The module name is kept as `higgsfield` for historical continuity even
though the production path is OpenAI direct.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Any, Optional, Protocol

import httpx

from . import logos as logo_resolver
from .logos import LogoResolution

log = logging.getLogger(__name__)


# ---------- Model selection ----------

MODEL_DEFAULTS = {
    "single":     ("gpt-image-1", "1:1",  "image"),
    "hot_take":   ("gpt-image-1", "1:1",  "image"),
    "reply":      ("gpt-image-1", "1:1",  "image"),
    "thread":     ("gpt-image-1", "1:1",  "image"),
    "long_form":  ("gpt-image-1", "16:9", "image"),
    "hero_video": ("kling-3",     "16:9", "video"),
    "recap":      ("veo-3-1",     "16:9", "video"),
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# ---------- Visual identity ----------

VISUAL_IDENTITY = (
    "Visual style: solid white background (#FFFFFF). Solid near-black text "
    "(#0F172A) for headlines and labels. Bright blue (#1F6FEB) only for the "
    "headline numeric value or a single accent rule. Modern sans-serif "
    "typeface throughout (clean and humanist, like Inter or SF Pro). "
    "Headlines are bold and filled — NEVER outlined, NEVER wireframe, "
    "NEVER hollow, NEVER ghost-stroked. Text must be SOLID FILL only. "
    "Reference aesthetic: a Bloomberg Terminal card or a Financial Times "
    "graphics-desk explainer. Crisp, premium, magazine-quality finance "
    "graphic. Watermark '@jacksonblau' bottom-left, small light gray "
    "(#94A3B8), 10pt. No drop shadows, no gradients, no decorative borders, "
    "no dark mode."
)


STRICT_RULES = (
    "Strict rules: (1) text must be SOLID FILL, never outlined; (2) every "
    "glyph spelled correctly — if it won't fit, shrink the surrounding "
    "card rather than render garbled text; (3) no URLs, no paragraphs, no "
    "prose beyond labeled headlines and short values; (4) no 'N/A' or "
    "placeholder values rendered as literal text; (5) numeric values must "
    "match the provided values exactly; (6) background is solid white; "
    "(7) layout MUST have at least three distinct labeled sections — never "
    "a single centered icon poster."
)


# ---------- The seven rich layout templates ----------
#
# Every brief lands in exactly one of these. There is NO iconic-mode
# fallback. The pipeline is rich-by-construction.

LAYOUT_TEMPLATES: dict[str, str] = {
    # 1. Enforcement / sanctions action (the Tether pattern)
    "enforcement_action": (
        "Vertical three-tier hierarchy with labeled connecting arrows showing "
        "the operational chain of an enforcement action. Top tier: the acting "
        "entity (issuer/exchange/government body) with its headline figure "
        "displayed prominently (frozen amount, fine, response window). Middle "
        "tier: the triggering authority (regulator/agency) with its response "
        "window or order detail. Bottom tier: the underlying chain or "
        "counterparty addresses with the ultimate beneficiary labeled. "
        "Connecting arrows between tiers are labeled with the relationship "
        "('ACTED ON', 'EXECUTED FREEZE ON'). Below the main figure, a two-tile "
        "supporting-stats row shows context figures (e.g., 3-year totals, "
        "address counts)."
    ),
    # 2. Protocol milestone (TVL, AUM crossing, product launch)
    "protocol_milestone": (
        "Hero milestone card with a clear three-section structure. Top: the "
        "protocol/issuer name in large bold type with its primary headline "
        "figure (TVL, AUM, supply) in oversized bright-blue digits. Middle: "
        "two or three product/category cards arranged horizontally, each "
        "labeled with its name and contributing figure. Bottom: a "
        "supporting-partners row listing major counterparty entities "
        "(custodian, transfer agent, asset manager) as labeled cards with "
        "their logos. Two small stat tiles at the very bottom for context "
        "(e.g., MoM change, year-over-year, category rank)."
    ),
    # 3. Policy / regulation explainer
    "policy_regulation": (
        "Three-section regulatory-explainer card. Top: headline naming the "
        "policy or bill (e.g., GENIUS Act, MiCA) with the issuing body's "
        "seal/logo to one side. Middle: a two-column comparison — left "
        "column the rule as written, right column the loophole or impact, "
        "each as labeled bullets in card format. Bottom: a labeled "
        "stakeholders row listing the affected entities (banks, "
        "stablecoin issuers, exchanges) each as a small labeled card. "
        "Two supporting-stat tiles at the bottom for affected-market size "
        "or implementation date."
    ),
    # 4. Deploy / announcement
    "deploy_announcement": (
        "Hero announcement card with a metadata grid. Large issuer name "
        "and product name top-center, the headline figure (filed AUM, "
        "valuation, supply) directly below in oversized bright-blue type. "
        "Below that a 2x2 or 3x1 metadata grid of labeled fields "
        "(structure, chain, transfer agent, custodian) each as 'LABEL → "
        "value' pairs in card format. Bottom row: two stat tiles for "
        "context (peer comparable, category TVL)."
    ),
    # 5. TVL / concentration ranking
    "tvl_concentration": (
        "Ranked horizontal-bar layout. Title bar at the top with the "
        "category and time period. One labeled row per entity sorted by "
        "size descending: small logo block on the left, entity name in "
        "the middle, AUM/size figure right-aligned at the end of the bar. "
        "The dominant entity's bar reaches full width; others scale "
        "proportionally. Bottom row: two supporting-stat tiles for "
        "category total and top-3 share."
    ),
    # 6. Capital flow / rotation
    "flow_rotation": (
        "Left-to-right directional flow diagram. Three labeled nodes: "
        "source on the left (with its size figure), intermediate (if any) "
        "in the middle, destination on the right (with its size figure). "
        "Labeled arrows between nodes showing magnitude and direction. "
        "Below the flow, a supporting-stats row with two tiles for "
        "context (e.g., flow as % of total, time window)."
    ),
    # 7. Bifurcation / split
    "bifurcation": (
        "Side-by-side two-column comparison layout. Title bar at the top "
        "naming the split. Each column has a header label, the entity or "
        "category name, then a labeled list of attributes with values "
        "stacked below as small labeled cards. Bottom: a supporting-stats "
        "row with two tiles for total size and split ratio."
    ),
}


# Keyword classifier — used as the deterministic fallback when the LLM-based
# layout selector is unavailable (no ANTHROPIC_API_KEY, network failure,
# unit tests). Always returns one of LAYOUT_TEMPLATES — never iconic.
def _rule_based_layout(brief: dict[str, Any]) -> str:
    angle = ((brief or {}).get("narrative_angle", "") or "").lower()
    headline = ((brief or {}).get("headline", "") or "").lower()
    text = f"{angle} {headline}"

    if any(k in text for k in (
        "sanction", "freeze", "frozen", "ofac", "enforcement", "fine",
        "seizure", "seized", "indictment", "lawsuit",
    )):
        return "enforcement_action"
    if any(k in text for k in (
        "transfer agent", "custodian", "registrar", "deploy", "launch",
        "filed", "filing", "new fund", "new product", "files",
    )):
        return "deploy_announcement"
    if any(k in text for k in (
        "consolidat", "concentrat", "absorb", "leading", "top issuer",
        "ranked", "rank ", " rank,",
    )):
        return "tvl_concentration"
    if any(k in text for k in ("fragment", "bifurcat", "split", " vs ", " vs.", "twin")):
        return "bifurcation"
    if any(k in text for k in ("flow", "inflow", "outflow", "rotation", "migrat", "into ", "out of")):
        return "flow_rotation"
    if any(k in text for k in (
        "loophole", "regulation", "regulator", "policy", "rule",
        "genius act", "mica", "bill", "law",
    )):
        return "policy_regulation"
    # Default — protocol milestone is rich and covers the long tail
    # (TVL updates, AUM crossings, product growth).
    return "protocol_milestone"


def _llm_layout(brief: dict[str, Any]) -> Optional[str]:
    """Use claude-haiku to pick a layout. Returns None on any failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None
    options = list(LAYOUT_TEMPLATES.keys())
    prompt = (
        "Classify this finance/crypto news brief into exactly one of these "
        f"infographic layout templates: {', '.join(options)}.\n\n"
        f"HEADLINE: {(brief or {}).get('headline', '')}\n"
        f"NARRATIVE ANGLE: {(brief or {}).get('narrative_angle', '')}\n"
        f"ENTITIES: {', '.join((brief or {}).get('entities', []) or [])}\n\n"
        "Return ONLY the template name, nothing else."
    )
    try:
        r = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": "claude-haiku-4-5-20251001",
                "max_tokens": 30,
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=10.0,
        )
        r.raise_for_status()
        text = r.json()["content"][0]["text"].strip().lower()
        # exact match
        if text in LAYOUT_TEMPLATES:
            return text
        # substring match (handles trailing punctuation)
        for k in LAYOUT_TEMPLATES:
            if k in text:
                return k
    except Exception as e:  # noqa: BLE001
        log.debug("LLM layout selector failed: %s", e)
    return None


def select_layout(brief: dict[str, Any]) -> tuple[str, str]:
    """Pick a layout template. Returns (template_key, selector_used)."""
    # Honor an explicit override on the brief
    explicit = (brief or {}).get("layout_template")
    if explicit and explicit in LAYOUT_TEMPLATES:
        return explicit, "explicit"
    llm_choice = _llm_layout(brief)
    if llm_choice is not None:
        return llm_choice, "llm"
    return _rule_based_layout(brief), "rule_based"


# ---------- kdp transformation (replaces the old strict filter) ----------

_PLACEHOLDER_VALUES = frozenset({
    "", "n/a", "na", "n/a aum", "—", "–", "-", "--", "tbd", "tba",
    "unknown", "none", "null", "pending", "?", "??",
})

_META_LABELS = frozenset({
    "headline", "full message", "source url", "source link",
    "telegram url", "telegram link", "url", "link", "raw", "raw text",
})

_MAX_KDP_VALUE_LEN = 40


def _is_placeholder(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in _PLACEHOLDER_VALUES or "n/a" in v


def _summarize_long_value(value: str, max_len: int = _MAX_KDP_VALUE_LEN) -> str:
    """Compress a long value to ≤max_len characters while preserving meaning.

    Tries (in order): pull a number, pull a short noun phrase, hard truncate.
    Used to salvage paragraph-shaped values that the old filter would drop.
    """
    v = (value or "").strip()
    if len(v) <= max_len:
        return v
    # Look for a $-denominated number or percentage in the first 80 chars
    m = re.search(r"(\$?\d[\d,.]*[%BMK]?\s*[a-zA-Z]{0,12})", v[:120])
    if m and len(m.group(1)) <= max_len:
        return m.group(1).strip()
    # Otherwise hard-truncate at a word boundary
    cut = v[: max_len - 1].rsplit(" ", 1)[0]
    return cut + "…"


def _renderable_kdps(kdps: list[dict[str, Any]], limit: int = 4) -> list[dict[str, str]]:
    """Transform kdps into a render-friendly form.

    Drops: meta-labels, URLs, n/a values. Summarizes: paragraphs and long
    values to ≤40 chars. This is LESS aggressive than the old filter —
    paragraphs aren't dropped, they're salvaged.
    """
    out: list[dict[str, str]] = []
    for k in kdps or []:
        label = (k.get("label") or "").strip()
        value = (k.get("value") or "").strip()
        if not value:
            continue
        if _is_placeholder(value):
            continue
        if label.lower() in _META_LABELS:
            continue
        lower = value.lower()
        if lower.startswith(("http://", "https://", "www.", "t.me/", "ftp://")):
            continue
        if "://" in value:
            continue
        # Newlines or markdown markers → first sentence only
        if "\n" in value or any(c in value for c in "*#`"):
            value = re.split(r"[.\n]", value, maxsplit=1)[0].strip()
            if not value:
                continue
        value = _summarize_long_value(value)
        if value:
            out.append({"label": label, "value": value})
        if len(out) >= limit:
            break
    return out


def _clean_headline(headline: str) -> str:
    if not headline:
        return headline
    h = re.sub(r":\s*n/a\s+AUM\b", "", headline, flags=re.IGNORECASE)
    h = re.sub(r"\(\s*n/a\s+AUM\s*\)", "", h, flags=re.IGNORECASE)
    h = re.sub(r"\s+n/a\s+AUM\b", "", h, flags=re.IGNORECASE)
    h = re.sub(r"\bn/a\b", "", h, flags=re.IGNORECASE)
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\s+\)", ")", h)
    h = re.sub(r"\(\s*\)", "", h)
    h = re.sub(r":\s*$", "", h)
    return h.strip()


# ---------- Prompt assembly ----------

def _entity_directives(resolutions: list[LogoResolution]) -> str:
    """Build the entity-rendering directive block for the prompt.

    Per-tier instructions: Tier-1/2 entities reference an attached image
    file (image[N] in the API call). Tier-3 entities ask the model to
    render the authentic logo from its training. Tier-4 entities render
    as typographic wordmarks.
    """
    if not resolutions:
        return ""
    parts: list[str] = []
    ref_brands = [r for r in resolutions if r.renders_via_reference_image]
    model_brands = [r for r in resolutions if r.tier == "tier3_model_knowledge"]
    wordmarks = [r for r in resolutions if r.tier == "tier4_typographic"]
    if ref_brands:
        names = ", ".join(r.canonical_name for r in ref_brands)
        parts.append(
            f"For these entities, composite the AUTHENTIC logo provided as a "
            f"reference image (preserve aspect ratio, place inside the relevant "
            f"labeled card or tier): {names}."
        )
    if model_brands:
        names = ", ".join(r.canonical_name for r in model_brands)
        parts.append(
            f"For these globally-recognized entities, render their authentic "
            f"official logo in correct brand color and proportion: {names}."
        )
    if wordmarks:
        names = ", ".join(r.canonical_name for r in wordmarks)
        parts.append(
            f"For these niche brands, do NOT invent a graphic logo. Render the "
            f"brand name as a clean wordmark in simple sans-serif type, in "
            f"solid near-black: {names}."
        )
    return " ".join(parts)


def _format_kdps_for_prompt(kdps: list[dict[str, str]]) -> str:
    if not kdps:
        return ""
    return "; ".join(f'"{k["value"]}" labeled "{k["label"]}"' for k in kdps)


def build_image_prompt(
    brief: dict[str, Any],
    format_hint: str = "single",
    *,
    layout_key: Optional[str] = None,
    resolutions: Optional[list[LogoResolution]] = None,
) -> str:
    """Compose the full image prompt for a brief.

    If `layout_key` / `resolutions` are provided, they're used as-is (so the
    dispatcher can compute them once and emit them into diagnostics). If
    omitted, they're computed here.
    """
    brief = brief or {}
    headline = _clean_headline((brief.get("headline") or "").strip()[:140])
    kdps = _renderable_kdps(brief.get("key_data_points") or [], limit=4)
    entities = brief.get("entities") or []
    aspect = MODEL_DEFAULTS.get(format_hint, ("gpt-image-1", "1:1", "image"))[1]

    if layout_key is None:
        layout_key, _ = select_layout(brief)
    template = LAYOUT_TEMPLATES.get(layout_key, LAYOUT_TEMPLATES["protocol_milestone"])

    if resolutions is None:
        resolutions = logo_resolver.resolve_entities(entities)

    data_pairs = _format_kdps_for_prompt(kdps)
    entity_block = _entity_directives(resolutions)

    parts = [
        VISUAL_IDENTITY,
        f'Headline at the top, bold filled near-black sans-serif, three lines maximum: "{headline}".' if headline else "",
        f"Composition: {template}",
        (
            f"Render exactly these labeled values inside the appropriate "
            f"sections, each as a big bold filled number (use the bright "
            f"blue accent for the headline figure) with its short label "
            f"below: {data_pairs}."
            if data_pairs else
            "If specific numeric values are not provided in the brief, "
            "render the layout structure with the entity names and their "
            "relationships visible — do NOT invent numeric values."
        ),
        entity_block,
        STRICT_RULES,
        f"{aspect} aspect ratio.",
    ]
    return " ".join(p for p in parts if p)


def build_infographic_prompt(brief: dict[str, Any]) -> str:
    """Canonical entry point for prompt construction (algo-refit alias)."""
    return build_image_prompt(brief, format_hint="single")


def build_video_prompt(brief: dict[str, Any], format_hint: str) -> tuple[str, int]:
    base = build_image_prompt(brief, format_hint)
    motion = (
        "Animate as an infographic: labels fade in, numbers count up, "
        "bars/arrows draw on with a single sweep. No camera shake, no zoom, "
        "no fast cuts. End frame holds for 1-2 seconds."
    )
    duration = 12 if format_hint == "recap" else 8
    return f"{base} {motion}", duration


# ---------- Client abstraction ----------

class HiggsfieldClient(Protocol):
    def generate_image(
        self,
        *,
        prompt: str,
        model: str,
        aspect: str,
        reference_images: Optional[list[Path]] = None,
    ) -> str: ...

    def generate_video(
        self, *, prompt: str, model: str, aspect: str, duration_s: int
    ) -> str: ...

    def poll(self, *, job_id: str, timeout_s: int = 90) -> dict[str, Any]: ...


class _OpenAIImagesClient:
    """Production client. Calls OpenAI gpt-image-1.

    When `reference_images` is non-empty, uses /v1/images/edits (multipart)
    so the model composites the actual logo files. Otherwise falls back
    to /v1/images/generations.
    """

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.quality = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")

    def generate_image(
        self,
        *,
        prompt: str,
        model: str,
        aspect: str,
        reference_images: Optional[list[Path]] = None,
    ) -> str:
        if not self.api_key:
            raise NotImplementedError(
                "OPENAI_API_KEY not set. Add it to your env or to Fly secrets."
            )
        size = {"1:1": "1024x1024", "16:9": "1536x1024", "9:16": "1024x1536"}.get(
            aspect, "1024x1024"
        )

        # Edits API: pass reference images. Generations API: prompt only.
        refs = [p for p in (reference_images or []) if p and Path(p).exists()]
        if refs:
            files = []
            for i, p in enumerate(refs[:8]):  # OpenAI accepts up to ~8 refs
                files.append(("image[]", (Path(p).name, Path(p).read_bytes(), "image/png")))
            data = {
                "model": self.model,
                "prompt": prompt[:32000],
                "size": size,
                "quality": self.quality,
                "n": "1",
            }
            r = httpx.post(
                "https://api.openai.com/v1/images/edits",
                headers={"Authorization": f"Bearer {self.api_key}"},
                data=data,
                files=files,
                timeout=120.0,
            )
        else:
            r = httpx.post(
                "https://api.openai.com/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "prompt": prompt[:32000],
                    "n": 1,
                    "size": size,
                    "quality": self.quality,
                },
                timeout=120.0,
            )
        r.raise_for_status()
        body = r.json()
        b64 = body["data"][0]["b64_json"]
        png_bytes = base64.b64decode(b64)
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="openai_img_") as f:
            f.write(png_bytes)
            return f.name

    def generate_video(
        self, *, prompt: str, model: str, aspect: str, duration_s: int
    ) -> str:
        raise NotImplementedError("Video generation not yet wired in production.")

    def poll(self, *, job_id: str, timeout_s: int = 90) -> dict[str, Any]:
        return {"storage_url": job_id, "credits_used": 1}


_default_client: HiggsfieldClient = _OpenAIImagesClient()


def set_client(client: HiggsfieldClient) -> None:
    global _default_client
    _default_client = client


def get_client() -> HiggsfieldClient:
    return _default_client


# ---------- Render entrypoints ----------

def render(brief: dict[str, Any], format_hint: str = "single") -> dict[str, Any]:
    """Render a single AI image asset.

    Returns a MediaAsset-shaped dict including a `diagnostics` block that
    the dispatcher merges into the persisted media_assets row. The
    dispatcher wraps THIS function with QA + retry + deterministic
    fallback — keep the function focused on a single AI generation.
    """
    model_key, aspect, kind = MODEL_DEFAULTS.get(format_hint, MODEL_DEFAULTS["single"])
    if kind == "video":
        prompt, duration_s = build_video_prompt(brief, format_hint)
    else:
        duration_s = None
        layout_key, selector = select_layout(brief)
        resolutions = logo_resolver.resolve_entities(brief.get("entities") or [])
        prompt = build_image_prompt(
            brief, format_hint,
            layout_key=layout_key,
            resolutions=resolutions,
        )

    diagnostics: dict[str, Any] = {
        "source": "ai",
        "model": model_key,
        "aspect": aspect,
        "prompt_chars": len(prompt) if prompt else 0,
    }
    if kind != "video":
        diagnostics["layout_template"] = layout_key
        diagnostics["layout_selector"] = selector
        diagnostics["logo_tiers"] = logo_resolver.diagnostics_summary(resolutions)

    asset: dict[str, Any] = {
        "kind": kind,
        "source": "higgsfield",
        "model": model_key,
        "prompt": prompt,
        "status": "queued",
        "aspect": aspect,
        "duration_s": duration_s,
        "diagnostics": diagnostics,
    }

    t0 = time.time()
    try:
        if kind == "video":
            job_id = _default_client.generate_video(
                prompt=prompt, model=model_key, aspect=aspect, duration_s=duration_s or 8
            )
            asset["higgsfield_job_id"] = job_id
            asset["status"] = "running"
            result = _default_client.poll(job_id=job_id, timeout_s=90)
            asset["status"] = "ready"
            asset["storage_url"] = result.get("storage_url", "")
            asset["credits_used"] = result.get("credits_used")
        else:
            ref_paths = [
                r.rasterized_path for r in resolutions
                if r.rasterized_path and r.renders_via_reference_image
            ]
            local_path = _default_client.generate_image(
                prompt=prompt, model=model_key, aspect=aspect,
                reference_images=ref_paths,
            )
            asset["local_path"] = local_path
            asset["status"] = "ready"
            asset["credits_used"] = 1
            # Supabase upload is the dispatcher's responsibility.
    except NotImplementedError as e:
        asset["status"] = "queued"
        asset["note"] = f"Image client not wired: {e}"
    except Exception as e:  # noqa: BLE001
        asset["status"] = "failed"
        asset["error"] = str(e)
        log.warning("higgsfield.render failed: %s", e)

    asset["diagnostics"]["elapsed_ms"] = int((time.time() - t0) * 1000)
    return asset


def render_with_prompt_override(
    brief: dict[str, Any],
    *,
    prompt: str,
    format_hint: str = "single",
    resolutions: Optional[list[LogoResolution]] = None,
) -> dict[str, Any]:
    """Generate an image using a caller-supplied prompt (e.g., a QA-refined
    retry prompt). Same entity-reference-image logic. Used by the dispatcher
    on QA failure retry.
    """
    model_key, aspect, _ = MODEL_DEFAULTS.get(format_hint, MODEL_DEFAULTS["single"])
    if resolutions is None:
        resolutions = logo_resolver.resolve_entities(brief.get("entities") or [])
    ref_paths = [
        r.rasterized_path for r in resolutions
        if r.rasterized_path and r.renders_via_reference_image
    ]
    t0 = time.time()
    asset: dict[str, Any] = {
        "kind": "image",
        "source": "higgsfield",
        "model": model_key,
        "prompt": prompt,
        "aspect": aspect,
        "diagnostics": {
            "source": "ai",
            "model": model_key,
            "aspect": aspect,
            "prompt_chars": len(prompt) if prompt else 0,
            "retry": True,
        },
        "status": "queued",
    }
    try:
        local = _default_client.generate_image(
            prompt=prompt, model=model_key, aspect=aspect,
            reference_images=ref_paths,
        )
        asset["local_path"] = local
        asset["status"] = "ready"
        asset["credits_used"] = 1
    except Exception as e:  # noqa: BLE001
        asset["status"] = "failed"
        asset["error"] = str(e)
    asset["diagnostics"]["elapsed_ms"] = int((time.time() - t0) * 1000)
    return asset


def record_higgsfield_asset(
    *,
    brief: dict[str, Any],
    format_hint: str,
    job_id: str,
    storage_url: str,
    credits_used: Optional[int] = None,
) -> dict[str, Any]:
    """Record an asset generated outside this module (e.g., MCP in Cowork dev)."""
    model_key, aspect, kind = MODEL_DEFAULTS.get(format_hint, MODEL_DEFAULTS["single"])
    if kind == "video":
        prompt, duration_s = build_video_prompt(brief, format_hint)
    else:
        prompt = build_image_prompt(brief, format_hint)
        duration_s = None
    return {
        "kind": kind,
        "source": "higgsfield",
        "model": model_key,
        "prompt": prompt,
        "higgsfield_job_id": job_id,
        "storage_url": storage_url,
        "status": "ready",
        "aspect": aspect,
        "duration_s": duration_s,
        "credits_used": credits_used,
    }


# ---------- Back-compat exports ----------
# Older callers reference _MAJOR_BRANDS or pick_layout directly. Keep
# thin shims so nothing breaks.

_MAJOR_BRANDS = frozenset(logo_resolver.MODEL_KNOWN_BRANDS.keys())

def pick_layout(brief: dict[str, Any], format_hint: str = "single") -> str:
    """Back-compat: returns the layout TEMPLATE TEXT (not the key)."""
    key, _ = select_layout(brief)
    return LAYOUT_TEMPLATES[key]
