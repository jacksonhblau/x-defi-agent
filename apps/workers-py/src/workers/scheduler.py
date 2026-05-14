"""Scheduler — evaluates run_jobs.cron and decides what to run when.

Used by the `agent watch` loop.
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any

from croniter import croniter
from psycopg.rows import dict_row

from . import db


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _compute_next_run(cron_expr: str, base: datetime | None = None) -> datetime | None:
    base = base or _now_utc()
    try:
        it = croniter(cron_expr, base)
        return it.get_next(datetime)
    except Exception:
        return None


def update_next_run(name: str) -> None:
    with db.conn() as c, c.cursor() as cur:
        cur.execute("select cron from run_jobs where name = %s", (name,))
        row = cur.fetchone()
        if not row or not row[0]:
            return
        next_run = _compute_next_run(row[0])
        cur.execute(
            "update run_jobs set next_run_at = %s where name = %s",
            (next_run, name),
        )
        c.commit()


def jobs_due() -> list[dict[str, Any]]:
    """Return enabled jobs that should run right now: either run_now=true or cron is due."""
    now = _now_utc()
    with db.conn() as c, c.cursor(row_factory=dict_row) as cur:
        cur.execute(
            """
            select id::text, name, command, cron, run_now, last_run_at, next_run_at
            from run_jobs
            where enabled
              and (run_now = true
                   or next_run_at is null
                   or next_run_at <= %s)
            order by sort_order asc
            """,
            (now,),
        )
        rows = cur.fetchall()

    due: list[dict[str, Any]] = []
    for r in rows:
        if r["run_now"]:
            due.append(r)
            continue
        # If next_run_at is null, compute it; only fire if cron predicts a time at or before now.
        if r["cron"]:
            nxt = r["next_run_at"]
            if nxt is None:
                # Compute from last_run_at, or from a minute ago if never run.
                base = r["last_run_at"] or (now.replace(microsecond=0))
                # We want: is there a cron tick in [base, now]?
                try:
                    it = croniter(r["cron"], base)
                    candidate = it.get_next(datetime)
                except Exception:
                    continue
                if candidate <= now:
                    due.append(r)
            elif nxt <= now:
                due.append(r)
    return due


def mark_running(name: str) -> None:
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            "update run_jobs set last_status = 'running' where name = %s",
            (name,),
        )
        c.commit()


def mark_complete(name: str, *, success: bool, error: str | None = None) -> None:
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            """
            update run_jobs set
                last_run_at = now(),
                last_status = %s,
                last_error = %s,
                run_now = false,
                next_run_at = case when cron is not null then %s else null end
            where name = %s
            """,
            (
                "ok" if success else "error",
                None if success else (error or "")[:1000],
                _compute_next_run((_fetch_cron(name) or "")),
                name,
            ),
        )
        c.commit()


def _fetch_cron(name: str) -> str | None:
    with db.conn() as c, c.cursor() as cur:
        cur.execute("select cron from run_jobs where name = %s", (name,))
        row = cur.fetchone()
        return row[0] if row else None


def run_command(command: str) -> tuple[bool, str]:
    """Invoke an agent CLI command as a subprocess. Returns (success, output)."""
    argv = ["python", "-m", "workers.cli"] + shlex.split(command)
    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        success = proc.returncode == 0
        output = (proc.stdout + "\n" + proc.stderr).strip()
        return success, output
    except subprocess.TimeoutExpired:
        return False, "Command timed out after 600s"
    except Exception as e:
        return False, str(e)
