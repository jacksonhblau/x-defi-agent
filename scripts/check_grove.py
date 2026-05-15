"""Verify the Grove/Basin post is still queued and ready to fire, and show
what its effective body looks like (the body the poster will actually publish).
"""

from __future__ import annotations

from workers import db
from psycopg.rows import dict_row

GROVE_DRAFT_ID = "76c98abc-df67-4ec6-979f-7eed1521419c"


def main() -> None:
    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select
              sp.id          as sp_id,
              sp.status      as sp_status,
              sp.post_at,
              sp.attempts,
              sp.last_error,
              d.status       as draft_status,
              d.format,
              d.reviewed_at,
              coalesce(d.edited_body, d.body) as effective_body,
              d.body_json,
              (d.edited_body is not null) as has_edit
            from scheduled_posts sp
            join drafts d on d.id = sp.draft_id
            where sp.draft_id = %s::uuid
            order by sp.post_at desc
            """,
            (GROVE_DRAFT_ID,),
        )
        rows = cur.fetchall()

    if not rows:
        print("No scheduled_posts found for the Grove draft. This is a problem.")
        return

    print(f"Found {len(rows)} scheduled_post(s) for Grove draft:\n")
    for r in rows:
        print(f"  scheduled_post id: {r['sp_id']}")
        print(f"  sp.status:       {r['sp_status']}")
        print(f"  post_at:         {r['post_at']}")
        print(f"  attempts:        {r['attempts']}")
        print(f"  last_error:      {r['last_error']}")
        print(f"  draft.status:    {r['draft_status']}")
        print(f"  draft.format:    {r['format']}")
        print(f"  draft.reviewed_at: {r['reviewed_at']}")
        print(f"  has_edit:        {r['has_edit']}")
        body = r["effective_body"] or ""
        print(f"  effective_body ({len(body)} chars, full):")
        print("  " + "-" * 70)
        for line in body.splitlines() or [""]:
            print(f"    {line}")
        print("  " + "-" * 70)

        if r["format"] == "thread" and r["body_json"]:
            bj = r["body_json"]
            if isinstance(bj, list):
                print(f"\n  body_json: {len(bj)} tweets (this is what the poster ACTUALLY sends for threads):")
                for i, tweet in enumerate(bj, 1):
                    print(f"\n  --- tweet {i}/{len(bj)} ({len(tweet)} chars) ---")
                    for line in tweet.splitlines() or [""]:
                        print(f"    {line}")
            else:
                print(f"  body_json: not a list (type={type(bj).__name__})")
        print()


if __name__ == "__main__":
    main()
