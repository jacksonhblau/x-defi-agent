"""Canva brand-template renderer.

Loads a `canva_payload` from a story brief, resolves issuer logos (local
bundle → URL upload → monogram fallback), submits a Canva autofill job,
polls until ready, exports PNG, uploads to Supabase Storage, and returns a
`MediaAsset`-shaped dict for persistence.

Connection layer is plug-injected:
- **Cowork dev** — Canva MCP server (tools prefixed `mcp__96182097-…`). The
  agent invokes the MCP tools and calls `record_canva_asset` with the
  resulting design_id and export URL.
- **Production VPS** — Canva Connect REST API with a service-account OAuth
  token. Requires Canva Enterprise — see `docs/canva_integration.md §2`.

The MCP-only dev path is the chosen mode for this iteration (Jackson opted
out of the Enterprise upgrade in the algo-refit Q&A).

See `docs/canva_integration.md` for the full spec.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Optional, Protocol


# ---------- Configuration ----------

LOGOS_DIR_DEFAULT = Path(__file__).resolve().parents[4].parent / "packages" / "graphics" / "logos" / "issuers"

MONOGRAM_SENTINEL = "MONOGRAM"


# ---------- Logo resolution ----------

def _logo_local_path(slug: str, logos_dir: Optional[Path] = None) -> Optional[Path]:
    """Return the local path to a logo SVG for `slug`, or None if absent."""
    d = Path(logos_dir) if logos_dir else LOGOS_DIR_DEFAULT
    p = d / f"{slug}.svg"
    return p if p.exists() else None


def _logo_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def resolve_logos(
    fields: dict[str, Any],
    *,
    asset_cache: Optional[dict[str, str]] = None,
    logos_dir: Optional[Path] = None,
    fetch_url_to_asset_id: Optional[callable] = None,
    upload_local_to_asset_id: Optional[callable] = None,
) -> dict[str, Any]:
    """Walk *_logo fields and resolve each to a Canva asset_id.

    The output is a copy of `fields` where each `{kind, slug | url}` value is
    replaced with a Canva asset_id string OR the MONOGRAM sentinel.

    Args:
      fields: autofill-payload fields dict (template-specific shape).
      asset_cache: dict mapping logo SHA-256 → canva_asset_id, to avoid
        re-uploading the same logo more than once per session/year.
      logos_dir: override the local logos bundle path (default
        packages/graphics/logos/issuers).
      fetch_url_to_asset_id: callable(url) → asset_id, for `kind=url` paths.
        Plug-injected (e.g., mcp__96182097-…__upload-asset-from-url or REST).
      upload_local_to_asset_id: callable(local_path: Path) → asset_id, for
        `kind=local` paths. Plug-injected.

    Returns:
      fields dict with logos resolved to asset_id strings.
    """
    asset_cache = asset_cache if asset_cache is not None else {}
    resolved = dict(fields)
    for key, val in fields.items():
        if not key.endswith("_logo"):
            continue
        if not isinstance(val, dict):
            continue
        kind = val.get("kind")
        if kind == "monogram":
            resolved[key] = MONOGRAM_SENTINEL
            continue
        if kind == "local":
            slug = val.get("slug", "")
            path = _logo_local_path(slug, logos_dir=logos_dir)
            if not path:
                # No local SVG — fall back to monogram. Calling code should
                # surface a "missing logo" card in the review UI.
                resolved[key] = MONOGRAM_SENTINEL
                continue
            sha = _logo_sha256(path)
            if sha in asset_cache:
                resolved[key] = asset_cache[sha]
                continue
            if upload_local_to_asset_id is None:
                # No uploader plugged in — leave the spec untouched so the
                # caller can dispatch via MCP and patch the field in.
                resolved[key] = {"_pending_upload": str(path), "sha256": sha}
                continue
            asset_id = upload_local_to_asset_id(path)
            asset_cache[sha] = asset_id
            resolved[key] = asset_id
            continue
        if kind == "url":
            url = val.get("url", "")
            if not url:
                resolved[key] = MONOGRAM_SENTINEL
                continue
            if fetch_url_to_asset_id is None:
                resolved[key] = {"_pending_url": url}
                continue
            resolved[key] = fetch_url_to_asset_id(url)
            continue
    return resolved


# ---------- Client abstraction ----------

class CanvaClient(Protocol):
    """Implementation interface for MCP or REST clients."""

    def create_autofill_job(self, *, brand_template_id: str, fields: dict[str, Any]) -> str:
        """Return job_id."""
        ...

    def wait_for_job(self, *, job_id: str, timeout_s: int = 60) -> dict[str, Any]:
        """Return result dict with at minimum a 'design_id' field."""
        ...

    def export_png(self, *, design_id: str) -> str:
        """Return a URL pointing to the exported PNG."""
        ...

    def upload_asset_from_url(self, *, url: str) -> str:
        """Return asset_id."""
        ...

    def upload_local_asset(self, *, path: Path) -> str:
        """Return asset_id."""
        ...


class _CanvaRESTClient:
    """Production Canva Connect client. Requires Canva Enterprise OAuth.
    Stub implementation — wire when CANVA_CLIENT_ID/CANVA_REFRESH_TOKEN are set.
    """

    def __init__(self):
        self.client_id = os.environ.get("CANVA_CLIENT_ID", "")
        self.refresh_token = os.environ.get("CANVA_REFRESH_TOKEN", "")
        self.brand_org_id = os.environ.get("CANVA_BRAND_ORG_ID", "")

    def create_autofill_job(self, *, brand_template_id: str, fields: dict[str, Any]) -> str:
        raise NotImplementedError(
            "Canva REST client not wired. In Cowork/dev, the agent invokes the "
            "MCP tools (mcp__96182097-…) and calls record_canva_asset() with the "
            "resulting design_id and storage_url."
        )

    def wait_for_job(self, *, job_id: str, timeout_s: int = 60) -> dict[str, Any]:
        raise NotImplementedError("Canva REST wait_for_job not wired.")

    def export_png(self, *, design_id: str) -> str:
        raise NotImplementedError("Canva REST export_png not wired.")

    def upload_asset_from_url(self, *, url: str) -> str:
        raise NotImplementedError("Canva REST upload_asset_from_url not wired.")

    def upload_local_asset(self, *, path: Path) -> str:
        raise NotImplementedError("Canva REST upload_local_asset not wired.")


_default_client: CanvaClient = _CanvaRESTClient()


def set_client(client: CanvaClient) -> None:
    global _default_client
    _default_client = client


# ---------- Template registry lookup ----------

def lookup_canva_template_id(slug: str, *, db_fetch: Optional[callable] = None) -> Optional[str]:
    """Resolve a template slug (e.g., 'rwa_t1_adoption_snapshot') to a Canva-side
    brand_template_id by consulting the canva_templates table.

    The db_fetch callable is plug-injected so the module doesn't hard-depend
    on the `workers.db` import path. In production, pass `workers.db.fetch_canva_template`.
    """
    if db_fetch is None:
        return None
    row = db_fetch(slug)
    if not row:
        return None
    return row.get("canva_template_id")


# ---------- Render entrypoint ----------

def render(brief: dict[str, Any], *, db_fetch: Optional[callable] = None) -> dict[str, Any]:
    """Render a data-led asset via Canva.

    Reads `brief.canva_payload`, resolves logos, dispatches autofill, polls,
    exports PNG, returns a ready MediaAsset dict.

    In Cowork/dev with the REST stub client, this returns a 'queued' asset
    with the prepared fields so the agent can dispatch the MCP tools manually.
    """
    payload = (brief or {}).get("canva_payload") or {}
    slug = payload.get("template_id", "")
    fields_in = payload.get("fields") or {}

    asset: dict[str, Any] = {
        "kind": "image",
        "source": "canva",
        "canva_template_slug": slug,
        "status": "queued",
        "prepared_fields": fields_in,
    }

    canva_template_id = lookup_canva_template_id(slug, db_fetch=db_fetch)
    if not canva_template_id:
        # Template not registered in the canva_templates table. This is a
        # blocker — surface clearly so the agent can prompt Jackson to build it.
        asset["note"] = (
            f"canva_templates table has no row for slug '{slug}'. Build the "
            f"template in Canva, then INSERT INTO canva_templates."
        )
        return asset

    try:
        fields = resolve_logos(
            fields_in,
            fetch_url_to_asset_id=getattr(_default_client, "upload_asset_from_url", None) and (
                lambda u: _default_client.upload_asset_from_url(url=u)
            ),
            upload_local_to_asset_id=getattr(_default_client, "upload_local_asset", None) and (
                lambda p: _default_client.upload_local_asset(path=p)
            ),
        )
        job_id = _default_client.create_autofill_job(brand_template_id=canva_template_id, fields=fields)
        asset["status"] = "running"
        asset["canva_job_id"] = job_id
        design = _default_client.wait_for_job(job_id=job_id, timeout_s=60)
        design_id = design.get("design_id")
        asset["canva_design_id"] = design_id
        export_url = _default_client.export_png(design_id=design_id)
        asset["storage_url"] = export_url
        asset["status"] = "ready"
    except NotImplementedError:
        asset["status"] = "queued"
        asset["note"] = (
            "Canva REST client not wired — agent must dispatch the MCP tools "
            "(create-design-from-brand-template + perform-editing-operations + "
            "export-design) and call record_canva_asset() with the result."
        )
    except Exception as e:  # noqa: BLE001
        asset["status"] = "failed"
        asset["error"] = str(e)

    return asset


def record_canva_asset(
    *,
    template_slug: str,
    canva_design_id: str,
    storage_url: str,
    fields_used: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Record a Canva asset that was generated outside the Python layer
    (e.g., by the agent invoking the MCP tools in a Cowork session).
    """
    return {
        "kind": "image",
        "source": "canva",
        "canva_template_slug": template_slug,
        "canva_design_id": canva_design_id,
        "storage_url": storage_url,
        "status": "ready",
        "prepared_fields": fields_used or {},
    }
