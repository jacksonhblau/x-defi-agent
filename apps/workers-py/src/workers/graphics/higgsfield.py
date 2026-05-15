"""Higgsfield image / video renderer.

Builds prompts for Higgsfield models, calls the MCP server (dev) or REST API
(prod), polls until ready, applies the @jacksonblau watermark, uploads to
Supabase Storage, and writes a `media_assets` row.

The MCP/REST client is plug-injected so the same module works in:
- **Cowork dev** — Higgsfield MCP server (tools prefixed `mcp__39dcce27-…`).
  The calling Claude session executes the MCP tools and passes the resulting
  storage URL into `record_higgsfield_asset`.
- **Production VPS** — Higgsfield REST API (`HIGGSFIELD_REST_URL`,
  `HIGGSFIELD_API_KEY`). Implemented in `_HiggsfieldRESTClient`.

See `docs/higgsfield_integration.md` for the full spec.
"""

from __future__ import annotations

import os
from typing import Any, Optional, Protocol

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
    "thread": ("kling-3", "16:9", "video"),
    "hero_video": ("kling-3", "16:9", "video"),
    "long_form": ("gpt_image_2", "16:9", "image"),
    "recap": ("veo-3-1", "16:9", "video"),
}


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


# ---------- Prompt construction (pure, testable) ----------

# Algo-refit visual identity. Higgsfield output is an INFOGRAPHIC that visually
# reproduces the data and named entities discussed in the post body, NOT an
# abstract metaphor that loosely connects to the message. Think Bloomberg
# Terminal or a financial analyst's deck slide — typography-forward, structured
# layout, labeled stats, real entity names rendered legibly.
VISUAL_IDENTITY_SUFFIX = (
    "Style: editorial financial infographic, minimal, light-mode. "
    "Background near-white (#FAFAFA to #FFFFFF). Primary blue #1F6FEB used "
    "sparingly for emphasis (one accent per block). Near-black #0F172A for "
    "headline type, dark gray #64748B for labels. Geometric sans-serif "
    "typography only (Inter or similar), tabular numbers, semibold for values, "
    "regular for labels. No decorative fonts. No stock-photo finance clichés "
    "(no piggy banks, no rising arrow with dollar sign, no robot handshakes, "
    "no generic crypto art). No abstract concept illustration. The image is "
    "a structured visual reproduction of the data and entities discussed in "
    "the post — every labeled value and entity name in the text appears "
    "legibly in the image. "
    "Watermark '@jacksonblau' bottom-left, dark gray #64748B, 10pt. "
    "Mood: analytical, sober, premium, dense without crowding."
)


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


def _format_key_data_points(kdps: list[dict[str, Any]], limit: int = 6) -> str:
    """Render key_data_points as a verbatim block the model must reproduce."""
    pairs: list[str] = []
    for kdp in kdps[:limit]:
        label = (kdp.get("label") or "").strip()
        value = (kdp.get("value") or "").strip()
        if label and value:
            pairs.append(f'"{value}" labeled "{label}"')
    return "; ".join(pairs)


def _format_entities(entities: list[str]) -> str:
    """Strip @-prefixes and join for the prompt."""
    return ", ".join((e or "").lstrip("@").strip() for e in (entities or []) if e)


def build_image_prompt(brief: dict[str, Any], format_hint: str) -> str:
    """Compose a Higgsfield-ready infographic prompt for a story brief.

    The prompt instructs the model to render an infographic that visually
    reproduces the specific data, entities, and relationships in the brief —
    not an abstract metaphor.
    """
    brief = brief or {}
    headline = (brief.get("headline") or "").strip()
    angle = (brief.get("narrative_angle") or "tokenized RWA market dynamics").strip()
    kdps = brief.get("key_data_points") or []
    entities = brief.get("entities") or []
    aspect = MODEL_DEFAULTS.get(format_hint, ("gpt_image_2", "1:1", "image"))[1]

    layout = pick_layout(brief, format_hint)
    data_pairs = _format_key_data_points(kdps)
    entity_list = _format_entities(entities)

    parts = [
        f"Editorial financial infographic about: {angle}.",
        f'Headline to render at the top, semibold, near-black: "{headline[:90]}".' if headline else "",
        f"Render these exact labeled values verbatim, legibly, inside the layout: {data_pairs}." if data_pairs else "",
        f"Named entities to include, rendered as text labels (no logos): {entity_list}." if entity_list else "",
        f"Layout: {layout}",
        VISUAL_IDENTITY_SUFFIX,
        f"{aspect} aspect ratio.",
    ]
    return " ".join(p for p in parts if p)


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


class _HiggsfieldRESTClient:
    """Production REST client. Stub implementation — wire to Higgsfield Cloud
    when the enterprise account is provisioned.

    Configuration via env:
      HIGGSFIELD_REST_URL (default https://cloud.higgsfield.ai/api/v1)
      HIGGSFIELD_API_KEY  (required for prod)
    """

    def __init__(self, *, base_url: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url or _env("HIGGSFIELD_REST_URL", "https://cloud.higgsfield.ai/api/v1")
        self.api_key = api_key or _env("HIGGSFIELD_API_KEY", "")

    def generate_image(self, *, prompt: str, model: str, aspect: str) -> str:
        raise NotImplementedError(
            "Higgsfield REST client not yet wired. In Cowork/dev, render via the "
            "Higgsfield MCP tools (mcp__39dcce27-…) and call record_higgsfield_asset() "
            "with the resulting storage URL. In prod, wire this method to the "
            "Higgsfield Cloud /jobs/image POST."
        )

    def generate_video(self, *, prompt: str, model: str, aspect: str, duration_s: int) -> str:
        raise NotImplementedError("Higgsfield REST video not yet wired — see generate_image note.")

    def poll(self, *, job_id: str, timeout_s: int = 90) -> dict[str, Any]:
        raise NotImplementedError("Higgsfield REST poll not yet wired — see generate_image note.")


# Default client is REST. In Cowork sessions the agent overrides this by
# manually executing the MCP tools and calling record_higgsfield_asset().
_default_client: HiggsfieldClient = _HiggsfieldRESTClient()


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
            job_id = _default_client.generate_image(prompt=prompt, model=model_key, aspect=aspect)
        asset["higgsfield_job_id"] = job_id
        asset["status"] = "running"
        result = _default_client.poll(job_id=job_id, timeout_s=90)
        asset["status"] = "ready"
        asset["storage_url"] = result.get("storage_url", "")
        asset["credits_used"] = result.get("credits_used")
    except NotImplementedError:
        # Expected in Cowork/dev when the REST client is the default. The agent
        # is responsible for invoking the MCP tool and calling record_higgsfield_asset.
        asset["status"] = "queued"
        asset["note"] = "REST client not wired — agent must dispatch via MCP and call record_higgsfield_asset()."
    except Exception as e:  # noqa: BLE001
        asset["status"] = "failed"
        asset["error"] = str(e)

    return asset


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
