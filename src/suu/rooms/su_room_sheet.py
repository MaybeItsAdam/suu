"""The Students' Union's public room-booking Google Sheet, read without a login.

The SU publishes each term's bookings for its own rooms as a Google Sheet
anyone with the link can view (the link sits on the logged-in page
``/node/139269``). Google serves every public sheet as plain HTML:

- ``/spreadsheets/d/<id>/htmlview`` lists the tabs, as ``items.push({name:
  "...", ..., gid: "..."})`` calls in an inline script.
- ``/spreadsheets/d/<id>/htmlview/sheet?headers=false&gid=<gid>`` is one tab
  as a ``table.waffle``, keeping merges (``colspan``/``rowspan``) and fill
  colours (a ``.ritz .waffle .sN{background-color:...}`` rule per class).

The CSV export keeps neither merges nor colours, which is what the booking
*type* and *duration* live in — hence HTML.

Tab layout (Term 3 2025/26, checked against the live sheet):

- ``🔑 KEY & INFO`` — the colour legend: a swatch cell, then its label.
- ``Template`` — an empty week.
- One tab per week, named by its Monday as ``d.m.yy`` (``27.4.26``). Each
  holds seven day blocks. A block is a header row of slot times
  (``8:00 am`` … ``9:30 pm``, 30 minutes each) then one row per room: the
  weekday and ``27 April`` (``rowspan`` over the block — no year, so it comes
  from the tab name), the room label, then one cell per slot. A booking is a
  cell whose text is the booker, whose ``colspan`` is its length in slots and
  whose fill says what kind of booking it is.

Parsing is pure (:func:`parse_tabs`, :func:`parse_legend`,
:func:`parse_week_tab`); :func:`fetch_sheet` does the fetching. Following the
suu rule, a page that isn't a sheet (a sign-in wall, a 404, a sheet shared
privately) raises :class:`RoomSheetError` rather than coming back empty.
"""

from __future__ import annotations

import html as html_lib
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup, Tag

LONDON = ZoneInfo("Europe/London")
SHEETS_BASE = "https://docs.google.com/spreadsheets/d"
USER_AGENT = "AdamsCampusToolbox/1.0 (UCL student tools; +https://adamscampustoolbox.org.uk)"
REQUEST_TIMEOUT = 30
# Seconds between tab fetches in fetch_sheet. A term is ~12 tabs.
POLITE_DELAY = 1.0

# Legend kinds. These are the canonical labels; KEY text is mapped onto them
# by keyword (see _canonical_kind) so a reworded key keeps the same kinds.
AVAILABLE = "Available"
QUIET_ONLY = "Quiet only"
WEEKLY = "Weekly block"
BIWEEKLY = "Bi-weekly/monthly"
ADHOC = "Ad-hoc"
STAFF = "Staff"
PROJECT_ACTIVE = "Project Active"
ARTS_UCL = "artsUCL"
UNAVAILABLE = "Unavailable"

# The Term 3 2025/26 key, used when the KEY tab can't be read or lacks a colour.
DEFAULT_LEGEND: Dict[str, str] = {
    "#ffffff": AVAILABLE,
    "#cccccc": QUIET_ONLY,
    "#6d9eeb": WEEKLY,
    "#c9daf8": BIWEEKLY,
    "#b6d7a8": ADHOC,
    "#ea9999": STAFF,
    "#b4a7d6": PROJECT_ACTIVE,
    "#f6b26b": ARTS_UCL,
    "#434343": UNAVAILABLE,
}

_KIND_KEYWORDS: Sequence[Tuple[str, str]] = (
    # Order matters: "Available (Quiet Bookings Only)" before "Available",
    # "Bi-Weekly" before "Weekly", "Unavailable" before "Available".
    (r"unavailable", UNAVAILABLE),
    (r"quiet", QUIET_ONLY),
    (r"bi-?weekly|monthly", BIWEEKLY),
    (r"weekly", WEEKLY),
    (r"ad[- ]?hoc", ADHOC),
    (r"staff", STAFF),
    (r"project\s*active", PROJECT_ACTIVE),
    (r"arts\s*ucl", ARTS_UCL),
    (r"^available\b", AVAILABLE),
)

_MONTHS = {
    m: i
    for i, names in enumerate(
        [
            ("jan", "january"), ("feb", "february"), ("mar", "march"),
            ("apr", "april"), ("may",), ("jun", "june"), ("jul", "july"),
            ("aug", "august"), ("sep", "sept", "september"), ("oct", "october"),
            ("nov", "november"), ("dec", "december"),
        ],
        start=1,
    )
    for m in names
}
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")

_SHEET_ID_RE = re.compile(
    r"docs\.google\.com/spreadsheets/(?:u/\d+/)?d/(?!e/)([A-Za-z0-9_-]{25,})"
)
_LEGACY_KEY_RE = re.compile(r"docs\.google\.com/(?:a/[^/]+/)?spreadsheet[^\"'\s]*?[?&]key=([A-Za-z0-9_-]{20,})")
_TAB_RE = re.compile(
    r'items\.push\(\{name:\s*"((?:[^"\\]|\\.)*)".*?gid:\s*"(-?\d+)"', re.S
)
_WEEK_NAME_RE = re.compile(r"^\s*(\d{1,2})\.(\d{1,2})\.(\d{2}|\d{4})\s*$")
_CLOCK_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\s*$", re.I)
_CLOCK_24_RE = re.compile(r"^\s*(\d{1,2}):(\d{2})\s*$")
_DAY_DATE_RE = re.compile(
    r"^\s*(?:(?P<wd>[A-Za-z]+),?\s+)?(?P<d>\d{1,2})(?:st|nd|rd|th)?\s+(?P<m>[A-Za-z]+)\.?\s*$"
)
_CSS_RULE_RE = re.compile(r"\.waffle\s+\.(s\d+)\s*\{([^}]*)\}")
_BG_RE = re.compile(r"background-color\s*:\s*([^;]+)")


class RoomSheetError(RuntimeError):
    """The page isn't the public room sheet (missing, private, or not a sheet)."""


@dataclass(frozen=True)
class Tab:
    name: str
    gid: str
    week_start: Optional[date] = None


@dataclass(frozen=True)
class SheetBlock:
    """One contiguous run of same-kind slots in one room.

    ``text`` is the cell text (the booker), ``""`` for an uncaptioned fill
    such as an Unavailable or Quiet-only run. ``kind`` is a legend label or
    ``"unknown:<hex>"``.
    """

    room_label: str
    starts_at: datetime
    ends_at: datetime
    text: str
    kind: str


@dataclass
class SheetResult:
    title: str
    tabs: List[Tab]
    blocks: List[SheetBlock]
    legend: Dict[str, str] = field(default_factory=dict)
    # Per-tab block counts, keyed by tab name — handy for spotting an empty week.
    blocks_per_tab: Dict[str, int] = field(default_factory=dict)


# --------------------------------------------------------------------- ids


def extract_sheet_id(url_or_html: str) -> Optional[str]:
    """The first Google Sheets id in a URL or a blob of HTML, else ``None``.

    Published-to-web ids (``/d/e/2PACX-…``) are skipped: they don't work with
    the ``htmlview`` endpoints this module reads.
    """
    if not url_or_html:
        return None
    text = html_lib.unescape(url_or_html).replace("\\/", "/")
    m = _SHEET_ID_RE.search(text) or _LEGACY_KEY_RE.search(text)
    return m.group(1) if m else None


def tab_list_url(sheet_id: str) -> str:
    return f"{SHEETS_BASE}/{sheet_id}/htmlview"


def tab_url(sheet_id: str, gid: str) -> str:
    return f"{SHEETS_BASE}/{sheet_id}/htmlview/sheet?headers=false&gid={gid}"


# ----------------------------------------------------------------- fetching


def _get(url: str, session: Any = None) -> str:
    """GET ``url`` and return the body, raising RoomSheetError on refusal.

    ``session`` is anything with a requests-style ``get`` (a
    ``requests.Session``, or a test double); without one, urllib is used.
    """
    if session is not None:
        resp = session.get(url, timeout=REQUEST_TIMEOUT, headers={"User-Agent": USER_AGENT})
        status = getattr(resp, "status_code", 200)
        final = str(getattr(resp, "url", url) or url)
        body = resp.text
    else:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as r:
                status, final = r.status, r.geturl()
                body = r.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            status, final, body = e.code, url, ""
        except urllib.error.URLError as e:
            raise RoomSheetError(f"Could not reach {url}: {e.reason}") from e
    if status in (401, 403):
        raise RoomSheetError(f"Access denied (HTTP {status}) for {url} — is the sheet public?")
    if status == 404:
        raise RoomSheetError(f"No such sheet (HTTP 404): {url}")
    if status >= 400:
        raise RoomSheetError(f"HTTP {status} fetching {url}")
    if "accounts.google.com" in final:
        raise RoomSheetError(f"{url} redirected to a Google sign-in — the sheet isn't public")
    return body


def list_tabs(sheet_id: str, session: Any = None) -> List[Tab]:
    """The sheet's tabs in order; weekly tabs carry ``week_start``."""
    return parse_tabs(_get(tab_list_url(sheet_id), session))


def fetch_sheet(
    sheet_id: str,
    session: Any = None,
    *,
    delay: float = POLITE_DELAY,
    weeks_only: bool = True,
) -> SheetResult:
    """Fetch the tab list, the legend and every weekly tab, and parse them.

    Raises :class:`RoomSheetError` if the sheet can't be read, has no weekly
    tabs, or a weekly tab isn't a booking grid.
    """
    listing = _get(tab_list_url(sheet_id), session)
    title = parse_title(listing)
    tabs = parse_tabs(listing)
    weeks = [t for t in tabs if t.week_start is not None]
    if not weeks:
        raise RoomSheetError(
            f"Sheet {sheet_id} ({title!r}) has no tabs named like a week (d.m.yy): "
            f"{[t.name for t in tabs]}"
        )

    legend = dict(DEFAULT_LEGEND)
    key_tab = next((t for t in tabs if "key" in t.name.lower()), None)
    if key_tab is not None:
        time.sleep(delay)
        legend.update(parse_legend(_get(tab_url(sheet_id, key_tab.gid), session)))

    blocks: List[SheetBlock] = []
    per_tab: Dict[str, int] = {}
    targets = weeks if weeks_only else tabs
    for tab in targets:
        if tab.week_start is None:
            continue
        time.sleep(delay)
        tab_blocks = parse_week_tab(_get(tab_url(sheet_id, tab.gid), session), tab.week_start, legend)
        per_tab[tab.name] = len(tab_blocks)
        blocks.extend(tab_blocks)
    return SheetResult(title=title, tabs=tabs, blocks=blocks, legend=legend, blocks_per_tab=per_tab)


def room_labels(blocks: Iterable[SheetBlock]) -> List[str]:
    """Distinct room labels, in first-seen order."""
    seen: Dict[str, None] = {}
    for b in blocks:
        seen.setdefault(b.room_label, None)
    return list(seen)


# ------------------------------------------------------------------ parsing


def _js_unescape(s: str) -> str:
    return re.sub(
        r"\\(x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|.)",
        lambda m: chr(int(m.group(1)[1:], 16)) if m.group(1)[0] in "xu" and len(m.group(1)) > 1 else m.group(1),
        s,
    )


def parse_week_name(name: str) -> Optional[date]:
    """``"27.4.26"`` → 2026-04-27; anything else → ``None``."""
    m = _WEEK_NAME_RE.match(name)
    if not m:
        return None
    d, mo, y = (int(g) for g in m.groups())
    if y < 100:
        y += 2000
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def parse_title(page_html: str) -> str:
    soup = BeautifulSoup(page_html, "html.parser")
    node = soup.select_one("#doc-title .name")
    if node:
        return node.get_text(strip=True)
    t = soup.title.get_text(strip=True) if soup.title else ""
    return re.sub(r"\s*-\s*Google (Drive|Sheets)\s*$", "", t)


def parse_tabs(page_html: str) -> List[Tab]:
    """Tabs from an ``htmlview`` page. Raises if the page lists none."""
    tabs = []
    for m in _TAB_RE.finditer(page_html):
        name = _js_unescape(m.group(1))
        tabs.append(Tab(name=name, gid=m.group(2), week_start=parse_week_name(name)))
    if not tabs:
        raise RoomSheetError(
            "Page lists no sheet tabs — not a Google Sheets htmlview page "
            f"(title {parse_title(page_html)!r})"
        )
    return tabs


def _normalise_colour(value: str) -> Optional[str]:
    v = value.strip().lower().replace("!important", "").strip()
    if v.startswith("#"):
        h = v[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return "#" + h[:6] if len(h) >= 6 else None
    m = re.match(r"rgba?\((\d+)\s*,\s*(\d+)\s*,\s*(\d+)", v)
    if m:
        return "#" + "".join(f"{int(x):02x}" for x in m.groups())
    if v == "white":
        return "#ffffff"
    return None


def _class_backgrounds(page_html: str) -> Dict[str, str]:
    out = {}
    for m in _CSS_RULE_RE.finditer(page_html):
        bg = _BG_RE.search(m.group(2))
        if bg:
            colour = _normalise_colour(bg.group(1))
            if colour:
                out[m.group(1)] = colour
    return out


def _cell_background(td: Tag, class_bg: Dict[str, str]) -> Optional[str]:
    style = td.get("style") or ""
    bg = _BG_RE.search(style)
    if bg:
        colour = _normalise_colour(bg.group(1))
        if colour:
            return colour
    for cls in td.get("class") or []:
        if cls in class_bg:
            return class_bg[cls]
    return None


def _cell_text(td: Tag) -> str:
    return re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip()


@dataclass
class _Cell:
    text: str
    bg: Optional[str]
    row: int
    col: int
    rowspan: int
    colspan: int


def _waffle_grid(page_html: str) -> Tuple[List[List[Optional[_Cell]]], BeautifulSoup]:
    """The ``table.waffle`` as a dense grid; a merged cell fills every slot it spans.

    Row-number ``th`` cells, the freeze-bar column and the freeze-bar row are
    not sheet cells and are dropped.
    """
    soup = BeautifulSoup(page_html, "html.parser")
    table = soup.select_one("table.waffle")
    if table is None:
        raise RoomSheetError(
            f"Page has no sheet grid (table.waffle) — title {parse_title(page_html)!r}"
        )
    class_bg = _class_backgrounds(page_html)
    grid: List[List[Optional[_Cell]]] = []
    pending: Dict[Tuple[int, int], _Cell] = {}
    body = table.find("tbody") or table
    r = 0
    for tr in body.find_all("tr", recursive=False):
        tds = [td for td in tr.find_all("td", recursive=False)]
        real = [td for td in tds if "freezebar-cell" not in (td.get("class") or [])]
        if not real:
            continue
        row: List[Optional[_Cell]] = []
        c = 0

        def fill_pending() -> None:
            nonlocal c
            while (r, c) in pending:
                row.append(pending.pop((r, c)))
                c += 1

        for td in real:
            fill_pending()
            rs = int(td.get("rowspan") or 1)
            cs = int(td.get("colspan") or 1)
            cell = _Cell(_cell_text(td), _cell_background(td, class_bg), r, c, rs, cs)
            for dc in range(cs):
                row.append(cell)
                for dr in range(1, rs):
                    pending[(r + dr, c + dc)] = cell
            c += cs
        fill_pending()
        grid.append(row)
        r += 1
    return grid, soup


def _parse_clock(text: str) -> Optional[Tuple[int, int]]:
    m = _CLOCK_RE.match(text)
    if m:
        h, mi, ap = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
        if not (1 <= h <= 12 and mi < 60):
            return None
        h = h % 12 + (12 if ap == "p" else 0)
        return h, mi
    m = _CLOCK_24_RE.match(text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2))
        if h < 24 and mi < 60:
            return h, mi
    return None


def _time_header(row: List[Optional[_Cell]]) -> Optional[Dict[int, Tuple[int, int]]]:
    """``{column: (hour, minute)}`` if this row is a slot-time header."""
    times: Dict[int, Tuple[int, int]] = {}
    for c, cell in enumerate(row):
        if cell is None or cell.col != c:
            continue
        t = _parse_clock(cell.text)
        if t is not None:
            times[c] = t
    return times if len(times) >= 4 else None


def _resolve_day(text: str, week_start: date) -> Optional[date]:
    m = _DAY_DATE_RE.match(text)
    if not m:
        return None
    wd = (m.group("wd") or "").lower()
    if wd and wd not in _WEEKDAYS and wd[:3] not in {w[:3] for w in _WEEKDAYS}:
        return None
    month = _MONTHS.get(m.group("m").lower())
    if month is None:
        return None
    day = int(m.group("d"))
    best: Optional[date] = None
    for y in (week_start.year - 1, week_start.year, week_start.year + 1):
        try:
            cand = date(y, month, day)
        except ValueError:
            continue
        if best is None or abs((cand - week_start).days) < abs((best - week_start).days):
            best = cand
    return best


def parse_legend(page_html: str) -> Dict[str, str]:
    """``{hex: kind}`` from the KEY tab: a text-less swatch cell, then its label.

    Labels are mapped to the canonical kinds by keyword; a label that matches
    none is kept verbatim. Returns ``{}`` if no legend rows are found.
    """
    grid, _ = _waffle_grid(page_html)
    legend: Dict[str, str] = {}
    for row in grid:
        cells = []
        for c, cell in enumerate(row):
            if cell is not None and cell.col == c:
                cells.append(cell)
        for i, cell in enumerate(cells):
            if not cell.text or i == 0:
                continue
            swatch = cells[i - 1]
            if swatch.text or swatch.bg is None:
                break
            label = cell.text
            if not re.match(r"^(available|booked|unavailable)\b", label, re.I):
                break
            legend[swatch.bg] = _canonical_kind(label)
            break
    return legend


def _canonical_kind(label: str) -> str:
    low = label.lower()
    for pattern, kind in _KIND_KEYWORDS:
        if re.search(pattern, low):
            return kind
    return label


def parse_week_tab(
    page_html: str,
    week_start: date,
    legend: Optional[Dict[str, str]] = None,
) -> List[SheetBlock]:
    """Every non-white run of slots in a weekly tab, as :class:`SheetBlock`.

    - Slot times come from each day block's own header row; a block ends at
      the next column's time, or one slot-length after the last column.
    - A booking merged across rooms (``rowspan``) yields one block per room.
    - Adjacent uncaptioned cells of the same kind (a row of grey
      Unavailable cells) are merged into one block; captioned cells never
      are, since two back-to-back bookings by one booker are two bookings.
    - White cells are Available and not emitted — unless they carry text,
      which is kept (as ``Available``) so a booking typed without a fill
      isn't lost.

    Raises :class:`RoomSheetError` if the page has no slot-time header or no
    dated day block, so a reshaped sheet fails loudly instead of parsing to
    nothing.
    """
    legend = {**DEFAULT_LEGEND, **(legend or {})}
    grid, _ = _waffle_grid(page_html)
    blocks: List[SheetBlock] = []
    times: Optional[Dict[int, Tuple[int, int]]] = None
    saw_header = saw_day = False
    emitted: set = set()

    for row in grid:
        header = _time_header(row)
        if header is not None:
            times = header
            saw_header = True
            continue
        if times is None:
            continue
        first_slot = min(times)
        # Left-hand columns: day / date / room label.
        day: Optional[date] = None
        room: Optional[str] = None
        for c in range(min(first_slot, len(row))):
            cell = row[c]
            if cell is None or not cell.text:
                continue
            d = _resolve_day(cell.text, week_start)
            if d is not None:
                day = d
            elif cell.text.lower().rstrip(",") in _WEEKDAYS:
                continue
            elif cell.rowspan == 1 or room is None:
                room = cell.text
        if day is None or room is None:
            continue
        saw_day = True
        blocks.extend(_row_blocks(row, times, day, room, legend, emitted))

    if not saw_header:
        raise RoomSheetError("Tab has no slot-time header row (e.g. '8:00 am') — not a booking grid")
    if not saw_day:
        raise RoomSheetError("Tab has no dated day blocks (e.g. 'Monday' / '27 April') — not a booking grid")
    return blocks


def _slot_minutes(times: Dict[int, Tuple[int, int]]) -> int:
    cols = sorted(times)
    diffs = [
        (times[b][0] * 60 + times[b][1]) - (times[a][0] * 60 + times[a][1])
        for a, b in zip(cols, cols[1:])
        if b == a + 1
    ]
    diffs = [d for d in diffs if d > 0]
    return min(diffs) if diffs else 30


def _row_blocks(
    row: List[Optional[_Cell]],
    times: Dict[int, Tuple[int, int]],
    day: date,
    room: str,
    legend: Dict[str, str],
    emitted: set,
) -> List[SheetBlock]:
    slot = timedelta(minutes=_slot_minutes(times))
    last_col = max(times)

    def at(col: int) -> datetime:
        if col in times:
            h, m = times[col]
            return datetime(day.year, day.month, day.day, h, m, tzinfo=LONDON)
        h, m = times[last_col]
        base = datetime(day.year, day.month, day.day, h, m, tzinfo=LONDON)
        return base + slot * (col - last_col)

    out: List[SheetBlock] = []
    c = min(times)
    while c <= last_col and c < len(row):
        cell = row[c]
        if cell is None:
            c += 1
            continue
        start_col = max(cell.col, min(times))
        end_col = min(cell.col + cell.colspan, last_col + 1)
        c = max(end_col, c + 1)
        colour = cell.bg or "#ffffff"
        kind = legend.get(colour, f"unknown:{colour}")
        if kind == AVAILABLE and not cell.text:
            continue
        key = (id(cell), room)
        if key in emitted:
            continue
        emitted.add(key)
        block = SheetBlock(room, at(start_col), at(end_col), cell.text, kind)
        prev = out[-1] if out else None
        if (
            prev is not None
            and not prev.text
            and not block.text
            and prev.kind == block.kind
            and prev.ends_at == block.starts_at
        ):
            out[-1] = SheetBlock(room, prev.starts_at, block.ends_at, "", block.kind)
        else:
            out.append(block)
    return out
