"""Story builder. For v0 we map each material signal 1:1 into a story.

In a later commit we'll cluster related signals (same entity, same 6h window) into
a single story before drafting.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .. import config, db


# Maps signal source identifiers to the X handle that should be credited in posts.
# If a source isn't here, posts won't carry a data-source attribution.
SOURCE_HANDLES: dict[str, str] = {
    "defillama": "@DefiLlama",
    "rwa_xyz": "@rwa_xyz",
    "vaultsfyi": "@vaultsfyi",
    "bubblemaps": "@bubblemaps",
    "etherscan": "@etherscan",
    # Telegram intentionally NOT mapped here. Telegram is just an aggregator —
    # the real publisher handle is resolved per-message from the article URL
    # inside the message body (see _brief_from_telegram + PUBLISHER_HANDLES).
    "telegram_newswire": "",
    # Onchain RPC data (Alchemy) doesn't get a source tag because the chain itself
    # is the source of truth, not the RPC provider. Leave blank.
    "alchemy": "",
    "x_firehose": "",  # the OP gets tagged in the reply itself, not as a source
}


def source_handle_for(source: str) -> str | None:
    """Return the X handle for a signal source, or None if no attribution needed."""
    handle = SOURCE_HANDLES.get(source, "")
    return handle if handle else None


# Curated publisher domain → X handle. Used to credit the ACTUAL source of a
# Telegram newswire item (the article it links to), not the @RWAxyzNewswire
# aggregator. Handles here are best-effort verified manually; add to this list
# as you encounter new domains in messages.
PUBLISHER_HANDLES: dict[str, str | None] = {
    # Crypto / web3 outlets
    "coindesk.com":         "@CoinDesk",
    "cointelegraph.com":    "@Cointelegraph",
    "theblock.co":          "@TheBlock__",
    "decrypt.co":           "@decryptmedia",
    "blockworks.co":        "@Blockworksco",
    "bankless.com":         "@BanklessHQ",
    "defiant.io":           "@DefiantNews",
    "thedefiant.io":        "@DefiantNews",
    "milkroad.com":         "@MilkRoadDaily",
    "crypto.news":          "@cryptodotnews",
    "cryptobriefing.com":   "@CryptoBriefing",
    "cryptoslate.com":      "@CryptoSlate",
    "ambcrypto.com":        "@AMBCrypto",
    "bitcoinist.com":       "@bitcoinist",
    "yellow.com":           None,             # uncertain handle; safer to skip
    "techbullion.com":      "@TechBullion",
    "ts2.tech":             None,             # tech aggregator; no clear handle
    "rwa.io":               "@rwa_io",
    # PR / wires
    "businesswire.com":     "@businesswire",
    "prnewswire.com":       "@PRNewswire",
    "globenewswire.com":    "@globenewswire",
    "accesswire.com":       "@accesswire",
    # Mainstream business / finance
    "bloomberg.com":        "@business",
    "reuters.com":          "@Reuters",
    "wsj.com":              "@WSJ",
    "ft.com":               "@FinancialTimes",
    "cnbc.com":             "@CNBC",
    "forbes.com":           "@Forbes",
    "fortune.com":          "@FortuneMagazine",
    "marketwatch.com":      "@MarketWatch",
    "barrons.com":           "@barronsonline",
    # Local / general (don't tag the aggregator)
    "manilatimes.net":      None,
    "aol.com":              None,
    "yahoo.com":             None,
    "msn.com":               None,
    # Issuer-direct domains (the entity tag is already in the body)
    "blackrock.com":        "@BlackRock",
    "fidelity.com":         "@Fidelity",
    "circle.com":           "@CircleConsumer",
    "ondofinance.com":      "@OndoFinance",
    "centrifuge.io":        "@centrifuge",
    "maple.finance":        "@maplefinance",
    "goldfinch.finance":    "@goldfinch_fi",
    "securitize.io":        "@Securitize",
}


_SOURCE_LINK_RE = re.compile(r'\[Source\]\((https?://[^\s)]+)\)', re.IGNORECASE)
_ANY_URL_RE = re.compile(r'(https?://[^\s)\]]+)')


def _extract_source_url(text: str) -> str | None:
    """Pull the article URL out of a Telegram newswire message.

    The wire format is consistent: a markdown `[Source](URL)` link at the end.
    Falls back to the first non-Telegram URL we can find.
    """
    if not text:
        return None
    m = _SOURCE_LINK_RE.search(text)
    if m:
        return m.group(1)
    # Fallback: any URL that isn't t.me
    for m in _ANY_URL_RE.finditer(text):
        url = m.group(1)
        if "t.me/" in url:
            continue
        return url
    return None


def _publisher_handle_from_url(url: str | None) -> tuple[str | None, str | None]:
    """Resolve a URL to (domain, publisher_handle_or_None).

    Returns (domain_for_display, x_handle). If the domain is in our map but
    explicitly None, the handle is None (we know about this publisher but
    don't have a verified handle to use).
    """
    if not url:
        return None, None
    try:
        parsed = urlparse(url)
    except Exception:
        return None, None
    domain = (parsed.netloc or "").lower()
    if domain.startswith("www."):
        domain = domain[4:]
    if not domain:
        return None, None
    # Try exact match first, then walk up subdomains (e.g. blog.coindesk.com → coindesk.com)
    parts = domain.split(".")
    for i in range(len(parts) - 1):
        candidate = ".".join(parts[i:])
        if candidate in PUBLISHER_HANDLES:
            return candidate, PUBLISHER_HANDLES[candidate]
    return domain, None


# Known issuer/manager → X handle. Used to derive `entities` from RWA.xyz manager
# names and from Telegram message text. Add to this as the watchlist grows.
MANAGER_HANDLES: dict[str, str] = {
    "blackrock":            "@BlackRock",
    "circle":               "@CircleConsumer",
    "ondo":                 "@ondofinance",
    "maple":                "@maplefinance",
    "centrifuge":           "@centrifuge",
    "goldfinch":            "@goldfinch_fi",
    "realt":                "@realtplatform",
    "superstate":           "@SuperstateInc",
    "openeden":             "@openeden_X",
    "backed":               "@backed_fi",
    "swarm":                "@swarm_markets",
    "franklin templeton":   "@franklintempleton",
    "fidelity":             "@Fidelity",
    "wisdomtree":           "@WisdomTreeFunds",
    "securitize":           "@Securitize",
    "bny mellon":           "@BNYMellon",
    "jpmorgan":             "@JPMorgan",
    "spiko":                None,    # no X handle; placeholder for future
    "paxos":                "@paxos",
    "tether":               "@Tether_to",
}


def _handles_from_text(text: str) -> list[str]:
    """Scan text for known manager/issuer names and return matching X handles."""
    if not text:
        return []
    lower = text.lower()
    handles: list[str] = []
    for needle, handle in MANAGER_HANDLES.items():
        if handle and needle in lower and handle not in handles:
            handles.append(handle)
    return handles


def _format_dollars(n: float | int | None) -> str:
    if n is None:
        return "n/a"
    n = float(n)
    if abs(n) >= 1e9:
        return f"${n/1e9:.2f}B"
    if abs(n) >= 1e6:
        return f"${n/1e6:.1f}M"
    if abs(n) >= 1e3:
        return f"${n/1e3:.0f}K"
    return f"${n:.0f}"


def _brief_from_defillama(signal: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    name = payload.get("name") or signal.get("entity") or "Unknown protocol"
    twitter = payload.get("twitter")
    entities = [f"@{twitter}"] if twitter else []
    change_1d = payload.get("change_1d_pct") or 0.0

    key_points: list[dict[str, Any]] = []
    if payload.get("tvl_usd") is not None:
        key_points.append({"label": "TVL", "value": _format_dollars(payload["tvl_usd"]), "source": "@DefiLlama"})
    if payload.get("change_1d_pct") is not None:
        key_points.append({"label": "24h change", "value": f"{payload['change_1d_pct']:+.2f}%", "source": "@DefiLlama"})
    if payload.get("change_7d_pct") is not None:
        key_points.append({"label": "7d change", "value": f"{payload['change_7d_pct']:+.2f}%", "source": "@DefiLlama"})
    if payload.get("category"):
        key_points.append({"label": "Category", "value": payload["category"], "source": "@DefiLlama"})
    if payload.get("chain"):
        key_points.append({"label": "Chain", "value": payload["chain"], "source": "@DefiLlama"})

    return {
        "headline": f"{name}: 24h TVL move {change_1d:+.2f}%",
        "narrative_angle": "rwa protocol tvl shift; assess size, direction, and magnitude vs peers",
        "entities": entities,
        "source_handles": ["@DefiLlama"],
        "key_data_points": key_points,
    }


def _brief_from_rwa_xyz(signal: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """RWA.xyz signals carry a rich payload. The market value is a nested object:
    {val, val_7d, val_30d, val_90d, chg_7d_pct, chg_30d_pct, chg_90d_pct, ...}
    """
    name = payload.get("name") or signal.get("entity") or "Unknown asset"
    asset_class = payload.get("asset_class") or "Tokenized asset"
    manager = payload.get("manager") or ""

    # Extract scalar values from the nested object
    mv_obj = payload.get("circulating_market_value_dollar")
    if isinstance(mv_obj, dict):
        current_val = mv_obj.get("val")
        chg_7d = mv_obj.get("chg_7d_pct")
        chg_30d = mv_obj.get("chg_30d_pct")
        chg_90d = mv_obj.get("chg_90d_pct")
    else:
        current_val = mv_obj if isinstance(mv_obj, (int, float)) else None
        chg_7d = chg_30d = chg_90d = None

    # For aum_delta signals we also have explicit change_pct vs previous signal
    explicit_change = payload.get("change_pct")
    is_aum_delta = signal.get("signal_type") == "aum_delta"

    # Derive headline based on signal type
    if is_aum_delta and explicit_change is not None:
        headline = f"{name}: {explicit_change:+.2f}% market value move"
    elif chg_30d is not None and abs(chg_30d) >= 5:
        headline = f"{name}: {chg_30d:+.2f}% over 30d ({_format_dollars(current_val)} AUM)"
    else:
        headline = f"{name}: {_format_dollars(current_val)} AUM ({asset_class})"

    entities = _handles_from_text(f"{name} {manager}")

    key_points: list[dict[str, Any]] = []
    if current_val is not None:
        key_points.append({"label": "Current AUM", "value": _format_dollars(current_val), "source": "@rwa_xyz"})
    if chg_7d is not None:
        key_points.append({"label": "7d change", "value": f"{chg_7d:+.2f}%", "source": "@rwa_xyz"})
    if chg_30d is not None:
        key_points.append({"label": "30d change", "value": f"{chg_30d:+.2f}%", "source": "@rwa_xyz"})
    if chg_90d is not None:
        key_points.append({"label": "90d change", "value": f"{chg_90d:+.2f}%", "source": "@rwa_xyz"})
    if manager:
        key_points.append({"label": "Manager", "value": manager, "source": "@rwa_xyz"})
    if payload.get("asset_class"):
        key_points.append({"label": "Asset class", "value": payload["asset_class"], "source": "@rwa_xyz"})

    return {
        "headline": headline,
        "narrative_angle": "tokenized asset AUM movement; what does the trajectory imply about institutional demand",
        "entities": entities,
        "source_handles": ["@rwa_xyz"],
        "key_data_points": key_points,
    }


def _brief_from_telegram(signal: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Telegram messages already arrive as natural-language news. The brief
    captures the message text so the drafter can produce a take on it.

    Source attribution: we extract the [Source](URL) link from the message body
    and credit the PUBLISHER (e.g. @CoinDesk, @TechBullion) — NOT the
    @RWAxyzNewswire aggregator. If we don't have a verified handle for the
    publisher, source_handles is left empty (the post stays untagged on source).
    """
    text = payload.get("text") or ""
    telegram_msg_url = payload.get("url") or ""

    # Headline = first non-empty line of the message, stripped of markdown
    first_line = next((ln.strip() for ln in text.split("\n") if ln.strip()), "RWA newsfeed update")
    first_line = first_line.replace("**", "").replace("__", "").strip()
    if len(first_line) > 140:
        first_line = first_line[:137] + "..."

    # Extract the actual source article URL from the message body and resolve
    # to a publisher X handle (best-effort verified, see PUBLISHER_HANDLES).
    article_url = _extract_source_url(text)
    publisher_domain, publisher_handle = _publisher_handle_from_url(article_url)

    # Entities come from named issuers/managers detected in the message body
    entities = _handles_from_text(text)

    # If the publisher itself is also an issuer (e.g. blackrock.com), the
    # publisher_handle may duplicate something in entities — that's fine, we'll
    # dedup before posting.

    source_handles: list[str] = []
    if publisher_handle:
        source_handles.append(publisher_handle)

    source_label = publisher_handle or publisher_domain or "newsfeed"

    key_points: list[dict[str, Any]] = [
        {"label": "Headline", "value": first_line, "source": source_label},
        {"label": "Full message", "value": text[:1500], "source": source_label},
    ]
    if article_url:
        key_points.append({"label": "Source URL", "value": article_url, "source": source_label})
    if publisher_domain and not publisher_handle:
        # Useful debugging signal: we found a domain we don't have a handle for.
        # The drafter will see this so it knows to cite the URL in prose if needed.
        key_points.append({
            "label": "Note",
            "value": f"Publisher domain {publisher_domain} has no verified X handle in PUBLISHER_HANDLES; cite the URL in body rather than tag.",
            "source": "system",
        })
    key_points.append({"label": "Telegram URL", "value": telegram_msg_url, "source": "internal"})

    return {
        "headline": first_line,
        "narrative_angle": (
            "newsfeed item — write an analyst take that adds context, mechanism, or contrast "
            "to the surface news. Tag the entities in the brief. If a publisher X handle is "
            "in source_handles, credit them. If not, you may cite the source URL in prose "
            "(e.g. 'per the announcement') instead of forcing an @-mention."
        ),
        "entities": entities,
        "source_handles": source_handles,
        "key_data_points": key_points,
    }


def _brief_generic(signal: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    """Fallback for unknown sources."""
    name = payload.get("name") or signal.get("entity") or signal.get("signal_type") or "Update"
    source_handle = source_handle_for(signal.get("source", ""))
    return {
        "headline": str(name),
        "narrative_angle": "unclassified signal; assess and produce a take based on available data",
        "entities": [],
        "source_handles": [source_handle] if source_handle else [],
        "key_data_points": [{"label": k, "value": str(v)[:200], "source": source_handle or signal.get("source", "")} for k, v in payload.items()][:8],
    }


def signal_to_story_brief(signal: dict[str, Any]) -> dict[str, Any]:
    """Turn one scored signal into a story brief. Dispatches by source."""
    payload = signal["payload"] if isinstance(signal["payload"], dict) else json.loads(signal["payload"])
    source = signal.get("source", "")

    if source == "defillama":
        base = _brief_from_defillama(signal, payload)
    elif source == "rwa_xyz":
        base = _brief_from_rwa_xyz(signal, payload)
    elif source == "telegram_newswire":
        base = _brief_from_telegram(signal, payload)
    else:
        base = _brief_generic(signal, payload)

    th = config.thresholds()
    score = signal.get("materiality_score") or 0
    formats = ["single"]
    if score >= th["materiality"]["minimum_for_thread"]:
        formats.append("thread")

    base["format_recommendation"] = formats
    base["graphic_spec"] = None
    base["signal_ids"] = [signal["id"]]

    # ---- Algo-refit v2 enrichment ----
    # Every brief gets `tiers`, `flow_labels`, and `supporting_stats` so the
    # graphics pipeline has structured layout content regardless of which
    # source built the brief. See workers.stories.enrichment for the shape.
    from .enrichment import enrich_for_graphics as _enrich_for_graphics
    _enrich_for_graphics(base)
    return base


def build_open_stories(limit: int = 20) -> list[dict[str, Any]]:
    """Pull recent scored signals above threshold and write story rows."""
    th = config.thresholds()
    min_score = th["materiality"]["default_threshold"]

    with db.conn() as c:
        from psycopg.rows import dict_row
        with c.cursor(row_factory=dict_row) as cur:
            cur.execute(
                """
                select id::text, observed_at, source, source_id, entity, signal_type,
                       payload, materiality_score, novelty_score
                from signals
                where processed_at is not null
                  and materiality_score >= %s
                  and promoted_to_story_id is null
                order by observed_at desc
                limit %s
                """,
                (min_score, limit),
            )
            signals = cur.fetchall()

    created: list[dict[str, Any]] = []
    for sig in signals:
        brief = signal_to_story_brief(sig)
        with db.conn() as c, c.cursor() as cur:
            # ---- Dedup: link this signal to an existing recent story with the same
            # headline rather than spawning a duplicate. Same news arriving from
            # multiple sources (Telegram + DeFiLlama + RWA.xyz) used to triple our
            # story count and triple our draft generation costs.
            cur.execute(
                """
                select id::text, signals_ids
                from stories
                where headline = %s
                  and status in ('open', 'drafted')
                  and created_at > now() - interval '7 days'
                order by created_at desc
                limit 1
                """,
                (brief["headline"],),
            )
            existing = cur.fetchone()
            if existing:
                existing_id, existing_signal_ids = existing
                # Avoid double-listing the same signal_id
                if str(sig["id"]) not in [str(s) for s in (existing_signal_ids or [])]:
                    cur.execute(
                        "update stories set signals_ids = array_append(signals_ids, %s) where id = %s::uuid",
                        (sig["id"], existing_id),
                    )
                cur.execute(
                    "update signals set promoted_to_story_id = %s where id = %s",
                    (existing_id, sig["id"]),
                )
                c.commit()
                # Skip — we linked the signal to the existing story. Not added to
                # `created` because it's not a new story.
                continue

            cur.execute(
                """
                insert into stories (headline, narrative_angle, entities, source_handles,
                                     key_data_points, format_recommendation, signals_ids)
                values (%s, %s, %s, %s, %s::jsonb, %s, %s)
                returning id::text
                """,
                (
                    brief["headline"],
                    brief["narrative_angle"],
                    brief["entities"],
                    brief.get("source_handles") or [],
                    json.dumps(brief["key_data_points"]),
                    brief["format_recommendation"],
                    [sig["id"]],
                ),
            )
            story_id = cur.fetchone()[0]
            cur.execute(
                "update signals set promoted_to_story_id = %s where id = %s",
                (story_id, sig["id"]),
            )
            c.commit()
        brief["id"] = story_id
        created.append(brief)
    return created
