"""Graphics dispatcher — the hybrid AI + deterministic pipeline.

Routing model (post algo-refit, May 2026 v2):

  1. AI render (higgsfield.render) — primary path for every brief. Uses
     gpt-image-1 with real entity logos passed as reference images, one of
     seven rich layout templates selected by claude-haiku, never iconic
     mode.
  2. Vision QA gate (qa.check) — claude-haiku scrutinizes the rendered PNG
     against a seven-point checklist. Pass → ship.
  3. One retry with QA-refined prompt — qa.refine_prompt_for_failures
     appends targeted hints. Pass → ship.
  4. Deterministic Ledger Cartography plate — canvas_design.render. Always
     publishable; satisfies the checklist by construction. Real local SVG
     logos when matched, monogram blocks otherwise.

Every asset carries a `diagnostics` JSONB payload that lands in
media_assets.diagnostics (migration 0003) so the team can see WHY each post
got the image it did and where the long tail of failures is.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from . import canva, canvas_design, higgsfield, logos as logo_resolver, qa as qa_gate
from .qa import QAResult

log = logging.getLogger(__name__)


EDITORIAL_KIND = "editorial"
COMBO_KIND = "recap_grid"
TIME_SERIES_KIND = "time_series"


# ---------- Tunables ----------

def _retry_limit() -> int:
    try:
        return int(os.environ.get("GRAPHICS_QA_RETRY_LIMIT", "1"))
    except ValueError:
        return 1


def _qa_strict() -> bool:
    return os.environ.get("GRAPHICS_QA_STRICT", "true").lower() != "false"


# ---------- Main entry ----------

def dispatch_for_draft(
    draft: dict[str, Any],
    brief: dict[str, Any],
    *,
    video_materiality_floor: int = 80,
) -> list[dict[str, Any]]:
    """Produce one (or two) ready MediaAsset dicts for a draft.

    The brief's graphic_kind shapes the prompt's layout via select_layout()
    but does not affect routing — every brief follows the same waterfall.
    """
    fmt = (draft or {}).get("format", "single")
    kind = (brief or {}).get("graphic_kind") or (
        "deploy_card" if ((brief or {}).get("key_data_points") or []) else EDITORIAL_KIND
    )
    materiality = int((brief or {}).get("materiality_score", 0) or 0)

    # Video paths remain unwired in production; the still-image path
    # serves threads and recaps until a video backend is in place. The
    # combos below are kept commented for fast re-enablement.
    # if kind == EDITORIAL_KIND and materiality >= video_materiality_floor and fmt == "thread":
    #     return [_render_with_qa(brief, "hero_video"), _render_with_qa(brief, fmt)]
    # if kind == COMBO_KIND:
    #     return [_render_with_qa(brief, fmt), _render_with_qa(brief, "hero_video")]

    return [_render_with_qa(brief, fmt)]


# ---------- The QA + retry + fallback waterfall ----------

def _render_with_qa(brief: dict[str, Any], fmt: str) -> dict[str, Any]:
    """The full AI render → QA → retry → deterministic fallback chain.

    Always returns a MediaAsset dict with status=='ready' (unless the
    deterministic fallback ALSO fails, in which case status=='failed').
    """
    # Pre-resolve logos & layout once so both attempts share them (and so
    # diagnostics record the same routing decisions whether or not we
    # ended up shipping the AI render).
    entities = (brief or {}).get("entities") or []
    resolutions = logo_resolver.resolve_entities(entities)
    layout_key, selector = higgsfield.select_layout(brief)

    asset = higgsfield.render(brief, fmt)

    # If we couldn't even dispatch (no API key in dev), surface a queued
    # asset rather than fall through to QA — the agent will fill it in.
    if asset.get("status") in ("queued", "failed") and not asset.get("local_path"):
        # Try deterministic fallback right away so we don't ship an empty asset.
        return _fallback_to_deterministic(
            brief, layout_key=layout_key, selector=selector,
            resolutions=resolutions,
            ai_failure=asset.get("error") or asset.get("note") or "dispatch_failed",
        )

    # Run QA on the rendered PNG.
    image_path = asset.get("local_path") or asset.get("storage_url")
    qa_result = qa_gate.check(image_path, brief, attempt=1)
    asset.setdefault("diagnostics", {})["qa"] = qa_result.as_diagnostics()

    if qa_result.passed:
        return _finalize(asset, brief, layout_key, selector, resolutions, qa_result)

    # Strict mode → at least one retry. Advisory mode → ship anyway with
    # the failure recorded in diagnostics.
    if not _qa_strict():
        asset["diagnostics"]["qa_advisory_only"] = True
        return _finalize(asset, brief, layout_key, selector, resolutions, qa_result)

    # Retry with a refined prompt
    if _retry_limit() >= 1:
        refined_prompt = qa_gate.refine_prompt_for_failures(asset.get("prompt", ""), qa_result)
        retry_asset = higgsfield.render_with_prompt_override(
            brief, prompt=refined_prompt, format_hint=fmt, resolutions=resolutions,
        )
        if retry_asset.get("status") == "ready" and retry_asset.get("local_path"):
            retry_qa = qa_gate.check(retry_asset["local_path"], brief, attempt=2)
            retry_asset.setdefault("diagnostics", {})["qa"] = retry_qa.as_diagnostics()
            retry_asset["diagnostics"]["layout_template"] = layout_key
            retry_asset["diagnostics"]["layout_selector"] = selector
            retry_asset["diagnostics"]["logo_tiers"] = logo_resolver.diagnostics_summary(resolutions)
            if retry_qa.passed:
                return _finalize(retry_asset, brief, layout_key, selector, resolutions, retry_qa)
            qa_result = retry_qa  # carry forward for the fallback reason

    # Two QA failures → deterministic plate
    return _fallback_to_deterministic(
        brief,
        layout_key=layout_key,
        selector=selector,
        resolutions=resolutions,
        ai_failure=f"qa_failed:{','.join(qa_result.failed_checks)}",
    )


def _finalize(
    asset: dict[str, Any],
    brief: dict[str, Any],
    layout_key: str,
    selector: str,
    resolutions: list[logo_resolver.LogoResolution],
    qa_result: QAResult,
) -> dict[str, Any]:
    """Stamp a successful AI asset with the final diagnostics and upload."""
    d = asset.setdefault("diagnostics", {})
    d["layout_template"] = layout_key
    d["layout_selector"] = selector
    d["logo_tiers"] = logo_resolver.diagnostics_summary(resolutions)
    d["fallback_to_deterministic"] = False
    # Supabase upload happens here so the deterministic fallback path can
    # reuse the same upload helper.
    if asset.get("local_path") and not asset.get("storage_url"):
        public_url = _upload_to_supabase(Path(asset["local_path"]), asset.get("id", ""))
        asset["storage_url"] = public_url or asset["local_path"]
        asset["uploaded_to_supabase"] = public_url is not None
    return asset


def _fallback_to_deterministic(
    brief: dict[str, Any],
    *,
    layout_key: str,
    selector: str,
    resolutions: list[logo_resolver.LogoResolution],
    ai_failure: str,
) -> dict[str, Any]:
    """Render via canvas_design.render and stamp matching diagnostics."""
    det = canvas_design.render(brief)
    d = det.setdefault("diagnostics", {})
    d["layout_template"] = layout_key
    d["layout_selector"] = selector
    d["logo_tiers"] = logo_resolver.diagnostics_summary(resolutions)
    d["fallback_to_deterministic"] = True
    d["fallback_reason"] = ai_failure
    return det


# ---------- Supabase upload (shared) ----------

def _upload_to_supabase(local_path: Path, asset_id: str) -> str | None:
    """Reuse the same upload pattern as higgsfield._upload_to_supabase_storage,
    but available to both the AI and deterministic paths from one place.
    """
    import httpx
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = (
        os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    bucket = os.environ.get("SUPABASE_MEDIA_BUCKET", "media")
    if not (supabase_url and service_key):
        return None
    if not asset_id:
        import uuid as _uuid
        asset_id = str(_uuid.uuid4())
    object_key = f"infographics/{asset_id}.png"
    upload_url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    public_url = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{object_key}"
    try:
        body = local_path.read_bytes()
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


__all__ = [
    "dispatch_for_draft",
    "higgsfield",
    "canvas_design",
    "canva",
    "logo_resolver",
    "qa_gate",
]
