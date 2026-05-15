"""Render a Ledger Cartography plate for a story brief.

Each plate is a clean schematic diagram of one financial structure: tiered
cards stacked vertically (or side-by-side), labeled connecting arrows
spelling out the relationships, supporting figures below. Every value and
entity in the post body appears legibly in the plate.

This is the canvas-design path that replaces both the abstract Higgsfield
metaphor approach AND the Canva templates for data-led posts. See
packages/graphics/canvas_design/Ledger_Cartography.md for the philosophy.

Usage:
    python render_ledger_cartography.py <story_brief.json> <output.png>

Or call render_plate(spec, out_path) from another module.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from PIL import Image, ImageDraw, ImageFont


# ---------- Paths ----------

# Bundled fonts ship with the project (under packages/graphics/canvas_design/fonts/)
# so the Docker image on Fly has them too. Override via CANVAS_DESIGN_FONTS_DIR env
# var if you need to point at a different font directory in dev.
import os as _os
FONTS_DIR = Path(
    _os.environ.get(
        "CANVAS_DESIGN_FONTS_DIR",
        str(Path(__file__).resolve().parent / "fonts"),
    )
)


# ---------- Blockchain ticker map ----------

# When a tier's name matches a known L1 / L2, the monogram uses the L1 token
# ticker (ETH, BTC, SOL) instead of first-2-character initials (ET, BI, SO).
BLOCKCHAIN_TICKERS = {
    "ethereum": "ETH",
    "ether": "ETH",
    "bitcoin": "BTC",
    "solana": "SOL",
    "polygon": "POL",
    "matic": "POL",
    "avalanche": "AVAX",
    "arbitrum": "ARB",
    "optimism": "OP",
    "base": "BASE",
    "bnb chain": "BNB",
    "binance smart chain": "BNB",
    "bnb": "BNB",
    "near": "NEAR",
    "polkadot": "DOT",
    "cardano": "ADA",
    "tron": "TRX",
    "xrp ledger": "XRP",
    "ripple": "XRP",
    "xrp": "XRP",
    "sui": "SUI",
    "aptos": "APT",
    "stellar": "XLM",
    "cosmos": "ATOM",
    "celestia": "TIA",
    "ton": "TON",
    "hedera": "HBAR",
    "monad": "MON",
    "berachain": "BERA",
    "sei": "SEI",
    "injective": "INJ",
    "fantom": "FTM",
    "sonic": "S",
}


# ---------- Color palette ----------

PAPER = (250, 250, 250)              # #FAFAFA — substrate
INK_BLUE = (31, 111, 235)            # #1F6FEB — primary accent
INK_BLACK = (15, 23, 42)             # #0F172A — headline / value type
LABEL_GRAY = (100, 116, 139)         # #64748B — labels / marginalia
BORDER_GRAY = (220, 224, 230)        # #DCE0E6 — card borders
PANEL_GRAY = (245, 246, 248)         # #F5F6F8 — secondary card fill


# ---------- Font cache ----------

def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS_DIR / name), size=size)


# ---------- Helpers ----------

def _tracked_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int],
    tracking: int = 4,
) -> int:
    """Draw text with letter-spacing. Returns the total width drawn."""
    x, y = xy
    start_x = x
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        w = font.getbbox(ch)[2] - font.getbbox(ch)[0]
        x += w + tracking
    return x - start_x - tracking


def _tracked_width(text: str, font: ImageFont.FreeTypeFont, tracking: int) -> int:
    if not text:
        return 0
    return sum(
        (font.getbbox(c)[2] - font.getbbox(c)[0]) for c in text
    ) + tracking * max(0, len(text) - 1)


def _wrap_to_width(text: str, font: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    """Greedy word-wrap to fit max_w."""
    words = text.split()
    if not words:
        return []
    lines: list[str] = []
    current = words[0]
    for w in words[1:]:
        candidate = current + " " + w
        bbox = font.getbbox(candidate)
        if (bbox[2] - bbox[0]) <= max_w:
            current = candidate
        else:
            lines.append(current)
            current = w
    lines.append(current)
    return lines


def _draw_logo_block(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    size: int,
    initials: str,
    fill: tuple[int, int, int] = INK_BLUE,
    text_fill: tuple[int, int, int] = PAPER,
    font: Optional[ImageFont.FreeTypeFont] = None,
) -> None:
    """Render a square monogram block with initials. Replaces SVG logos for v1.

    Auto-sizes the font based on initial length so 3-4 char tickers (ETH, AVAX)
    still fit cleanly in the same square as 2-char initials (BR, BM).
    """
    try:
        draw.rounded_rectangle(
            (x, y, x + size, y + size),
            radius=int(size * 0.10),
            fill=fill,
        )
    except AttributeError:
        draw.rectangle((x, y, x + size, y + size), fill=fill)
    if font is None:
        # Scale the font down as the initials get longer.
        n = max(1, len(initials))
        scale = {1: 0.55, 2: 0.45, 3: 0.34, 4: 0.26}.get(n, max(0.18, 1.05 / n))
        font = _font("Outfit-Bold.ttf", int(size * scale))
    tw = font.getbbox(initials)[2] - font.getbbox(initials)[0]
    th = font.getbbox(initials)[3] - font.getbbox(initials)[1]
    draw.text(
        (x + (size - tw) // 2, y + (size - th) // 2 - int(size * 0.05)),
        initials, font=font, fill=text_fill,
    )


def _draw_arrow_down(
    draw: ImageDraw.ImageDraw,
    x: int, y_top: int, y_bot: int,
    color: tuple[int, int, int],
    weight: int,
    head_size: int,
) -> None:
    """Vertical arrow from (x, y_top) to (x, y_bot), arrowhead at the bottom."""
    draw.line((x, y_top, x, y_bot - head_size), fill=color, width=weight)
    # Arrowhead — a triangle
    draw.polygon(
        [
            (x, y_bot),
            (x - head_size, y_bot - head_size),
            (x + head_size, y_bot - head_size),
        ],
        fill=color,
    )


# ---------- Plate spec ----------

@dataclass
class Tier:
    """One labeled tier card in the structural diagram."""
    name: str               # "BlackRock"
    role_label: str         # "ISSUER / EVENT" or "TRANSFER AGENT"
    value: str              # "$7B" — primary number for the tier (optional, "" for none)
    value_label: str        # "FILED AUM"
    description: str        # one-line description of what this tier does
    initials: str           # "BR" — for the monogram block
    accent: bool = False    # if True, use INK_BLUE for the monogram + emphasized border


@dataclass
class SupportingFigure:
    value: str              # "$1.7B over 14 months"
    label: str              # "BUIDL COMPARABLE"


@dataclass
class PlateSpec:
    """Everything needed to render one Ledger Cartography schematic plate."""
    headline: str           # The literal post headline
    plate_no: str           # "PLATE XXIV"
    figure_no: str          # "FIGURE I"
    section_caps: str       # "STRUCTURAL HIERARCHY" or similar
    source_line: str        # "SOURCE · SEC FILING · 2026"
    tiers: list[Tier]
    arrow_labels: list[str] # one per arrow, between tiers (len = len(tiers) - 1)
    supporting_figures: list[SupportingFigure] = field(default_factory=list)


# ---------- Renderer ----------

def render_plate(
    spec: PlateSpec,
    out_path: Path,
    *,
    size: int = 1080,
    oversample: int = 4,
) -> Path:
    """Render the plate to `out_path` as a PNG at `size`px square."""
    S = size * oversample
    M = int(S * 0.06)               # outer margin

    img = Image.new("RGB", (S, S), PAPER)
    draw = ImageDraw.Draw(img)

    # ---------- Top frame rule + plate marginalia ----------
    rule_top = int(S * 0.055)
    draw.line((M, rule_top, S - M, rule_top), fill=INK_BLACK, width=oversample)

    margin_font = _font("GeistMono-Regular.ttf", int(S * 0.011))
    margin_track = int(S * 0.0028)

    left_marginalia = f"LEDGER ATLAS · VOL. I · {spec.plate_no}"
    _tracked_text(
        draw, (M, rule_top - int(S * 0.022)),
        left_marginalia, margin_font, LABEL_GRAY, tracking=margin_track,
    )
    fn_w = _tracked_width(spec.figure_no, margin_font, margin_track)
    _tracked_text(
        draw, (S - M - fn_w, rule_top - int(S * 0.022)),
        spec.figure_no, margin_font, LABEL_GRAY, tracking=margin_track,
    )

    # ---------- Section caps + headline (sans, semibold, two-line wrap) ----------
    section_caps_font = _font("Outfit-Bold.ttf", int(S * 0.0125))
    section_caps_track = int(S * 0.0040)
    sc_w = _tracked_width(spec.section_caps, section_caps_font, section_caps_track)
    _tracked_text(
        draw, (M, rule_top + int(S * 0.020)),
        spec.section_caps, section_caps_font, LABEL_GRAY, tracking=section_caps_track,
    )

    # Headline — semibold sans, near-black, wraps to 2 lines if needed.
    headline_size = int(S * 0.034)
    headline_font = _font("Outfit-Bold.ttf", headline_size)
    headline_max_w = S - 2 * M
    headline_lines = _wrap_to_width(spec.headline, headline_font, headline_max_w)
    headline_y = rule_top + int(S * 0.045)
    line_height = int(headline_size * 1.20)
    for i, line in enumerate(headline_lines[:2]):
        draw.text((M, headline_y + i * line_height), line,
                  font=headline_font, fill=INK_BLACK)
    headline_block_bottom = headline_y + min(2, len(headline_lines)) * line_height

    # ---------- Tier cards (stacked vertically) ----------
    figure_top = headline_block_bottom + int(S * 0.025)
    # Reserve bottom space for supporting figures + footer
    has_support = bool(spec.supporting_figures)
    footer_h = int(S * 0.065)
    support_h = int(S * 0.115) if has_support else 0
    figure_bot = S - footer_h - support_h - int(S * 0.020)
    figure_h = figure_bot - figure_top

    n_tiers = len(spec.tiers)
    n_arrows = n_tiers - 1
    arrow_h = int(S * 0.070)
    total_arrow_h = n_arrows * arrow_h
    card_h = (figure_h - total_arrow_h) // n_tiers
    card_w = S - 2 * M

    # Card text fonts
    tier_name_font = _font("Outfit-Bold.ttf", int(S * 0.025))
    role_label_font = _font("GeistMono-Regular.ttf", int(S * 0.0105))
    role_label_track = int(S * 0.0026)
    value_font = _font("Outfit-Bold.ttf", int(S * 0.030))
    value_label_font = _font("GeistMono-Regular.ttf", int(S * 0.0095))
    desc_font = _font("Outfit-Regular.ttf", int(S * 0.0145))

    arrow_label_font = _font("GeistMono-Regular.ttf", int(S * 0.011))
    arrow_label_track = int(S * 0.0030)

    cur_y = figure_top
    for idx, tier in enumerate(spec.tiers):
        # ----- Card background + border -----
        try:
            draw.rounded_rectangle(
                (M, cur_y, M + card_w, cur_y + card_h),
                radius=int(S * 0.012),
                fill=PAPER,
                outline=INK_BLUE if tier.accent else BORDER_GRAY,
                width=oversample * (2 if tier.accent else 1),
            )
        except AttributeError:
            draw.rectangle(
                (M, cur_y, M + card_w, cur_y + card_h),
                fill=PAPER,
                outline=INK_BLUE if tier.accent else BORDER_GRAY,
                width=oversample * (2 if tier.accent else 1),
            )

        # ----- Layout inside the card -----
        pad = int(S * 0.020)
        logo_size = int(card_h * 0.55)
        logo_x = M + pad
        logo_y = cur_y + (card_h - logo_size) // 2
        _draw_logo_block(
            draw, logo_x, logo_y, logo_size,
            initials=tier.initials,
            fill=INK_BLUE if tier.accent else INK_BLACK,
        )

        # Left text column (name + role label + description)
        text_x = logo_x + logo_size + pad
        # Name (semibold)
        name_y = cur_y + pad
        draw.text((text_x, name_y), tier.name, font=tier_name_font, fill=INK_BLACK)
        # Role label (tracked caps gray)
        rl_y = name_y + int(S * 0.030)
        _tracked_text(
            draw, (text_x, rl_y),
            tier.role_label, role_label_font, LABEL_GRAY, tracking=role_label_track,
        )
        # Description (regular gray)
        if tier.description:
            desc_y = rl_y + int(S * 0.022)
            desc_max_w = card_w - (text_x - M) - pad - int(S * 0.18)  # leave room for value column
            for li, line in enumerate(_wrap_to_width(tier.description, desc_font, desc_max_w)[:2]):
                draw.text((text_x, desc_y + li * int(S * 0.020)),
                          line, font=desc_font, fill=LABEL_GRAY)

        # Right value column (only if value is non-empty)
        if tier.value:
            value_x_right = M + card_w - pad
            v_w = value_font.getbbox(tier.value)[2] - value_font.getbbox(tier.value)[0]
            v_y = cur_y + pad + int(S * 0.005)
            draw.text((value_x_right - v_w, v_y), tier.value,
                      font=value_font, fill=INK_BLUE if tier.accent else INK_BLACK)
            # Value label (right-aligned tracked caps)
            vl_w = _tracked_width(tier.value_label, value_label_font, role_label_track)
            vl_y = v_y + int(S * 0.038)
            _tracked_text(
                draw, (value_x_right - vl_w, vl_y),
                tier.value_label, value_label_font, LABEL_GRAY, tracking=role_label_track,
            )

        cur_y += card_h

        # ----- Arrow + label between this card and the next -----
        if idx < n_arrows:
            arrow_y_top = cur_y + int(S * 0.012)
            arrow_y_bot = cur_y + arrow_h - int(S * 0.008)
            arrow_x = M + card_w // 2
            _draw_arrow_down(
                draw, arrow_x, arrow_y_top, arrow_y_bot,
                color=INK_BLACK,
                weight=oversample * 1,
                head_size=int(S * 0.012),
            )
            # Arrow label: positioned to the right of the arrow line
            label = spec.arrow_labels[idx]
            lw = _tracked_width(label, arrow_label_font, arrow_label_track)
            lx = arrow_x + int(S * 0.014)
            ly = (arrow_y_top + arrow_y_bot) // 2 - int(S * 0.008)
            _tracked_text(
                draw, (lx, ly), label,
                arrow_label_font, LABEL_GRAY, tracking=arrow_label_track,
            )
            cur_y += arrow_h

    # ---------- Supporting figures (compact side-by-side cards) ----------
    if spec.supporting_figures:
        sup_top = figure_bot + int(S * 0.012)
        sup_h = support_h - int(S * 0.020)
        n_sup = len(spec.supporting_figures)
        gap = int(S * 0.015)
        sup_w = (S - 2 * M - (n_sup - 1) * gap) // n_sup

        sup_value_font = _font("Outfit-Bold.ttf", int(S * 0.022))
        sup_label_font = _font("GeistMono-Regular.ttf", int(S * 0.0095))

        for i, sf in enumerate(spec.supporting_figures):
            sx = M + i * (sup_w + gap)
            sy = sup_top
            try:
                draw.rounded_rectangle(
                    (sx, sy, sx + sup_w, sy + sup_h),
                    radius=int(S * 0.010),
                    fill=PANEL_GRAY,
                    outline=BORDER_GRAY,
                    width=oversample,
                )
            except AttributeError:
                draw.rectangle(
                    (sx, sy, sx + sup_w, sy + sup_h),
                    fill=PANEL_GRAY, outline=BORDER_GRAY, width=oversample,
                )
            # Value (left-aligned, semibold)
            vx = sx + int(S * 0.018)
            vy = sy + int(S * 0.018)
            # Wrap value if too wide
            value_lines = _wrap_to_width(sf.value, sup_value_font, sup_w - 2 * int(S * 0.018))
            for li, line in enumerate(value_lines[:2]):
                draw.text((vx, vy + li * int(S * 0.026)),
                          line, font=sup_value_font, fill=INK_BLACK)
            # Label (tracked caps gray, below)
            lx = vx
            ly = sy + sup_h - int(S * 0.026)
            _tracked_text(
                draw, (lx, ly), sf.label,
                sup_label_font, LABEL_GRAY, tracking=role_label_track,
            )

    # ---------- Bottom rule + source marginalia + watermark ----------
    rule_bot = S - int(S * 0.045)
    draw.line((M, rule_bot, S - M, rule_bot), fill=INK_BLACK, width=oversample)
    _tracked_text(
        draw, (M, rule_bot + int(S * 0.011)),
        spec.source_line, margin_font, LABEL_GRAY, tracking=margin_track,
    )
    watermark = "@JACKSONBLAU"
    w_w = _tracked_width(watermark, margin_font, margin_track)
    _tracked_text(
        draw, (S - M - w_w, rule_bot + int(S * 0.011)),
        watermark, margin_font, LABEL_GRAY, tracking=margin_track,
    )

    # ---------- Downsample for crisp output ----------
    final = img.resize((size, size), Image.LANCZOS)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.save(out_path, format="PNG", optimize=True)
    return out_path


# ---------- Brief → PlateSpec ----------

def _initials(name: str) -> str:
    """Return monogram initials for an entity name.

    Blockchains: use the L1 token ticker from BLOCKCHAIN_TICKERS (ETH, BTC, SOL).
    Other entities: first two characters or first letter of each of the first
    two words.
    """
    name = (name or "").strip().lstrip("@")
    if not name:
        return "—"
    # Blockchain ticker lookup (case-insensitive, exact match on lowercase name)
    key = name.lower().strip()
    if key in BLOCKCHAIN_TICKERS:
        return BLOCKCHAIN_TICKERS[key]
    parts = [p for p in name.replace(",", " ").split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[1][0]).upper()
    return name[:2].upper()


def plate_from_brief(brief: dict) -> PlateSpec:
    """Translate a story brief to a PlateSpec for the schematic plate.

    Heuristic: tries to identify three tiers from key_data_points + entities:
      - Top tier: the headline issuer/event with its primary value (Filed AUM, etc.)
      - Middle tier: the operational role (Transfer Agent / Custodian / Manager)
      - Bottom tier: the canonical chain or substrate
    Plus up to 2 supporting figures from the remaining key_data_points.
    """
    headline = brief.get("headline") or "Untitled"
    kdps = brief.get("key_data_points") or []
    entities = [e.lstrip("@") for e in (brief.get("entities") or [])]

    # Find the labels of interest
    def _find(label_substring: str) -> Optional[dict]:
        ls = label_substring.lower()
        for kd in kdps:
            if ls in (kd.get("label") or "").lower():
                return kd
        return None

    aum_kdp = _find("aum") or _find("filed") or (kdps[0] if kdps else None)
    transfer_kdp = _find("transfer") or _find("agent") or _find("custodian")
    chain_kdp = _find("chain") or _find("ledger") or _find("substrate")

    # Tier 1 — issuer
    issuer_name = entities[0] if entities else "Unknown Issuer"
    tiers = [
        Tier(
            name=issuer_name,
            role_label="ISSUER · EVENT",
            value=(aum_kdp.get("value") if aum_kdp else "") or "",
            value_label=(aum_kdp.get("label") if aum_kdp else "").upper(),
            description=f"{issuer_name} files a tokenized money market fund onchain.",
            initials=_initials(issuer_name),
            accent=True,
        ),
    ]

    # Tier 2 — operational role
    if transfer_kdp:
        op_name = transfer_kdp.get("value") or "Transfer Agent"
        op_role = (transfer_kdp.get("label") or "TRANSFER AGENT").upper()
        op_initials = _initials(op_name)
        tiers.append(Tier(
            name=op_name,
            role_label=op_role,
            value="",
            value_label="",
            description="Maintains investor records and executes transfers, treating the L1 as canonical state.",
            initials=op_initials,
        ))

    # Tier 3 — canonical chain
    if chain_kdp:
        ch_name = chain_kdp.get("value") or "Ethereum"
        ch_role = (chain_kdp.get("label") or "CANONICAL CHAIN").upper()
        ch_initials = _initials(ch_name)
        tiers.append(Tier(
            name=ch_name,
            role_label=ch_role,
            value="",
            value_label="",
            description="L1 ledger that serves as the single, canonical state of token ownership.",
            initials=ch_initials,
        ))

    # Arrow labels — operational verbs
    arrow_labels: list[str] = []
    if len(tiers) >= 2:
        arrow_labels.append("APPOINTS · DELEGATES AUTHORITY TO")
    if len(tiers) >= 3:
        arrow_labels.append("AUTHORITY OVER CANONICAL STATE")

    # Supporting figures — up to 2 remaining numeric kdps
    used_labels = {
        (aum_kdp or {}).get("label"),
        (transfer_kdp or {}).get("label"),
        (chain_kdp or {}).get("label"),
    }
    supporting: list[SupportingFigure] = []
    for kd in kdps:
        if kd.get("label") in used_labels:
            continue
        v = kd.get("value", "")
        if not v:
            continue
        supporting.append(SupportingFigure(
            value=v, label=(kd.get("label") or "").upper(),
        ))
        if len(supporting) >= 2:
            break

    source_field = brief.get("source") or "PUBLIC FILING"
    return PlateSpec(
        headline=headline,
        plate_no="PLATE XXIV",
        figure_no="FIGURE I",
        section_caps="STRUCTURAL HIERARCHY",
        source_line=f"SOURCE · {source_field.upper()} · 2026",
        tiers=tiers,
        arrow_labels=arrow_labels,
        supporting_figures=supporting,
    )


# ---------- CLI ----------

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python render_ledger_cartography.py <brief.json> <out.png>")
        sys.exit(1)
    brief_path = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    payload = json.loads(brief_path.read_text())
    brief = payload.get("story") or payload
    spec = plate_from_brief(brief)
    result = render_plate(spec, out_path)
    print(f"Rendered: {result}")
