"""Scheduler — evaluates run_jobs.cron AND picks high-virality slots for posts.

Used by the `agent watch` loop (job firing) and by dashboard.apply_from_excel
(post slot picking when the user approves a draft with no specific time).
"""

from __future__ import annotations

import shlex
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from croniter import croniter
from psycopg.rows import dict_row

from . import db


# =============================================================================
# Auto-scheduling: pick high-virality posting slots
# =============================================================================

ET = ZoneInfo("America/New_York")

# Preferred posting windows in LOCAL ET, ordered by historical engagement for
# finance/crypto content. Each is (start_hour, end_hour), half-open.
PREFERRED_WINDOWS_ET: list[tuple[int, int]] = [
    (9, 10),    # 9-10am ET — US wake-up + market open
    (12, 13),   # 12-1pm ET — lunch scroll
    (17, 18),   # 5-6pm ET — commute home
    (20, 21),   # 8-9pm ET — evening, catches Asia early
]

MIN_GAP_MINUTES = 75            # min minutes between any two posts
DAILY_CAP_WEEKDAY = 8           # max posts on Mon-Fri (ET)
DAILY_CAP_WEEKEND = 4           # max posts on Sat-Sun


def _in_preferred_window(dt_et: datetime) -> bool:
    return any(start <= dt_et.hour < end for (start, end) in PREFERRED_WINDOWS_ET)


def _daily_cap_for(dt_et: datetime) -> int:
    return DAILY_CAP_WEEKEND if dt_et.weekday() >= 5 else DAILY_CAP_WEEKDAY


def next_optimal_slot(
    *,
    now_utc: datetime | None = None,
    existing_utc: list[datetime] | None = None,
    max_lookahead_days: int = 7,
) -> datetime:
    """Find the next high-virality posting slot in UTC.

    Constraints applied in order:
      1. Must land inside a PREFERRED_WINDOWS_ET window (ET-localized hour).
      2. Must be at least MIN_GAP_MINUTES from any time in existing_utc.
      3. Must not push the ET-day's count past the daily cap (weekday/weekend aware).
      4. Must be at least 15 minutes in the future.

    The search proceeds in 15-minute increments. If nothing fits within the
    lookahead window (very unusual), falls back to "first preferred slot
    tomorrow morning" so we never block forever.
    """
    now_utc = now_utc or datetime.now(timezone.utc)
    existing_utc = existing_utc or []
    # Normalize to UTC-aware
    existing_utc = [
        (t if t.tzinfo else t.replace(tzinfo=timezone.utc)) for t in existing_utc
    ]

    # Snap candidate to the next quarter-hour at least 15 min in the future
    candidate = now_utc + timedelta(minutes=15)
    candidate = candidate.replace(second=0, microsecond=0)
    minute_floor = (candidate.minute // 15) * 15
    candidate = candidate.replace(minute=minute_floor)

    steps = max_lookahead_days * 24 * 4   # 15-minute slots
    for _ in range(steps):
        candidate_et = candidate.astimezone(ET)

        if not _in_preferred_window(candidate_et):
            candidate += timedelta(minutes=15)
            continue

        # Min gap check against all existing scheduled times
        too_close = any(
            abs((candidate - t).total_seconds()) < MIN_GAP_MINUTES * 60
            for t in existing_utc
        )
        if too_close:
            candidate += timedelta(minutes=15)
            continue

        # Daily cap check (by ET calendar day)
        candidate_day = candidate_et.date()
        same_day_count = sum(
            1 for t in existing_utc if t.astimezone(ET).date() == candidate_day
        )
        if same_day_count >= _daily_cap_for(candidate_et):
            # Skip to start of next ET day (12:01am ET → next preferred window)
            next_day_et = (candidate_et + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            candidate = next_day_et.astimezone(timezone.utc)
            continue

        return candidate

    # Fallback: tomorrow 9am ET
    tomorrow_et = (now_utc.astimezone(ET) + timedelta(days=1)).replace(
        hour=9, minute=0, second=0, microsecond=0
    )
    return tomorrow_et.astimezone(timezone.utc)


def fetch_existing_scheduled() -> list[datetime]:
    """Return all currently-queued or posting times. Used to constrain new picks."""
    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            "select post_at from scheduled_posts where status in ('queued', 'posting')"
        )
        return [row[0] for row in cur.fetchall()]


# =============================================================================
# Job scheduling: cron-based run_jobs evaluation (existing behavior)
# =============================================================================



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
