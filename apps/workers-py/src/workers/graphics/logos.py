"""Entity logo resolver — the load-bearing fix for Tether-tier consistency.

Four resolution tiers, tried in order until one returns a renderable mark:

  Tier 1  Local SVG library at packages/graphics/logos/issuers/
  Tier 2  Brandfetch (preferred) / Clearbit logo CDN by inferred domain
  Tier 3  Model-knowledge — return a `model_render` hint so the prompt asks
          gpt-image-1 to render the authentic logo from its own training
          (works for ~30 globally famous brands)
  Tier 4  Typographic fallback — render the entity name as a clean wordmark

The resolver returns a `LogoResolution` per entity. The graphics pipeline
uses these in two ways:

  - For the AI render (images/edits): rasterize any Tier-1/Tier-2 SVG/PNG to
    a 512×512 transparent PNG, pass as a reference image, and tell the model
    to composite it. Tier-3 entities are listed in the prompt by name (the
    model handles the visual). Tier-4 entities are rendered as typographic
    wordmarks in the prompt.

  - For the deterministic Ledger Cartography plate: Tier-1 SVGs replace the
    monogram block in render_ledger_cartography._draw_logo_block. Tiers 2-4
    fall back to the existing monogram path.

Cache: rasterized PNGs and Brandfetch/Clearbit downloads are stored under
$AGENT_DATA_DIR/logo_cache/ (or data/logo_cache/ in dev). Cache key is the
normalized slug. TTL is effectively infinite — the bundle changes rarely.
"""

from __future__ import annotations

import logging
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import httpx

log = logging.getLogger(__name__)


# ---------- Tier 3: brands gpt-image-1 reliably renders from training ----------

# These map normalized-slug → canonical name the model should use. Order is
# stable for diagnostic comparability. Keep this list in sync with the
# "_MAJOR_BRANDS" reference in higgsfield.py — they're the same set.
MODEL_KNOWN_BRANDS: dict[str, str] = {
    # Stablecoin / crypto-native
    "tether": "Tether",
    "circle": "Circle",
    "usdc": "USDC",
    "usdt": "USDT",
    "bitcoin": "Bitcoin",
    "ethereum": "Ethereum",
    "solana": "Solana",
    "tron": "TRON",
    "ripple": "Ripple",
    "xrp": "XRP",
    "binance": "Binance",
    "coinbase": "Coinbase",
    "kraken": "Kraken",
    # TradFi asset managers / banks
    "blackrock": "BlackRock",
    "jpmorgan": "JPMorgan",
    "jp morgan": "JPMorgan",
    "j.p. morgan": "J.P. Morgan",
    "fidelity": "Fidelity",
    "vanguard": "Vanguard",
    "goldman sachs": "Goldman Sachs",
    "morgan stanley": "Morgan Stanley",
    "bny mellon": "BNY Mellon",
    "bnymellon": "BNY Mellon",
    "state street": "State Street",
    "wisdomtree": "WisdomTree",
    "ishares": "iShares",
    "spdr": "SPDR",
    "invesco": "Invesco",
    "vaneck": "VanEck",
    "franklin templeton": "Franklin Templeton",
    "ubs": "UBS",
    "deutsche bank": "Deutsche Bank",
    "barclays": "Barclays",
    "hsbc": "HSBC",
    "visa": "Visa",
    "mastercard": "Mastercard",
    "paypal": "PayPal",
    # US government / regulator seals
    "ofac": "OFAC (Office of Foreign Assets Control)",
    "sec": "SEC (US Securities and Exchange Commission)",
    "federal reserve": "Federal Reserve",
    "fed": "Federal Reserve",
    "us treasury": "US Treasury",
    "treasury": "US Treasury",
    "fdic": "FDIC",
    "occ": "OCC (Office of the Comptroller of the Currency)",
    "cftc": "CFTC",
    "irs": "IRS",
    # Ratings agencies / market infra
    "moodys": "Moody's",
    "moody's": "Moody's",
    "s&p": "S&P",
    "fitch": "Fitch",
    "dtcc": "DTCC",
}


# ---------- Domain lookup for Brandfetch / Clearbit ----------

# Entity → known domain. Brandfetch's lookup API takes a domain, so we maintain
# a small hand-curated map for high-traffic crypto/finance brands whose names
# don't trivially imply their domain (e.g., "BlackRock" → blackrock.com works,
# but "Ondo Finance" → ondo.finance is non-obvious).
ENTITY_DOMAINS: dict[str, str] = {
    "ondo": "ondo.finance",
    "ondofinance": "ondo.finance",
    "ondo finance": "ondo.finance",
    "backed": "backed.fi",
    "backed.fi": "backed.fi",
    "centrifuge": "centrifuge.io",
    "maple": "maple.finance",
    "maplefinance": "maple.finance",
    "maple finance": "maple.finance",
    "goldfinch": "goldfinch.finance",
    "goldfinch_fi": "goldfinch.finance",
    "openeden": "openeden.com",
    "securitize": "securitize.io",
    "blackrock": "blackrock.com",
    "jpmorgan": "jpmorgan.com",
    "j.p. morgan": "jpmorgan.com",
    "tether": "tether.to",
    "circle": "circle.com",
    "coinbase": "coinbase.com",
    "kraken": "kraken.com",
    "binance": "binance.com",
    "ripple": "ripple.com",
    "ethereum": "ethereum.org",
    "tron": "tron.network",
    "solana": "solana.com",
    "fidelity": "fidelity.com",
    "vanguard": "vanguard.com",
    "wisdomtree": "wisdomtree.com",
    "vaneck": "vaneck.com",
    "franklin templeton": "franklintempleton.com",
    "bnymellon": "bnymellon.com",
    "bny mellon": "bnymellon.com",
    "state street": "statestreet.com",
    "ubs": "ubs.com",
    "moodys": "moodys.com",
    "moody's": "moodys.com",
    "s&p": "spglobal.com",
    "fitch": "fitchratings.com",
    "dtcc": "dtcc.com",
    "visa": "visa.com",
    "mastercard": "mastercard.com",
    "paypal": "paypal.com",
}


# ---------- Resolution dataclass ----------

@dataclass
class LogoResolution:
    """The resolver's verdict for one entity."""
    entity: str                # the raw entity name from the brief
    canonical_name: str        # cleaned display name
    tier: str                  # "tier1_local_svg" | "tier2_cdn" | "tier3_model_knowledge" | "tier4_typographic"
    local_path: Optional[Path] = None      # SVG or PNG on disk (Tiers 1 and 2)
    rasterized_path: Optional[Path] = None # 512x512 transparent PNG for the image-edits API
    domain: Optional[str] = None           # for Tier 2 attribution
    note: str = ""

    @property
    def renders_via_reference_image(self) -> bool:
        """True if the AI render should pass the file as an `image[]` ref."""
        return self.tier in ("tier1_local_svg", "tier2_cdn")


# ---------- Path helpers ----------

def _logos_dir() -> Path:
    """Where the local SVG library lives.

    Override via LOGO_BUNDLE_DIR if the dev tree is in an unusual location.
    """
    env = os.environ.get("LOGO_BUNDLE_DIR")
    if env and Path(env).exists():
        return Path(env)
    candidates = [
        Path("/app/packages/graphics/logos/issuers"),                     # Fly
        Path(__file__).resolve().parents[5] / "packages/graphics/logos/issuers",  # dev
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[-1]


def _cache_dir() -> Path:
    """Where we stash rasterized PNGs and CDN downloads.

    Persistent volume on Fly; ./data/logo_cache/ in dev.
    """
    base = Path(os.environ.get("AGENT_DATA_DIR", ""))
    if base.exists():
        out = base / "logo_cache"
    else:
        out = Path(__file__).resolve().parents[5] / "data" / "logo_cache"
    out.mkdir(parents=True, exist_ok=True)
    return out


# ---------- Normalization ----------

_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _slug(name: str) -> str:
    """Normalize an entity name to a comparable slug."""
    s = (name or "").lstrip("@").strip().lower()
    s = _NON_ALNUM.sub("", s)
    return s


def _canonical_name(entity: str) -> str:
    """Strip @-prefix and trim. Used for display in the prompt and diagnostics."""
    return (entity or "").lstrip("@").strip()


# ---------- Tier 1: local SVG bundle ----------

def _scan_local_bundle() -> dict[str, Path]:
    """Build a slug → file Path index from the local logo bundle.

    Indexes both SVG and PNG. Re-scanned per resolve() call — the bundle is
    small (~80 files) and may grow during a session.
    """
    out: dict[str, Path] = {}
    d = _logos_dir()
    if not d.exists():
        return out
    for p in d.iterdir():
        if p.suffix.lower() not in (".svg", ".png"):
            continue
        if p.name.startswith(".") or p.name.lower() == "readme.md":
            continue
        out[_slug(p.stem)] = p
    return out


def _try_tier1(entity: str, bundle: dict[str, Path]) -> Optional[Path]:
    """Match the entity against the local bundle."""
    s = _slug(entity)
    if s in bundle:
        return bundle[s]
    # Loose match: try entity slug as substring (handles "BNY Mellon" vs "bnymellon.svg")
    for slug, path in bundle.items():
        if slug and (slug in s or s in slug):
            if abs(len(slug) - len(s)) <= 4:  # avoid spurious one-letter overlaps
                return path
    return None


# ---------- Tier 2: Brandfetch / Clearbit CDN ----------

def _infer_domain(entity: str) -> Optional[str]:
    """Look up a domain from the manual map, with light fuzzy matching."""
    s = _slug(entity)
    if s in ENTITY_DOMAINS:
        return ENTITY_DOMAINS[s]
    # Try whitespace-preserved key
    lower = (entity or "").lstrip("@").strip().lower()
    if lower in ENTITY_DOMAINS:
        return ENTITY_DOMAINS[lower]
    return None


def _try_tier2(entity: str) -> Optional[Path]:
    """Fetch from Brandfetch (if API key set) else Clearbit. Cache to disk.

    Returns the cached PNG path on success, None on any failure. Network
    failures are non-fatal — the resolver falls through to Tier 3/4.
    """
    domain = _infer_domain(entity)
    if not domain:
        return None
    cache = _cache_dir() / f"{_slug(entity)}_cdn.png"
    if cache.exists() and cache.stat().st_size > 200:
        return cache

    bf_key = os.environ.get("BRANDFETCH_API_KEY")
    cb_key = os.environ.get("CLEARBIT_API_KEY")  # Clearbit's free logo API needs no key

    urls: list[str] = []
    if bf_key:
        # Brandfetch logo-link API — square PNG, transparent background.
        urls.append(f"https://cdn.brandfetch.io/{domain}/w/512/h/512/icon?c={bf_key}")
    # Clearbit's logo CDN is unauthenticated and free. PNG, transparent.
    urls.append(f"https://logo.clearbit.com/{domain}?size=512&format=png")
    if cb_key:
        urls.append(f"https://logo.clearbit.com/{domain}?size=512&format=png&key={cb_key}")

    for url in urls:
        try:
            r = httpx.get(url, timeout=8.0, follow_redirects=True)
            if r.status_code == 200 and len(r.content) > 200:
                cache.write_bytes(r.content)
                return cache
        except Exception as e:  # noqa: BLE001
            log.debug("CDN logo fetch failed for %s via %s: %s", entity, url, e)
            continue
    return None


# ---------- Rasterization (SVG → PNG for the image-edits API) ----------

_RASTER_LOCK = threading.Lock()


def _rasterize_svg(svg_path: Path, out_path: Path, size: int = 512) -> Optional[Path]:
    """Convert an SVG to a transparent PNG. Returns the out path on success.

    Uses cairosvg if available (preferred); falls back to copying through
    Pillow if the input is already raster. Failures are non-fatal — the
    pipeline drops to the prompt-only path for that entity.
    """
    if not svg_path.exists():
        return None
    if svg_path.suffix.lower() == ".png":
        # Already raster; copy bytes through.
        out_path.write_bytes(svg_path.read_bytes())
        return out_path
    try:
        import cairosvg  # type: ignore
        with _RASTER_LOCK:
            cairosvg.svg2png(
                url=str(svg_path),
                write_to=str(out_path),
                output_width=size,
                output_height=size,
                background_color=None,  # transparent
            )
        if out_path.exists() and out_path.stat().st_size > 200:
            return out_path
    except ImportError:
        log.warning(
            "cairosvg not installed — SVG logos can't be rasterized for the "
            "image-edits API. Install via `pip install cairosvg` to enable "
            "Tier-1 reference-image compositing."
        )
    except Exception as e:  # noqa: BLE001
        log.warning("SVG rasterization failed for %s: %s", svg_path, e)
    return None


# ---------- Public API ----------

def resolve_entity(
    entity: str,
    *,
    bundle: Optional[dict[str, Path]] = None,
) -> LogoResolution:
    """Resolve one entity through the four-tier waterfall.

    Pure function aside from the disk cache reads/writes and HTTP. Always
    returns a LogoResolution — never raises.
    """
    canonical = _canonical_name(entity)
    bundle = bundle if bundle is not None else _scan_local_bundle()

    # ---- Tier 1 ----
    t1 = _try_tier1(entity, bundle)
    if t1 is not None:
        rasterized = _cache_dir() / f"{_slug(entity)}_t1.png"
        if not rasterized.exists():
            _rasterize_svg(t1, rasterized)
        return LogoResolution(
            entity=entity,
            canonical_name=canonical,
            tier="tier1_local_svg",
            local_path=t1,
            rasterized_path=rasterized if rasterized.exists() else None,
            note=f"matched local bundle slug={_slug(t1.stem)}",
        )

    # ---- Tier 2 ----
    t2 = _try_tier2(entity)
    if t2 is not None:
        return LogoResolution(
            entity=entity,
            canonical_name=canonical,
            tier="tier2_cdn",
            local_path=t2,
            rasterized_path=t2,  # already PNG
            domain=_infer_domain(entity),
            note=f"fetched from CDN domain={_infer_domain(entity)}",
        )

    # ---- Tier 3 ----
    s = _slug(entity)
    if s in MODEL_KNOWN_BRANDS:
        return LogoResolution(
            entity=entity,
            canonical_name=MODEL_KNOWN_BRANDS[s],
            tier="tier3_model_knowledge",
            note="ask the model to render the authentic logo from training",
        )

    # ---- Tier 4 ----
    return LogoResolution(
        entity=entity,
        canonical_name=canonical,
        tier="tier4_typographic",
        note="render as a clean typographic wordmark",
    )


def resolve_entities(entities: list[str]) -> list[LogoResolution]:
    """Batch-resolve a list of entities. De-duplicates by slug."""
    bundle = _scan_local_bundle()
    seen: set[str] = set()
    out: list[LogoResolution] = []
    for e in entities or []:
        if not e:
            continue
        s = _slug(e)
        if s in seen:
            continue
        seen.add(s)
        out.append(resolve_entity(e, bundle=bundle))
    return out


def diagnostics_summary(resolutions: list[LogoResolution]) -> dict[str, str]:
    """Build the `logo_tiers` block for media_assets.diagnostics.

    Keyed by the *input* entity name (with @ stripped) so the review UI
    surfaces the same names the brief contained. Tier-3 brands whose
    canonical_name was expanded ("OFAC" → "OFAC (Office of Foreign Assets
    Control)") still appear in the dict under their original key.
    """
    out: dict[str, str] = {}
    for r in resolutions:
        key = (r.entity or "").lstrip("@").strip() or r.canonical_name
        out[key] = r.tier
    return out
