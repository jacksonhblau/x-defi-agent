"""Postgres connection + helpers. Uses psycopg3 with a thread-safe pool."""

from __future__ import annotations

import atexit
import hashlib
import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from . import config


_pool: ConnectionPool | None = None


def _close_pool_on_exit() -> None:
    """Close the pool before Python finalization so the worker thread can join cleanly.

    Without this, Python 3.14 raises a noisy PythonFinalizationError from
    psycopg_pool's __del__ during interpreter shutdown.
    """
    global _pool
    if _pool is not None:
        try:
            _pool.close(timeout=2.0)
        except Exception:
            pass
        _pool = None


atexit.register(_close_pool_on_exit)


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = config.env().database_url
        if not url:
            raise RuntimeError("DATABASE_URL is not set in .env")
        _pool = ConnectionPool(conninfo=url, min_size=1, max_size=5, open=True)
    return _pool


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    p = pool()
    with p.connection() as c:
        yield c


def make_dedup_hash(source: str, entity: str | None, signal_type: str, payload: dict[str, Any]) -> str:
    """Stable hash for deduplicating signals.

    We hash a canonical JSON serialization of (source, entity, signal_type, payload)
    so the same event from the same source produces the same hash regardless of
    ingest time.
    """
    canonical = json.dumps(
        {"s": source, "e": entity or "", "t": signal_type, "p": payload},
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def insert_signal(
    *,
    source: str,
    signal_type: str,
    payload: dict[str, Any],
    observed_at: datetime,
    entity: str | None = None,
    source_id: str | None = None,
) -> str | None:
    """Insert a signal. Returns the row id, or None if it was a duplicate."""
    dedup_hash = make_dedup_hash(source, entity, signal_type, payload)
    with conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            insert into signals (observed_at, source, source_id, entity, signal_type, payload, dedup_hash)
            values (%s, %s, %s, %s, %s, %s::jsonb, %s)
            on conflict (dedup_hash) do nothing
            returning id::text
            """,
            (observed_at, source, source_id, entity, signal_type, json.dumps(payload), dedup_hash),
        )
        row = cur.fetchone()
        c.commit()
        return row["id"] if row else None


def fetch_unprocessed_signals(limit: int = 50) -> list[dict[str, Any]]:
    """Return signals where processed_at is null, oldest first."""
    with conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id::text, observed_at, source, source_id, entity, signal_type, payload
            from signals
            where processed_at is null
            order by observed_at asc
            limit %s
            """,
            (limit,),
        )
        return cur.fetchall()


def mark_signal_scored(signal_id: str, *, materiality: int, novelty: int, notes: str = "") -> None:
    with conn() as c, c.cursor() as cur:
        cur.execute(
            """
            update signals
            set processed_at = now(),
                materiality_score = %s,
                novelty_score = %s,
                notes = %s
            where id = %s
            """,
            (materiality, novelty, notes, signal_id),
        )
        c.commit()


def apply_schema_file(schema_path: str) -> None:
    """Run a SQL file against the database. Used by the migrate command."""
    with open(schema_path) as f:
        sql = f.read()
    with conn() as c, c.cursor() as cur:
        cur.execute(sql)
        c.commit()
