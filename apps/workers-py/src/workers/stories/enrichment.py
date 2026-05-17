"""Pure-function graphics enrichment for story briefs.

Lives in its own module (rather than inside builder.py) so it has zero
dependencies on the DB layer or config — both of which pull in pydantic.
That lets the test suite import this directly without spinning up the
whole story-builder import chain.

The graphics pipeline reads `tiers`, `flow_labels`, and `supporting_stats`
straight off the brief. They're additive; legacy callers that haven't run
through this enrichment still work (the graphics layer falls back to
deriving them from entities + key_data_points on the fly).
"""

from __future__ import annotations

from typing import Any


def enrich_for_graphics(brief: dict[str, Any]) -> None:
    """Mutate `brief` in-place to add tiers/flow_labels/supporting_stats."""
    if not isinstance(brief, dict):
        return
    entities = [e for e in (brief.get("entities") or []) if e]
    kdps = brief.get("key_data_points") or []

    tiers: list[dict[str, str]] = []
    if entities:
        primary = entities[0].lstrip("@")
        primary_value = ""
        primary_value_label = ""
        if kdps:
            v = (kdps[0].get("value") or "").strip()
            if v and "n/a" not in v.lower():
                primary_value = v
                primary_value_label = (kdps[0].get("label") or "").upper()
        tiers.append({
            "name": primary,
            "role": "PRIMARY ENTITY",
            "value": primary_value,
            "value_label": primary_value_label,
            "description": _first_sentence(brief.get("headline", "")),
        })
        for e in entities[1:3]:
            tiers.append({
                "name": e.lstrip("@"),
                "role": "COUNTERPARTY",
                "value": "",
                "value_label": "",
                "description": "",
            })

    flow_labels: list[str] = []
    angle = (brief.get("narrative_angle") or "").lower()
    if len(tiers) >= 2:
        if any(k in angle for k in ("sanction", "freeze", "enforcement")):
            flow_labels.append("ACTED ON")
        elif any(k in angle for k in ("transfer agent", "custodian", "registrar")):
            flow_labels.append("APPOINTS")
        elif "flow" in angle or "rotation" in angle:
            flow_labels.append("FLOWS INTO")
        else:
            flow_labels.append("RELATED TO")
    if len(tiers) >= 3:
        if any(k in angle for k in ("sanction", "freeze", "enforcement")):
            flow_labels.append("EXECUTED ON")
        else:
            flow_labels.append("REFERENCED BY")

    supporting: list[dict[str, str]] = []
    for kd in kdps[1:]:
        v = (kd.get("value") or "").strip()
        label = (kd.get("label") or "").strip()
        if not v or "n/a" in v.lower():
            continue
        if label.lower() in ("headline", "full message", "source url", "url", "link"):
            continue
        if v.startswith(("http://", "https://")):
            continue
        if len(v) > 40:
            continue
        supporting.append({"value": v, "label": label.upper()})
        if len(supporting) >= 2:
            break

    brief["tiers"] = tiers
    brief["flow_labels"] = flow_labels
    brief["supporting_stats"] = supporting


def _first_sentence(text: str, max_chars: int = 100) -> str:
    if not text:
        return ""
    t = text.strip()
    for sep in [". ", "? ", "! "]:
        idx = t.find(sep)
        if 15 < idx < max_chars:
            return t[: idx + 1]
    return t[:max_chars]
