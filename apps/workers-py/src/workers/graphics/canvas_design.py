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

import logging
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx

log = logging.getLogger(__name__)


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


# ---------- Supabase Storage upload ----------

SUPABASE_MEDIA_BUCKET_DEFAULT = "media"


def _upload_to_supabase(local_path: Path, asset_id: str) -> Optional[str]:
    """Upload a rendered PNG to Supabase Storage. Return the public URL or None.

    Requires:
      - SUPABASE_URL (e.g. https://<ref>.supabase.co)
      - SUPABASE_SERVICE_KEY (or SUPABASE_SERVICE_ROLE_KEY) — server-side write
      - A `media` bucket (or override via SUPABASE_MEDIA_BUCKET) configured for
        public access. Create it once in the Supabase dashboard.

    Falls back to `None` (caller uses the local filesystem path) when env is
    missing or the upload fails — never raises.
    """
    supabase_url = os.environ.get("SUPABASE_URL")
    service_key = (
        os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    )
    bucket = os.environ.get("SUPABASE_MEDIA_BUCKET", SUPABASE_MEDIA_BUCKET_DEFAULT)
    if not (supabase_url and service_key):
        log.info("Supabase upload skipped: SUPABASE_URL or SUPABASE_SERVICE_KEY missing")
        return None

    object_key = f"canvas_design/{asset_id}.png"
    upload_url = f"{supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{object_key}"
    public_url = f"{supabase_url.rstrip('/')}/storage/v1/object/public/{bucket}/{object_key}"

    try:
        with local_path.open("rb") as f:
            body = f.read()
        response = httpx.post(
            upload_url,
            content=body,
            headers={
                "Authorization": f"Bearer {service_key}",
                "Content-Type": "image/png",
                "x-upsert": "true",
                "Cache-Control": "public, max-age=31536000, immutable",
            },
            timeout=30,
        )
        if response.status_code >= 400:
            log.warning(
                "Supabase Storage upload failed (%s): %s. URL=%s. "
                "Common causes: bucket '%s' doesn't exist or isn't public.",
                response.status_code, response.text[:200], upload_url, bucket,
            )
            return None
        return public_url
    except Exception as e:  # noqa: BLE001
        log.warning("Supabase Storage upload exception: %s", e)
        return None


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
        # Upload to Supabase Storage so the Vercel UI can fetch it.
        # Falls back to the local path if the bucket isn't configured yet.
        public_url = _upload_to_supabase(rendered, asset_id)
        storage_url = public_url or str(rendered)
        return {
            "id": asset_id,
            "kind": "image",
            "source": "canvas_design",
            "model": "ledger_cartography_v1",
            "prompt": "",  # not LLM-generated; deterministic render
            "storage_url": storage_url,
            "local_path": str(rendered),
            "uploaded_to_supabase": public_url is not None,
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
