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
#
# Algo-refit final (May 16, 2026): Higgsfield (via OpenAI gpt-image-1) is the
# sole image-generation path. The model knows authentic brand logos for the
# entities we care about (Tether, BlackRock, TRON, Ethereum, OFAC, etc.) so
# every plate gets contextual visual cues instead of generic monogram blocks.
#
# canvas_design and canva remain importable as fallbacks but the dispatcher
# routes every kind to higgsfield by default.

EDITORIAL_KIND = "editorial"
COMBO_KIND = "recap_grid"
TIME_SERIES_KIND = "time_series"


def dispatch_for_draft(
    draft: dict[str, Any],
    brief: dict[str, Any],
    *,
    video_materiality_floor: int = 80,
) -> list[dict[str, Any]]:
    """Dispatch a draft to the right media backend(s) and return the produced assets.

    All graphic_kinds route to higgsfield.render() — the OpenAI-backed
    infographic generator with real brand logo rendering. The brief's
    graphic_kind influences the prompt's layout choice but not the backend.

    Returns:
      list of MediaAsset dicts (typically 1, occasionally 2 for high-materiality
      threads that get a video hero + a still plate).
    """
    kind = (brief or {}).get("graphic_kind")
    if not kind:
        kind = "deploy_card" if ((brief or {}).get("key_data_points") or []) else EDITORIAL_KIND
    fmt = (draft or {}).get("format", "single")
    materiality = int((brief or {}).get("materiality_score", 0) or 0)

    # High-materiality editorial thread: short video hero + still plate.
    if kind == EDITORIAL_KIND and materiality >= video_materiality_floor and fmt == "thread":
        return [
            higgsfield.render(brief, "hero_video"),
            higgsfield.render(brief, fmt),
        ]

    # Recap grid: still plate + short video.
    if kind == COMBO_KIND:
        return [higgsfield.render(brief, fmt), higgsfield.render(brief, "hero_video")]

    # Everything else: single Higgsfield image.
    return [higgsfield.render(brief, fmt)]


__all__ = [
    "dispatch_for_draft",
    "higgsfield",
    "canvas_design",
    "canva",
]
