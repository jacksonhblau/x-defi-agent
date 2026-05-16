"""Higgsfield-style image renderer.

Builds prompts and calls a backing image-generation model to produce
editorial financial infographics for X posts. The aesthetic locked in is
the "Tether v2" style: vertical-hierarchy infographic with the headline
at the top, every labeled value from the brief rendered legibly, named
entities accompanied by their ACTUAL brand logos, light-mode, single
blue accent, @jacksonblau watermark.

Two backends are supported:
- **OpenAI Images API direct** (production default). Calls `gpt-image-1`
  via httpx with `OPENAI_API_KEY`. Same model that Higgsfield's
  `gpt_image_2` wraps. ~$0.04 per medium 1024x1024 image.
- **Higgsfield MCP** (dev / Cowork). The calling agent invokes the MCP
  tool and writes the resulting URL via `record_higgsfield_asset`.

The Module name kept as `higgsfield` for historical continuity even though
the production path is OpenAI direct.
"""

from __future__ import annotations

import base64
import logging
import os
from typing import Any, Optional, Protocol

import httpx

log = logging.getLogger(__name__)

# ---------- Model selection table ----------

# Per docs/higgsfield_integration.md §2. Defaults can be overridden by env.
#
# Algo-refit (May 2026): Higgsfield output is INFOGRAPHIC-style, not abstract
# editorial. The agent renders tightly-curated visuals that reproduce the actual
# data and entities from the brief — labeled values, named relationships, real
# typography. Pick text/diagram-capable models accordingly:
#   - gpt_image_2 — best text rendering + infographic tags
#   - nano_banana_2 — explicit "diagrams" capability, photorealistic
#   - kling_o1_image — for non-text-heavy versions
# Flux 2 is reserved for the rare case where the post is genuinely metaphorical
# (e.g., a held-view essay with no anchoring numbers).
MODEL_DEFAULTS = {
    "single": ("gpt_image_2", "1:1", "image"),
    "hot_take": ("gpt_image_2", "1:1", "image"),
    "reply": ("nano_banana_flash", "1:1", "image"),
    # Threads use still images for now — video generation isn't wired in
    # production (only OpenAI gpt-image-1 is). 1:1 matches singles so X
    # renders both formats consistently in-feed.
    "thread": ("gpt_image_2", "1:1", "image"),
    # hero_video / recap remain video format definitions for future wire-up;
    # they're currently unreachable because dispatch_for_draft routes
    # everything through the still-image path.
    "hero_video": ("kling-3", "16:9", "video"),
    "long_form": ("gpt_image_2", "16:9", "image"),
    "recap": ("veo-3-1", "16:9", "video"),
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# ---------- Prompt construction (pure, testable) ----------

# Visual identity. The model frequently defaults to a dark-mode/wireframe
# aesthetic when prompts are too prescriptive about "minimal" / "geometric"
# layouts. The fix is to lead with the AESTHETIC explicitly (white background,
# dark text, real logos) and reference the Bloomberg/FT template by name —
# the model has strong priors on what those look like, and they look right.
VISUAL_IDENTITY_SUFFIX = (
    "Visual style: solid white background (#FFFFFF). Solid near-black text "
    "(#0F172A) for headlines and labels. Bright blue (#1F6FEB) only for "
    "the headline numeric value or a single accent rule. Modern sans-serif "
    "typeface throughout (clean and humanist, like Inter or SF Pro). "
    "Headlines are bold and filled — NEVER outlined, NEVER wireframe, "
    "NEVER hollow, NEVER ghost-stroked. Text must be SOLID FILL only. "
    "Reference aesthetic: a Bloomberg Terminal card or a Financial Times "
    "graphics-desk explainer. Crisp, premium, magazine-quality finance "
    "graphic — NOT a sketch, NOT a wireframe, NOT a dark dashboard. "
    "Watermark '@jacksonblau' bottom-left, small light gray (#94A3B8), 10pt."
)

# Major brands gpt-image-1 reliably renders with real logos (Tether's green T,
# BlackRock's wordmark, the OFAC seal, TRON's diamond, JPMorgan's serif
# wordmark, etc.). For these, ask for the authentic logo.
_MAJOR_BRANDS = frozenset({
    "tether", "blackrock", "jpmorgan", "j.p. morgan", "visa", "mastercard",
    "ofac", "sec", "federal reserve", "fed", "us treasury", "treasury",
    "tron", "ethereum", "bitcoin", "solana", "ripple", "coinbase", "paypal",
    "binance", "kraken", "fidelity", "vanguard", "wisdomtree", "ishares",
    "spdr", "invesco", "vaneck", "franklin templeton", "moody's", "s&p",
    "fitch", "dtcc", "bnymellon", "bny mellon", "state street", "ubs",
    "goldman sachs", "morgan stanley", "deutsche bank", "barclays", "hsbc",
})


def _split_known_vs_niche(entities: list[str]) -> tuple[list[str], list[str]]:
    """Split entity list into (major-brand logos, niche-brand wordmarks).

    Niche brands (Ondo, Pendle, Babylon, FalconX, etc.) get rendered as clean
    typographic wordmarks in their brand color instead of invented graphic
    logos — the model doesn't reliably know them and tends to fabricate.
    """
    major, niche = [], []
    for raw in entities or []:
        clean = (raw or "").lstrip("@").strip()
        if not clean:
            continue
        if any(brand in clean.lower() for brand in _MAJOR_BRANDS):
            major.append(clean)
        else:
            niche.append(clean)
    return major, niche


def pick_layout(brief: dict[str, Any], format_hint: str) -> str:
    """Choose an infographic layout based on the brief's shape.

    Returns a layout description that the model should follow when arranging
    the data points and entities visually.
    """
    explicit = (brief or {}).get("visual_layout")
    if explicit:
        return str(explicit)
    angle = ((brief or {}).get("narrative_angle", "") or "").lower()
    kdps = (brief or {}).get("key_data_points", []) or []
    n = len(kdps)

    # Relationship / authority / sovereignty stories → vertical hierarchy
    if any(k in angle for k in ("transfer agent", "custodian", "canonical", "authority", "sovereign", "registrar")):
        return (
            "Vertical three-tier hierarchy with labeled connecting arrows showing "
            "the operational relationship between entities. Top tier: the headline "
            "issuer/event with its AUM/size figure displayed prominently. Middle "
            "tier: the named operational role (transfer agent, custodian, registrar) "
            "with the entity name and its function labeled. Bottom tier: the "
            "underlying chain or canonical-state layer with its name. Arrows are "
            "labeled with the relationship they represent."
        )

    # Concentration / consolidation → ranked horizontal bars
    if any(k in angle for k in ("consolidat", "concentrat", "absorb", "leading", "top issuer")):
        return (
            "Horizontal ranked-bar layout: one labeled row per entity, sorted by "
            "size descending. Logo or initials block on the left, entity name in "
            "the middle, AUM/size figure right-aligned at the end of the bar. The "
            "dominant entity's bar reaches the full width; others scale proportionally."
        )

    # Bifurcation / split → side-by-side columns
    if any(k in angle for k in ("fragment", "bifurcat", "split", "vs ", " vs.", "twin", "native")):
        return (
            "Side-by-side two-column comparison layout. Each column has a header "
            "label, the entity/category name, then a labeled list of attributes "
            "with values stacked below."
        )

    # Capital flow / rotation → directional diagram
    if any(k in angle for k in ("flow", "inflow", "rotation", "migrat", "into ", "out of")):
        return (
            "Left-to-right directional flow diagram. Source on the left (with "
            "labeled size figure), destination on the right (with labeled size "
            "figure), labeled arrow between them showing magnitude and direction."
        )

    # New deploy / announcement → hero card with metadata grid
    if any(k in angle for k in ("deploy", "launch", "filed", "filing", "new fund", "new product")):
        return (
            "Hero announcement card. Large entity name top-center, key headline "
            "figure (AUM, valuation) directly below in oversized type. Metadata "
            "grid below with three to five labeled fields (structure, chain, "
            "transfer agent, custodian, launch date) each as 'LABEL → value' pairs."
        )

    # Default: stat card sized by data-point count
    if n >= 4:
        return (
            "Hero-figure layout: one large headline number top-center with its "
            "label, supporting data points arranged in a 2x2 grid below, each "
            "as 'LABEL → value'."
        )
    if n >= 2:
        return (
            "Stacked stat card: one large headline number with its label, "
            "supporting figures listed below as 'LABEL → value' rows."
        )
    return "Single centered hero stat with its label rendered semibold below."


# Placeholder values that must NEVER be rendered into an image. If a kdp's value
# matches one of these (case-insensitive, whitespace-trimmed), the kdp is dropped
# from the prompt entirely. Rendering "N/a" as literal text in a financial
# infographic looks worse than rendering no stat at all.
_PLACEHOLDER_VALUES = frozenset({
    "", "n/a", "na", "n/a aum", "—", "–", "-", "--", "tbd", "tba",
    "unknown", "none", "null", "pending", "?", "??",
})

# Meta-labels from the story-builder that should NEVER appear as kdp slots in an
# image. These are bookkeeping fields (the headline itself, source URLs, the
# full Telegram message, etc.) — they aren't stat-shaped and the model can't
# render paragraphs/URLs legibly. They live in the brief for OTHER purposes
# (drafting the post body) but they're poison for the visual prompt.
_META_LABELS = frozenset({
    "headline", "full message", "source url", "source link",
    "telegram url", "telegram link", "url", "link", "note",
    "system", "internal", "raw", "raw text", "body", "summary",
    "description", "article", "tweet", "message",
})

# Max kdp value length the model can render legibly at 1024px. The Tether
# reference image's longest value is "OFAC RESPONSE WINDOW" (20 chars).
# Anything longer than this becomes hallucinated glyph soup.
_MAX_KDP_VALUE_LEN = 40


def _is_meaningful_value(value: str) -> bool:
    """Return True if the value is a real datum we can render, not a placeholder.

    Used to drop kdps like `{"label": "AUM", "value": "n/a"}` before they reach
    the image prompt. Without this filter, OpenAI faithfully renders "N/a" as
    text in the infographic, which is worse than showing no stat at all.
    """
    if not value:
        return False
    v = value.strip().lower()
    if v in _PLACEHOLDER_VALUES:
        return False
    # Catch compound placeholders: "$n/a", "n/a AUM", "USD n/a", etc.
    if "n/a" in v:
        return False
    return True


def _is_renderable_kdp(label: str, value: str) -> bool:
    """Return True only if (label, value) is short and stat-shaped enough to
    render legibly in an infographic.

    The model cannot render paragraphs, URLs, or long sentences cleanly at
    1024x1024 — it hallucinates approximate-looking glyphs. The Tether gold-
    standard image worked because every value was ≤20 chars and stat-shaped.
    This filter enforces that discipline.
    """
    if not _is_meaningful_value(value):
        return False
    v = value.strip()
    label_norm = (label or "").strip().lower()

    # Meta-labels are bookkeeping fields, not stats
    if label_norm in _META_LABELS:
        return False
    # Reject URLs outright (any scheme)
    lower = v.lower()
    if lower.startswith(("http://", "https://", "www.", "t.me/", "ftp://")):
        return False
    # Reject anything containing a URL token
    if "://" in v or ".com/" in lower or ".xyz/" in lower or "t.me/" in lower:
        return False
    # Reject long values that won't render legibly
    if len(v) > _MAX_KDP_VALUE_LEN:
        return False
    # Reject paragraphs (newlines) and markdown (bullets/headings/code/links)
    if any(c in v for c in "\n\r*#`[]"):
        return False
    # Reject sentence-shaped values: ends in period AND has 4+ words
    if v.endswith(".") and v.count(" ") >= 4:
        return False
    return True


def _clean_headline(headline: str) -> str:
    """Strip 'n/a AUM' style placeholders out of a headline.

    Story-builder titles like 'Foo Fund: n/a AUM (Commodities)' embed the
    missing data point in the title itself. Drop the placeholder so the model
    doesn't render 'N/a' in the hero type. Also tidy up trailing punctuation
    that gets orphaned by the removal.
    """
    import re
    if not headline:
        return headline
    h = headline
    # `: n/a AUM` → drop
    h = re.sub(r":\s*n/a\s+AUM\b", "", h, flags=re.IGNORECASE)
    # `(n/a AUM)` → drop
    h = re.sub(r"\(\s*n/a\s+AUM\s*\)", "", h, flags=re.IGNORECASE)
    # bare ` n/a AUM` → drop
    h = re.sub(r"\s+n/a\s+AUM\b", "", h, flags=re.IGNORECASE)
    # generic ` n/a ` token cleanup (won't catch dollarized variants but safe)
    h = re.sub(r"\bn/a\b", "", h, flags=re.IGNORECASE)
    # Collapse whitespace and orphaned punctuation
    h = re.sub(r"\s+", " ", h)
    h = re.sub(r"\s+\)", ")", h)
    h = re.sub(r"\(\s*\)", "", h)
    h = re.sub(r":\s*$", "", h)
    h = re.sub(r"\s+,", ",", h)
    return h.strip()


def _format_key_data_points(kdps: list[dict[str, Any]], limit: int = 6) -> str:
    """Render key_data_points as a verbatim block the model must reproduce.

    Drops kdps that aren't stat-shaped and renderable (placeholders, URLs,
    paragraphs, meta-labels, long sentences). Only short labeled values get
    through — that's the Tether-gold-standard discipline.
    """
    pairs: list[str] = []
    for kdp in kdps[:limit]:
        label = (kdp.get("label") or "").strip()
        value = (kdp.get("value") or "").strip()
        if _is_renderable_kdp(label, value):
            pairs.append(f'"{value}" labeled "{label}"')
    return "; ".join(pairs)


def _format_entities(entities: list[str]) -> str:
    """Strip @-prefixes and join for the prompt."""
    return ", ".join((e or "").lstrip("@").strip() for e in (entities or []) if e)


def _pick_category_icon_hint(headline: str, brief: dict[str, Any]) -> str:
    """Pick a single category-icon hint for iconic-mode prompts.

    Used when there are no renderable stats. The model gets one clean motif
    instead of being tempted to invent numbers.
    """
    h = (headline or "").lower()
    angle = ((brief or {}).get("narrative_angle", "") or "").lower()
    text = f"{h} {angle}"
    if any(k in text for k in ("treasury", "treasuries", "t-bill", "treasury debt")):
        return "Central motif: a stylized US Treasury seal or bond certificate, geometric and minimal."
    if any(k in text for k in ("gold", "silver", "copper", "metal", "palladium", "platinum", "nickel")):
        return "Central motif: a stylized metallic bar/ingot, geometric and minimal."
    if any(k in text for k in ("oil", "gas", "energy", "brent", "wti")):
        return "Central motif: a stylized oil-barrel or pipeline geometric icon, minimal."
    if "commodit" in text:
        return "Central motif: a stylized commodity-bar geometric icon, minimal."
    if "real estate" in text or "reit" in text:
        return "Central motif: a stylized skyline or building geometric icon, minimal."
    if any(k in text for k in ("equity", "stock", "share class", "tranche")):
        return "Central motif: a stylized share-certificate or ticker geometric icon, minimal."
    if any(k in text for k in ("bond", "credit", "debt")):
        return "Central motif: a stylized bond-certificate geometric icon, minimal."
    if any(k in text for k in ("stablecoin", "usdc", "usdt", "usd1", "digital dollar", "money market")):
        return "Central motif: a stylized digital-dollar coin geometric icon, minimal."
    if any(k in text for k in ("private credit", "loan", "lending")):
        return "Central motif: a stylized capital-flow geometric icon (arrow between two nodes), minimal."
    return "Central motif: a simple geometric tokenization mark (linked nodes / registry seal), minimal."


def _build_iconic_prompt(headline: str, entities: list[str], brief: dict[str, Any], aspect: str) -> str:
    """Build a minimal iconic-mode prompt for briefs with no renderable stats.

    The image is purely typographic + iconographic: cleaned headline, real
    entity brand logos (for major brands) or wordmarks (for niche brands),
    one category icon. No stat slots, no invented numbers, no 'N/A' text.
    """
    major_entities, niche_entities = _split_known_vs_niche(entities)
    icon_hint = _pick_category_icon_hint(headline, brief)
    parts = [
        VISUAL_IDENTITY_SUFFIX,
        (
            f'Single centered headline, bold filled near-black sans-serif, '
            f'three lines maximum: "{headline}".'
            if headline else ""
        ),
        (
            f"Render these MAJOR brands as their authentic official logos in "
            f"correct brand color: {', '.join(major_entities)}."
            if major_entities else ""
        ),
        (
            f"For these niche/crypto-native brands, do NOT invent a graphic "
            f"logo. Render the brand name as a clean lowercase wordmark in a "
            f"simple sans-serif: {', '.join(niche_entities)}."
            if niche_entities else ""
        ),
        icon_hint,
        (
            "Strict rules: (1) text must be SOLID FILL, never outlined or "
            "wireframe; (2) every glyph spelled correctly — if it won't fit, "
            "shrink the surrounding layout; (3) NO numeric values, percentages, "
            "or stat blocks anywhere; (4) NO URLs or hyperlink text; (5) NO "
            "paragraphs or prose beyond the headline; (6) background is solid "
            "white, never black or dark; (7) composition: centered, generous "
            "whitespace, single category motif, no decorative borders."
        ),
        VISUAL_IDENTITY_SUFFIX,
        f"{aspect} aspect ratio.",
    ]
    return " ".join(p for p in parts if p)


def build_image_prompt(brief: dict[str, Any], format_hint: str) -> str:
    """Compose an infographic prompt for any story brief.

    The "Tether v2" pattern (May 2026): vertical hierarchy infographic
    rendering headline + labeled values + named entities with their actual
    brand logos. The model knows logos for Tether, TRON, BlackRock, OFAC,
    Ethereum, etc. — telling it to render the authentic brand logos is the
    key unlock vs. generic icons.

    When a brief has no renderable stats (all kdps are placeholders like
    "n/a"), the prompt falls back to iconic mode — headline + entity logos
    + one category motif, no stat slots. Rendering 'N/a' as literal text
    is strictly worse than no stat at all.
    """
    brief = brief or {}
    raw_headline = (brief.get("headline") or "").strip()[:120]
    headline = _clean_headline(raw_headline)
    kdps_raw = brief.get("key_data_points") or []
    # Drop non-renderable kdps BEFORE layout selection so layout sizing
    # matches the actual rendered content. Strict filter rejects URLs,
    # paragraphs, meta-labels, sentences, and anything over 40 chars —
    # the model can only render short stat-shaped values legibly.
    kdps = [
        k for k in kdps_raw
        if _is_renderable_kdp(
            (k.get("label") or "").strip(),
            (k.get("value") or "").strip(),
        )
    ]
    entities = brief.get("entities") or []
    aspect = MODEL_DEFAULTS.get(format_hint, ("gpt_image_2", "1:1", "image"))[1]

    # No renderable stats → iconic mode (entity logos + category motif only).
    if not kdps:
        return _build_iconic_prompt(headline, entities, brief, aspect)

    # Cap at 3 data points. Beyond that the model has to shrink text so far
    # that it loses legibility — that's where "Manaaer" / "Assnmodlties" /
    # "Giobai" hallucinations come from. Tighter is better.
    kdps = kdps[:3]
    data_pairs = _format_key_data_points(kdps, limit=3)

    major_entities, niche_entities = _split_known_vs_niche(entities)

    parts = [
        # LEAD with visual style — the model's prior on Bloomberg/FT style is
        # what we want, so name it before any layout description.
        VISUAL_IDENTITY_SUFFIX,
        f'Headline at the top, bold filled near-black sans-serif, three lines maximum: "{headline}".' if headline else "",
        (
            f"Below the headline, render exactly these labeled values, each as a "
            f"big bold filled number (use the bright blue accent for the headline "
            f"figure) with its short label below: {data_pairs}."
            if data_pairs else ""
        ),
        (
            f"For these MAJOR brands, render their authentic official logo in "
            f"correct brand color and proportion: {', '.join(major_entities)}."
            if major_entities else ""
        ),
        (
            f"For these niche/crypto-native brands, do NOT invent a graphic logo. "
            f"Render the brand name as a clean lowercase wordmark in a simple "
            f"sans-serif, in solid near-black or the brand's known accent color "
            f"if widely recognized: {', '.join(niche_entities)}."
            if niche_entities else ""
        ),
        # Single-card layout — way simpler than the previous prescriptive layouts.
        (
            "Composition: single centered card on the white background. "
            "Generous whitespace. Two or three horizontal sections separated by "
            "thin gray hairlines. No drop shadows. No gradients. No decorative "
            "borders. No dark mode."
        ),
        # Compact strict-rules block.
        (
            "Strict rules: (1) text must be SOLID FILL, never outlined or "
            "wireframe; (2) every glyph spelled correctly — if it won't fit, "
            "shrink the surrounding card rather than render garbled text; "
            "(3) no URLs, no paragraphs, no prose; (4) no 'N/A' or placeholder "
            "values; (5) numeric values must match the provided values exactly; "
            "(6) background is solid white, never black or dark."
        ),
        f"{aspect} aspect ratio.",
    ]
    return " ".join(p for p in parts if p)


def build_infographic_prompt(brief: dict[str, Any]) -> str:
    """Alias — the algo-refit canonical entry point for prompt construction."""
    return build_image_prompt(brief, format_hint="single")


def build_video_prompt(brief: dict[str, Any], format_hint: str) -> tuple[str, int]:
    """Compose a Higgsfield-ready video prompt + duration (seconds).

    Video for the agent is an infographic that animates — labels resolve in,
    bars grow, arrows draw, values count up. Same data discipline as still
    infographics: every value in the post body appears in the video.
    """
    base = build_image_prompt(brief, format_hint)
    motion = (
        "Animate as an infographic: text labels resolve in with a subtle fade, "
        "numbers count up to their final value, bars/arrows draw on with a "
        "single sweep. No camera shake. No zoom. No fast cuts. The end frame "
        "is identical to the still infographic spec above and holds for 1-2 "
        "seconds."
    )
    duration = 12 if format_hint == "recap" else 8
    return f"{base} {motion}", duration


# ---------- Client abstraction ----------

class HiggsfieldClient(Protocol):
    """Implementation interface for either MCP (dev) or REST (prod) clients."""

    def generate_image(self, *, prompt: str, model: str, aspect: str) -> str:
        """Start generation. Return job_id."""
        ...

    def generate_video(self, *, prompt: str, model: str, aspect: str, duration_s: int) -> str:
        """Start video generation. Return job_id."""
        ...

    def poll(self, *, job_id: str, timeout_s: int = 90) -> dict[str, Any]:
        """Poll until ready or failed. Return result dict with 'storage_url' on success."""
        ...


class _OpenAIImagesClient:
    """Production image-generation client. Calls OpenAI's `gpt-image-1`
    directly via httpx — same model that Higgsfield's `gpt_image_2` wraps.

    Configuration via env:
      OPENAI_API_KEY      (required for prod)
      OPENAI_IMAGE_MODEL  (default `gpt-image-1`)
      OPENAI_IMAGE_QUALITY (default `medium`; options `low|medium|high`)
    """

    def __init__(self):
        self.api_key = os.environ.get("OPENAI_API_KEY", "")
        self.model = os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1")
        self.quality = os.environ.get("OPENAI_IMAGE_QUALITY", "medium")

    def generate_image(self, *, prompt: str, model: str, aspect: str) -> str:
        """Synchronously generate an image. Returns a local /tmp filename.

        Unlike async APIs there's no job_id; the request blocks until the
        image is ready (~10–30s). We write the bytes to /tmp and return that
        path; the caller uploads to Supabase Storage.
        """
        if not self.api_key:
            raise NotImplementedError(
                "OPENAI_API_KEY not set. Add it to your env (locally) or to Fly "
                "secrets (production): `fly secrets set OPENAI_API_KEY=sk-...`. "
                "OpenAI gpt-image-1 is the same model Higgsfield's gpt_image_2 wraps."
            )

        size = {"1:1": "1024x1024", "16:9": "1536x1024", "9:16": "1024x1536"}.get(aspect, "1024x1024")

        response = httpx.post(
            "https://api.openai.com/v1/images/generations",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "prompt": prompt[:32000],  # OpenAI prompt cap is generous
                "n": 1,
                "size": size,
                "quality": self.quality,
            },
            timeout=90.0,
        )
        response.raise_for_status()
        data = response.json()
        b64 = data["data"][0]["b64_json"]
        png_bytes = base64.b64decode(b64)

        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False, prefix="openai_img_") as f:
            f.write(png_bytes)
            return f.name

    def generate_video(self, *, prompt: str, model: str, aspect: str, duration_s: int) -> str:
        raise NotImplementedError(
            "Video generation not yet wired in production. Use Higgsfield MCP in "
            "Cowork or wire Veo/Kling separately."
        )

    def poll(self, *, job_id: str, timeout_s: int = 90) -> dict[str, Any]:
        # OpenAI Images is synchronous — generate_image returns the local path
        # directly. This poll is a no-op compatibility shim.
        return {"storage_url": job_id, "credits_used": 1}


# Default client: OpenAI direct (production). In Cowork dev, the agent can
# override by calling `record_higgsfield_asset` after manually running the
# Higgsfield MCP tool.
_default_client: HiggsfieldClient = _OpenAIImagesClient()


def set_client(client: HiggsfieldClient) -> None:
    """Plug in a custom client (e.g., for testing or MCP-mediated dev runs)."""
    global _default_client
    _default_client = client


# ---------- Render entrypoint ----------

def render(brief: dict[str, Any], format_hint: str = "single") -> dict[str, Any]:
    """Render an editorial asset via Higgsfield.

    In production this calls the REST client end-to-end. In Cowork/dev, the
    calling agent should override via `set_client` or simply build the prompt
    here, run the MCP tool manually, then construct the MediaAsset dict
    with `record_higgsfield_asset`.

    Returns a MediaAsset dict (status='queued' on failure to dispatch, or
    'ready' once storage_url is available).
    """
    model_key, aspect, kind = MODEL_DEFAULTS.get(format_hint, MODEL_DEFAULTS["single"])
    model_key = _env(
        "HIGGSFIELD_DEFAULT_VIDEO_MODEL" if kind == "video" else "HIGGSFIELD_DEFAULT_IMAGE_MODEL",
        model_key,
    )

    if kind == "video":
        prompt, duration_s = build_video_prompt(brief, format_hint)
    else:
        prompt = build_image_prompt(brief, format_hint)
        duration_s = None

    asset: dict[str, Any] = {
        "kind": kind,
        "source": "higgsfield",
        "model": model_key,
        "prompt": prompt,
        "status": "queued",
        "aspect": aspect,
        "duration_s": duration_s,
    }

    try:
        if kind == "video":
            job_id = _default_client.generate_video(
                prompt=prompt, model=model_key, aspect=aspect, duration_s=duration_s or 8
            )
        else:
            # OpenAI client's generate_image returns a local /tmp PNG path.
            local_path = _default_client.generate_image(prompt=prompt, model=model_key, aspect=aspect)
            asset["status"] = "running"

            # Upload to Supabase Storage so the Vercel UI can render the image.
            import uuid as _uuid
            from pathlib import Path
            asset_id = str(_uuid.uuid4())
            asset["id"] = asset_id

            public_url = _upload_to_supabase_storage(Path(local_path), asset_id)
            asset["storage_url"] = public_url or local_path
            asset["local_path"] = local_path
            asset["uploaded_to_supabase"] = public_url is not None
            asset["status"] = "ready"
            asset["credits_used"] = 1
            return asset

        # Video path (unchanged — async, polls)
        asset["higgsfield_job_id"] = job_id
        asset["status"] = "running"
        result = _default_client.poll(job_id=job_id, timeout_s=90)
        asset["status"] = "ready"
        asset["storage_url"] = result.get("storage_url", "")
        asset["credits_used"] = result.get("credits_used")
    except NotImplementedError as e:
        # Expected in Cowork/dev when OPENAI_API_KEY is missing — the agent
        # is responsible for invoking the MCP tool and calling record_higgsfield_asset.
        asset["status"] = "queued"
        asset["note"] = f"Image client not wired: {e}"
    except Exception as e:  # noqa: BLE001
        asset["status"] = "failed"
        asset["error"] = str(e)
        log.warning("higgsfield.render failed: %s", e)

    return asset


# ---------- Supabase Storage upload (re-used from canvas_design pattern) ----------

def _upload_to_supabase_storage(local_path, asset_id: str) -> Optional[str]:
    """Upload the generated PNG to the public `media` bucket. Falls back to
    None on any failure — caller will use the local path as storage_url so
    the asset row still gets created.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = (
        os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    bucket = os.environ.get("SUPABASE_MEDIA_BUCKET", "media")
    if not (supabase_url and service_key):
        return None
    object_key = f"higgsfield/{asset_id}.png"
    upload_url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    public_url = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{object_key}"
    try:
        with open(local_path, "rb") as f:
            body = f.read()
        r = httpx.post(
            upload_url,
            content=body,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "image/png",
                "x-upsert": "true",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
            timeout=30.0,
        )
        if r.status_code >= 400:
            log.warning("Supabase upload failed (%s): %s", r.status_code, r.text[:200])
            return None
        return public_url
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase upload exception: %s", e)
        return None


def record_higgsfield_asset(
    *,
    brief: dict[str, Any],
    format_hint: str,
    job_id: str,
    storage_url: str,
    credits_used: Optional[int] = None,
) -> dict[str, Any]:
    """Record a Higgsfield asset that was generated outside the Python layer
    (e.g., by the agent invoking the MCP tool in a Cowork session).

    Returns a ready MediaAsset dict for persisting to the media_assets table.
    """
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
