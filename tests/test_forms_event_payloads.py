"""The Toolbox event → ARF / TRF / What's On listing mappings.

Read against ``samples/native/toolbox-event/winter-ball.json`` (synthetic). The
definitions are scaffolds with unconfirmed selectors, so what's pinned here is
the contract that will survive a capture: the keys, the budget arithmetic, and
the SU's rules (15% contingency, never over 50% ticket sales, break even, cash
door sales only at £10 or less, paid tickets on the TRF and free ones on the
listing).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from suu.forms.loader import load_form_definition
from suu.forms.payload import (
    ARF_ACCOUNT_LINE,
    build_activity_registration_data,
    build_event_listing_data,
    build_ticket_request_data,
    london_date_time,
    normalize_ticket_tiers,
)

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "native" / "toolbox-event" / "winter-ball.json"


@pytest.fixture
def sample():
    return json.loads(SAMPLE.read_text(encoding="utf-8"))


def keys_fit(form_id: str, data: dict) -> set[str]:
    """Every payload key is a field (and a list row's keys its children); returns the fields left unfed."""
    definition = load_form_definition(form_id)
    top = {f.name: f for f in definition.fields}
    assert set(data) <= set(top), set(data) - set(top)
    for name, value in data.items():
        if top[name].type == "list":
            children = {c.name for c in top[name].fields or []}
            for row in value:
                assert set(row) <= children, (name, set(row) - children)
    return {name for name, f in top.items() if name not in data and f.value is None}


# ---------------------------------------------------------------------------
# Shared pieces
# ---------------------------------------------------------------------------

def test_london_date_time_turns_utc_into_london():
    assert london_date_time("2026-12-04T19:00:00.000Z") == ("2026-12-04", "19:00")
    # BST: 18:30 UTC is 19:30 in London.
    assert london_date_time("2026-06-10T18:30:00Z") == ("2026-06-10", "19:30")
    # Late UTC on a BST night is the next London day.
    assert london_date_time("2026-06-10T23:30:00Z") == ("2026-06-11", "00:30")


def test_london_date_time_leaves_an_unknown_time_empty():
    assert london_date_time("2026-12-04T00:00:00Z", time_known=False) == ("2026-12-04", "")
    assert london_date_time(None) == ("", "")
    assert london_date_time("not a date") == ("", "")


def test_ticket_tiers_budget_at_most_half_the_quantity(sample):
    tiers = normalize_ticket_tiers(sample["event"]["ticketTiers"])
    assert [(t["name"], t["price"], t["quantity"], t["projected"]) for t in tiers] == [
        ("Early Bird - Members", 25.0, 40, 20),
        # projectedSales 60 of 80 is capped at 40.
        ("Standard", 30.0, 80, 40),
        ("Committee helpers", 0.0, 10, 5),
    ]
    assert normalize_ticket_tiers([{"price": 5}, "junk", None]) == []
    assert normalize_ticket_tiers(None) == []


# ---------------------------------------------------------------------------
# ARF
# ---------------------------------------------------------------------------

def test_activity_registration_budget_breaks_even_with_contingency(sample):
    data = build_activity_registration_data(sample["event"], sample["costs"])

    assert data["expenditure"] == [
        {"description": "Facility hire - Old Refectory hire", "amount": "1200.00"},
        {"description": "Coach/instructors - Ceilidh Band Ltd", "amount": "450.00"},
        {"description": "Printed tickets and posters", "amount": "35.50"},
        # The receipt with no amount is left out; 15% of 1685.50.
        {"description": "Contingency (15%)", "amount": "252.82"},
    ]
    assert data["income"] == [
        {"description": "Early Bird - Members - £25.00 x 20 = £500.00", "amount": "500.00"},
        {"description": "Standard - £30.00 x 40 = £1200.00", "amount": "1200.00"},
        {"description": ARF_ACCOUNT_LINE, "amount": "238.32"},
    ]
    spend = sum(float(line["amount"]) for line in data["expenditure"])
    income = sum(float(line["amount"]) for line in data["income"])
    assert round(income - spend, 2) == 0


def test_activity_registration_fields(sample):
    data = build_activity_registration_data(sample["event"], sample["costs"])
    assert data["club_society"] == "Volunteering Society"
    assert data["activity_name"] == "Volunteering Society Winter Ball"
    assert (data["start_date"], data["start_time"], data["end_date"], data["end_time"]) == (
        "2026-12-04", "19:00", "2026-12-04", "23:30",
    )
    assert data["location"] == "Old Refectory, Wilkins Building"
    assert data["expected_attendance"] == "120"
    assert data["reason_expenditure_over_350"] is True
    assert data["reason_not_regular"] is True
    assert data["reason_high_risk"] is True
    assert data["reason_charity"] is False
    assert data["overnight_or_abroad"] == "No"
    assert data["external_speaker"] == "No"
    # Not known about this event, so not sent: the staff-request criterion
    # (nothing records it) and external collaboration (absent from the sample).
    assert keys_fit("su_activity_registration", data) == {"reason_staff_request", "reason_external_collaboration"}


def test_activity_registration_with_nothing_known_sends_no_guesses():
    data = build_activity_registration_data({"title": "Picnic", "society": "Hiking Club"})
    assert data["expenditure"] == [] and data["income"] == []
    assert data["reason_expenditure_over_350"] is False
    for unknown in ("reason_charity", "reason_high_risk", "overnight_or_abroad", "external_speaker"):
        assert unknown not in data
    assert data["start_date"] == "" and data["expected_attendance"] == ""


def test_activity_registration_surplus_needs_no_account_line():
    event = {"ticketTiers": [{"name": "Ticket", "price": 10, "quantity": 100}]}
    data = build_activity_registration_data(event, [{"description": "Room", "amount": 100}])
    assert [line["description"] for line in data["income"]] == ["Ticket - £10.00 x 50 = £500.00"]


# ---------------------------------------------------------------------------
# TRF
# ---------------------------------------------------------------------------

def test_ticket_request_sends_paid_tiers_and_the_listing(sample):
    url = "https://studentsunionucl.org/whats-on/clubs-societies/volunteering-society-winter-ball"
    data = build_ticket_request_data(sample["event"], whats_on_url=url, activity_registration_ref="12345")
    assert data["whats_on_url"] == url
    assert data["request_type"] == "Event tickets"
    assert (data["event_date"], data["start_time"], data["end_time"]) == ("2026-12-04", "19:00", "23:30")
    assert data["activity_registration_form"] == "12345"
    assert data["ticket_tiers"] == [
        {"name": "Early Bird - Members", "price": "25.00", "quantity": "40", "audience": ""},
        {"name": "Standard", "price": "30.00", "quantity": "80", "audience": "UCL students"},
    ]
    # Cash on the door was asked for, but the tickets cost more than £10.
    assert data["cash_door_sales"] == "No"
    assert keys_fit("su_ticket_request", data) == {"additional_information"}


def test_ticket_request_allows_cash_only_at_ten_pounds_or_less():
    event = {"cashDoorSales": True, "ticketTiers": [{"name": "Entry", "price": 10, "quantity": 50}]}
    assert build_ticket_request_data(event)["cash_door_sales"] == "Yes"
    event["cashDoorSales"] = False
    assert build_ticket_request_data(event)["cash_door_sales"] == "No"


def test_ticket_request_leaves_out_an_arf_reference_it_doesnt_have(sample):
    data = build_ticket_request_data(sample["event"])
    assert "activity_registration_form" not in data
    assert data["whats_on_url"] == ""


# ---------------------------------------------------------------------------
# What's On listing
# ---------------------------------------------------------------------------

def test_event_listing_fields(sample, tmp_path):
    image = tmp_path / "winter-ball.jpg"
    data = build_event_listing_data(sample["event"], image)
    assert data["title"] == "Volunteering Society Winter Ball"
    assert data["owner_group"] == "Volunteering Society"
    assert (data["start_date"], data["start_time"], data["end_date"], data["end_time"]) == (
        "2026-12-04", "19:00", "2026-12-04", "23:30",
    )
    assert data["online"] is False
    assert data["venue"] == "Old Refectory, Wilkins Building"
    assert data["image"] == str(image)
    assert data["contact_email"] == "volunteering.society@ucl.ac.uk"
    assert data["tags"] == "Social, Free"
    # Only the free tier: paid tickets are the TRF's.
    assert data["ticket_tiers"] == [{"name": "Committee helpers", "price": "0.00", "quantity": "10"}]
    # No source for the access lists yet.
    assert keys_fit("su_event_listing", data) == {"family_friendly", "wheelchair_access"}


def test_event_listing_carries_no_url_for_a_file(sample):
    """Like a receipt, the image is a local file the caller downloaded; never the Toolbox's URL."""
    data = build_event_listing_data(sample["event"])
    assert data["image"] == ""
    assert "imageUrl" not in json.dumps(data) and "http" not in data["image"]


def test_online_event_has_no_venue(sample):
    event = dict(sample["event"], online=True)
    assert build_event_listing_data(event)["venue"] == ""


def test_unknown_time_is_left_empty_not_midnight(sample):
    event = dict(sample["event"], timeKnown=False, startTime="2026-12-04T00:00:00Z", endTime="2026-12-04T23:59:00Z")
    data = build_event_listing_data(event)
    assert data["start_time"] == "" and data["end_time"] == ""
    assert data["start_date"] == "2026-12-04"
