"""Story builder. For v0 we map each material signal 1:1 into a story.

In a later commit we'll cluster related signals (same entity, same 6h window) into
a single story before drafting.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .. import config, db


# Maps signal source identifiers to the X handle that should be credited in posts.
# If a source isn't here, posts won't carry a data-source attribution.
SOURCE_HANDLES: dict[str, str] = {
    "defillama": "@DefiLlama",
    "rwa_xyz": "@rwa_xyz",
    "telegram_newswire": "@RWAxyzNewswire",
    "vaultsfyi": "@vaultsfyi",
    "bubblemaps": "@bubblemaps",
    "etherscan": "@etherscan",
    # Onchain RPC data (Alchemy) doesn't get a source tag because the chain itself
    # is the source of truth, not the RPC provider. Leave blank.
    "alchemy": "",
    "x_firehose": "",  # the OP gets tagged in the reply itself, not as a source
}


def source_handle_for(source: str) -> str | None:
    """Return the X handle for a signal source, or None if no attribution needed."""
    handle = SOURCE_HANDLES.get(source, "")
    return handle if handle else None


def signal_to_story_brief(signal: dict[str, Any]) -> dict[str, Any]:
    """Turn one scored signal into a story brief object the drafter consumes."""
    payload = signal["payload"] if isinstance(signal["payload"], dict) else json.loads(signal["payload"])
    name = payload.get("name") or signal.get("entity") or "Unknown"
    twitter = payload.get("twitter")
    subject_handle = f"@{twitter}" if twitter else None
    source = signal.get("source", "")
    source_handle = source_handle_for(source)

    # Map data-point sources from raw identifiers to X handles
    def _data_source_label(src: str) -> str:
        return source_handle_for(src) or src

    key_points: list[dict[str, Any]] = []
    if "tvl_usd" in payload:
        key_points.append({"label": "TVL", "value": f"${payload['tvl_usd']:,.0f}", "source": _data_source_label(source)})
    if "change_1d_pct" in payload:
        key_points.append({"label": "24h change", "value": f"{payload['change_1d_pct']:+.2f}%", "source": _data_source_label(source)})
    if "change_7d_pct" in payload and payload["change_7d_pct"] is not None:
        key_points.append({"label": "7d change", "value": f"{payload['change_7d_pct']:+.2f}%", "source": _data_source_label(source)})
    if payload.get("category"):
        key_points.append({"label": "Category", "value": payload["category"], "source": _data_source_label(source)})
    if payload.get("chain"):
        key_points.append({"label": "Chain", "value": payload["chain"], "source": _data_source_label(source)})

    th = config.thresholds()
    score = signal.get("materiality_score") or 0
    formats = ["single"]
    if score >= th["materiality"]["minimum_for_thread"]:
        formats.append("thread")

    # `entities` = handles the post is ABOUT (subject of analysis).
    # `source_handles` = handles the post must CREDIT for data attribution.
    # Both go through the same tagging logic in the prompt, but separated here for clarity.
    entities: list[str] = []
    if subject_handle:
        entities.append(subject_handle)

    source_handles: list[str] = []
    if source_handle:
        source_handles.append(source_handle)

    return {
        "headline": f"{name}: 24h TVL move {payload.get('change_1d_pct', 0):+.2f}%",
        "narrative_angle": "tvl shift in an RWA protocol; assess size and direction",
        "entities": entities,
        "source_handles": source_handles,
        "key_data_points": key_points,
        "format_recommendation": formats,
        "graphic_spec": None,
        "signal_ids": [signal["id"]],
    }


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
            cur.execute(
                """
                insert into stories (headline, narrative_angle, entities, key_data_points,
                                     format_recommendation, signals_ids)
                values (%s, %s, %s, %s::jsonb, %s, %s)
                returning id::text
                """,
                (
                    brief["headline"],
                    brief["narrative_angle"],
                    brief["entities"],
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
