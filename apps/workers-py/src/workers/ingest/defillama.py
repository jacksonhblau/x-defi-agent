"""DeFiLlama ingest worker.

DeFiLlama exposes free public endpoints (no API key required for these).
We focus on the RWA category and yield-bearing assets.

Endpoints used:
  GET https://api.llama.fi/protocols                    - all protocols with current TVL
  GET https://api.llama.fi/protocol/{slug}              - protocol detail with historical TVL
  GET https://yields.llama.fi/pools                     - all yield pools (vaults)

For v0 we pull the protocols list, filter to RWA category, and emit one
`tvl_delta` signal per protocol whose 24h change crosses the configured threshold.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from .. import config, db


DEFILLAMA_PROTOCOLS_URL = "https://api.llama.fi/protocols"
DEFILLAMA_YIELDS_URL = "https://yields.llama.fi/pools"

# Categories we care about. DeFiLlama's category strings are messy across protocols;
# we accept any of these (case-insensitive substring match).
RWA_CATEGORY_HINTS = (
    "rwa",
    "real world assets",
    "treasury",
    "tokenized",
    "private credit",
)


def _is_rwa(protocol: dict[str, Any]) -> bool:
    category = (protocol.get("category") or "").lower()
    return any(hint in category for hint in RWA_CATEGORY_HINTS)


def fetch_protocols() -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(DEFILLAMA_PROTOCOLS_URL)
        r.raise_for_status()
        return r.json()


def fetch_pools() -> list[dict[str, Any]]:
    with httpx.Client(timeout=30.0) as client:
        r = client.get(DEFILLAMA_YIELDS_URL)
        r.raise_for_status()
        data = r.json()
        return data.get("data", [])


def ingest_protocol_tvl_deltas(*, write_to_db: bool = True) -> list[dict[str, Any]]:
    """Pull all protocols, filter to RWA, emit a signal for each one with a 24h TVL delta.

    Returns the list of signal payloads (handy for testing without a DB connection).
    """
    th = config.thresholds()
    tvl_delta_threshold_pct = th["onchain"]["tvl_delta_threshold_pct"]

    protocols = fetch_protocols()
    rwa_protocols = [p for p in protocols if _is_rwa(p)]

    now = datetime.now(timezone.utc)
    signals_emitted: list[dict[str, Any]] = []

    for p in rwa_protocols:
        change_pct = p.get("change_1d")
        tvl = p.get("tvl")
        if change_pct is None or tvl is None:
            continue
        if abs(change_pct) < tvl_delta_threshold_pct:
            continue

        payload = {
            "name": p.get("name"),
            "slug": p.get("slug"),
            "category": p.get("category"),
            "chain": p.get("chain"),
            "tvl_usd": tvl,
            "change_1d_pct": change_pct,
            "change_7d_pct": p.get("change_7d"),
            "twitter": p.get("twitter"),
            "url": p.get("url"),
        }
        signals_emitted.append(payload)

        if write_to_db:
            db.insert_signal(
                source="defillama",
                signal_type="tvl_delta",
                payload=payload,
                observed_at=now,
                entity=p.get("slug"),
                source_id=p.get("slug"),
            )

    return signals_emitted
