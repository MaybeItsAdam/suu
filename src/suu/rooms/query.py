"""High-level room availability and schedule query functions."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import click

from suu.rooms.client import UclTimetableClient
from suu.rooms.expansion import DAY_POSITIONS, expand_event


# Sample central campus building mappings
KNOWN_ROOMS = [
    {"site_id": "005", "room_id": "B104", "name": "Student Centre B104", "building": "Student Centre", "capacity": 24},
    {"site_id": "005", "room_id": "B105", "name": "Student Centre B105", "building": "Student Centre", "capacity": 30},
    {"site_id": "005", "room_id": "B202", "name": "Student Centre B202", "building": "Student Centre", "capacity": 16},
    {"site_id": "012", "room_id": "XLG1", "name": "Christopher Ingold XLG1", "building": "Christopher Ingold", "capacity": 120},
    {"site_id": "012", "room_id": "G21", "name": "Christopher Ingold G21", "building": "Christopher Ingold", "capacity": 45},
    {"site_id": "030", "room_id": "LT1", "name": "Cruciform LT1", "building": "Cruciform", "capacity": 300},
    {"site_id": "030", "room_id": "B101", "name": "Cruciform B101", "building": "Cruciform", "capacity": 40},
    {"site_id": "088", "room_id": "G01", "name": "Bloomsbury Theatre Studio", "building": "Bloomsbury", "capacity": 80},
]


def list_rooms(building: Optional[str] = None) -> List[Dict[str, Any]]:
    """List known UCL rooms, optionally filtered by building name."""
    if not building:
        return KNOWN_ROOMS
    b_lower = building.lower()
    return [r for r in KNOWN_ROOMS if b_lower in r["building"].lower() or b_lower in r["name"].lower()]


def find_free_rooms(
    building: Optional[str] = None,
    min_capacity: int = 0,
    target_time: Optional[datetime] = None,
    client: Optional[UclTimetableClient] = None,
) -> List[Dict[str, Any]]:
    """Find currently free rooms on campus at target_time (defaults to now)."""
    check_dt = target_time or datetime.now(timezone.utc)
    cl = client or UclTimetableClient()

    candidate_rooms = list_rooms(building)
    if min_capacity > 0:
        candidate_rooms = [r for r in candidate_rooms if r.get("capacity", 0) >= min_capacity]

    # Get live year and calendar
    years = cl.get_live_years()
    live_year = years[0] if years else "LIVE-25-26"
    cal = cl.get_academic_calendar(live_year)

    free_rooms: List[Dict[str, Any]] = []

    for rm in candidate_rooms:
        site_id = rm["site_id"]
        room_id = rm["room_id"]
        loc_data = cl.get_location_events(live_year, site_id, room_id)
        raw_events = loc_data.get("events", []) if isinstance(loc_data, dict) else []

        is_occupied = False
        occupied_by = ""

        for ev in raw_events:
            occurrences = expand_event(ev, cal)
            for occ in occurrences:
                st = occ.get("start_at")
                et = occ.get("end_at")
                if st and et and st <= check_dt <= et:
                    is_occupied = True
                    occupied_by = occ.get("title") or "Scheduled Class / Event"
                    break
            if is_occupied:
                break

        if not is_occupied:
            free_rooms.append(
                {
                    "name": rm["name"],
                    "building": rm["building"],
                    "capacity": rm["capacity"],
                    "site_id": site_id,
                    "room_id": room_id,
                    "status": "Available",
                }
            )

    return free_rooms


def query_room_schedule(
    room_query: str,
    target_date: Optional[str] = None,
    client: Optional[UclTimetableClient] = None,
) -> Dict[str, Any]:
    """Query daily/weekly event schedule for a room by name or code."""
    cl = client or UclTimetableClient()
    matches = list_rooms(room_query)
    if not matches:
        # Fallback to direct match if possible
        rm_info = {"site_id": "005", "room_id": room_query, "name": room_query, "building": "Unknown", "capacity": 0}
    else:
        rm_info = matches[0]

    years = cl.get_live_years()
    live_year = years[0] if years else "LIVE-25-26"
    cal = cl.get_academic_calendar(live_year)

    loc_data = cl.get_location_events(live_year, rm_info["site_id"], rm_info["room_id"])
    raw_events = loc_data.get("events", []) if isinstance(loc_data, dict) else []

    all_occurrences: List[Dict[str, Any]] = []
    for ev in raw_events:
        occs = expand_event(ev, cal)
        for occ in occs:
            if target_date and occ.get("date") != target_date:
                continue
            all_occurrences.append(occ)

    all_occurrences.sort(key=lambda x: str(x.get("start_at", "")))

    return {
        "room_name": rm_info["name"],
        "building": rm_info["building"],
        "capacity": rm_info["capacity"],
        "events": all_occurrences,
    }
