"""SU room-booking Google Sheet parser (suu.rooms.su_room_sheet).

Fixtures under tests/fixtures/su_room_sheet/ are the live Term 3 2025/26 sheet
(10yIxgUm-WoIiSGk4w4OXicIMH46CUy2C2k-hm31lS7E) with scripts stripped; the week
tab keeps its CSS and header rows but only three rooms of Monday and Tuesday
(the day/date rowspans cut from 32 to 3 to match).
"""

from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from suu.rooms import su_room_sheet as rs
from suu.rooms.su_room_sheet import (
    LONDON,
    RoomSheetError,
    SheetBlock,
    extract_sheet_id,
    parse_legend,
    parse_tabs,
    parse_title,
    parse_week_name,
    parse_week_tab,
    room_labels,
)

FIXTURES = Path(__file__).parent / "fixtures" / "su_room_sheet"
SHEET_ID = "10yIxgUm-WoIiSGk4w4OXicIMH46CUy2C2k-hm31lS7E"
WEEK = date(2026, 4, 27)


def _read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _at(d: int, h: int, m: int = 0, month: int = 4) -> datetime:
    return datetime(2026, month, d, h, m, tzinfo=LONDON)


@pytest.fixture(scope="module")
def week_blocks():
    return parse_week_tab(_read("week-27.4.26.html"), WEEK)


# ---------------------------------------------------------------- sheet ids


@pytest.mark.parametrize(
    "text",
    [
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?usp=sharing",
        f"https://docs.google.com/spreadsheets/d/{SHEET_ID}",
        f"https://docs.google.com/spreadsheets/u/1/d/{SHEET_ID}/htmlview#gid=0",
        f'<p>See the <a href="https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit?gid=320908680#gid=320908680">'
        "room timetable</a>.</p>",
        f'{{"url":"https:\\/\\/docs.google.com\\/spreadsheets\\/d\\/{SHEET_ID}\\/htmlview"}}',
        f"&lt;a href=&quot;https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit&amp;x=1&quot;&gt;",
    ],
)
def test_extract_sheet_id(text):
    assert extract_sheet_id(text) == SHEET_ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "https://docs.google.com/document/d/1abcdefghijklmnopqrstuvwxyz0123/edit",
        "https://docs.google.com/spreadsheets/d/e/2PACX-1vQabcdefghijklmnopqrstuvwxyz0123456789/pubhtml",
        "<a href='https://studentsunionucl.org/node/139269'>rooms</a>",
    ],
)
def test_extract_sheet_id_rejects_non_sheets(text):
    assert extract_sheet_id(text) is None


# --------------------------------------------------------------------- tabs


def test_parse_tabs_lists_every_tab_in_order():
    tabs = parse_tabs(_read("tabs.html"))
    assert [t.name for t in tabs] == [
        "\U0001f511 KEY & INFO",
        "Template",
        "27.4.26",
        "4.5.26",
        "11.5.26",
        "18.5.26",
        "25.5.26",
        "1.6.26",
        "8.6.26",
    ]
    assert tabs[0].gid == "320908680" and tabs[0].week_start is None
    assert tabs[1].gid == "2097907204" and tabs[1].week_start is None
    assert tabs[2].gid == "146794525" and tabs[2].week_start == date(2026, 4, 27)
    assert tabs[-1].week_start == date(2026, 6, 8)
    assert all(t.week_start.weekday() == 0 for t in tabs[2:])


def test_parse_title():
    assert parse_title(_read("tabs.html")) == "Term 3 2025/26 - Student Activities Room Bookings"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("27.4.26", date(2026, 4, 27)),
        ("1.6.26", date(2026, 6, 1)),
        ("05.01.2027", date(2027, 1, 5)),
        ("Template", None),
        ("31.2.26", None),
        ("27.4", None),
    ],
)
def test_parse_week_name(name, expected):
    assert parse_week_name(name) == expected


def test_parse_tabs_refuses_a_page_that_is_not_a_sheet():
    with pytest.raises(RoomSheetError):
        parse_tabs("<html><head><title>Sign in - Google Accounts</title></head><body></body></html>")


# ------------------------------------------------------------------- legend


def test_parse_legend_reads_the_key_tab():
    assert parse_legend(_read("key.html")) == rs.DEFAULT_LEGEND


def test_parse_legend_follows_a_recoloured_key():
    html = _read("key.html").replace("#6d9eeb", "#123456")
    legend = parse_legend(html)
    assert legend["#123456"] == rs.WEEKLY
    assert "#6d9eeb" not in legend


# --------------------------------------------------------------- week grid


def test_slot_columns_map_to_times_and_colspan_to_duration(week_blocks):
    yoga = next(b for b in week_blocks if b.text == "Yoga and Meditation Club")
    # colspan=2 starting at the 11:00 column.
    assert yoga.room_label == "Bloomsbury Theatre Conference Room"
    assert (yoga.starts_at, yoga.ends_at) == (_at(27, 11), _at(27, 12))

    arts = next(b for b in week_blocks if b.text == "artsUCL Fringe Rehearsals")
    # colspan=14 from 10:00 → seven hours.
    assert (arts.starts_at, arts.ends_at) == (_at(27, 10), _at(27, 17))
    assert arts.kind == rs.ARTS_UCL

    staff = next(b for b in week_blocks if b.text == "JH")
    # Starts on a half-hour column.
    assert (staff.starts_at, staff.ends_at) == (_at(27, 15, 30), _at(27, 16, 30))


def test_block_in_the_last_column_ends_one_slot_later(week_blocks):
    # The 9:00/9:30 pm columns are Unavailable; the run ends at 22:00.
    last = [b for b in week_blocks if b.room_label == "Bloomsbury Theatre Conference Room"
            and b.starts_at.date() == WEEK][-1]
    assert (last.starts_at, last.ends_at, last.kind, last.text) == (
        _at(27, 21), _at(27, 22), rs.UNAVAILABLE, "")


def test_times_are_aware_europe_london(week_blocks):
    b = week_blocks[0]
    assert b.starts_at.tzinfo is LONDON
    assert b.starts_at.utcoffset() == timedelta(hours=1)  # BST in April


def test_day_blocks_get_their_own_dates(week_blocks):
    days = {b.starts_at.date() for b in week_blocks}
    assert days == {date(2026, 4, 27), date(2026, 4, 28)}
    tuesday_jazz = next(b for b in week_blocks if b.text == "Jazz Society")
    assert (tuesday_jazz.starts_at, tuesday_jazz.ends_at) == (_at(28, 19), _at(28, 21))


def test_colour_decides_kind(week_blocks):
    kinds = {b.text: b.kind for b in week_blocks if b.text}
    assert kinds["Yoga and Meditation Club"] == rs.WEEKLY
    assert kinds["Project Active"] == rs.PROJECT_ACTIVE
    assert kinds["JH"] == rs.STAFF
    assert kinds["Musical Theatre Society"] == rs.ADHOC


def test_empty_unavailable_cells_merge_into_one_block(week_blocks):
    # Rehearsal Room, Monday: four single grey cells 08:00–10:00.
    first = next(b for b in week_blocks if b.room_label == "Bloomsbury Theatre Rehearsal Room")
    assert (first.starts_at, first.ends_at, first.text, first.kind) == (
        _at(27, 8), _at(27, 10), "", rs.UNAVAILABLE)


def test_back_to_back_bookings_stay_separate(week_blocks):
    # Two adjacent "Project Active" merges at 08:00 and 09:00 are two bookings.
    pa = [b for b in week_blocks if b.text == "Project Active" and b.starts_at.date() == WEEK
          and b.starts_at.hour < 10]
    assert [(b.starts_at.hour, b.ends_at.hour) for b in pa] == [(8, 9), (9, 10)]


def test_white_cells_are_not_blocks(week_blocks):
    assert all(b.kind != rs.AVAILABLE for b in week_blocks)


def test_room_labels(week_blocks):
    assert room_labels(week_blocks) == [
        "Bloomsbury Theatre Conference Room",
        "Bloomsbury Theatre Rehearsal Room",
        "Bloomsbury Theatre 204",
    ]


def test_fixture_block_count(week_blocks):
    assert len(week_blocks) == 29


# ------------------------------------------------ synthetic grid edge cases

_CSS = (
    "<style>.ritz .waffle .s1{background-color:#ffffff;}"
    ".ritz .waffle .s2{background-color:#cccccc;}"
    ".ritz .waffle .s3{background-color:#6d9eeb;}"
    ".ritz .waffle .s4{background-color:#434343;}"
    ".ritz .waffle .s5{background-color:#abcdef;}</style>"
)


def _grid(rows: str, header: str = "") -> str:
    header = header or (
        '<tr><td class="s1" colspan="3"></td><td class="freezebar-cell"></td>'
        '<td class="s1">6:00 pm</td><td class="s1">6:30 pm</td>'
        '<td class="s1">7:00 pm</td><td class="s1">7:30 pm</td></tr>'
    )
    return f'<html><head>{_CSS}</head><body><table class="waffle"><tbody>{header}{rows}</tbody></table></body></html>'


def _room(label: str, cells: str, day: str = "") -> str:
    return f'<tr>{day}<td class="s1">{label}</td><td class="freezebar-cell"></td>{cells}</tr>'


def test_rowspan_booking_covers_each_room():
    html = _grid(
        _room("Room A", '<td class="s3" colspan="2" rowspan="2">Chess Society</td>'
                        '<td class="s1"></td><td class="s1"></td>',
              day='<td class="s1" rowspan="2">Friday</td><td class="s1" rowspan="2">1 May</td>')
        + _room("Room B", '<td class="s1"></td><td class="s1"></td>')
    )
    blocks = parse_week_tab(html, WEEK)
    assert [(b.room_label, b.starts_at, b.ends_at, b.text) for b in blocks] == [
        ("Room A", _at(1, 18, month=5), _at(1, 19, month=5), "Chess Society"),
        ("Room B", _at(1, 18, month=5), _at(1, 19, month=5), "Chess Society"),
    ]


def test_quiet_only_unknown_colour_and_uncoloured_text():
    html = _grid(
        _room("Room A",
              '<td class="s2"></td><td class="s2"></td>'
              '<td class="s5">Mystery</td><td class="s1">Typed without fill</td>',
              day='<td class="s1">Monday, 27 April</td><td class="s1"></td>')
    )
    blocks = parse_week_tab(html, WEEK)
    assert [(b.starts_at.strftime("%H:%M"), b.ends_at.strftime("%H:%M"), b.text, b.kind) for b in blocks] == [
        ("18:00", "19:00", "", rs.QUIET_ONLY),
        ("19:00", "19:30", "Mystery", "unknown:#abcdef"),
        ("19:30", "20:00", "Typed without fill", rs.AVAILABLE),
    ]


def test_day_date_takes_the_nearest_year_across_new_year():
    header = (
        '<tr><td class="s1" colspan="2"></td>'
        '<td class="s1">8:00 am</td><td class="s1">8:30 am</td>'
        '<td class="s1">9:00 am</td><td class="s1">9:30 am</td></tr>'
    )
    html = _grid(
        '<tr><td class="s1">Friday 1 January</td><td class="s1">Room A</td>'
        '<td class="s4" colspan="4"></td></tr>',
        header=header,
    )
    [block] = parse_week_tab(html, date(2020, 12, 28))
    assert block.starts_at == datetime(2021, 1, 1, 8, 0, tzinfo=LONDON)
    assert block.ends_at == datetime(2021, 1, 1, 10, 0, tzinfo=LONDON)
    assert block.starts_at.utcoffset() == timedelta(0)


def test_refuses_a_page_without_a_grid():
    with pytest.raises(RoomSheetError):
        parse_week_tab("<html><title>Page not found</title></html>", WEEK)


def test_refuses_a_tab_that_is_not_a_booking_grid():
    with pytest.raises(RoomSheetError):
        parse_week_tab(_read("key.html"), WEEK)


# ------------------------------------------------------------------ fetching


class _Resp:
    def __init__(self, text: str, status: int = 200, url: str = ""):
        self.text, self.status_code, self.url = text, status, url


class _Session:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def get(self, url, **_):
        self.calls.append(url)
        return self.pages(url)


def test_fetch_sheet_reads_key_and_weeks(monkeypatch):
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    tabs_html = _read("tabs.html")
    week_html = _read("week-27.4.26.html")
    key_html = _read("key.html")

    def pages(url):
        if url.endswith("/htmlview"):
            return _Resp(tabs_html, url=url)
        if "gid=320908680" in url:
            return _Resp(key_html, url=url)
        return _Resp(week_html, url=url)

    session = _Session(pages)
    result = rs.fetch_sheet(SHEET_ID, session=session)
    assert result.title == "Term 3 2025/26 - Student Activities Room Bookings"
    assert len(result.tabs) == 9
    assert list(result.blocks_per_tab) == ["27.4.26", "4.5.26", "11.5.26", "18.5.26", "25.5.26", "1.6.26", "8.6.26"]
    assert len(result.blocks) == 7 * 29
    # Template is never fetched; KEY is.
    assert not any("gid=2097907204" in u for u in session.calls)
    assert any("gid=320908680" in u for u in session.calls)
    assert all("headers=false" in u for u in session.calls[1:])


@pytest.mark.parametrize(
    "resp",
    [
        _Resp("", status=404),
        _Resp("", status=403),
        _Resp("<html><title>Sign in</title></html>", url="https://accounts.google.com/v3/signin"),
        _Resp("<html><title>Something else</title></html>"),
    ],
)
def test_fetch_sheet_raises_instead_of_returning_empty(monkeypatch, resp):
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    with pytest.raises(RoomSheetError):
        rs.fetch_sheet(SHEET_ID, session=_Session(lambda url: resp))


def test_fetch_sheet_raises_when_there_are_no_week_tabs(monkeypatch):
    monkeypatch.setattr(rs.time, "sleep", lambda s: None)
    only_key = 'items.push({name: "KEY", pageUrl: "x", gid: "1"});'
    with pytest.raises(RoomSheetError, match="no tabs named like a week"):
        rs.fetch_sheet(SHEET_ID, session=_Session(lambda url: _Resp(only_key, url=url)))
