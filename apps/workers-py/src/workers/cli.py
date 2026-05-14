"""Typer CLI entry point. Invoke via `agent <command>` after `pip install -e .`"""

from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import typer
from rich import print as rprint

from . import config
from .ingest import defillama, rwa_xyz, telegram_newswire
from .scoring import materiality
from .stories import builder
from .drafts import generator

app = typer.Typer(no_args_is_help=True, help="x-defi-agent CLI")


@app.command()
def migrate() -> None:
    """Apply the Postgres schema and seed default run_jobs (idempotent)."""
    from . import db
    schema_path = config.PROJECT_ROOT / "packages" / "db" / "schema.sql"
    rprint(f"[bold]Applying schema from {schema_path}[/bold]")
    db.apply_schema_file(str(schema_path))
    rprint("[green]Schema applied[/green]")
    inserted = db.seed_default_run_jobs()
    rprint(f"[green]Seeded run_jobs: {inserted} new, {len(db.DEFAULT_RUN_JOBS) - inserted} already present[/green]")


@app.command()
def ingest(
    source: str = typer.Option("defillama", help="Which source to poll: defillama | rwa_xyz | telegram"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print signals instead of writing to DB"),
) -> None:
    """Run one ingest cycle for the given source."""
    if source == "defillama":
        signals = defillama.ingest_protocol_tvl_deltas(write_to_db=not dry_run)
        rprint(f"[bold]DeFiLlama: {len(signals)} RWA TVL-delta signals[/bold]")
    elif source == "rwa_xyz":
        signals = rwa_xyz.ingest_top_assets(write_to_db=not dry_run)
        rprint(f"[bold]RWA.xyz: {len(signals)} signals (new deploys + AUM deltas)[/bold]")
    elif source == "telegram":
        signals = telegram_newswire.fetch_recent_messages(limit=30, write_to_db=not dry_run)
        rprint(f"[bold]Telegram: {len(signals)} newsfeed signals[/bold]")
    else:
        raise typer.BadParameter(f"Unknown source: {source}")

    for s in signals[:5]:
        rprint(s)
    if len(signals) > 5:
        rprint(f"[dim]...and {len(signals) - 5} more[/dim]")


@app.command(name="telegram-login")
def telegram_login() -> None:
    """One-time interactive login for the Telegram client.

    Run this once before the watch loop tries to fetch messages. It prompts for
    the SMS code Telegram sends to your phone, then writes a session file to
    data/telegram.session for non-interactive use.
    """
    telegram_newswire.interactive_login()


@app.command()
def score(limit: int = typer.Option(20, help="Max signals to score this run")) -> None:
    """Score unprocessed signals via Claude."""
    n = materiality.score_unprocessed(limit=limit)
    rprint(f"[green]Scored {n} signals[/green]")


@app.command(name="build-stories")
def build_stories(limit: int = typer.Option(20)) -> None:
    """Promote scored signals to stories."""
    created = builder.build_open_stories(limit=limit)
    rprint(f"[green]Created {len(created)} stories[/green]")
    for s in created[:3]:
        rprint(s)


@app.command()
def draft(
    story_id: str = typer.Option(None, help="Specific story id to draft. If omitted, drafts the most recent open story."),
    all_open: bool = typer.Option(False, "--all-open", help="Draft every open story instead of just the most recent one."),
) -> None:
    """Generate drafts for one or more stories.

    Drafts are persisted to the `drafts` table (status='pending') for the Excel
    dashboard to surface. A copy is also written to data/drafts/<story_id>.json
    for local inspection.
    """
    from . import db
    if all_open:
        counts = generator.draft_all_open()
        rprint(f"[green]Drafted {counts['drafts']} drafts across {counts['stories']} stories[/green]")
        return
    if story_id is None:
        with db.conn() as c:
            from psycopg.rows import dict_row
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "select id::text, headline, entities, key_data_points, format_recommendation "
                    "from stories where status = 'open' order by created_at desc limit 1"
                )
                row = cur.fetchone()
        if row is None:
            rprint("[yellow]No open stories. Run ingest + score + build-stories first.[/yellow]")
            return
        story_id = row["id"]
        brief = {
            "id": row["id"],
            "headline": row["headline"],
            "entities": row["entities"],
            "key_data_points": row["key_data_points"],
            "format_recommendation": row["format_recommendation"],
        }
    else:
        with db.conn() as c:
            from psycopg.rows import dict_row
            with c.cursor(row_factory=dict_row) as cur:
                cur.execute(
                    "select id::text, headline, entities, key_data_points, format_recommendation "
                    "from stories where id = %s",
                    (story_id,),
                )
                row = cur.fetchone()
        if row is None:
            raise typer.BadParameter(f"Story not found: {story_id}")
        brief = {
            "id": row["id"],
            "headline": row["headline"],
            "entities": row["entities"],
            "key_data_points": row["key_data_points"],
            "format_recommendation": row["format_recommendation"],
        }

    rprint(f"[bold]Drafting for story: {brief['headline']}[/bold]")
    drafts = generator.generate_for_story(brief)
    ids = generator.save_drafts_to_db(story_id, drafts)

    out_dir = config.PROJECT_ROOT / "data" / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{story_id}.json"
    with out_path.open("w") as f:
        json.dump({"story": brief, "drafts": drafts, "saved_ids": ids}, f, indent=2, default=str)
    rprint(f"[green]Wrote {out_path} and saved {len(ids)} drafts to DB[/green]")
    for d in drafts:
        rprint(f"\n[bold cyan]--- {d['format']} ---[/bold cyan]")
        rprint(d["body"])
        if d["ai_check_flags"]:
            rprint(f"[red]AI-tell flags: {d['ai_check_flags']}[/red]")


@app.command(name="test-e2e")
def test_e2e(source: str = typer.Option("defillama")) -> None:
    """End-to-end: ingest → score → build-stories → draft. Single-shot."""
    rprint("[bold]Step 1/4: Ingest[/bold]")
    if source == "defillama":
        signals = defillama.ingest_protocol_tvl_deltas(write_to_db=True)
        rprint(f"  {len(signals)} signals emitted")
    else:
        raise typer.BadParameter(f"Unknown source: {source}")

    rprint("[bold]Step 2/4: Score[/bold]")
    n = materiality.score_unprocessed(limit=20)
    rprint(f"  {n} signals scored")

    rprint("[bold]Step 3/4: Build stories[/bold]")
    stories = builder.build_open_stories(limit=20)
    rprint(f"  {len(stories)} stories created")

    if not stories:
        rprint("[yellow]No stories crossed materiality threshold today. End-to-end test stops here.[/yellow]")
        return

    rprint("[bold]Step 4/4: Draft (top story)[/bold]")
    top = stories[0]
    drafts = generator.generate_for_story(top)
    ids = generator.save_drafts_to_db(top["id"], drafts)
    out_dir = config.PROJECT_ROOT / "data" / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{top['id']}.json"
    with out_path.open("w") as f:
        json.dump({"story": top, "drafts": drafts, "saved_ids": ids}, f, indent=2, default=str)
    rprint(f"\n[green]End-to-end complete. Output: {out_path} ({len(ids)} drafts saved to DB)[/green]\n")
    for d in drafts:
        rprint(f"[bold cyan]--- {d['format']} ---[/bold cyan]")
        rprint(d["body"])
        if d["ai_check_flags"]:
            rprint(f"[red]AI-tell flags: {d['ai_check_flags']}[/red]")
        rprint("")


@app.command(name="post-due")
def post_due() -> None:
    """Drain the scheduled_posts queue: publish any draft whose post_at has passed."""
    from . import poster
    result = poster.drain_due()
    rprint(f"[green]Posted {result['posted']}, failed {result['failed']}, skipped {result['skipped']}[/green]")


@app.command(name="schedule-status")
def schedule_status() -> None:
    """Print the current posting schedule in local ET time. No Excel needed."""
    from . import db
    from zoneinfo import ZoneInfo
    et = ZoneInfo("America/New_York")
    with db.conn() as c, c.cursor() as cur:
        cur.execute("select status, count(*) from drafts group by status order by status")
        drafts_summary = cur.fetchall()
        cur.execute("select status, count(*) from scheduled_posts group by status order by status")
        sp_summary = cur.fetchall()
        cur.execute(
            "select sp.post_at, sp.status, left(d.body, 80) "
            "from scheduled_posts sp join drafts d on d.id = sp.draft_id "
            "where sp.status in ('queued', 'posting') "
            "order by sp.post_at asc limit 30"
        )
        upcoming = cur.fetchall()
    rprint("[bold]DRAFTS by status:[/bold]")
    for s, n in drafts_summary:
        rprint(f"  {s}: {n}")
    rprint("\n[bold]SCHEDULED_POSTS by status:[/bold]")
    for s, n in sp_summary:
        rprint(f"  {s}: {n}")
    rprint(f"\n[bold]UPCOMING ({len(upcoming)} queued/posting, sorted):[/bold]")
    for post_at, st, body in upcoming:
        if post_at.tzinfo is None:
            from datetime import timezone as tz_
            post_at = post_at.replace(tzinfo=tz_.utc)
        local = post_at.astimezone(et).strftime("%a %Y-%m-%d %I:%M %p ET")
        rprint(f"  {local}  [{st}]  {body}")


@app.command(name="reschedule-imminent")
def reschedule_imminent() -> None:
    """One-shot: re-time any queued post whose post_at is now-or-past into
    the next high-virality slots, respecting min-gap and daily cap.

    Use this after approving a batch of drafts with the old (immediate-fire)
    scheduling, to spread them across upcoming optimal windows instead.
    """
    from . import db, scheduler

    with db.conn() as c, c.cursor() as cur:
        cur.execute(
            "select id::text from scheduled_posts "
            "where status = 'queued' and post_at < now() + interval '5 minutes' "
            "order by post_at asc"
        )
        ids = [row[0] for row in cur.fetchall()]

    if not ids:
        rprint("[yellow]No immediate-fire posts found. Nothing to reschedule.[/yellow]")
        return

    rprint(f"[bold]Rescheduling {len(ids)} immediate-fire posts into future optimal slots...[/bold]")
    already_scheduled: list = []
    for sp_id in ids:
        slot = scheduler.next_optimal_slot(existing_utc=already_scheduled)
        with db.conn() as c, c.cursor() as cur:
            cur.execute(
                "update scheduled_posts set post_at = %s where id = %s::uuid",
                (slot, sp_id),
            )
            c.commit()
        already_scheduled.append(slot)
        local = slot.astimezone(scheduler.ET).strftime("%a %Y-%m-%d %I:%M %p ET")
        rprint(f"  → {local}")

    rprint(f"\n[green]Done. {len(ids)} posts now spread across optimal windows.[/green]")


@app.command(name="excel-export")
def excel_export() -> None:
    """Build agent_dashboard.xlsx from current DB state."""
    from .excel import dashboard
    path = dashboard.export_to_excel()
    rprint(f"[green]Exported dashboard to {path}[/green]")


@app.command(name="excel-apply")
def excel_apply() -> None:
    """Read agent_dashboard.xlsx and push user edits back to DB."""
    from .excel import dashboard
    counts = dashboard.apply_from_excel()
    if counts.get("skipped_locked"):
        rprint("[yellow]Excel file is currently locked (open in Excel). Skipping apply.[/yellow]")
        return
    rprint(f"[green]Applied edits: {counts}[/green]")


@app.command()
def watch(
    interval: int = typer.Option(60, help="Seconds between cycles"),
    once: bool = typer.Option(False, "--once", help="Run a single cycle and exit (for cron use)"),
) -> None:
    """Main control loop: read Excel, run due jobs, post due drafts, write Excel back.

    This is what you run on your Mac in a long-lived terminal (or under tmux/screen).
    Edit agent_dashboard.xlsx anytime; changes apply on the next cycle.
    """
    from .excel import dashboard
    from . import scheduler, poster

    rprint(f"[bold]Starting watch loop (interval={interval}s, once={once})[/bold]")
    while True:
        cycle_started = datetime.now(timezone.utc).isoformat(timespec="seconds")
        rprint(f"\n[dim]── cycle {cycle_started} ──[/dim]")

        # 1. Apply any user edits from Excel
        try:
            counts = dashboard.apply_from_excel()
            if counts.get("skipped_locked"):
                rprint("  [yellow]Excel locked, skipping apply this cycle[/yellow]")
            elif any(counts.values()):
                rprint(f"  Applied: {counts}")
        except Exception as e:
            rprint(f"  [red]apply_from_excel error: {e}[/red]")

        # 2. Run any due jobs
        try:
            due = scheduler.jobs_due()
            for job in due:
                rprint(f"  Running [{job['name']}]: {job['command']}")
                scheduler.mark_running(job["name"])
                success, output = scheduler.run_command(job["command"])
                scheduler.mark_complete(job["name"], success=success, error=None if success else output)
                if not success:
                    rprint(f"  [red]Job failed: {output[:300]}[/red]")
        except Exception as e:
            rprint(f"  [red]scheduler error: {e}[/red]")

        # 3. Drain due scheduled posts (separate from job loop so even if jobs fail,
        #    queued posts still go out)
        try:
            result = poster.drain_due()
            if result["posted"] or result["failed"]:
                rprint(f"  Poster: {result}")
        except Exception as e:
            rprint(f"  [red]poster error: {e}[/red]")

        # 4. Re-export Excel
        try:
            dashboard.export_to_excel()
        except PermissionError:
            rprint("  [yellow]Excel locked, skipping export this cycle[/yellow]")
        except Exception as e:
            rprint(f"  [red]export_to_excel error: {e}[/red]")

        if once:
            return
        time.sleep(interval)


if __name__ == "__main__":
    app()
