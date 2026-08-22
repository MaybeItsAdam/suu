"""What's On time parsing: the three shapes that produced bad rows.

Production held 4,963 AdhocEvent rows, of which 191 ran longer than twelve
hours — and 181 of those started at exactly 00:00, because the scraper
defaulted an unparsed time to midnight and paired it with 23:59. 73 of them
swallowed other events whole on the calendar. A further 80 rows had
endTime <= startTime, from combining both ends of "18:30 - 00:00" with the
same date.

The fixtures below drive the real scrape loop against a fake driver, so the
day-header/card-grid interplay is exercised, not just the parser.
"""
import datetime as dt

import pytest

pytest.importorskip("selenium")

from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver.common.by import By

from suu.scrape.whatson import WhatsOnScraper, _parse_time_range


# ── fake DOM ───────────────────────────────────────────────────────────────


class _El:
    def __init__(self, text="", attrs=None, children=None):
        self.text = text
        self._attrs = attrs or {}
        self._children = children or {}

    def get_attribute(self, name):
        return self._attrs.get(name)

    def find_element(self, by, selector):
        try:
            return self._children[(by, selector)]
        except KeyError:
            raise NoSuchElementException(selector)


def _day_header(date_obj):
    return _El(text=date_obj.strftime("%A %d %B %Y"), attrs={"class": "day-header"})


def _card(link, title, time_text=None, location="Gordon Street", society="Test Society"):
    primary_children = {}
    if time_text is not None:
        primary_children[(By.CSS_SELECTOR, ".list-item--time")] = _El(text=time_text)
    primary_text = f"{time_text} {title}" if time_text is not None else title
    primary = _El(text=primary_text, children=primary_children)

    secondary = _El(
        children={
            (By.CSS_SELECTOR, ".list-item--location span"): _El(text=location),
            (By.CSS_SELECTOR, ".list-item--group span"): _El(text=society),
        }
    )

    return _El(
        attrs={"class": "card-grid"},
        children={
            (By.TAG_NAME, "a"): _El(attrs={"href": link}),
            (By.CSS_SELECTOR, ".MuiListItemText-primary"): primary,
            (By.CSS_SELECTOR, ".MuiListItemText-secondary"): secondary,
        },
    )


class _FakeDriver:
    """Just enough driver for `scrape()`: serves one page of rows, then stops."""

    def __init__(self, rows):
        self.rows = rows
        self._first_header = next(
            r for r in rows if "day-header" in (r.get_attribute("class") or "")
        )

    def get(self, url):
        pass

    def execute_script(self, *args, **kwargs):
        pass

    def find_elements(self, by, selector):
        return self.rows

    def find_element(self, by, selector):
        if ".whats-on-container" in selector:
            return _El()
        if selector == ".day-header":
            return self._first_header
        if "whats-on-datepicker" in selector:
            return _El()
        # No List button and no Next button — pagination stops on its own.
        raise NoSuchElementException(selector)

    def quit(self):
        pass


def _run(rows, start, end):
    """Run the real scrape loop over `rows`, with no browser and no network."""
    import suu.scrape.whatson as whatson_module

    class _NoSleep:
        @staticmethod
        def sleep(_seconds):
            pass

    original_sleep = whatson_module.time.sleep
    original_driver = whatson_module.get_selenium_driver
    original_enrich = WhatsOnScraper.enrich_event_details
    whatson_module.time.sleep = _NoSleep.sleep
    whatson_module.get_selenium_driver = lambda **kwargs: _FakeDriver(rows)
    WhatsOnScraper.enrich_event_details = lambda self, events: None
    try:
        return WhatsOnScraper(start, end).scrape()["events"]
    finally:
        whatson_module.time.sleep = original_sleep
        whatson_module.get_selenium_driver = original_driver
        WhatsOnScraper.enrich_event_details = original_enrich


# ── shape 1: no `.list-item--time` element at all ──────────────────────────


def test_missing_time_element_yields_no_times_not_midnight():
    day = dt.date(2026, 8, 23)
    events = _run(
        [_day_header(day), _card("https://su/hike", "Hike: Thames Path")],
        "2026-08-23",
        "2026-08-23",
    )

    assert len(events) == 1
    event = events[0]
    assert event["start_time"] is None
    assert event["end_time"] is None
    assert event["time_known"] is False
    # The date is still known — that is the whole distinction.
    assert event["date"] == "2026-08-23"
    assert event["title"] == "Hike: Thames Path"


def test_unparseable_time_text_is_not_rounded_to_midnight():
    day = dt.date(2026, 8, 23)
    events = _run(
        [_day_header(day), _card("https://su/fair", "Freshers Fair", time_text="All day")],
        "2026-08-23",
        "2026-08-23",
    )

    assert events[0]["start_time"] is None
    assert events[0]["time_known"] is False


# ── shape 2: one link under several day-headers (a recurring series) ───────


def test_repeat_under_later_day_header_is_a_second_event_not_a_span():
    link = "https://su/nerdy-prudes-must-die"
    rows = [
        _day_header(dt.date(2026, 8, 24)),
        _card(link, "Nerdy Prudes Must Die", time_text="19:30 - 21:30"),
        _day_header(dt.date(2026, 8, 25)),
        _card(link, "Nerdy Prudes Must Die", time_text="19:30 - 21:30"),
        _day_header(dt.date(2026, 8, 26)),
        _card(link, "Nerdy Prudes Must Die", time_text="19:30 - 21:30"),
    ]
    events = _run(rows, "2026-08-24", "2026-08-26")

    assert len(events) == 3
    assert [e["date"] for e in events] == ["2026-08-24", "2026-08-25", "2026-08-26"]
    # Every occurrence is a two-hour evening show, not a 48-hour block.
    for event in events:
        start = dt.datetime.fromisoformat(event["start_time"])
        end = dt.datetime.fromisoformat(event["end_time"])
        assert (end - start) == dt.timedelta(hours=2)
        assert start.hour == 19
    # ...and each one is separately addressable, because AdhocEvent.sourceId
    # is UNIQUE and the bare link is now shared by three rows.
    assert len({e["source_id"] for e in events}) == 3
    assert events[0]["source_id"] == f"{link}#2026-08-24"


def test_same_link_twice_under_one_day_header_is_emitted_once():
    """Pages overlap when both navigation paths move the calendar."""
    link = "https://su/quiz"
    rows = [
        _day_header(dt.date(2026, 8, 24)),
        _card(link, "Quiz Night", time_text="19:00 - 21:00"),
        _card(link, "Quiz Night", time_text="19:00 - 21:00"),
    ]
    events = _run(rows, "2026-08-24", "2026-08-24")

    assert len(events) == 1


# ── shape 3: a range that runs past midnight ───────────────────────────────


def test_range_ending_at_midnight_rolls_onto_the_next_day():
    day = dt.date(2026, 8, 24)
    events = _run(
        [_day_header(day), _card("https://su/club-night", "Club Night", time_text="18:30 - 00:00")],
        "2026-08-24",
        "2026-08-24",
    )

    start = dt.datetime.fromisoformat(events[0]["start_time"])
    end = dt.datetime.fromisoformat(events[0]["end_time"])
    assert end > start
    assert end.date() == dt.date(2026, 8, 25)
    assert (end - start) == dt.timedelta(hours=5, minutes=30)
    assert events[0]["time_known"] is True


# ── the parser on its own ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "text,expected_start,expected_end",
    [
        ("18:30 - 20:00", (18, 30), (20, 0)),
        ("18:30 – 20:00", (18, 30), (20, 0)),  # en dash, as the site writes it
        ("6pm - 8pm", (18, 0), (20, 0)),
        ("18:30", (18, 30), None),  # a known start beats discarding it
    ],
)
def test_parse_time_range_shapes(text, expected_start, expected_end):
    day = dt.date(2026, 8, 24)
    start, end = _parse_time_range(text, day)
    assert (start.hour, start.minute) == expected_start
    if expected_end is None:
        assert end is None
    else:
        assert (end.hour, end.minute) == expected_end


@pytest.mark.parametrize("text", ["", None, "All day", "TBC", "-", "  "])
def test_parse_time_range_never_invents_a_time(text):
    assert _parse_time_range(text, dt.date(2026, 8, 24)) == (None, None)


def test_parse_time_range_keeps_the_local_offset_across_bst():
    """Times stay Europe/London-aware, so the DB cast to UTC is correct."""
    summer = _parse_time_range("18:30 - 20:00", dt.date(2026, 8, 24))[0]
    winter = _parse_time_range("18:30 - 20:00", dt.date(2026, 12, 24))[0]
    assert summer.utcoffset() == dt.timedelta(hours=1)
    assert winter.utcoffset() == dt.timedelta(0)
