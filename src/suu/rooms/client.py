"""Client for UCL's online-timetable API (https://timetable.mesh.ucl.ac.uk)."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple
import requests

BASE_URL = "https://timetable.mesh.ucl.ac.uk/online-timetable-api-proxy/v0.1"
USER_AGENT = "AdamsCampusToolbox/1.0 (UCL student tools; +https://adamscampustoolbox.org.uk)"
DEFAULT_WORKERS = 4
MODULE_BATCH_SIZE = 60
MODULE_PAGE_SIZE = 200
REQUEST_TIMEOUT = 30
MAX_ATTEMPTS = 3


class UclTimetableError(RuntimeError):
    """Network or API error from the UCL timetable endpoint."""


class UclTimetableClient:
    """Public backend client for UCL CMIS timetable API."""

    def __init__(self, session: Optional[requests.Session] = None):
        self._session = session or requests.Session()
        self._session.headers.update({"User-Agent": USER_AGENT})

    def _get(self, path: str, params: Optional[dict] = None) -> Any:
        url = f"{BASE_URL}/{path.lstrip('/')}"
        last_exc: Optional[Exception] = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                res = self._session.get(url, params=params, timeout=REQUEST_TIMEOUT)
                if res.status_code == 404:
                    return None
                res.raise_for_status()
                return res.json()
            except Exception as e:
                last_exc = e
                if attempt < MAX_ATTEMPTS:
                    time.sleep(0.5 * attempt)
        raise UclTimetableError(f"GET {url} failed after {MAX_ATTEMPTS} attempts: {last_exc}")

    def get_live_years(self) -> List[str]:
        """Fetch live academic year keys (e.g. ['LIVE-25-26', 'LIVE-26-27'])."""
        data = self._get("admin-param-settings")
        if not isinstance(data, list):
            return []
        years = []
        for item in data:
            if isinstance(item, dict) and item.get("set_name") == "set_set_id":
                val = item.get("set_value")
                if val:
                    years.append(str(val))
        return sorted(list(set(years)))

    def get_academic_calendar(self, year_set_id: str) -> Dict[int, Dict[int, str]]:
        """Fetch week number & day position -> ISO date mapping for an academic year set.
        
        Returns: {week_num: {day_pos (1=Mon): 'YYYY-MM-DD'}}
        """
        data = self._get("academic-calendar-info", params={"set_id": year_set_id})
        if not isinstance(data, list):
            return {}
        
        cal: Dict[int, Dict[int, str]] = {}
        for row in data:
            if not isinstance(row, dict):
                continue
            week = row.get("week_number")
            day_pos = row.get("day_position")
            date_str = row.get("calendar_date")
            if week and day_pos and date_str:
                cal.setdefault(int(week), {})[int(day_pos)] = str(date_str)[:10]
        return cal

    def get_location_events(self, year_set_id: str, site_id: str, room_id: str) -> Dict[str, Any]:
        """Fetch room details and full calendar events for a specific site & room ID."""
        data = self._get(
            "location",
            params={"set_id": year_set_id, "site_id": site_id, "room_id": room_id},
        )
        if not isinstance(data, dict):
            return {"site_id": site_id, "room_id": room_id, "events": []}
        return data

    def list_module_deliveries(self, year_set_id: str, limit: int = 200, offset: int = 0) -> List[Dict[str, Any]]:
        """Fetch paginated module list for room discovery."""
        data = self._get(
            "module-delivery",
            params={"set_id": year_set_id, "limit": limit, "offset": offset},
        )
        if isinstance(data, list):
            return data
        if isinstance(data, dict):
            return data.get("module_deliveries", []) or data.get("results", [])
        return []
