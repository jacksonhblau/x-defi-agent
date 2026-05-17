"""X poster — publishes approved drafts to X via API v2 (tweepy, OAuth 1.0a).

Drained by the `post_due` job in the watch loop. Pulls anything from
scheduled_posts where post_at <= now() and status = 'queued'.

For threads, posts each tweet in order with in_reply_to_tweet_id chaining.
For replies, posts with in_reply_to_tweet_id set to the target tweet.
For quote tweets, posts with quote_tweet_id set.

Media: ready media_assets rows for the draft are uploaded to X via the v1.1
media/upload endpoint (the only one X exposes for image upload), then
attached to the FIRST tweet only (singles, thread tweet 1, reply, quote)
via the v2 create_tweet media_ids param.

Records to the posts and engagement tables on success.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

import httpx
import tweepy
from psycopg.rows import dict_row

from . import config, db


log = logging.getLogger(__name__)

# Mirrors scheduler.MIN_GAP_MINUTES. Enforced in drain_due() so that catching
# up a backlog (e.g., after a watch-loop outage) cannot fire multiple posts
# back-to-back and tank engagement.
MIN_GAP_MINUTES = 75

_client: tweepy.Client | None = None
_api_v1: tweepy.API | None = None


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


def api_v1() -> tweepy.API:
    """Tweepy v1.1 API client. Required for media/upload — X has not exposed
    image upload via v2 yet, so we use OAuth 1.0a against v1.1."""
    global _api_v1
    if _api_v1 is None:
        env = config.env()
        auth = tweepy.OAuth1UserHandler(
            env.x_api_key, env.x_api_secret,
            env.x_access_token, env.x_access_secret,
        )
        _api_v1 = tweepy.API(auth)
    return _api_v1


def _upload_media_from_url(url: str) -> str | None:
    """Download an image from `url` and upload to X. Returns media_id_string,
    or None on any failure (so the post still goes out without media rather
    than blocking publication entirely).
    """
    if not url or not isinstance(url, str):
        return None
    if not (url.startswith("http://") or url.startswith("https://")):
        # Local path or unknown scheme — try direct upload if the file exists,
        # otherwise skip.
        if os.path.isfile(url):
            try:
                m = api_v1().media_upload(filename=url)
                return getattr(m, "media_id_string", None) or str(getattr(m, "media_id", "")) or None
            except Exception as e:  # noqa: BLE001
                log.warning("media_upload local-path failed for %s: %s", url, e)
                return None
        return None

    # Download to a temp file, upload, clean up.
    tmp_path: str | None = None
    try:
        suffix = os.path.splitext(urlparse(url).path)[1] or ".png"
        with httpx.stream("GET", url, timeout=30.0, follow_redirects=True) as r:
            r.raise_for_status()
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False, prefix="x_media_") as f:
                tmp_path = f.name
                for chunk in r.iter_bytes(chunk_size=65536):
                    f.write(chunk)
        m = api_v1().media_upload(filename=tmp_path)
        return getattr(m, "media_id_string", None) or str(getattr(m, "media_id", "")) or None
    except Exception as e:  # noqa: BLE001
        log.warning("media_upload from url failed for %s: %s", url, e)
        return None
    finally:
        if tmp_path and os.path.isfile(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _fetch_media_urls_for_draft(draft_id: str, max_images: int = 4) -> list[str]:
    """Return up to `max_images` ready media storage_urls for this draft.
    X allows up to 4 images per tweet.
    """
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            select storage_url
            from media_assets
            where draft_id = %s::uuid
              and status = 'ready'
              and storage_url is not null
              and kind in ('image', 'still')
            order by created_at asc
            limit %s
            """,
            (draft_id, max_images),
        )
        return [r[0] for r in cur.fetchall() if r[0]]


def _post_single(
    text: str,
    *,
    reply_to: str | None = None,
    quote_id: str | None = None,
    media_ids: list[str] | None = None,
) -> str:
    """Post one tweet. Returns the tweet id."""
    kwargs: dict[str, Any] = {"text": text}
    if reply_to:
        kwargs["in_reply_to_tweet_id"] = reply_to
    if quote_id:
        kwargs["quote_tweet_id"] = quote_id
    if media_ids:
        kwargs["media_ids"] = media_ids
    resp = client().create_tweet(**kwargs)
    if not resp or not resp.data:
        raise RuntimeError(f"X API returned no data: {resp}")
    return str(resp.data["id"])


def _assert_no_leading_mention(text: str) -> None:
    """Refuse to post tweets whose first non-space character is @. X classifies
    such tweets as replies to the mentioned account and hides them from the
    main feed (reach killer). The voice rules block this upstream, but we
    double-check here so a botched edit can't slip through.
    """
    stripped = text.lstrip()
    if stripped.startswith("@"):
        raise RuntimeError(
            f"Refusing to post: tweet starts with @-mention which X treats as a "
            f"reply. Edit the draft to move the mention later in the line. "
            f"Offending text: {stripped[:80]!r}"
        )


def _post_thread(tweets: list[str], *, media_ids: list[str] | None = None) -> list[str]:
    """Post a thread as a chain of replies. Returns all tweet ids in order.

    Media attaches to the FIRST tweet only — subsequent thread tweets are
    text-only replies. This matches X's convention for thread hero plates.
    """
    if not tweets:
        raise RuntimeError("Refusing to post: thread has zero tweets")
    # Only the FIRST tweet of a thread must not start with @ — subsequent
    # tweets in the chain are already replies (to the previous tweet), so
    # leading @-mentions there are fine.
    _assert_no_leading_mention(tweets[0])
    ids: list[str] = []
    reply_to: str | None = None
    for i, t in enumerate(tweets):
        # Media on tweet 1 only.
        per_tweet_media = media_ids if i == 0 else None
        tid = _post_single(t, reply_to=reply_to, media_ids=per_tweet_media)
        ids.append(tid)
        reply_to = tid
    return ids


def drain_due() -> dict[str, int]:
    """Post any scheduled drafts whose post_at has passed. Returns counts.

    Engagement-aware: posts at most ONE draft per call, and only if at least
    MIN_GAP_MINUTES have elapsed since the most recent successful post. This
    prevents back-to-back firing when several scheduled rows have gone
    overdue together (e.g., after a watch-loop outage), which X otherwise
    reads as spam and suppresses distribution on.
    """
    posted = 0
    failed = 0
    skipped = 0

    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        # Engagement gap guard: if the last successful post was within
        # MIN_GAP_MINUTES, skip this cycle. The next cycle (60s later) will
        # re-check; eventually the gap clears and the oldest queued row goes.
        cur.execute("select max(posted_at) as last_posted from posts")
        gap_row = cur.fetchone()
        last_posted = gap_row["last_posted"] if gap_row else None
        if last_posted is not None:
            now = datetime.now(timezone.utc)
            if last_posted.tzinfo is None:
                last_posted = last_posted.replace(tzinfo=timezone.utc)
            elapsed_s = (now - last_posted).total_seconds()
            if elapsed_s < MIN_GAP_MINUTES * 60:
                return {"posted": 0, "failed": 0, "skipped": 1}

        # Limit 1, not 5: we only ever post a single draft per drain cycle.
        # Anything else that's overdue waits until the gap above clears.
        cur.execute(
            """
            select sp.id::text as sp_id, sp.draft_id::text as draft_id, sp.attempts,
                   d.format, d.body, d.body_json, d.reply_to_tweet_id, d.quote_tweet_id,
                   coalesce(d.edited_body, d.body) as effective_body
            from scheduled_posts sp
            join drafts d on d.id = sp.draft_id
            where sp.status = 'queued' and sp.post_at <= now()
            order by sp.post_at asc
            limit 1
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
            # Fetch + upload any ready media for this draft. If uploads fail
            # we proceed without media rather than blocking publication.
            media_urls = _fetch_media_urls_for_draft(draft_id)
            media_ids: list[str] = []
            for url in media_urls:
                mid = _upload_media_from_url(url)
                if mid:
                    media_ids.append(mid)

            if row["format"] == "thread":
                tweets = row["body_json"] if isinstance(row["body_json"], list) else json.loads(row["body_json"])
                tweet_ids = _post_thread(tweets, media_ids=media_ids or None)
            elif row["format"] in ("single", "hot_take"):
                tweet_ids = [_post_single(row["effective_body"], media_ids=media_ids or None)]
            elif row["format"] == "reply":
                tweet_ids = [_post_single(row["effective_body"], reply_to=row["reply_to_tweet_id"], media_ids=media_ids or None)]
            elif row["format"] == "quote_tweet":
                tweet_ids = [_post_single(row["effective_body"], quote_id=row["quote_tweet_id"], media_ids=media_ids or None)]
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
