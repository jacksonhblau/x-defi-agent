"""Two-in-one diagnostic + fix:

1. Disable run_jobs whose `command` doesn't map to an actual CLI subcommand
   (hot-take and recap were planned but never implemented). Disabled jobs
   stay in the table for future re-enable; they just won't auto-fire.

2. Run rwa_xyz.ingest_top_assets directly, with full traceback printed,
   so we can see WHY it's blowing up.
"""

from __future__ import annotations

import traceback


GHOST_COMMANDS = (
    "hot-take",
    "recap --weekly",
)


def fix_ghost_jobs() -> None:
    from workers import db

    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            update run_jobs
            set enabled = false,
                run_now = false,
                last_error = 'Disabled by ops: CLI command not yet implemented. Re-enable when the corresponding subcommand exists in workers.cli.'
            where command = any(%s)
            returning name, command
            """,
            (list(GHOST_COMMANDS),),
        )
        rows = cur.fetchall()
        c.commit()
        print(f"Disabled {len(rows)} ghost-command job(s):")
        for r in rows:
            print(" ", r)


def diagnose_rwa() -> None:
    print("\n=== Running rwa_xyz.ingest_top_assets directly ===")
    try:
        from workers.ingest import rwa_xyz
        signals = rwa_xyz.ingest_top_assets(write_to_db=False)
        print(f"OK: produced {len(signals)} signals (dry-run, nothing written)")
        for s in signals[:3]:
            print(" ", s)
    except Exception:
        print("\n--- FULL TRACEBACK ---")
        traceback.print_exc()


if __name__ == "__main__":
    fix_ghost_jobs()
    diagnose_rwa()
