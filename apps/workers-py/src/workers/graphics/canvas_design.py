"""Canvas Design adapter — bridges the workers package to the renderer in
packages/graphics/canvas_design/.

The renderer itself lives in `packages/graphics/canvas_design/` because it
ships with bundled fonts and a philosophy doc — it's its own self-contained
unit. This module makes it callable from the workers' graphics dispatcher.

In production (Fly), the Dockerfile copies `packages/` to `/app/packages/`,
so we add that to sys.path on import. In dev, the same path resolution works
relative to the repo root.

`render(brief)` produces a `MediaAsset`-shaped dict matching the
`media_assets` table schema. The PNG itself is written to the worker's
persistent volume at `/app/data/media/` (or `./data/media/` in dev). For
v1, the `storage_url` is the local path; uploading to Supabase Storage so
the Vercel UI can render it is a follow-up.
"""

from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# ---------- Make the packages/graphics/canvas_design module importable ----------

def _add_packages_to_path() -> None:
    """Make `packages/graphics/canvas_design/render_ledger_cartography` importable."""
    candidates = [
        Path("/app/packages"),                                    # Fly production
        Path(__file__).resolve().parents[5] / "packages",         # dev: repo root
    ]
    for c in candidates:
        if c.exists() and str(c) not in sys.path:
            sys.path.insert(0, str(c))


_add_packages_to_path()


# Now import the renderer. Lazy-imported inside render() to keep the module
# load cheap (PIL pulls in lots of code).

# ---------- Output paths ----------

def _media_dir() -> Path:
    """Where to write rendered PNGs.

    On Fly: /app/data/media/ (persistent volume, mounted at agent_data).
    In dev: ./data/media/ relative to repo root.
    """
    fly_path = Path("/app/data/media")
    if fly_path.parent.exists():
        fly_path.mkdir(parents=True, exist_ok=True)
        return fly_path
    dev_path = Path(__file__).resolve().parents[5] / "data" / "drafts" / "media"
    dev_path.mkdir(parents=True, exist_ok=True)
    return dev_path


# ---------- Public API ----------

def render(brief: dict[str, Any]) -> dict[str, Any]:
    """Render a Ledger Cartography plate for one story brief.

    Returns a MediaAsset dict for persistence to the media_assets table.
    On error, returns a failed-status asset (caller should surface to the
    review UI as media_pending).
    """
    asset_id = str(uuid.uuid4())
    out_path = _media_dir() / f"{asset_id}.png"

    try:
        # Lazy import — keeps anti_ai.py and other lightweight imports cheap.
        from graphics.canvas_design.render_ledger_cartography import (
            plate_from_brief,
            render_plate,
        )
        spec = plate_from_brief(brief)
        rendered = render_plate(spec, out_path)
        return {
            "id": asset_id,
            "kind": "image",
            "source": "canvas_design",
            "model": "ledger_cartography_v1",
            "prompt": "",  # not LLM-generated; deterministic render
            "storage_url": str(rendered),
            "status": "ready",
            "credits_used": 0,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "ready_at": datetime.now(timezone.utc).isoformat(),
            "plate_title": (brief or {}).get("plate_title"),
            "tier_count": len(spec.tiers),
        }
    except Exception as e:  # noqa: BLE001
        return {
            "id": asset_id,
            "kind": "image",
            "source": "canvas_design",
            "status": "failed",
            "error": str(e),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
