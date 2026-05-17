#!/usr/bin/env python3
"""Populate packages/graphics/logos/issuers/ from logo_manifest.json.

Strategy per entry:
  - `simpleicons`: download SVG from simpleicons.org/icons/<slug>.svg (MIT,
    monochrome paths — recolor at render time)
  - `wikipedia_commons`: download SVG directly from the provided URL
  - `manual`: skip — these need to be sourced by hand from press kits.
    The script prints a checklist for what's still missing.

Run:
    python3 scripts/fetch_logos.py

Idempotent — files that already exist are skipped unless --force is passed.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packages" / "graphics" / "logos" / "logo_manifest.json"
BUNDLE = ROOT / "packages" / "graphics" / "logos" / "issuers"

SIMPLEICONS_CDN = "https://cdn.simpleicons.org/{slug}"


def _download(url: str, dest: Path) -> bool:
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (DeFi-X-Poster logo fetcher)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        if len(data) < 200:
            print(f"  ⚠ {dest.name}: response too small ({len(data)} bytes)", file=sys.stderr)
            return False
        dest.write_bytes(data)
        return True
    except urllib.error.HTTPError as e:
        print(f"  ✗ {dest.name}: HTTP {e.code} ({url})", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ {dest.name}: {e}", file=sys.stderr)
        return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true", help="Re-download even if file exists")
    ap.add_argument("--priority", type=int, choices=[1, 2], help="Only process priority N entries")
    args = ap.parse_args()

    manifest = json.loads(MANIFEST.read_text())
    BUNDLE.mkdir(parents=True, exist_ok=True)

    fetched = skipped = missing_manual = 0
    manual_todo: list[str] = []

    for e in manifest["entities"]:
        if args.priority and e.get("priority") != args.priority:
            continue
        slug = e["slug"]
        out = BUNDLE / f"{slug}.svg"
        current = e.get("current")
        if current and not args.force:
            cp = BUNDLE / current
            if cp.exists():
                print(f"  ⤳ {slug}: already in bundle as {current}, leaving in place")
                skipped += 1
                continue
        if out.exists() and not args.force:
            skipped += 1
            continue

        if "simpleicons" in e:
            url = SIMPLEICONS_CDN.format(slug=e["simpleicons"])
            print(f"  ↓ {slug} ← simpleicons:{e['simpleicons']}")
            if _download(url, out):
                fetched += 1
        elif "wikipedia_commons" in e:
            print(f"  ↓ {slug} ← Wikimedia Commons")
            if _download(e["wikipedia_commons"], out):
                fetched += 1
        else:
            missing_manual += 1
            manual_todo.append(f"{slug} ({e['display']}) — source: {e.get('manual', '?')}")

    print()
    print(f"Fetched:        {fetched}")
    print(f"Skipped (have): {skipped}")
    print(f"Manual TODO:    {missing_manual}")
    if manual_todo:
        print("\nManual sourcing required for the following entities. Pull each from")
        print("the entity's official press kit / brand resources page, save as")
        print(f"{BUNDLE}/<slug>.svg, viewBox 0 0 100 100, no embedded fonts.\n")
        for line in manual_todo:
            print(f"  - {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
