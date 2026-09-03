"""CLI commands for `suu rooms`."""

from __future__ import annotations

from typing import Optional
import click

from suu.retrieve.export import export_data


@click.group()
def rooms() -> None:
    """Find free study rooms and query UCL campus room timetables."""


@rooms.command("free")
@click.option("--building", default=None, help="Filter by building name (e.g. 'Student Centre', 'Cruciform').")
@click.option("--min-capacity", type=int, default=0, help="Minimum room capacity.")
@click.option("--csv", "as_csv", is_flag=True, help="Save as CSV file.")
@click.option("--xlsx", "as_xlsx", is_flag=True, help="Save as Excel (.xlsx) file.")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
@click.option("--sheets", "as_sheets", is_flag=True, help="Copy to clipboard in Google Sheets format.")
def free_rooms(
    building: Optional[str],
    min_capacity: int,
    as_csv: bool,
    as_xlsx: bool,
    as_json: bool,
    as_sheets: bool,
) -> None:
    """Find currently free study & meeting rooms on campus."""
    from suu.rooms.query import find_free_rooms
    click.echo("Searching UCL timetable API for free rooms...")
    results = find_free_rooms(building=building, min_capacity=min_capacity)
    fieldnames = ["name", "building", "capacity", "status"]
    export_data(
        rows=results,
        fieldnames=fieldnames,
        prefix="free_rooms",
        as_csv=as_csv,
        as_xlsx=as_xlsx,
        as_json=as_json,
        as_sheets=as_sheets,
    )


@rooms.command("query")
@click.argument("room_name")
@click.option("--date", "target_date", default=None, help="Filter by date (YYYY-MM-DD).")
@click.option("--json", "as_json", is_flag=True, help="Save as JSON file.")
def query_room(room_name: str, target_date: Optional[str], as_json: bool) -> None:
    """Query scheduled events for a room by name or code."""
    from suu.rooms.query import query_room_schedule
    data = query_room_schedule(room_name, target_date=target_date)
    click.echo(f"\nSchedule for {data['room_name']} ({data['building']}, Capacity {data['capacity']}):")
    click.echo("-" * 60)
    events = data.get("events", [])
    if not events:
        click.echo("No scheduled events found.")
        return
    for ev in events[:15]:
        title = ev.get("title") or ev.get("module_code") or "Class"
        dt_str = str(ev.get("start_at", ""))[:16].replace("T", " ")
        click.echo(f"  [{dt_str}] {title}")
    if len(events) > 15:
        click.echo(f"  ... and {len(events) - 15} more events.")


@rooms.command("list")
@click.option("--building", default=None, help="Filter by building name.")
def list_rooms_cmd(building: Optional[str]) -> None:
    """List known central UCL rooms and capacities."""
    from suu.rooms.query import list_rooms
    rms = list_rooms(building=building)
    click.echo(f"Known UCL rooms ({len(rms)}):")
    for r in rms:
        click.echo(f"  - {r['name']} ({r['building']}): Capacity {r['capacity']}")


@rooms.command("sync")
@click.option("--year", default=None, help="Academic year set (e.g. LIVE-25-26).")
def sync_rooms(year: Optional[str]) -> None:
    """Sync/sweep live room list from UCL Timetable API."""
    from suu.rooms.client import UclTimetableClient
    cl = UclTimetableClient()
    years = cl.get_live_years()
    target_year = year or (years[0] if years else "LIVE-25-26")
    click.echo(f"Connected to UCL Timetable API ({target_year}).")
    cal = cl.get_academic_calendar(target_year)
    click.echo(f"Loaded calendar ({len(cal)} weeks indexed).")
