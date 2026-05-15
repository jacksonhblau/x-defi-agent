"""One-shot: bump the Grove/Basin queued post to fire in 15 minutes, and
verify no test-tweet rows leaked into the posts table. Run on Fly:

    fly ssh sftp shell --app x-defi-agent
    put scripts/bump_grove.py /app/bump_grove.py
    exit
    fly ssh console --app x-defi-agent -C "python /app/bump_grove.py"
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from workers import db

GROVE_DRAFT_ID = "76c98abc-df67-4ec6-979f-7eed1521419c"
TEST_TWEET_ID = "2055115739011379692"


def main() -> None:
    new_time = datetime.now(timezone.utc) + timedelta(minutes=15)

    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            update scheduled_posts
            set post_at = %s, attempts = 0, last_error = null
            where draft_id = %s::uuid and status = 'queued'
            returning id, post_at
            """,
            (new_time, GROVE_DRAFT_ID),
        )
        bumped = cur.fetchall()
        print(f"Bumped {len(bumped)} Grove row(s). New post_at:")
        for row in bumped:
            print(" ", row)

        cur.execute(
            """
            select id, root_tweet_id, body
            from posts
            where body like 'agent-auth-test%%'
               or body like 'rotation-verify%%'
               or root_tweet_id = %s
            """,
            (TEST_TWEET_ID,),
        )
        leaks = cur.fetchall()
        if leaks:
            print(f"\n!!! Found {len(leaks)} test-tweet row(s) in posts. Deleting:")
            for row in leaks:
                print(" ", row)
            cur.execute(
                """
                delete from posts
                where body like 'agent-auth-test%%'
                   or body like 'rotation-verify%%'
                   or root_tweet_id = %s
                """,
                (TEST_TWEET_ID,),
            )
        else:
            print("\nposts table is clean — no test tweets present.")

        c.commit()


if __name__ == "__main__":
    main()
