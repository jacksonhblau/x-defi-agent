"""Graphics dispatcher.

Routes a draft to the right media backend based on the story brief's
`graphic_kind` field. The two backends are:

- **Higgsfield** (`workers.graphics.higgsfield`) — editorial/concept imagery
  via MCP server (dev) or Higgsfield REST (prod).
- **Canva** (`workers.graphics.canva`) — data-led brand templates with real
  issuer logos pulled from RWA.xyz + local bundle.

High-materiality posts may produce *two* assets (a Higgsfield hero plus a
Canva data card). Every draft must exit with at least one ready media asset
or it will be blocked at the review queue by `anti_ai.check_media_present`.

The dispatcher itself is pure routing — the actual backends do the work.
The renderer functions return `MediaAsset`-shaped dicts that match the
`media_assets` table schema in `packages/db/schema.sql`.

See `docs/canva_integration.md §1` for the full routing matrix and
`docs/higgsfield_integration.md §2` for model selection rules.
"""

from __future__ import annotations

from typing import Any

from . import canva, higgsfield


# ---------- Routing ----------

EDITORIAL_KIND = "editorial"
CANVA_KINDS = {"data_card", "comparison", "leaderboard", "time_series", "deploy_card"}
COMBO_KIND = "recap_grid"  # both Higgsfield hero + Canva grid


def dispatch_for_draft(
    draft: dict[str, Any],
    brief: dict[str, Any],
    *,
    video_materiality_floor: int = 80,
) -> list[dict[str, Any]]:
    """Dispatch a draft to the right media backend(s) and return the produced assets.

    Args:
      draft: dict with at minimum 'format' (single|thread|reply|hot_take|long_form).
      brief: story brief dict with 'graphic_kind', 'materiality_score',
             'narrative_angle', 'key_data_points', and optionally 'canva_payload'.
      video_materiality_floor: materiality threshold above which threads get
             a Higgsfield video instead of a still image.

    Returns:
      list of MediaAsset dicts (one or two), each with at minimum:
        kind: 'image' | 'video'
        source: 'higgsfield' | 'canva'
        status: 'queued' | 'running' | 'ready' | 'failed'
        prompt: str (for higgsfield) OR
        canva_template_slug: str + canva_design_id: str (for canva)
        storage_url: str (set when status == 'ready')
    """
    kind = (brief or {}).get("graphic_kind", EDITORIAL_KIND)
    fmt = (draft or {}).get("format", "single")
    materiality = int((brief or {}).get("materiality_score", 0) or 0)

    # Pure Canva path: data-led posts.
    if kind in CANVA_KINDS:
        return [canva.render(brief)]

    # Combo path: weekly recap grid.
    if kind == COMBO_KIND:
        return [canva.render(brief), higgsfield.render(brief, fmt)]

    # High-materiality editorial thread: both editorial hero + Canva data card.
    if kind == EDITORIAL_KIND and materiality >= video_materiality_floor and fmt == "thread":
        return [
            higgsfield.render(brief, "hero_video"),
            canva.render(brief) if (brief or {}).get("canva_payload") else higgsfield.render(brief, fmt),
        ]

    # Default editorial path: single Higgsfield asset matching the format.
    return [higgsfield.render(brief, fmt)]


__all__ = [
    "dispatch_for_draft",
    "higgsfield",
    "canva",
]
