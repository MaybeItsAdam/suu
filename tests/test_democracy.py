"""Democracy parsers against saved SU pages (tests/fixtures/democracy/, trimmed)."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from suu.scrape.democracy import (
    DemocracyPageError,
    DemocracyScraper,
    academic_year_of,
    parse_archive,
    parse_policy_list,
    parse_policy_page,
    parse_zone_cards,
    sanitise_html,
)

FIXTURES = Path(__file__).parent / "fixtures" / "democracy"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


# ── zone pages ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "fixture,body,count,first_code",
    [
        ("zone_az.html", "AZ", 5, "AZ2601"),
        ("zone_ez.html", "EZ", 5, "EZ2601"),
        ("zone_wcz.html", "WCZ", 5, "WCZ2601"),
        ("zone_ue.html", "UE", 7, "UE2601"),
    ],
)
def test_zone_cards_yield_one_meeting_per_card(fixture, body, count, first_code):
    cards = parse_zone_cards(_html(fixture), body)
    assert len(cards) == count
    assert cards[0].code == first_code
    assert [c.number for c in cards] == list(range(1, count + 1))
    assert all(c.academic_year == "2026-27" for c in cards)


def test_zone_card_times_are_london_wall_clock_across_the_clock_change():
    ue = parse_zone_cards(_html("zone_ue.html"), "UE")
    # 6 Oct 2026 is BST: 18:00 London is 17:00 UTC.
    assert ue[0].starts_at.astimezone(timezone.utc) == datetime(2026, 10, 6, 17, 0, tzinfo=timezone.utc)
    assert ue[0].ends_at.astimezone(timezone.utc) == datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)
    az = parse_zone_cards(_html("zone_az.html"), "AZ")
    # 27 Oct 2026 is GMT again.
    assert az[0].starts_at.astimezone(timezone.utc) == datetime(2026, 10, 27, 18, 0, tzinfo=timezone.utc)


def test_zone_card_links_lose_the_stray_front_controller():
    ue = parse_zone_cards(_html("zone_ue.html"), "UE")
    assert ue[0].event_url.startswith("https://studentsunionucl.org/whats-on/representation/union-executive-meeting-1")
    assert "/index.php/" not in ue[0].event_url
    wcz = parse_zone_cards(_html("zone_wcz.html"), "WCZ")
    assert wcz[0].title == "Welfare & Community Zone: Meeting 1"


def test_zone_page_without_the_widget_is_refused():
    with pytest.raises(DemocracyPageError):
        parse_zone_cards("<html><title>Activities Zone</title><body>redesigned</body></html>", "AZ")


def test_academic_year_runs_august_to_july():
    assert academic_year_of(datetime(2026, 8, 1).date()) == 2026
    assert academic_year_of(datetime(2027, 7, 31).date()) == 2026


# ── archive ─────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def archive():
    return {e.code: e for e in parse_archive(_html("archive.html"))}


def test_archive_covers_every_body_and_year(archive):
    assert len(archive) == 111
    assert {e.body for e in archive.values()} == {"AZ", "EZ", "WCZ", "UE"}
    assert {e.academic_year for e in archive.values()} == {
        "2021-22", "2022-23", "2023-24", "2024-25", "2025-26",
    }


def test_archive_pdf_links_carry_their_label(archive):
    assert archive["AZ2502"].papers_url.endswith("/2025-12/AZ2502%20Minutes%20%26%20Papers.pdf")
    assert archive["AZ2502"].papers_label == "Minutes & Papers"
    assert archive["EZ2402"].papers_label == "Papers"  # Drupal's _0 suffix dropped
    # A filename without the code keeps its whole name as the label.
    assert archive["UE2507"].papers_label == "Agenda and Papers with Minutes"
    # Relative hrefs are made absolute.
    assert archive["AZ2401"].papers_url.startswith("https://studentsunionucl.org/sites/default/files/")


def test_archive_keys_on_link_text_not_data_id(archive):
    # EZ2502's anchor has a stale data-id pointing at EZ2302's page.
    assert "/2025-12/EZ2502" in archive["EZ2502"].papers_url


def test_archive_notes_a_link_to_the_wrong_meeting(archive):
    assert archive["AZ2101"].papers_url.endswith("papers-for-activities-zone-az2102")
    assert "AZ2102" in archive["AZ2101"].note
    assert archive["AZ2102"].note is None


def test_archive_legacy_entries_keep_the_page_url(archive):
    assert archive["AZ2301"].papers_url == "https://studentsunionucl.org/papers-for-activities-zone-az2301"
    assert archive["AZ2301"].papers_label is None


def test_archive_missing_separator_still_splits_two_meetings(archive):
    assert archive["EZ2202"].number == 2
    assert archive["EZ2203"].number == 3


def test_archive_plain_text_entries_become_notes_with_the_year_corrected(archive):
    cancelled = archive["WCZ2504"]
    assert cancelled.listed_code == "WCZ2404"
    assert cancelled.cancelled is True
    assert cancelled.papers_url is None
    assert "cancelled" in cancelled.note
    waiting = archive["WCZ2505"]
    assert waiting.cancelled is False
    assert waiting.note == "Papers waiting approval."
    # The genuine 2024-25 meetings are untouched by the typo.
    assert archive["WCZ2404"].papers_url.endswith("WCZ2404%20Papers.pdf")


def test_archive_login_wall_is_refused():
    with pytest.raises(DemocracyPageError):
        parse_archive(_html("login_wall.html"))


# ── policy register ─────────────────────────────────────────────────────


def test_policy_list_current_page():
    rows, has_next = parse_policy_list(_html("policy_current_p0.html"), "CURRENT")
    assert len(rows) == 22
    assert has_next is False
    first = rows[0]
    assert first.code == "UP2508"
    assert first.status == "CURRENT"
    assert first.progress == "COMPLETED"
    assert first.origin == "WCZ"
    assert first.officer_name == "President"
    assert first.officer_slug == "president"
    assert first.date_lapses == "2028-02-02T12:00:00Z"
    assert first.source_url == (
        "https://studentsunionucl.org/policy/up2508/union-should-join-coalition-to-end-gambling-ads"
    )


def test_policy_list_lapsed_page_paginates_and_tolerates_no_officer():
    rows, has_next = parse_policy_list(_html("policy_lapsed_p0.html"), "LAPSED")
    assert len(rows) == 25
    assert has_next is True
    assert all(r.status == "LAPSED" for r in rows)
    assert any(r.officer_name is None and r.officer_slug is None for r in rows)
    assert rows[0].officer_name == "Equity & Inclusion Officer"


def test_policy_list_refuses_a_page_filtered_to_another_status():
    with pytest.raises(DemocracyPageError, match="LAPSED"):
        parse_policy_list(_html("policy_lapsed_p0.html"), "CURRENT")


def test_policy_list_refuses_the_login_wall():
    with pytest.raises(DemocracyPageError):
        parse_policy_list(_html("login_wall.html"), "CURRENT")


# ── policy pages ────────────────────────────────────────────────────────


def test_policy_page_sidebar_facts():
    page = parse_policy_page(_html("policy_up2508.html"))
    assert page.code == "UP2508"
    assert page.status == "CURRENT"
    assert page.date_passed == "2026-02-02T12:00:00Z"
    assert page.date_lapses == "2028-02-02T12:00:00Z"
    assert page.origin == "WCZ"
    assert page.officer_slug == "president"
    assert page.pdf_url is None
    assert page.updates == []
    assert page.body_html.startswith("<p><strong>What would you like the union to work on?</strong></p>")


def test_policy_page_updates():
    page = parse_policy_page(_html("policy_up2301.html"))
    assert page.status == "LAPSED"
    assert len(page.updates) == 1
    update = page.updates[0]
    assert update.date == "2024-09-02"
    assert update.title == "Completion of Policy"
    assert update.body_html.startswith("<p>This policy is now considered completed")


def test_policy_page_pdf_and_list_body():
    page = parse_policy_page(_html("policy_up1908.html"))
    assert page.pdf_url == (
        "https://studentsunionucl.org/sites/default/files/policies/"
        "policy_proposal_amended2_-_students_support_the_ucu_strike.pdf"
    )
    assert "<ul>" in page.body_html and "<h2>" in page.body_html
    assert page.officer_name is None


def test_policy_page_login_wall_is_refused():
    with pytest.raises(DemocracyPageError):
        parse_policy_page(_html("login_wall.html"))


# ── sanitiser ───────────────────────────────────────────────────────────


def test_sanitise_keeps_the_safe_subset_only():
    dirty = (
        '<div class="x"><p style="color:red">Hi <b>there</b> <span>friend</span></p>'
        '<script>alert(1)</script><a href="/policy/up1" onclick="x()">rel</a>'
        '<a href="javascript:alert(1)">bad</a><img src="x.png"><h5>small</h5></div>'
    )
    clean = sanitise_html(dirty)
    assert clean == (
        '<p>Hi <strong>there</strong> friend</p>'
        '<a href="https://studentsunionucl.org/policy/up1">rel</a>badsmall'
    )


# ── HTTP ────────────────────────────────────────────────────────────────


class _Resp:
    def __init__(self, text, url, status=200):
        self.text, self.url, self.status_code = text, url, status


class _Session:
    def __init__(self, pages):
        self.pages = pages
        self.headers = {}
        self.calls = []

    def get(self, url, params=None, timeout=None):
        self.calls.append((url, dict(params or {})))
        key = (url, (params or {}).get("page", "0"))
        text = self.pages[key]
        return _Resp(text, url)


def test_scraper_pages_the_register_until_there_is_no_next_link():
    lapsed = _html("policy_lapsed_p0.html")
    last = lapsed.replace("pager__item--next", "pager__item--gone")
    url = "https://studentsunionucl.org/policy"
    session = _Session({(url, "0"): lapsed, (url, "1"): last})
    rows = DemocracyScraper(delay=0, session=session).fetch_policy_list("LAPSED")
    assert len(rows) == 50
    assert [c[1].get("page") for c in session.calls] == [None, "1"]
    assert all(c[1]["field_policy_status_target_id_verf"] == "40660" for c in session.calls)


def test_scraper_treats_a_login_redirect_as_an_error():
    class Redirecting(_Session):
        def get(self, url, params=None, timeout=None):
            return _Resp("<html></html>", "https://studentsunionucl.org/user/login?destination=/x")

    with pytest.raises(DemocracyPageError, match="login"):
        DemocracyScraper(delay=0, session=Redirecting({})).fetch_archive()
