"""Telegram newswire listener.

Subscribes (as a regular Telegram user, via Telethon's MTProto client) to one
or more public channels listed in TELEGRAM_CHANNELS env var. The default is
@RWAxyzNewswire — the highest-signal RWA newsfeed.

Each new message becomes one `newsfeed` signal. The message body is stored in
the payload so the materiality scorer can read it.

Run `agent telegram-login` once interactively before the watch loop tries to
fetch messages — Telethon needs an SMS code on first connect.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from telethon.sync import TelegramClient
from telethon.tl.types import Message

from .. import config, db


def _client() -> TelegramClient:
    env = config.env()
    if not env.telegram_api_id or not env.telegram_api_hash:
        raise RuntimeError("TELEGRAM_API_ID and TELEGRAM_API_HASH must be set in .env")
    session_path = env.telegram_session_path
    # Resolve relative paths against the project root so workers run consistently
    if not Path(session_path).is_absolute():
        session_path = str(config.PROJECT_ROOT / session_path)
    return TelegramClient(session_path, int(env.telegram_api_id), env.telegram_api_hash)


def interactive_login() -> None:
    """One-time interactive login. Prompts for SMS code on stdin.

    Call via `agent telegram-login` before using the watch loop.
    """
    env = config.env()
    if not env.telegram_phone:
        raise RuntimeError("TELEGRAM_PHONE is not set in .env (format: +15551234567)")
    client = _client()
    client.start(phone=env.telegram_phone)  # prompts for SMS code interactively
    me = client.get_me()
    handle = getattr(me, "username", None) or getattr(me, "first_name", "unknown")
    session_file = client.session.filename
    client.disconnect()
    print(f"Logged in as @{handle}. Session saved to {session_file}.")


def fetch_recent_messages(*, limit: int = 30, write_to_db: bool = True) -> list[dict[str, Any]]:
    """Fetch the last N messages from each configured channel and emit signals.

    Returns the list of payloads emitted (for dry-run testing).
    """
    env = config.env()
    channels_raw = env.telegram_channels or ""
    channels = [c.strip() for c in channels_raw.split(",") if c.strip()]
    if not channels:
        return []

    emitted: list[dict[str, Any]] = []
    client = _client()
    try:
        client.connect()
        if not client.is_user_authorized():
            raise RuntimeError(
                "Telegram session is not authorized. Run 'agent telegram-login' once."
            )

        for channel in channels:
            try:
                msgs = list(client.iter_messages(channel, limit=limit))
            except Exception as e:
                print(f"[telegram] error fetching {channel}: {e}")
                continue

            for msg in msgs:
                if not isinstance(msg, Message):
                    continue
                text = msg.text or msg.message
                if not text:
                    continue

                entity = f"telegram:{channel}:{msg.id}"
                payload = {
                    "channel": channel,
                    "message_id": msg.id,
                    "text": text,
                    "date": msg.date.isoformat() if msg.date else None,
                    "url": f"https://t.me/{channel}/{msg.id}",
                    "views": getattr(msg, "views", None),
                    "forwards": getattr(msg, "forwards", None),
                }
                emitted.append(payload)

                if write_to_db:
                    observed_at = msg.date or datetime.now(timezone.utc)
                    if observed_at.tzinfo is None:
                        observed_at = observed_at.replace(tzinfo=timezone.utc)
                    db.insert_signal(
                        source="telegram_newswire",
                        signal_type="newsfeed",
                        payload=payload,
                        observed_at=observed_at,
                        entity=entity,
                        source_id=str(msg.id),
                    )
    finally:
        try:
            client.disconnect()
        except Exception:
            pass

    return emitted
