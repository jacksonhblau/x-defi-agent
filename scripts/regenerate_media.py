#!/usr/bin/env python3
"""Regenerate infographic images for existing drafts through the v2 pipeline.

Use case: you've shipped the algo-refit v2 graphics work and want to backfill
the new Tether-tier images onto drafts/scheduled posts that were generated
under the old (regressed) pipeline.

Cleanly:
  - Doesn't touch already-posted tweets (those are immutable).
  - Honors a safety margin so the post_due cron can't fire a scheduled post
    mid-swap.
  - Marks the old media_assets row 'superseded' instead of deleting it, so
    the audit trail stays intact and diagnostics-vs-diagnostics comparisons
    are possible after the fact.
  - Idempotent: re-running it on the same draft regenerates again. (Set
    --skip-recent-success to avoid re-regenerating drafts whose latest
    media is already from the v2 pipeline.)
  - Dry-run mode prints every action without making API calls or DB writes.

Usage:
    # See what would be regenerated for all unposted drafts:
    python3 scripts/regenerate_media.py --dry-run

    # Regenerate one specific draft:
    python3 scripts/regenerate_media.py --draft-id <uuid>

    # Regenerate every pending+approved+scheduled draft:
    python3 scripts/regenerate_media.py --status pending,approved,scheduled

    # Only regenerate scheduled drafts whose post_at is at least 30 min out
    # (so the post_due cron can't catch us mid-swap):
    python3 scripts/regenerate_media.py --status scheduled --safety-margin 30m

    # Skip drafts whose latest media is already v2:
    python3 scripts/regenerate_media.py --skip-recent-success
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

# Make the workers package importable when running from the repo root.
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "workers-py" / "src"))


def _parse_duration(s: str) -> timedelta:
    """Parse '30m', '2h', '1d' into a timedelta."""
    m = re.fullmatch(r"(\d+)([smhd])", s.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError(f"bad duration: {s!r}, expected like 30m, 2h, 1d")
    n, unit = int(m.group(1)), m.group(2)
    return timedelta(seconds=n) * {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]


def _coerce_draft_row(row: dict[str, Any]) -> dict[str, Any]:
    """Map a SELECT row from drafts+stories into the shapes the pipeline expects."""
    brief = row.get("brief_json") or {}
    if isinstance(brief, str):
        brief = json.loads(brief)
    # The drafts.format column drives format_hint inside the dispatcher.
    draft = {
        "id": str(row["id"]),
        "format": row["format"],
        "body": row.get("body") or row.get("edited_body") or "",
        "status": row["status"],
    }
    return {"draft": draft, "brief": brief}


def _is_v2_asset(asset_row: dict[str, Any]) -> bool:
    """A v2 asset has a 'diagnostics' JSONB column with layout_template set.

    Pre-v2 rows have NULL diagnostics. We use that to detect 'already
    regenerated' when --skip-recent-success is set.
    """
    d = asset_row.get("diagnostics")
    if isinstance(d, str):
        try:
            d = json.loads(d)
        except Exception:
            return False
    return isinstance(d, dict) and bool(d.get("layout_template"))


def main() -> int:
    ap = argparse.ArgumentParser(formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--draft-id", help="Regenerate one specific draft (UUID).")
    ap.add_argument(
        "--status",
        default="pending,approved,scheduled",
        help="Comma-separated draft statuses to consider. Default: pending,approved,scheduled. "
             "Never includes 'posted' — those tweets are immutable.",
    )
    ap.add_argument(
        "--since",
        type=_parse_duration,
        default=None,
        help="Only drafts created within this window (e.g. 7d). Default: no limit.",
    )
    ap.add_argument(
        "--safety-margin",
        type=_parse_duration,
        default=_parse_duration("15m"),
        help="Skip scheduled drafts whose post_at is within this window. Default: 15m.",
    )
    ap.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Max drafts to process this run. Default: 50.",
    )
    ap.add_argument(
        "--skip-recent-success",
        action="store_true",
        help="Skip drafts whose latest media_assets row was already produced by the v2 pipeline.",
    )
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would happen without making any API calls or DB writes.",
    )
    args = ap.parse_args()

    # Late imports so --help works without a configured env.
    from workers import db
    from workers.graphics import dispatch_for_draft
    from workers.stories.enrichment import enrich_for_graphics

    statuses = [s.strip() for s in args.status.split(",") if s.strip() and s.strip() != "posted"]
    now = datetime.now(timezone.utc)
    cutoff_post_at = now + args.safety_margin
    since_cutoff = (now - args.since) if args.since else None

    # Build the candidate query. We pull each draft with its story's brief_json,
    # the latest media_assets row (for v2 detection), and the scheduled_posts
    # row if any. Filtering by post_at safety margin happens in SQL.
    where = ["d.status = ANY(%s)"]
    params: list[Any] = [statuses]
    if since_cutoff is not None:
        where.append("d.created_at >= %s")
        params.append(since_cutoff)
    if args.draft_id:
        where.append("d.id = %s::uuid")
        params.append(args.draft_id)

    sql = f"""
        select
          d.id::text         as id,
          d.format           as format,
          d.body             as body,
          d.edited_body      as edited_body,
          d.status           as status,
          d.created_at       as created_at,
          d.graphic_url      as graphic_url,
          s.id::text         as story_id,
          s.headline         as headline,
          s.narrative_angle  as narrative_angle,
          s.entities         as entities,
          s.source_handles   as source_handles,
          s.key_data_points  as key_data_points,
          sp.id::text        as scheduled_post_id,
          sp.post_at         as post_at,
          sp.status          as sp_status,
          (
            select to_jsonb(m) from (
              select id::text, storage_url, status, source, diagnostics, ready_at
              from media_assets
              where draft_id = d.id
              order by created_at desc limit 1
            ) m
          )                  as latest_asset
        from drafts d
        join stories s on s.id = d.story_id
        left join scheduled_posts sp on sp.draft_id = d.id and sp.status = 'queued'
        where {' and '.join(where)}
        order by d.created_at desc
        limit %s
    """
    params.append(args.limit)

    from psycopg.rows import dict_row
    with db.conn() as c:
        with c.cursor(row_factory=dict_row) as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()

    print(f"Found {len(rows)} candidate drafts (statuses={statuses}).")
    print(f"Safety margin: skipping any scheduled draft with post_at < {cutoff_post_at.isoformat()}.")
    print()

    actions: list[dict[str, Any]] = []
    for r in rows:
        skip_reason: Optional[str] = None
        if r["post_at"] is not None and r["post_at"] < cutoff_post_at:
            skip_reason = f"post_at={r['post_at'].isoformat()} within safety margin"
        elif args.skip_recent_success and r["latest_asset"] and _is_v2_asset(r["latest_asset"]):
            skip_reason = "latest media is already v2"
        actions.append({"row": r, "skip_reason": skip_reason})

    n_skip = sum(1 for a in actions if a["skip_reason"])
    n_act = len(actions) - n_skip
    print(f"Will regenerate: {n_act}    Skipping: {n_skip}")
    print()

    # Build the brief in the shape the dispatcher needs. The brief on stories
    # may be a flattened set of columns rather than a single brief_json — pull
    # what we need explicitly.
    def _row_to_brief(r: dict[str, Any]) -> dict[str, Any]:
        kdps = r["key_data_points"]
        if isinstance(kdps, str):
            try:
                kdps = json.loads(kdps)
            except Exception:
                kdps = []
        return {
            "id": r["story_id"],
            "headline": r["headline"],
            "narrative_angle": r["narrative_angle"],
            "entities": list(r["entities"] or []),
            "source_handles": list(r["source_handles"] or []),
            "key_data_points": kdps or [],
        }

    for a in actions:
        r = a["row"]
        head = (r["headline"] or "")[:70]
        if a["skip_reason"]:
            print(f"  – SKIP  {r['id']}  [{r['status']:<9}]  {head}  ({a['skip_reason']})")
            continue
        print(f"  ↻ regen {r['id']}  [{r['status']:<9}]  {head}")

        brief = _row_to_brief(r)
        enrich_for_graphics(brief)

        if args.dry_run:
            from workers.graphics import higgsfield
            layout, selector = higgsfield.select_layout(brief)
            print(f"      → layout={layout} ({selector})")
            from workers.graphics import logos as L
            tiers = L.diagnostics_summary(L.resolve_entities(brief["entities"]))
            print(f"      → logo tiers: {tiers}")
            continue

        # Live mode: run dispatcher, persist new media_assets, supersede old.
        draft_dict = {"format": r["format"], "id": r["id"]}
        try:
            new_assets = dispatch_for_draft(draft_dict, brief)
        except Exception as e:  # noqa: BLE001
            print(f"      ✗ dispatch failed: {type(e).__name__}: {e}")
            continue

        ready = [a for a in new_assets if a.get("status") == "ready"]
        if not ready:
            print(f"      ✗ no asset reached 'ready' status — leaving existing media in place")
            continue

        # Persist the new asset rows and supersede the old.
        with db.conn() as c, c.cursor() as cur:
            # Mark prior assets for this draft as 'superseded' (the CHECK
            # constraint on media_assets.status only allows queued/running/
            # ready/failed, so we annotate via a synthetic 'superseded_at'
            # timestamp inside diagnostics rather than changing the status
            # enum. That keeps the constraint intact and preserves history.
            cur.execute(
                """
                update media_assets
                set diagnostics = coalesce(diagnostics, '{}'::jsonb)
                                  || jsonb_build_object(
                                       'superseded_at', %s::text,
                                       'superseded_by_run', %s::text
                                     )
                where draft_id = %s::uuid
                  and (diagnostics is null or not (diagnostics ? 'superseded_at'))
                """,
                (now.isoformat(), "regenerate_media", r["id"]),
            )

            for asset in ready:
                cur.execute(
                    """
                    insert into media_assets
                        (draft_id, kind, source, model, prompt,
                         higgsfield_job_id, canva_template_slug, canva_design_id,
                         storage_url, status, credits_used, ready_at, diagnostics)
                    values
                        (%s::uuid, %s, %s, %s, %s,
                         %s, %s, %s,
                         %s, %s, %s, %s, %s::jsonb)
                    """,
                    (
                        r["id"],
                        asset.get("kind", "image"),
                        asset.get("source", "higgsfield"),
                        asset.get("model"),
                        asset.get("prompt") or "",
                        asset.get("higgsfield_job_id"),
                        asset.get("canva_template_slug"),
                        asset.get("canva_design_id"),
                        asset.get("storage_url"),
                        asset.get("status", "ready"),
                        asset.get("credits_used"),
                        asset.get("ready_at") or now,
                        json.dumps(asset.get("diagnostics") or {}),
                    ),
                )

            # Point drafts.graphic_url at the new primary asset's storage_url so
            # the review UI and the X poster pick up the new image.
            primary_url = ready[0].get("storage_url")
            if primary_url:
                cur.execute(
                    "update drafts set graphic_url = %s where id = %s::uuid",
                    (primary_url, r["id"]),
                )
            c.commit()

        diag = ready[0].get("diagnostics") or {}
        layout = diag.get("layout_template", "?")
        fallback = diag.get("fallback_to_deterministic", False)
        print(f"      ✓ layout={layout}  fallback={fallback}  url={primary_url}")

    print()
    print("Done.")
    if args.dry_run:
        print("Dry-run only — no DB writes or API calls were made.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
