"""What a listing's own page says about when it runs and who runs it.

The fixtures are the markup of real listings: the Hiking Club's all-day
"Walk: Greenwich Park" (a date and nothing else), a society social with its
clocks, and the owner-group field that names the host.
"""
import pytest

pytest.importorskip("bs4")

from bs4 import BeautifulSoup

from suu.scrape.whatson import apply_page_details, parse_event_host, parse_event_schedule


def soup(html):
    return BeautifulSoup(html, "html.parser")


ALL_DAY = """
<div class="field field--name-field-date-range field--type-smartdate field--label-hidden field__item">
  <time datetime="2026-09-20" class="datetime"> <span class="date">Sunday 20 September 2026</span> </time>
</div>
"""

TIMED = """
<div class="field field--name-field-date-range field--type-smartdate field--label-hidden field__item">
  <time datetime="2026-09-25T16:00:00+01:00" class="datetime"> <span class="date">Friday 25 September 2026</span> </time>
  <div class="time-wrapper"><time class="datetime">
    <span class="time">16:00</span> <span class="to">to</span> <span class="time">23:00</span>
  </time></div>
</div>
"""

PAST_MIDNIGHT = """
<div class="field field--name-field-date-range">
  <time datetime="2026-09-25T21:00:00+01:00" class="datetime"> <span class="date">Friday 25 September 2026</span> </time>
  <div class="time-wrapper"><time class="datetime">
    <span class="time">21:00</span> <span class="to">to</span> <span class="time">02:00</span>
  </time></div>
</div>
"""

HOST = """
<div class="field field--name-field-event-owner-group field--type-entity-reference">
  <ul class='links field__items'>
    <li>Hosted by <a href="/clubs-societies/hiking-club" hreflang="und">Hiking Club</a></li>
  </ul>
</div>
"""

WALK = "https://studentsunionucl.org/whats-on/clubs-societies/walk-greenwich-park-blackheath-to-canary-wharf-10km?v=96256"


def test_a_date_with_no_clock_is_the_su_saying_all_day():
    assert parse_event_schedule(soup(ALL_DAY)) == {
        "date": "2026-09-20",
        "start_time": None,
        "end_time": None,
        "all_day": True,
    }


def test_a_timed_listing_reads_its_start_and_end_in_london():
    assert parse_event_schedule(soup(TIMED)) == {
        "date": "2026-09-25",
        "start_time": "2026-09-25T16:00:00+01:00",
        "end_time": "2026-09-25T23:00:00+01:00",
        "all_day": False,
    }


def test_an_end_before_the_start_runs_past_midnight():
    schedule = parse_event_schedule(soup(PAST_MIDNIGHT))
    assert schedule["end_time"] == "2026-09-26T02:00:00+01:00"


def test_a_page_with_no_date_field_says_nothing_either_way():
    assert parse_event_schedule(soup("<div class='field--name-body'>Hi</div>")) is None


def test_the_host_is_the_owner_group_link():
    assert parse_event_host(soup(HOST)) == "Hiking Club"
    assert parse_event_host(soup("<div></div>")) is None


def listing(date, **extra):
    return {
        "link": WALK,
        "date": date,
        "start_time": None,
        "end_time": None,
        "time_known": False,
        "host_name": "",
        **extra,
    }


def test_an_all_day_walk_keeps_its_real_day_and_drops_the_evening_before():
    page = {"schedule": parse_event_schedule(soup(ALL_DAY)), "page_host_name": "Hiking Club"}
    events = [listing("2026-09-19", **page), listing("2026-09-20", **page)]

    apply_page_details(events)

    assert [event["date"] for event in events] == ["2026-09-20"]
    assert events[0]["all_day"] is True
    assert events[0]["time_known"] is False
    assert events[0]["host_name"] == "Hiking Club"


def test_the_day_before_is_kept_when_the_real_day_was_not_listed():
    page = {"schedule": parse_event_schedule(soup(ALL_DAY))}
    events = [listing("2026-09-19", **page)]

    apply_page_details(events)

    assert [event["date"] for event in events] == ["2026-09-19"]
    assert "all_day" not in events[0]


def test_a_missing_list_clock_is_filled_from_the_page():
    events = [listing("2026-09-25", schedule=parse_event_schedule(soup(TIMED)))]

    apply_page_details(events)

    assert events[0]["time_known"] is True
    assert events[0]["start_time"] == "2026-09-25T16:00:00+01:00"
    assert events[0]["end_time"] == "2026-09-25T23:00:00+01:00"
    assert events[0]["time_source"] == "event_page"


def test_the_page_never_overrides_a_clock_the_list_gave():
    events = [
        listing(
            "2026-09-25",
            start_time="2026-09-25T18:00:00+01:00",
            time_known=True,
            schedule=parse_event_schedule(soup(TIMED)),
        )
    ]

    apply_page_details(events)

    assert events[0]["start_time"] == "2026-09-25T18:00:00+01:00"
    assert "time_source" not in events[0]


def test_a_host_the_list_named_is_kept():
    events = [listing("2026-09-20", host_name="Mountaineering Club", page_host_name="Hiking Club")]

    apply_page_details(events)

    assert events[0]["host_name"] == "Mountaineering Club"
