"""Pure event & recurrence expansion logic for UCL room timetables."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")

DAY_POSITIONS: Dict[str, int] = {
    "MONDAY": 1,
    "TUESDAY": 2,
    "WEDNESDAY": 3,
    "THURSDAY": 4,
    "FRIDAY": 5,
    "SATURDAY": 6,
    "SUNDAY": 7,
}


def london_wall_clock_to_utc(day: str, hhmm: str) -> datetime:
    """Convert a London wall-clock date and time string ("09:00") into a UTC datetime."""
    d = date.fromisoformat(day)
    hours, minutes = (int(p) for p in hhmm.split(":"))
    local_dt = datetime(d.year, d.month, d.day, hours, minutes, tzinfo=LONDON)
    return local_dt.astimezone(timezone.utc)


def parse_weeks(weeks_str: str) -> List[int]:
    """Parse week numbers from API format like 'wks 20-25, 27' into list of integers."""
    result: List[int] = []
    clean = weeks_str.lower().replace("wks", "").strip()
    for part in clean.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            try:
                start_w, end_w = (int(x.strip()) for x in part.split("-", 1))
                result.extend(range(start_w, end_w + 1))
            except ValueError:
                pass
        else:
            try:
                result.append(int(part))
            except ValueError:
                pass
    return sorted(list(set(result)))


def expand_event(
    event: Dict[str, Any],
    calendar_info: Dict[int, Dict[int, str]],
) -> List[Dict[str, Any]]:
    """Expand a raw CMIS timetable event into explicit dated occurrences.
    
    calendar_info maps: week_number -> {day_position -> 'YYYY-MM-DD'}
    """
    expanded: List[Dict[str, Any]] = []

    day_name = str(event.get("day", "")).upper()
    day_pos = DAY_POSITIONS.get(day_name)
    if not day_pos:
        return []

    start_time = str(event.get("start_time", ""))
    end_time = str(event.get("end_time", ""))
    if not (start_time and end_time):
        return []

    weeks = parse_weeks(str(event.get("weeks", "")))
    if not weeks:
        # If no explicit weeks specified, try single date if provided
        single_date = event.get("date")
        if single_date:
            try:
                start_dt = london_wall_clock_to_utc(single_date, start_time)
                end_dt = london_wall_clock_to_utc(single_date, end_time)
                expanded.append({
                    "start_at": start_dt,
                    "end_at": end_dt,
                    "module": event.get("module_name") or event.get("title") or "Event",
                    "description": event.get("description", ""),
                })
            except Exception:
                pass
        return expanded

    for week in weeks:
        week_days = calendar_info.get(week, {})
        date_str = week_days.get(day_pos)
        if not date_str:
            continue
        try:
            start_dt = london_wall_clock_to_utc(date_str, start_time)
            end_dt = london_wall_clock_to_utc(date_str, end_time)
            expanded.append({
                "week": week,
                "date": date_str,
                "start_at": start_dt,
                "end_at": end_dt,
                "title": event.get("title") or event.get("module_name") or "Event",
                "module_code": event.get("module_code", ""),
                "event_type": event.get("event_type", ""),
            })
        except Exception:
            continue

    return expanded
