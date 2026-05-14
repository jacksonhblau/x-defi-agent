"""Anthropic client wrapper. One place for model selection, retry, and prompt loading."""

from __future__ import annotations

from typing import Any

from anthropic import Anthropic
from tenacity import retry, stop_after_attempt, wait_exponential

from . import config


_client: Anthropic | None = None


def client() -> Anthropic:
    global _client
    if _client is None:
        key = config.env().anthropic_api_key
        if not key:
            raise RuntimeError("ANTHROPIC_API_KEY is not set in .env")
        _client = Anthropic(api_key=key)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def complete(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> str:
    """Single non-streaming completion. Returns the text of the first content block."""
    msg = client().messages.create(
        model=model or config.env().anthropic_model,
        max_tokens=max_tokens,
        temperature=temperature,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    if not msg.content:
        return ""
    return msg.content[0].text  # type: ignore[union-attr]


def complete_json(
    *,
    system: str,
    user: str,
    model: str | None = None,
    max_tokens: int = 2048,
    temperature: float = 0.3,
) -> dict[str, Any]:
    """Completion that expects a JSON object back. Lower default temperature."""
    import json
    raw = complete(system=system, user=user, model=model, max_tokens=max_tokens, temperature=temperature)
    # Tolerate fenced output ```json ... ```
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw
        if raw.endswith("```"):
            raw = raw.rsplit("```", 1)[0]
        raw = raw.removeprefix("json\n").strip()
    return json.loads(raw)
