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
        {"type": "Facility hire", "description": "Facility hire - Old Refectory hire", "amount": "1200.00"},
        {"type": "Coach/instructors", "description": "Coach/instructors - Ceilidh Band Ltd", "amount": "450.00"},
        {"type": "Printed tickets and posters", "description": "Printed tickets and posters", "amount": "35.50"},
        # The receipt with no amount is left out; 15% of 1685.50.
        {"type": "Contingency", "description": "Contingency (15%)", "amount": "252.82"},
    ]
    assert data["income"] == [
        {"type": "Ticket sales", "description": "Early Bird - Members - £25.00 x 20 = £500.00", "amount": "500.00"},
        {"type": "Ticket sales", "description": "Standard - £30.00 x 40 = £1200.00", "amount": "1200.00"},
        {"type": "Non-Grant Funds", "description": ARF_ACCOUNT_LINE, "amount": "238.32"},
    ]
    spend = sum(float(line["amount"]) for line in data["expenditure"])
    income = sum(float(line["amount"]) for line in data["income"])
    assert round(income - spend, 2) == 0
    assert data["total_expenditure"] == "1938.32"
    assert data["total_income"] == "1938.32"
    assert data["costs_money_yes"] is True and data["costs_money_no"] is False
    assert data["generates_income_yes"] is True and data["generates_income_no"] is False


def test_activity_registration_fields(sample):
    data = build_activity_registration_data(sample["event"], sample["costs"])
    assert data["club_society"] == "Volunteering Society"
    assert data["activity_name"] == "Volunteering Society Winter Ball"
    assert data["proposed_dates"] == [
        {
            "date": "2026-12-04",
            "start_time": "19:00",
            "end_time": "23:30",
            "location": "Old Refectory, Wilkins Building",
        }
    ]
    assert data["expected_attendance"] == "120"
    assert data["risk_assessment_additional"] is True
    assert data["raising_for_charity_no"] is True
    assert data["external_speaker_no"] is True
    # Only the fields for the unchosen radio branches or unknown answers are left unfed.
    unfed = keys_fit("su_activity_registration", data)
    assert unfed == {
        "on_campus_yes",
        "on_campus_no",
        "on_campus_na",
        "raising_for_charity_yes",
        "charity_name",
        "charity_registration_number",
        "fundraising_detail",
        "charity_permission_letter",
        "previous_event_yes",
        "previous_event_no",
        "risk_assessment_core",
        "under_18s_yes",
        "under_18s_no",
        "under_18s_na",
        "external_speaker_yes",
        "external_speaker_form",
    }


def test_activity_registration_with_nothing_known_sends_no_guesses():
    data = build_activity_registration_data({"title": "Picnic", "society": "Hiking Club"})
    assert data["expenditure"] == [] and data["income"] == []
    assert data["costs_money_yes"] is False and data["costs_money_no"] is True
    assert data["generates_income_yes"] is False and data["generates_income_no"] is True
    for unknown in (
        "raising_for_charity_yes",
        "raising_for_charity_no",
        "risk_assessment_core",
        "risk_assessment_additional",
        "external_speaker_yes",
        "external_speaker_no",
    ):
        assert unknown not in data
    assert data["proposed_dates"][0]["date"] == "" and data["expected_attendance"] == ""


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
    assert data["selling_for_event"] is True
    assert data["expenditure_over_200_yes"] is True
    assert data["activity_registration_form"] == "12345"
    assert data["total_tickets"] == "120"
    assert data["ticket_tiers"] == [
        {
            "name": "Early Bird - Members",
            "audience": "",
            "quantity": "40",
            "price": "25.00",
            "on_sale_date": "",
            "on_sale_time": "",
            "off_sale_date": "",
            "off_sale_time": "",
        },
        {
            "name": "Standard",
            "audience": "UCL students",
            "quantity": "80",
            "price": "30.00",
            "on_sale_date": "",
            "on_sale_time": "",
            "off_sale_date": "",
            "off_sale_time": "",
        },
    ]
    assert data["raising_for_charity_no"] is True
    assert data["linked_to_external_speaker_no"] is True
    unfed = keys_fit("su_ticket_request", data)
    assert unfed == {
        "selling_for_product",
        "raising_for_charity_yes",
        "charity_name",
        "linked_to_external_speaker_yes",
        "expenditure_over_200_no",
        "ticket_description",
        "total_items",
        "clothing_or_kit_yes",
        "clothing_or_kit_no",
        "involves_coach_yes",
        "involves_coach_no",
    }


def test_ticket_request_leaves_out_an_arf_reference_it_doesnt_have(sample):
    data = build_ticket_request_data(sample["event"])
    assert "activity_registration_form" not in data
    assert "expenditure_over_200_yes" not in data
    assert data["whats_on_url"] == ""


# ---------------------------------------------------------------------------
# What's On listing
# ---------------------------------------------------------------------------

def test_event_listing_fields(sample, tmp_path):
    image = tmp_path / "winter-ball.jpg"
    data = build_event_listing_data(sample["event"], image)
    assert data["title"] == "Volunteering Society Winter Ball"
    assert data["owner_group"] == "Volunteering Society"
    assert data["event_category"] == "Clubs & Societies"
    assert (data["start_date"], data["start_time"], data["end_date"], data["end_time"]) == (
        "2026-12-04", "19:00", "2026-12-04", "23:30",
    )
    assert data["online"] is False
    assert data["venue"] == "Old Refectory, Wilkins Building"
    assert data["banner_image"] == str(image)
    assert data["card_image"] == str(image)
    assert data["contact_email"] == "volunteering.society@ucl.ac.uk"
    assert data["tags"] == "Social, Free"
    assert data["ticketing_type"] == "Club & Society event as part of a Ticket Request Form submission"
    # Only the free tier: paid tickets are the TRF's.
    assert data["ticket_tiers"] == [{"name": "Committee helpers", "price": "0.00", "quantity": "10"}]
    # No source for the access lists yet.
    assert keys_fit("su_event_listing", data) == {
        "postgraduate",
        "family_friendly",
        "wheelchair_access_yes",
        "wheelchair_access_no",
    }


def test_event_listing_carries_no_url_for_a_file(sample):
    """Like a receipt, the image is a local file the caller downloaded; never the Toolbox's URL."""
    data = build_event_listing_data(sample["event"])
    assert data["banner_image"] == "" and data["card_image"] == ""
    assert "imageUrl" not in json.dumps(data) and "http" not in data["banner_image"]


def test_online_event_has_no_venue(sample):
    event = dict(sample["event"], online=True)
    assert build_event_listing_data(event)["venue"] == ""


def test_unknown_time_is_left_empty_not_midnight(sample):
    event = dict(sample["event"], timeKnown=False, startTime="2026-12-04T00:00:00Z", endTime="2026-12-04T23:59:00Z")
    data = build_event_listing_data(event)
    assert data["start_time"] == "" and data["end_time"] == ""
    assert data["start_date"] == "2026-12-04"
