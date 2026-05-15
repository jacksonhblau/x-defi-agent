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

from . import canva, canvas_design, higgsfield


# ---------- Routing ----------

EDITORIAL_KIND = "editorial"

# Data-led graphic kinds → Ledger Cartography (canvas_design).
# Replaces the old Canva-template path (Jackson's call from the algo-refit Q&A).
CANVAS_DESIGN_KINDS = {"data_card", "comparison", "leaderboard", "deploy_card"}

# `time_series` still routes to Canva (queued) for now — the Ledger Cartography
# renderer doesn't yet have a chart layout. Falls back gracefully.
CANVA_FALLBACK_KINDS = {"time_series"}

COMBO_KIND = "recap_grid"  # editorial hero + data plate combo


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
             'narrative_angle', 'key_data_points'.
      video_materiality_floor: materiality threshold above which threads get
             a Higgsfield video instead of a still image.

    Returns:
      list of MediaAsset dicts (one or two), each with at minimum:
        kind: 'image' | 'video'
        source: 'higgsfield' | 'canvas_design' | 'canva'
        status: 'queued' | 'running' | 'ready' | 'failed'
        storage_url: str (set when status == 'ready')
    """
    kind = (brief or {}).get("graphic_kind", EDITORIAL_KIND)
    fmt = (draft or {}).get("format", "single")
    materiality = int((brief or {}).get("materiality_score", 0) or 0)

    # Data-led posts → Ledger Cartography schematic plate (deterministic Python).
    if kind in CANVAS_DESIGN_KINDS:
        return [canvas_design.render(brief)]

    # Time series (charts) — not yet covered by Ledger Cartography; keep Canva slot.
    if kind in CANVA_FALLBACK_KINDS:
        return [canva.render(brief)]

    # Recap grid: data plate + editorial hero.
    if kind == COMBO_KIND:
        return [canvas_design.render(brief), higgsfield.render(brief, fmt)]

    # High-materiality editorial thread: editorial hero + supporting data plate.
    if kind == EDITORIAL_KIND and materiality >= video_materiality_floor and fmt == "thread":
        return [
            higgsfield.render(brief, "hero_video"),
            canvas_design.render(brief) if (brief or {}).get("key_data_points") else higgsfield.render(brief, fmt),
        ]

    # Default editorial path: single Higgsfield asset matching the format.
    return [higgsfield.render(brief, fmt)]


__all__ = [
    "dispatch_for_draft",
    "higgsfield",
    "canvas_design",
    "canva",
]
