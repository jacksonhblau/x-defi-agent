"""X poster — publishes approved drafts to X via API v2 (tweepy, OAuth 1.0a).

Drained by the `post_due` job in the watch loop. Pulls anything from
scheduled_posts where post_at <= now() and status = 'queued'.

For threads, posts each tweet in order with in_reply_to_tweet_id chaining.
For replies, posts with in_reply_to_tweet_id set to the target tweet.
For quote tweets, posts with quote_tweet_id set.

Records to the posts and engagement tables on success.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import tweepy
from psycopg.rows import dict_row

from . import config, db


_client: tweepy.Client | None = None


def client() -> tweepy.Client:
    global _client
    if _client is None:
        env = config.env()
        if not all([env.x_api_key, env.x_api_secret, env.x_access_token, env.x_access_secret]):
            raise RuntimeError("X credentials are not fully set in .env")
        _client = tweepy.Client(
            consumer_key=env.x_api_key,
            consumer_secret=env.x_api_secret,
            access_token=env.x_access_token,
            access_token_secret=env.x_access_secret,
            wait_on_rate_limit=True,
        )
    return _client


def _post_single(text: str, *, reply_to: str | None = None, quote_id: str | None = None) -> str:
    """Post one tweet. Returns the tweet id."""
    kwargs: dict[str, Any] = {"text": text}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to
    if quote_id:
        kwargs["quote_tweet_id"] = quote_id
    resp = client().create_tweet(**kwargs)
    if not resp or not resp.data:
        raise RuntimeError(f"X API returned no data: {resp}")
    return str(resp.data["id"])


def _post_thread(tweets: list[str]) -> list[str]:
    """Post a thread as a chain of replies. Returns all tweet ids in order."""
    ids: list[str] = []
    reply_to: str | None = None
    for t in tweets:
        tid = _post_single(t, reply_to=reply_to)
        ids.append(tid)
        reply_to = tid
    return ids


def drain_due() -> dict[str, int]:
    """Post any scheduled drafts whose post_at has passed. Returns counts."""
    posted = 0
    failed = 0
    skipped = 0

    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select sp.id::text as sp_id, sp.draft_id::text as draft_id, sp.attempts,
                   d.format, d.body, d.body_json, d.reply_to_tweet_id, d.quote_tweet_id,
                   coalesce(d.edited_body, d.body) as effective_body
            from scheduled_posts sp
            join drafts d on d.id = sp.draft_id
            where sp.status = 'queued' and sp.post_at <= now()
            order by sp.post_at asc
            limit 5
            """
        )
        due = cur.fetchall()

    for row in due:
        sp_id = row["sp_id"]
        draft_id = row["draft_id"]

        # Mark posting
        with db.conn() as c, c.cursor() as cur:
            cur.execute(
                "update scheduled_posts set status = 'posting', attempts = attempts + 1 where id = %s::uuid",
                (sp_id,),
            )
            c.commit()

        try:
            if row["format"] == "thread":
                tweets = row["body_json"] if isinstance(row["body_json"], list) else json.loads(row["body_json"])
                tweet_ids = _post_thread(tweets)
            elif row["format"] in ("single", "hot_take"):
                tweet_ids = [_post_single(row["effective_body"])]
            elif row["format"] == "reply":
                tweet_ids = [_post_single(row["effective_body"], reply_to=row["reply_to_tweet_id"])]
            elif row["format"] == "quote_tweet":
                tweet_ids = [_post_single(row["effective_body"], quote_id=row["quote_tweet_id"])]
            else:
                raise RuntimeError(f"Unknown draft format: {row['format']}")

            with db.conn() as c, c.cursor() as cur:
                cur.execute(
                    """
                    insert into posts (draft_id, scheduled_post_id, tweet_ids, root_tweet_id, format, body)
                    values (%s::uuid, %s::uuid, %s, %s, %s, %s)
                    """,
                    (draft_id, sp_id, tweet_ids, tweet_ids[0], row["format"], row["effective_body"]),
                )
                cur.execute(
                    "update scheduled_posts set status = 'posted' where id = %s::uuid",
                    (sp_id,),
                )
                cur.execute(
                    "update drafts set status = 'posted' where id = %s::uuid",
                    (draft_id,),
                )
                c.commit()
            posted += 1
        except Exception as e:
            with db.conn() as c, c.cursor() as cur:
                cur.execute(
                    "update scheduled_posts set status = 'failed', last_error = %s where id = %s::uuid",
                    (str(e)[:1000], sp_id),
                )
                c.commit()
            failed += 1

    return {"posted": posted, "failed": failed, "skipped": skipped}
