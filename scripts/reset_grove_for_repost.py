"""Reset the Grove/Basin draft for a clean repost after manually deleting the
botched thread from X.

Steps, in one transaction:
1. Rebuild drafts.body_json from drafts.edited_body so the poster uses the
   reviewer's corrected text. Splits on blank lines (one tweet per chunk).
2. Delete the orphaned posts row (cascades to engagement rows) so the
   engagement tracker doesn't try to fetch metrics for a deleted tweet.
3. Delete the existing 'posted' scheduled_post.
4. Insert a fresh scheduled_post that fires in 15 minutes.
5. Flip drafts.status back to 'approved' so dashboards reflect reality.

Run only AFTER you've deleted the bad thread from X manually.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from workers import db


GROVE_DRAFT_ID = "76c98abc-df67-4ec6-979f-7eed1521419c"


def _split_thread(text: str) -> list[str]:
    """Split a thread body on one-or-more blank lines."""
    parts = re.split(r"\r?\n\s*\r?\n+", text)
    return [p.strip() for p in parts if p.strip()]


def main() -> None:
    now = datetime.now(timezone.utc)
    new_post_at = now + timedelta(minutes=15)

    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        # 1. Fetch current state.
        cur.execute(
            """
            select id, format, body, edited_body, body_json, status
            from drafts where id = %s::uuid
            """,
            (GROVE_DRAFT_ID,),
        )
        draft = cur.fetchone()
        if not draft:
            print("ERROR: Grove draft not found. Aborting.")
            return

        source_text = draft["edited_body"] or draft["body"]
        if not source_text:
            print("ERROR: draft has no edited_body and no body. Aborting.")
            return

        new_tweets = _split_thread(source_text)
        if not new_tweets:
            print("ERROR: edited_body produced zero tweets after splitting. Aborting.")
            return

        # Safety check: refuse to repost if the first tweet still starts with @.
        if new_tweets[0].lstrip().startswith("@"):
            print(
                "ERROR: first tweet of new body_json still starts with @. X will "
                "treat it as a reply. Edit the draft to remove the leading mention, "
                "then rerun this script. First-tweet preview: "
                f"{new_tweets[0][:80]!r}"
            )
            return

        print(f"Will rebuild body_json as {len(new_tweets)} tweets:")
        for i, t in enumerate(new_tweets, 1):
            preview = t.splitlines()[0] if t else ""
            print(f"  {i}/{len(new_tweets)} ({len(t)} chars): {preview[:80]}")

        # 2. Delete orphan posts row(s) (cascades engagement).
        cur.execute(
            "delete from posts where draft_id = %s::uuid returning id, root_tweet_id",
            (GROVE_DRAFT_ID,),
        )
        deleted_posts = cur.fetchall()
        print(f"\nDeleted {len(deleted_posts)} posts row(s).")
        for p in deleted_posts:
            print(f"  posts.id={p['id']} root_tweet_id={p['root_tweet_id']}")

        # 3. Delete all existing scheduled_posts for this draft.
        cur.execute(
            "delete from scheduled_posts where draft_id = %s::uuid returning id, status, post_at",
            (GROVE_DRAFT_ID,),
        )
        deleted_sp = cur.fetchall()
        print(f"\nDeleted {len(deleted_sp)} scheduled_posts row(s).")
        for s in deleted_sp:
            print(f"  sp.id={s['id']} status={s['status']} post_at={s['post_at']}")

        # 4. Insert fresh scheduled_post for +15 min.
        cur.execute(
            """
            insert into scheduled_posts (draft_id, post_at, status, attempts)
            values (%s::uuid, %s, 'queued', 0)
            returning id, post_at
            """,
            (GROVE_DRAFT_ID, new_post_at),
        )
        new_sp = cur.fetchone()
        print(f"\nInserted new scheduled_post:")
        print(f"  id={new_sp['id']} post_at={new_sp['post_at']}")

        # 5. Update draft: rebuild body_json, flip status back to approved.
        cur.execute(
            """
            update drafts
            set body_json = %s,
                status = 'approved'
            where id = %s::uuid
            """,
            (Jsonb(new_tweets), GROVE_DRAFT_ID),
        )
        print(f"\nUpdated draft: body_json rebuilt, status='approved'.")

        c.commit()
        print("\nCommitted. Watch logs and the dashboard for the repost.")


if __name__ == "__main__":
    main()
