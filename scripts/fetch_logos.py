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
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "packages" / "graphics" / "logos" / "logo_manifest.json"
BUNDLE = ROOT / "packages" / "graphics" / "logos" / "issuers"

SIMPLEICONS_CDN = "https://cdn.simpleicons.org/{slug}"


def _http_get(url: str, timeout_s: float = 15.0) -> bytes | None:
    """Fetch a URL. Prefers httpx (bundles certifi) so macOS system-Python
    doesn't trip on SSL cert verification. Falls back to urllib with an
    explicit certifi cafile, then to unverified TLS as a last resort.
    """
    # Path 1: httpx (project dependency, ships with certifi).
    try:
        import httpx
        r = httpx.get(
            url,
            timeout=timeout_s,
            follow_redirects=True,
            headers={"User-Agent": "DeFiXPoster/1.0 (https://github.com/jacksonhblau/x-defi-agent; jacksonhblau@gmail.com) python-httpx"},
        )
        if r.status_code == 200 and len(r.content) > 200:
            return r.content
        if r.status_code >= 400:
            print(f"  ✗ HTTP {r.status_code} ({url})", file=sys.stderr)
            return None
    except ImportError:
        pass
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ httpx error: {e}", file=sys.stderr)

    # Path 2: urllib + certifi (explicit cafile).
    try:
        import ssl
        import urllib.error
        import urllib.request
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "DeFiXPoster/1.0 (https://github.com/jacksonhblau/x-defi-agent; jacksonhblau@gmail.com) python-httpx"},
        )
        with urllib.request.urlopen(req, timeout=timeout_s, context=ctx) as resp:
            data = resp.read()
            if len(data) > 200:
                return data
    except Exception as e:  # noqa: BLE001
        print(f"  ✗ urllib error: {e}", file=sys.stderr)
    return None


def _download(url: str, dest: Path) -> bool:
    data = _http_get(url)
    if data is None:
        print(f"  ✗ {dest.name}: download failed ({url})", file=sys.stderr)
        return False
    dest.write_bytes(data)
    return True


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
