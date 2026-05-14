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
from .ingest import defillama
from .scoring import materiality
from .stories import builder
from .drafts import generator

app = typer.Typer(no_args_is_help=True, help="x-defi-agent CLI")


@app.command()
def migrate() -> None:
    """Apply the Postgres schema (idempotent)."""
    from . import db
    schema_path = config.PROJECT_ROOT / "packages" / "db" / "schema.sql"
    rprint(f"[bold]Applying schema from {schema_path}[/bold]")
    db.apply_schema_file(str(schema_path))
    rprint("[green]Schema applied[/green]")


@app.command()
def ingest(
    source: str = typer.Option("defillama", help="Which source to poll"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print signals instead of writing to DB"),
) -> None:
    """Run one ingest cycle for the given source."""
    if source == "defillama":
        signals = defillama.ingest_protocol_tvl_deltas(write_to_db=not dry_run)
        rprint(f"[bold]DeFiLlama: {len(signals)} RWA TVL-delta signals[/bold]")
        for s in signals[:5]:
            rprint(s)
        if len(signals) > 5:
            rprint(f"[dim]...and {len(signals) - 5} more[/dim]")
    else:
        raise typer.BadParameter(f"Unknown source: {source}")


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
) -> None:
    """Generate drafts for a story. Writes results to data/drafts/<story_id>.json."""
    from . import db
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

    out_dir = config.PROJECT_ROOT / "data" / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{story_id}.json"
    with out_path.open("w") as f:
        json.dump({"story": brief, "drafts": drafts}, f, indent=2, default=str)
    rprint(f"[green]Wrote {out_path}[/green]")
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
    out_dir = config.PROJECT_ROOT / "data" / "drafts"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{top['id']}.json"
    with out_path.open("w") as f:
        json.dump({"story": top, "drafts": drafts}, f, indent=2, default=str)
    rprint(f"\n[green]End-to-end complete. Output: {out_path}[/green]\n")
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
