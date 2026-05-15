"""RWA.xyz ingest worker.

Pulls the top tokenized assets by circulating market value, then emits:
- `new_deploy` signals for assets we've never seen before
- `aum_delta` signals for assets whose market value changed materially since last seen

API v4 reference: https://docs.rwa.xyz/home

Endpoints used:
  GET https://api.rwa.xyz/v4/assets?query={"filter":{...},"sort":{...},"pagination":{...}}

Auth: Bearer token from RWA_XYZ_API_KEY.

Query format is URL-encoded JSON in the `query` param. Filter shape:
  {"operator": "equals", "field": "asset_class_name", "value": "US Treasury Debt"}
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

import httpx
from psycopg.rows import dict_row

from .. import config, db


def _headers() -> dict[str, str]:
    key = config.env().rwa_xyz_api_key
    if not key:
        raise RuntimeError("RWA_XYZ_API_KEY is not set in .env")
    return {"Authorization": f"Bearer {key}", "Accept": "application/json"}


def _base_url() -> str:
    return config.env().rwa_xyz_base_url.rstrip("/") + "/v4"


def query_assets(
    *,
    asset_class: str | None = None,
    sort_field: str = "circulating_market_value_dollar",
    sort_direction: str = "desc",
    page: int = 1,
    per_page: int = 50,
) -> list[dict[str, Any]]:
    """Hit /v4/assets with the given filter+sort+pagination. Returns the result list."""
    query: dict[str, Any] = {
        "sort": {"field": sort_field, "direction": sort_direction},
        "pagination": {"page": page, "perPage": per_page},
    }
    if asset_class:
        query["filter"] = {"operator": "equals", "field": "asset_class_name", "value": asset_class}

    url = f"{_base_url()}/assets"
    with httpx.Client(timeout=30.0, headers=_headers()) as client:
        r = client.get(url, params={"query": json.dumps(query)})
        r.raise_for_status()
        data = r.json()
    # RWA.xyz responses typically wrap the list under a `data` or `results` key.
    # Be defensive and accept either shape, or a bare list.
    if isinstance(data, list):
        return data
    for key in ("data", "results", "items", "assets"):
        if isinstance(data.get(key), list):
            return data[key]
    return []


def _latest_signal_for_entity(entity: str, source: str = "rwa_xyz") -> dict[str, Any] | None:
    """Most-recent signal for this entity (any time)."""
    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id::text, observed_at, payload
            from signals
            where source = %s and entity = %s
            order by observed_at desc
            limit 1
            """,
            (source, entity),
        )
        return cur.fetchone()


def _aum_change_pct(old: float, new: float) -> float | None:
    if old is None or new is None or old == 0:
        return None
    return (new - old) / old * 100.0


def ingest_top_assets(
    *,
    per_page: int = 50,
    asset_classes: Iterable[str] = ("US Treasury Debt", "Private Credit", "Real Estate", "Commodities"),
    write_to_db: bool = True,
) -> list[dict[str, Any]]:
    """Pull the top assets in each category and emit signals.

    Strategy:
    - For each category, fetch the top N assets by circulating_market_value_dollar.
    - For each asset:
        - If we've never seen this asset_id before, emit a `new_deploy` signal.
        - If we have, compute the delta vs the most recent signal for the same entity.
          If |change| >= 5%, emit an `aum_delta` signal.
        - Otherwise, do nothing (the dedup hash would prevent a duplicate anyway).

    Returns the list of payloads emitted (handy for dry-run testing).
    """
    th = config.thresholds()
    aum_threshold_pct = th["onchain"].get("tvl_delta_threshold_pct", 5.0)
    emitted: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for asset_class in asset_classes:
        try:
            assets = query_assets(asset_class=asset_class, per_page=per_page)
        except httpx.HTTPStatusError as e:
            # Non-fatal: log and skip this class. Continue with others.
            print(f"[rwa_xyz] HTTP error on class={asset_class}: {e.response.status_code} {e.response.text[:200]}")
            continue
        except Exception as e:
            print(f"[rwa_xyz] error on class={asset_class}: {e}")
            continue

        for asset in assets:
            asset_id = asset.get("asset_id") or asset.get("id")
            if asset_id is None:
                continue
            entity = f"rwa_asset:{asset_id}"
            name = asset.get("name") or asset.get("asset_name") or f"asset_{asset_id}"
            market_value = asset.get("circulating_market_value_dollar") or asset.get("market_value_dollar")
            manager = asset.get("manager_name") or asset.get("issuer_name")

            payload_common = {
                "asset_id": asset_id,
                "name": name,
                "asset_class": asset.get("asset_class_name") or asset_class,
                "circulating_market_value_dollar": market_value,
                "manager": manager,
                "chain": asset.get("chain_name") or asset.get("primary_chain"),
                "url": f"https://app.rwa.xyz/asset/{asset_id}",
            }

            last = _latest_signal_for_entity(entity)
            if last is None:
                # First sighting → new_deploy
                payload = {**payload_common, "first_seen_at": now.isoformat()}
                emitted.append(payload)
                if write_to_db:
                    db.insert_signal(
                        source="rwa_xyz",
                        signal_type="new_deploy",
                        payload=payload,
                        observed_at=now,
                        entity=entity,
                        source_id=str(asset_id),
                    )
                continue

            # We've seen this asset before. Compare values.
            old_payload = last["payload"] if isinstance(last["payload"], dict) else json.loads(last["payload"])
            old_value = old_payload.get("circulating_market_value_dollar")
            change_pct = _aum_change_pct(old_value, market_value)
            if change_pct is None:
                continue
            if abs(change_pct) >= aum_threshold_pct:
                payload = {
                    **payload_common,
                    "previous_market_value_dollar": old_value,
                    "change_pct": change_pct,
                    "previous_observed_at": last["observed_at"].isoformat() if last["observed_at"] else None,
                }
                emitted.append(payload)
                if write_to_db:
                    db.insert_signal(
                        source="rwa_xyz",
                        signal_type="aum_delta",
                        payload=payload,
                        observed_at=now,
                        entity=entity,
                        source_id=str(asset_id),
                    )
    return emitted
