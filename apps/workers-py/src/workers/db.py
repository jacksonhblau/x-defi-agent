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


def _configure_connection(conn: psycopg.Connection) -> None:
    """Per-connection setup for Supabase Transaction Pooler compatibility.

    Two protections:
    1. Disable psycopg's auto-prepared statements (prevents future name collisions).
    2. DEALLOCATE ALL to wipe any prepared statements that survived from an
       earlier client on the same recycled physical connection.
    """
    conn.prepare_threshold = None
    try:
        with conn.cursor() as cur:
            cur.execute("deallocate all")
        conn.commit()
    except Exception:
        # If the connection is in a bad state, the next real query will surface it.
        try:
            conn.rollback()
        except Exception:
            pass


def pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        url = config.env().database_url
        if not url:
            raise RuntimeError("DATABASE_URL is not set in .env")
        _pool = ConnectionPool(
            conninfo=url,
            min_size=1,
            max_size=5,
            open=True,
            configure=_configure_connection,
        )
    return _pool


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    p = pool()
    with p.connection() as c:
        yield c


def make_dedup_hash(
    source: str,
    entity: str | None,
    signal_type: str,
    payload: dict[str, Any],
    source_id: str | None = None,
) -> str:
    """Stable hash for deduplicating signals.

    When the ingester provides a stable `source_id` (e.g. Telegram message_id,
    RWA.xyz asset_id, an X tweet_id), we hash (source, signal_type, source_id)
    — that uniquely identifies the underlying event without any volatile
    payload fields. This was the original intent.

    Previously this hashed the full payload, which broke for Telegram: each
    poll fetched updated `views` and `forwards` counts, producing a different
    hash for the same message every poll cycle (→ 3,500 duplicate rows for
    56 actual messages).

    When `source_id` is None we fall back to a stable subset of the payload
    that excludes known volatile keys.
    """
    if source_id:
        canonical = json.dumps(
            {"s": source, "t": signal_type, "sid": source_id},
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(canonical.encode()).hexdigest()

    # Fall back: strip known volatile keys from the payload before hashing.
    VOLATILE_KEYS = {"views", "forwards", "retrieved_at", "fetched_at", "as_of", "ts"}
    stable_payload = {k: v for k, v in (payload or {}).items() if k not in VOLATILE_KEYS}
    canonical = json.dumps(
        {"s": source, "e": entity or "", "t": signal_type, "p": stable_payload},
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
    dedup_hash = make_dedup_hash(source, entity, signal_type, payload, source_id=source_id)
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
    """Return signals where processed_at is null, NEWEST first.

    Newest-first matters for a news agent: stale news has zero engagement
    value, fresh news is what we want to surface. Older unscored signals
    naturally age out (cron keeps polling new ones; the queue drains forward).
    """
    with conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id::text, observed_at, source, source_id, entity, signal_type, payload
            from signals
            where processed_at is null
            order by observed_at desc
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


# Default seed for run_jobs. Stored in Python so we don't depend on SQL-statement
# ordering inside a migrate transaction. Idempotent via ON CONFLICT (name).
DEFAULT_RUN_JOBS = [
    # (name, description, command, cron, sort_order)
    ("ingest_defillama",  "Pull RWA-tagged protocols from DeFiLlama; emit TVL-delta signals",   "ingest --source defillama",   "*/10 * * * *", 10),
    ("ingest_rwa_xyz",    "Pull top tokenized assets from RWA.xyz API",                         "ingest --source rwa_xyz",     "*/15 * * * *", 11),
    ("ingest_telegram",   "Pull recent messages from @RWAxyzNewswire Telegram channel",         "ingest --source telegram",    "*/5 * * * *",  12),
    ("ingest_x_firehose", "Poll watchlist X accounts for new posts",                            "ingest --source x_firehose",  "*/2 * * * *",  13),
    ("ingest_alchemy",    "Watch onchain wallets and contract deploys",                         "ingest --source alchemy",     "*/5 * * * *",  14),
    ("score",             "Run materiality scorer over unprocessed signals",                    "score",                       "*/5 * * * *",  20),
    ("build_stories",     "Promote scored signals to stories",                                  "build-stories",               "*/10 * * * *", 30),
    ("draft",             "Generate drafts for open stories (all formats)",                     "draft --all-open",            "*/15 * * * *", 40),
    ("hot_take",          "Slow-day fallback: generate one non-obvious take per day",           "hot-take",                    "0 15 * * *",   50),
    ("weekly_recap",      "Friday digest: top RWA flows and movers this week",                  "recap --weekly",              "0 13 * * 5",   51),
    ("post_due",          "Drain scheduled_posts queue: publish anything past its post_at",     "post-due",                    "* * * * *",    60),
    ("engagement_24h",    "Capture impressions/likes/RTs at +24h on each post",                 "engagement --window 24h",     "*/30 * * * *", 70),
    ("engagement_7d",     "Capture impressions/likes/RTs at +7d on each post",                  "engagement --window 7d",      "0 */6 * * *",  71),
]


def seed_default_run_jobs() -> int:
    """Insert the default run_jobs if they don't already exist. Returns inserted count."""
    inserted = 0
    with conn() as c, c.cursor() as cur:
        for name, desc, cmd, cron, order in DEFAULT_RUN_JOBS:
            cur.execute(
                """
                insert into run_jobs (name, description, command, cron, sort_order)
                values (%s, %s, %s, %s, %s)
                on conflict (name) do update
                  set description = excluded.description,
                      command = excluded.command,
                      cron = coalesce(run_jobs.cron, excluded.cron),  -- preserve user cron edits
                      sort_order = excluded.sort_order
                returning (xmax = 0) as inserted
                """,
                (name, desc, cmd, cron, order),
            )
            row = cur.fetchone()
            if row and row[0]:
                inserted += 1
        c.commit()
    return inserted
